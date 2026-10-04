"""H1: 上位 1% / 10% 資産・所得シェアの「U 字型（Piketty 的）」軌跡は多数派か（記述のみ）。

決定的スクリプト。入力は data/marts/wealth_population_panel.parquet（主）と、頑健性のためだけに
data/staged/wid/top_shares.parquet の data_quality 列（副）。乱数は使わない。
出力: 標準出力に全数値、図を reports/figures/ に保存。

    uv run python themes/wealth-population-distribution/src/theme_wealth_population_distribution/\
analysis/<this file> [--data-dir data] \
        [--fig-dir themes/wealth-population-distribution/reports/figures]

## U 字判定の基準（結果を見る前に固定。以下の定義をそのままコードにしている）
対象系列 s_t（例: top1_wealth_share）、窓 W = [1950, 2024]。
1. 適格性: W 内で 1990 年より前に 3 観測以上、かつ 2000 年より後に 3 観測以上ある国のみ判定する
   （それ以外は「判定不能」として分母から外し、その数を報告する）。
2. 谷: W 内の最小値の年 t*（同値なら最初の年）。
3. 下降幅 decline = s(W 内の最初の観測) − s(t*)、上昇幅 rise = s(W 内の最後の観測) − s(t*)。
4. U 字 = (a) t* が [1965, 1995] にある、かつ (b) decline ≥ δ、かつ (c) rise ≥ δ。
   基準 δ = 0.01（1 pp）。
   谷が窓の端にある系列（単調増加・単調減少）は (a)(b)(c) のいずれかで落ちる。
5. 「多数派」= 適格国のうち U 字を満たす割合 > 0.5。片側二項検定（p=0.5、国は独立と仮定した目安）と
   Wilson 95% 区間を報告する。国同士は独立でないので p 値は参考値。
6. 補助指標（H1 の後半「1980 年前後を谷として上昇」の弱い形）:
   1980 年（最近傍の観測）から最新年への変化が正か。
頑健性（事前に列挙）: δ = 0.02、谷の許容窓 [1960, 2000]、分析窓 1970–2024、
系列末尾の「同一値の連続（≥ 5 年）」を外挿とみなして切り落とす、
data_quality が 4–5 の国×年を落とす。

純粋関数（coverage_table, classify_trajectory, binom_test_majority, wilson_ci,
strip_flat_tail, ...）は tests/test_analysis_h1.py で検証する。
"""

from __future__ import annotations

import argparse
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import polars as pl

THEME_DIR = Path(__file__).resolve().parents[3]
REPO_ROOT = THEME_DIR.parents[1]
MART = Path("marts") / "wealth_population_panel.parquet"
STAGED_SHARES = Path("staged") / "wid" / "top_shares.parquet"

SERIES: dict[str, tuple[str, str]] = {  # mart column -> (staged variable, percentile)
    "top1_wealth_share": ("shweal992j", "p99p100"),
    "top10_wealth_share": ("shweal992j", "p90p100"),
    "top1_income_share": ("sptinc992j", "p99p100"),
    "top10_income_share": ("sptinc992j", "p90p100"),
}
JAPAN = "JPN"

# dataviz palette (default instance): muted blue for the field, orange for the highlighted series.
BLUE = "#5598e7"
ORANGE = "#eb6834"
INK = "#333333"
MUTED = "#8a8a8a"


@dataclass(frozen=True)
class Criterion:
    """U 字判定のパラメータ。基準値は docstring の定義と一致させる。"""

    window: tuple[int, int] = (1950, 2024)
    trough_window: tuple[int, int] = (1965, 1995)
    min_delta: float = 0.01
    pre_cut: int = 1990  # 「前期」= year < pre_cut
    post_cut: int = 2000  # 「後期」= year > post_cut
    min_obs: int = 3

    def label(self) -> str:
        return (
            f"window={self.window[0]}-{self.window[1]} trough∈[{self.trough_window[0]},"
            f"{self.trough_window[1]}] δ={self.min_delta:.2f}"
        )


BASE = Criterion()


@dataclass(frozen=True)
class Trajectory:
    iso3: str
    n: int
    eligible: bool
    first_year: int | None
    first: float | None
    trough_year: int | None
    trough: float | None
    last_year: int | None
    last: float | None
    decline: float | None
    rise: float | None
    u_shape: bool | None
    year_1980: int | None
    change_since_1980: float | None


# ---------------------------------------------------------------- pure helpers (tested)
def coverage_table(panel: pl.DataFrame, col: str, *, crit: Criterion = BASE) -> pl.DataFrame:
    """国別: 非欠損の観測数、最初/最後の年、窓内の前期・後期の観測数。

    queries/coverage_by_country.sql に対応する。
    """
    lo, hi = crit.window
    return (
        panel.filter(pl.col(col).is_not_null())
        .group_by("iso3")
        .agg(
            pl.len().alias("n"),
            pl.col("year").min().alias("first_year"),
            pl.col("year").max().alias("last_year"),
            ((pl.col("year") >= lo) & (pl.col("year") < crit.pre_cut)).sum().alias("pre"),
            ((pl.col("year") > crit.post_cut) & (pl.col("year") <= hi)).sum().alias("post"),
        )
        .sort("iso3")
    )


def series_in_window(
    panel: pl.DataFrame, iso3: str, col: str, window: tuple[int, int]
) -> list[tuple[int, float]]:
    lo, hi = window
    df = (
        panel.filter(
            (pl.col("iso3") == iso3)
            & pl.col(col).is_not_null()
            & (pl.col("year") >= lo)
            & (pl.col("year") <= hi)
        )
        .select("year", col)
        .sort("year")
    )
    return [(int(y), float(v)) for y, v in df.rows()]


def nearest_obs(obs: list[tuple[int, float]], year: int) -> tuple[int, float] | None:
    """year に最も近い観測（同距離なら早い方）。空なら None。"""
    if not obs:
        return None
    return min(obs, key=lambda yv: (abs(yv[0] - year), yv[0]))


def classify_trajectory(
    iso3: str, obs: list[tuple[int, float]], *, crit: Criterion = BASE
) -> Trajectory:
    """docstring の U 字基準 1–4, 6 をそのまま実装。obs は窓内に限定済み・年昇順を仮定。"""
    n = len(obs)
    pre = sum(1 for y, _ in obs if y < crit.pre_cut)
    post = sum(1 for y, _ in obs if y > crit.post_cut)
    eligible = pre >= crit.min_obs and post >= crit.min_obs
    if not obs:
        return Trajectory(iso3, 0, False, *([None] * 11))
    first_year, first = obs[0]
    last_year, last = obs[-1]
    trough_year, trough = min(obs, key=lambda yv: (yv[1], yv[0]))
    decline = first - trough
    rise = last - trough
    near80 = nearest_obs(obs, 1980)
    change80 = last - near80[1] if near80 is not None else None
    u_shape: bool | None = None
    if eligible:
        tlo, thi = crit.trough_window
        u_shape = tlo <= trough_year <= thi and decline >= crit.min_delta and rise >= crit.min_delta
    return Trajectory(
        iso3,
        n,
        eligible,
        first_year,
        first,
        trough_year,
        trough,
        last_year,
        last,
        decline,
        rise,
        u_shape,
        near80[0] if near80 is not None else None,
        change80,
    )


def strip_flat_tail(obs: list[tuple[int, float]], *, min_run: int = 5) -> list[tuple[int, float]]:
    """末尾の同一値の連続が min_run 以上なら、その連続の最初の 1 点だけ残して以降を落とす。

    同一値の繰り返しは外挿（carry-forward）の疑いがあるため。
    """
    if not obs:
        return obs
    k = 1
    while k < len(obs) and obs[-1 - k][1] == obs[-1][1]:
        k += 1
    if k >= min_run:
        return obs[: len(obs) - k + 1]
    return obs


def longest_flat_run(obs: list[tuple[int, float]]) -> tuple[int, int | None]:
    """系列中で同一値が連続する最長の長さと、その開始年（記述: 補間・外挿の疑いの診断）。"""
    best, best_start = 0, None
    i = 0
    while i < len(obs):
        j = i
        while j + 1 < len(obs) and obs[j + 1][1] == obs[i][1]:
            j += 1
        if j - i + 1 > best:
            best, best_start = j - i + 1, obs[i][0]
        i = j + 1
    return best, best_start


def classify_all(
    panel: pl.DataFrame,
    col: str,
    *,
    crit: Criterion = BASE,
    strip_tail: int | None = None,
) -> pl.DataFrame:
    rows = []
    for iso3 in sorted(panel["iso3"].unique().to_list()):
        obs = series_in_window(panel, iso3, col, crit.window)
        if strip_tail is not None:
            obs = strip_flat_tail(obs, min_run=strip_tail)
        rows.append(asdict(classify_trajectory(iso3, obs, crit=crit)))
    return pl.DataFrame(rows)


def binom_test_majority(k: int, n: int) -> float:
    """片側正確二項検定 P(X >= k | n, p = 0.5)。n = 0 なら nan。"""
    if n == 0:
        return math.nan
    return float(sum(math.comb(n, i) for i in range(k, n + 1)) / 2**n)


def wilson_ci(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    if n == 0:
        return (math.nan, math.nan)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


@dataclass(frozen=True)
class MajorityTest:
    label: str
    eligible: int
    ineligible: int
    k: int
    share: float
    ci: tuple[float, float]
    p_one_sided: float

    def line(self) -> str:
        return (
            f"{self.label:<70} eligible={self.eligible:>2} (ineligible={self.ineligible:>2}) "
            f"U={self.k:>2} share={self.share:.3f} wilson95=[{self.ci[0]:.3f}, {self.ci[1]:.3f}] "
            f"p(one-sided, H0 p=0.5)={self.p_one_sided:.4f}"
        )


def majority_test(traj: pl.DataFrame, label: str) -> MajorityTest:
    elig = traj.filter(pl.col("eligible"))
    n = elig.height
    k = int(elig["u_shape"].sum()) if n else 0
    return MajorityTest(
        label,
        n,
        traj.height - n,
        k,
        k / n if n else math.nan,
        wilson_ci(k, n),
        binom_test_majority(k, n),
    )


def rise_since_1980_test(traj: pl.DataFrame, label: str) -> MajorityTest:
    """補助指標 6: 適格国のうち 1980 年（最近傍）→最新年の変化が正の国の割合。U 字の弱い形。"""
    elig = traj.filter(pl.col("eligible"))
    n = elig.height
    k = int((elig["change_since_1980"] > 0).sum()) if n else 0
    return MajorityTest(
        label,
        n,
        traj.height - n,
        k,
        k / n if n else math.nan,
        wilson_ci(k, n),
        binom_test_majority(k, n),
    )


def split_by_start(traj: pl.DataFrame, cutoff: int) -> tuple[pl.DataFrame, pl.DataFrame]:
    """探索的: 窓内の最初の観測が cutoff 以前の「長期系列」国と、それより後に始まる国に分ける。"""
    long = traj.filter(pl.col("first_year") <= cutoff)
    short = traj.filter(pl.col("first_year") > cutoff)
    return long, short


def rank_in_year(panel: pl.DataFrame, col: str, year: int, iso3: str) -> tuple[int | None, int]:
    """year における iso3 の順位（1 = シェア最大）と、その年の観測国数。"""
    df = panel.filter((pl.col("year") == year) & pl.col(col).is_not_null()).sort(
        [col, "iso3"], descending=[True, False]
    )
    codes = df["iso3"].to_list()
    return (codes.index(iso3) + 1 if iso3 in codes else None), len(codes)


def quality_flags(staged: pl.DataFrame, col: str) -> pl.DataFrame:
    """staged/wid/top_shares から該当系列の iso3×year×data_quality を取り出す。"""
    var, pct = SERIES[col]
    return staged.filter((pl.col("variable") == var) & (pl.col("percentile") == pct)).select(
        "iso3", "year", "data_quality"
    )


def drop_quality(panel: pl.DataFrame, flags: pl.DataFrame, col: str, bad: set[int]) -> pl.DataFrame:
    """data_quality ∈ bad の国×年について col を欠損にする（補完はしない。行は残す）。"""
    joined = panel.join(flags, on=["iso3", "year"], how="left")
    return joined.with_columns(
        pl.when(pl.col("data_quality").is_in(sorted(bad)))
        .then(None)
        .otherwise(pl.col(col))
        .alias(col)
    ).drop("data_quality")


# ---------------------------------------------------------------- figures
def _style(ax: Any) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(MUTED)
    ax.tick_params(colors=INK, labelsize=7)
    ax.grid(axis="y", color="#e5e5e5", linewidth=0.5)
    ax.set_axisbelow(True)


def fig_small_multiples(
    panel: pl.DataFrame, traj: pl.DataFrame, col: str, path: Path, *, title: str
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    lo, hi = BASE.window
    codes = sorted(panel["iso3"].unique().to_list())
    ncol = 8
    nrow = math.ceil(len(codes) / ncol)
    fig, axes = plt.subplots(nrow, ncol, figsize=(1.9 * ncol, 1.6 * nrow), sharex=True, sharey=True)
    flat = [ax for row in axes for ax in row]
    tmap = {r["iso3"]: r for r in traj.iter_rows(named=True)}
    for ax, iso3 in zip(flat, codes, strict=False):
        obs = series_in_window(panel, iso3, col, (lo, hi))
        color = ORANGE if iso3 == JAPAN else BLUE
        if obs:
            ax.plot([y for y, _ in obs], [v for _, v in obs], color=color, linewidth=1.2)
            ax.scatter([y for y, _ in obs], [v for _, v in obs], s=3, color=color)
        t = tmap.get(iso3)
        tag = ""
        if t is not None and t["eligible"]:
            tag = " U" if t["u_shape"] else " –"
            if t["trough_year"] is not None:
                ax.axvline(t["trough_year"], color=MUTED, linewidth=0.6, linestyle=":")
        elif t is not None:
            tag = " (n/a)"
        ax.set_title(
            f"{iso3}{tag} n={len(obs)}", fontsize=8, color=ORANGE if iso3 == JAPAN else INK
        )
        _style(ax)
    for ax in flat[len(codes) :]:
        ax.axis("off")
    fig.suptitle(
        f"{title}, {lo}-{hi}. Share of adults (equal-split), 0-1. Dotted = trough year; "
        "'U' = meets pre-registered U criterion, '–' = eligible but not U, (n/a) = too few obs.\n"
        "Source: World Inequality Database (wid.world), CC BY-NC-SA 4.0",
        fontsize=8,
        color=INK,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(path, dpi=150)
    plt.close(fig)


def fig_japan_vs_field(panel: pl.DataFrame, col: str, path: Path, *, title: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    lo, hi = BASE.window
    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    codes = sorted(panel["iso3"].unique().to_list())
    for iso3 in codes:
        if iso3 == JAPAN:
            continue
        obs = series_in_window(panel, iso3, col, (lo, hi))
        ax.plot([y for y, _ in obs], [v for _, v in obs], color=BLUE, alpha=0.25, linewidth=0.8)
    med = (
        panel.filter(pl.col(col).is_not_null() & (pl.col("year") >= 1980) & (pl.col("year") <= hi))
        .group_by("year")
        .agg(pl.col(col).median().alias("med"), pl.len().alias("n"))
        .sort("year")
    )
    ax.plot(med["year"], med["med"], color=INK, linewidth=1.8, label="cross-country median (1980+)")
    jp = series_in_window(panel, JAPAN, col, (lo, hi))
    ax.plot([y for y, _ in jp], [v for _, v in jp], color=ORANGE, linewidth=2.2, label="Japan")
    n_countries = len(codes)
    ax.set_xlabel("year", fontsize=8, color=INK)
    ax.set_ylabel(f"{col} (share, 0-1)", fontsize=8, color=INK)
    ax.set_title(
        f"{title}: Japan vs {n_countries - 1} other countries, {lo}-{hi}.\n"
        "Source: World Inequality Database (wid.world), CC BY-NC-SA 4.0",
        fontsize=9,
        color=INK,
    )
    ax.legend(frameon=False, fontsize=8)
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------- reporting
def print_coverage(panel: pl.DataFrame) -> None:
    print("== mart ==")
    y0, y1 = int(str(panel["year"].min())), int(str(panel["year"].max()))
    print(f"rows={panel.height} countries={panel['iso3'].n_unique()} years={y0}-{y1}")
    for c in [*SERIES, "bottom50_income_share", "population"]:
        nn = panel[c].null_count()
        print(f"  {c}: non-null={panel.height - nn} null_rate={nn / panel.height:.3f}")
    for col in SERIES:
        cov = coverage_table(panel, col)
        print(
            f"== coverage: {col} (window {BASE.window}, pre<{BASE.pre_cut}, "
            f"post>{BASE.post_cut}) =="
        )
        eligible = cov.filter((pl.col("pre") >= BASE.min_obs) & (pl.col("post") >= BASE.min_obs))
        print(
            f"  countries with data={cov.height} eligible={eligible.height} "
            f"first_year: min={int(str(cov['first_year'].min()))} "
            f"median={float(str(cov['first_year'].median())):.0f} "
            f"max={int(str(cov['first_year'].max()))}"
        )
        start_1980 = cov.filter(pl.col("first_year") >= 1980)["iso3"].to_list()
        print(f"  series starting 1980 or later ({len(start_1980)}): {' '.join(start_1980)}")
        pre_counts = cov.filter(pl.col("pre") < BASE.min_obs)["iso3"].to_list()
        print(
            f"  ineligible (<{BASE.min_obs} obs before {BASE.pre_cut}): "
            f"{' '.join(pre_counts) or '-'}"
        )


def print_trajectories(traj: pl.DataFrame, col: str) -> None:
    print(f"== trajectories: {col} ({BASE.label()}) ==")
    print(
        f"  {'iso3':<5}{'n':>3} {'first':>12} {'trough':>12} {'last':>12} "
        f"{'decline':>8} {'rise':>8} {'d1980':>8}  U"
    )
    for r in traj.iter_rows(named=True):
        if not r["eligible"]:
            print(f"  {r['iso3']:<5}{r['n']:>3}  (not eligible)")
            continue
        u = "U" if r["u_shape"] else "-"
        print(
            f"  {r['iso3']:<5}{r['n']:>3} {r['first_year']}:{r['first']:.3f} "
            f"{r['trough_year']}:{r['trough']:.3f} {r['last_year']}:{r['last']:.3f} "
            f"{r['decline']:>+8.3f} {r['rise']:>+8.3f} {r['change_since_1980']:>+8.3f}  {u}"
        )
    elig = traj.filter(pl.col("eligible"))
    if elig.height:
        tys = elig["trough_year"].to_list()
        print(
            f"  trough year among eligible: min={min(tys)} median={sorted(tys)[len(tys) // 2]} "
            f"max={max(tys)}; in [{BASE.trough_window[0]},{BASE.trough_window[1]}]: "
            f"{sum(BASE.trough_window[0] <= t <= BASE.trough_window[1] for t in tys)}/{len(tys)}"
        )
        up = int((elig["change_since_1980"] > 0).sum())
        print(
            f"  change since 1980 > 0: {up}/{elig.height} "
            f"(median change {float(str(elig['change_since_1980'].median())):+.3f})"
        )


def print_japan(panel: pl.DataFrame, traj: pl.DataFrame, col: str) -> None:
    r = traj.filter(pl.col("iso3") == JAPAN).row(0, named=True)
    latest = int(str(panel.filter(pl.col(col).is_not_null())["year"].max()))
    rank, n = rank_in_year(panel, col, latest, JAPAN)
    rank80, n80 = rank_in_year(panel, col, 1980, JAPAN)
    print(
        f"  {col}: JPN {r['first_year']}={r['first']:.3f} "
        f"trough {r['trough_year']}={r['trough']:.3f} "
        f"{r['last_year']}={r['last']:.3f} change_since_1980={r['change_since_1980']:+.3f} "
        f"u_shape={r['u_shape']} | rank {latest}: {rank}/{n} (1 = highest share); "
        f"rank 1980: {rank80}/{n80}"
    )
    field = traj.filter(pl.col("eligible") & (pl.col("iso3") != JAPAN))
    print(
        f"    other eligible countries: median change_since_1980="
        f"{float(str(field['change_since_1980'].median())):+.3f}, "
        f"JPN percentile of change (share of others with smaller change)="
        f"{(field['change_since_1980'] < r['change_since_1980']).mean():.2f}"
    )


def run(data_dir: Path, fig_dir: Path) -> None:
    panel = pl.read_parquet(data_dir / MART).sort(["iso3", "year"])
    staged = pl.read_parquet(data_dir / STAGED_SHARES)
    fig_dir.mkdir(parents=True, exist_ok=True)
    print_coverage(panel)

    print("\n== H1 main test: pre-registered U criterion (see module docstring) ==")
    base_traj: dict[str, pl.DataFrame] = {}
    for col in SERIES:
        traj = classify_all(panel, col)
        base_traj[col] = traj
        print_trajectories(traj, col)
        print("  " + majority_test(traj, f"[M] {col}").line())
        print("  " + rise_since_1980_test(traj, f"[A] rise since 1980 > 0: {col}").line())

    print(
        "\n== exploratory (not pre-registered): split by series start "
        "(first obs in window <= 1960 vs later; late starters cannot show a pre-trough decline) =="
    )
    for col in SERIES:
        long, short = split_by_start(base_traj[col], 1960)
        print(majority_test(long, f"[X] start<=1960: {col}").line())
        print(majority_test(short, f"[X] start>1960: {col}").line())
        print(rise_since_1980_test(short, f"[X] start>1960, rise since 1980 > 0: {col}").line())

    print("\n== Japan's position (descriptive; H3 income part only) ==")
    for col in SERIES:
        print_japan(panel, base_traj[col], col)

    fig_small_multiples(
        panel,
        base_traj["top1_wealth_share"],
        "top1_wealth_share",
        fig_dir / "h1_top1_wealth_small_multiples.png",
        title="Top 1% net personal wealth share by country (shweal992j p99p100)",
    )
    fig_small_multiples(
        panel,
        base_traj["top1_income_share"],
        "top1_income_share",
        fig_dir / "h1_top1_income_small_multiples.png",
        title="Top 1% pre-tax national income share by country (sptinc992j p99p100)",
    )
    fig_japan_vs_field(
        panel,
        "top1_wealth_share",
        fig_dir / "h1_top1_wealth_japan_vs_field.png",
        title="Top 1% wealth share",
    )
    fig_japan_vs_field(
        panel,
        "top1_income_share",
        fig_dir / "h1_top1_income_japan_vs_field.png",
        title="Top 1% income share",
    )

    print("\n== robustness (all pre-listed variants; majority test per series) ==")
    variants: list[tuple[str, Criterion, int | None, set[int] | None]] = [
        ("δ=0.02", Criterion(min_delta=0.02), None, None),
        ("trough window [1960,2000]", Criterion(trough_window=(1960, 2000)), None, None),
        ("analysis window 1970-2024", Criterion(window=(1970, 2024)), None, None),
        ("strip flat tail (>=5 identical trailing values)", BASE, 5, None),
        ("drop data_quality in {4,5}", BASE, None, {4, 5}),
        ("drop data_quality in {4,5} + strip flat tail", BASE, 5, {4, 5}),
    ]
    for name, crit, strip, bad in variants:
        for col in SERIES:
            p = panel
            if bad is not None:
                p = drop_quality(panel, quality_flags(staged, col), col, bad)
            traj = classify_all(p, col, crit=crit, strip_tail=strip)
            print(majority_test(traj, f"[R] {name}: {col}").line())
            if strip is not None or bad is not None:
                changed = traj.join(base_traj[col], on="iso3", suffix="_base").filter(
                    (pl.col("u_shape") != pl.col("u_shape_base"))
                    | (pl.col("eligible") != pl.col("eligible_base"))
                )
                if changed.height:
                    print(f"    classification changed for: {' '.join(changed['iso3'].to_list())}")

    print(
        "\n== data_quality flag distribution per series (WID advisory flag, 0-5; staged table) =="
    )
    for col in SERIES:
        q = quality_flags(staged, col).group_by("data_quality").len().sort("data_quality")
        print(f"  {col}: " + ", ".join(f"q{r[0]}={r[1]}" for r in q.rows()))
        flat = [
            (iso3, obs[-1][0] - strip_flat_tail(obs)[-1][0] + 1)
            for iso3 in sorted(panel["iso3"].unique().to_list())
            if (obs := series_in_window(panel, iso3, col, BASE.window))
            and len(strip_flat_tail(obs)) < len(obs)
        ]
        print(f"    flat tails (>=5 identical trailing values): {flat or '-'}")
        runs = [
            (iso3, run, start)
            for iso3 in sorted(panel["iso3"].unique().to_list())
            for run, start in [longest_flat_run(series_in_window(panel, iso3, col, BASE.window))]
            if run >= 10
        ]
        print(
            "    flat runs of >=10 identical consecutive values (iso3, length, start): "
            f"{runs or '-'}"
        )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", type=Path, default=REPO_ROOT / "data")
    ap.add_argument("--fig-dir", type=Path, default=THEME_DIR / "reports" / "figures")
    args = ap.parse_args()
    run(args.data_dir, args.fig_dir)


if __name__ == "__main__":
    main()
