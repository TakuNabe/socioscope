"""H1b: H1 の U 字判定を「観測年のみ」で再実行する感度分析（記述のみ、事前列挙）。

H1（a20261004_h1_ushape.py）は WID の全年を使ったが、WID の多くの年は補間・外挿である。
本スクリプトは staged/wid/data_points（WID_metadata の `method` 文から機械的に起こした
年別の construction = observed / partial / imputed / None=不明）と、staged/wid/top_shares の
`data_quality`（WID の 0–5 の観測レベル品質スコア。定義は非公開だが、metadata と照合すると
0 ≒ 純粋な補間・外挿・推計、高いほど一次データに近い）を使い、以下を**結果を見る前に**列挙した。

入力: data/marts/wealth_population_panel.parquet, data/staged/wid/data_points.parquet,
data/staged/wid/top_shares.parquet。乱数なし。純粋関数は tests/test_analysis_h1b.py で検証。

    uv run python themes/wealth-population-distribution/src/theme_wealth_population_distribution/\
analysis/<this file> [--data-dir data] [--fig-dir .../reports/figures]

## 変種（事前列挙。U 字基準・窓・適格性は H1 の BASE と同一）
- V0 基準: H1 と同じ（全年）。照合用。
- V1 metadata 厳格: construction == "observed" の年だけ残す（partial・imputed・不明は欠損化）。
  WID の資産系列には年別の construction 記述が無いので、資産は全国が判定不能になることが予想される。
  それ自体を結果として報告する。
- V2 metadata 緩和: construction == "imputed" の年だけ欠損化（observed・partial・不明は残す）。
- V3 data_quality 代理: data_quality == 0 の年を欠損化（metadata との照合表で 0 が補間・外挿と
  対応することを同時に示す）。
- V4 data_quality 代理（強）: data_quality <= 1 の年を欠損化。
- V5 併用: V2 と V3 の両方。
各変種で [M] 多数派検定、[A] 1980 年以降上昇、判定が変わった国、日本の位置（1980 年比・順位）
を出す。
欠損は補完しない（行は残し、該当年の値だけ None にする）。
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import polars as pl

from theme_wealth_population_distribution.analysis import a20261004_h1_ushape as h1

THEME_DIR = Path(__file__).resolve().parents[3]
REPO_ROOT = THEME_DIR.parents[1]
DATA_POINTS = Path("staged") / "wid" / "data_points.parquet"

CONSTRUCTIONS = ("observed", "partial", "imputed")
SERIES = ("top1_wealth_share", "top1_income_share")  # H1b scope: top 1% only (H1 wording)
JAPAN = h1.JAPAN
GREY = "#bdbdbd"


# ---------------------------------------------------------------- pure helpers (tested)
def construction_flags(data_points: pl.DataFrame, col: str) -> pl.DataFrame:
    """staged/wid/data_points から該当系列（変数単位）の iso3×year×construction を取り出す。"""
    var, _ = h1.SERIES[col]
    return data_points.filter(pl.col("variable") == var).select("iso3", "year", "construction")


def mask_construction(
    panel: pl.DataFrame,
    flags: pl.DataFrame,
    col: str,
    *,
    keep: set[str] | None = None,
    drop: set[str] | None = None,
) -> pl.DataFrame:
    """construction で col を欠損化する（行は残す、補完しない）。

    keep が与えられたら keep に無い年（不明 None を含む）を欠損化。
    drop が与えられたら drop に含まれる年だけ欠損化（不明は残す）。両方は不可。
    """
    if (keep is None) == (drop is None):
        msg = "give exactly one of keep / drop"
        raise ValueError(msg)
    joined = panel.join(flags, on=["iso3", "year"], how="left")
    c = pl.col("construction")
    if keep is not None:
        bad = c.is_null() | ~c.is_in(sorted(keep))
    else:
        bad = c.is_in(sorted(drop or set()))
    return joined.with_columns(pl.when(bad).then(None).otherwise(pl.col(col)).alias(col)).drop(
        "construction"
    )


def coverage_by_construction(
    panel: pl.DataFrame, flags: pl.DataFrame, col: str, window: tuple[int, int]
) -> pl.DataFrame:
    """国別: 窓内の非欠損年数と、その construction 内訳（observed/partial/imputed/unknown）。"""
    lo, hi = window
    df = (
        panel.filter(pl.col(col).is_not_null() & (pl.col("year") >= lo) & (pl.col("year") <= hi))
        .select("iso3", "year")
        .join(flags, on=["iso3", "year"], how="left")
    )
    c = pl.col("construction")
    return (
        df.group_by("iso3")
        .agg(
            pl.len().alias("n"),
            (c == "observed").sum().alias("observed"),
            (c == "partial").sum().alias("partial"),
            (c == "imputed").sum().alias("imputed"),
            c.is_null().sum().alias("unknown"),
            pl.col("year").filter(c == "observed").min().alias("first_observed"),
            pl.col("year").filter(c == "observed").max().alias("last_observed"),
        )
        .sort("iso3")
    )


def quality_by_construction(
    quality: pl.DataFrame, flags: pl.DataFrame, window: tuple[int, int]
) -> pl.DataFrame:
    """照合表: construction × data_quality の件数（窓内）。data_quality の向きの経験的確認。"""
    lo, hi = window
    df = quality.filter((pl.col("year") >= lo) & (pl.col("year") <= hi)).join(
        flags, on=["iso3", "year"], how="left"
    )
    return (
        df.with_columns(pl.col("construction").fill_null("unknown"))
        .group_by(["construction", "data_quality"])
        .len()
        .sort(["construction", "data_quality"])
    )


def changed_countries(traj: pl.DataFrame, base: pl.DataFrame) -> list[str]:
    """基準と比べて eligible か u_shape が変わった国。"""
    j = traj.join(base, on="iso3", suffix="_base")
    u, ub = (pl.col(c).cast(pl.Int8).fill_null(-1) for c in ("u_shape", "u_shape_base"))
    diff = j.filter((pl.col("eligible") != pl.col("eligible_base")) | (u != ub))
    return sorted(diff["iso3"].to_list())


# ---------------------------------------------------------------- figure
def fig_small_multiples_marked(
    panel: pl.DataFrame,
    flags: pl.DataFrame,
    traj: pl.DataFrame,
    col: str,
    path: Path,
    *,
    title: str,
) -> None:
    """H1 の小多重図に construction を重ねる: ● observed, ○ partial, 点線 imputed, 灰 不明。"""
    import math

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    lo, hi = h1.BASE.window
    codes = sorted(panel["iso3"].unique().to_list())
    ncol = 8
    nrow = math.ceil(len(codes) / ncol)
    fig, axes = plt.subplots(nrow, ncol, figsize=(1.9 * ncol, 1.6 * nrow), sharex=True, sharey=True)
    flat = [ax for row in axes for ax in row]
    tmap = {r["iso3"]: r for r in traj.iter_rows(named=True)}
    fmap = {(r["iso3"], r["year"]): r["construction"] for r in flags.iter_rows(named=True)}
    for ax, iso3 in zip(flat, codes, strict=False):
        obs = h1.series_in_window(panel, iso3, col, (lo, hi))
        color = h1.ORANGE if iso3 == JAPAN else h1.BLUE
        if obs:
            kinds = [fmap.get((iso3, y)) for y, _ in obs]
            # segments: a segment between consecutive points is imputed if either end is imputed
            for (y0, v0), (y1, v1), k0, k1 in zip(obs, obs[1:], kinds, kinds[1:], strict=False):
                imputed = "imputed" in (k0, k1)
                unknown = k0 is None and k1 is None
                ax.plot(
                    [y0, y1],
                    [v0, v1],
                    color=GREY if unknown else color,
                    linewidth=0.8 if (imputed or unknown) else 1.2,
                    linestyle=":" if imputed else "-",
                )
            for (y, v), k in zip(obs, kinds, strict=False):
                if k == "observed":
                    ax.scatter([y], [v], s=7, color=color, zorder=3)
                elif k == "partial":
                    ax.scatter(
                        [y], [v], s=9, facecolors="none", edgecolors=color, linewidths=0.6, zorder=3
                    )
        t = tmap.get(iso3)
        tag = ""
        if t is not None and t["eligible"]:
            tag = " U" if t["u_shape"] else " –"
        elif t is not None:
            tag = " (n/a)"
        n_obs = sum(1 for (y, _) in obs if fmap.get((iso3, y)) == "observed")
        ax.set_title(
            f"{iso3}{tag} obs={n_obs}/{len(obs)}",
            fontsize=8,
            color=h1.ORANGE if iso3 == JAPAN else h1.INK,
        )
        h1._style(ax)  # shared styling within the same analysis package
    for ax in flat[len(codes) :]:
        ax.axis("off")
    handles = [
        Line2D([], [], marker="o", color=h1.BLUE, linestyle="none", markersize=4, label="observed"),
        Line2D(
            [],
            [],
            marker="o",
            markerfacecolor="none",
            markeredgecolor=h1.BLUE,
            linestyle="none",
            markersize=4,
            label="partial (one input interpolated/extrapolated)",
        ),
        Line2D([], [], color=h1.BLUE, linestyle=":", label="imputed (interpolated/extrapolated)"),
        Line2D(
            [], [], color=GREY, linestyle="-", label="unknown (no per-year note in WID metadata)"
        ),
    ]
    fig.legend(handles=handles, loc="lower right", fontsize=7, frameon=False, ncol=4)
    fig.suptitle(
        f"{title}, {lo}-{hi}. Share of adults (equal-split), 0-1. Title: U/– = pre-registered U "
        "criterion on the V1 (observed-only) series, (n/a) = too few observed years; "
        "obs = observed/all years.\nConstruction from WID_metadata `method`; "
        "Source: World Inequality Database (wid.world), CC BY-NC-SA 4.0",
        fontsize=8,
        color=h1.INK,
    )
    fig.tight_layout(rect=(0, 0.03, 1, 0.95))
    fig.savefig(path, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------- reporting
def print_coverage(panel: pl.DataFrame, flags: dict[str, pl.DataFrame]) -> None:
    lo, hi = h1.BASE.window
    for col in SERIES:
        cov = coverage_by_construction(panel, flags[col], col, (lo, hi))
        tot = {k: int(cov[k].sum()) for k in ("n", "observed", "partial", "imputed", "unknown")}
        print(f"== coverage by construction: {col} (window {lo}-{hi}) ==")
        print(
            f"  country-years: n={tot['n']} observed={tot['observed']} "
            f"({tot['observed'] / tot['n']:.3f}) partial={tot['partial']} "
            f"({tot['partial'] / tot['n']:.3f}) imputed={tot['imputed']} "
            f"({tot['imputed'] / tot['n']:.3f}) unknown={tot['unknown']} "
            f"({tot['unknown'] / tot['n']:.3f})"
        )
        with_obs = cov.filter(pl.col("observed") > 0)
        print(
            f"  countries with >=1 observed year: {with_obs.height}/{cov.height}; "
            f"with >=3 observed before {h1.BASE.pre_cut}: "
            f"{_n_pre_observed(panel, flags[col], col)}"
        )
        print(
            f"  {'iso3':<5}{'n':>4}{'obs':>5}{'part':>5}{'imp':>5}{'unk':>5}  first_obs  last_obs"
        )
        for r in cov.iter_rows(named=True):
            fo = r["first_observed"] if r["first_observed"] is not None else "-"
            lo_ = r["last_observed"] if r["last_observed"] is not None else "-"
            print(
                f"  {r['iso3']:<5}{r['n']:>4}{r['observed']:>5}{r['partial']:>5}"
                f"{r['imputed']:>5}{r['unknown']:>5}  {fo!s:>9}  {lo_!s:>8}"
            )


def _n_pre_observed(panel: pl.DataFrame, flags: pl.DataFrame, col: str) -> int:
    lo, _ = h1.BASE.window
    df = (
        panel.filter(pl.col(col).is_not_null() & (pl.col("year") >= lo))
        .join(flags, on=["iso3", "year"], how="left")
        .filter((pl.col("construction") == "observed") & (pl.col("year") < h1.BASE.pre_cut))
        .group_by("iso3")
        .len()
        .filter(pl.col("len") >= h1.BASE.min_obs)
    )
    return df.height


def print_crosstab(quality: pl.DataFrame, flags: dict[str, pl.DataFrame]) -> None:
    print(
        "\n== data_quality x construction (window, both series; rows=construction, "
        "cols=data_quality 0..5) =="
    )
    for col in SERIES:
        q = h1.quality_flags(quality, col)
        ct = quality_by_construction(q, flags[col], h1.BASE.window)
        print(f"  {col}:")
        for cons in [*CONSTRUCTIONS, "unknown"]:
            row = ct.filter(pl.col("construction") == cons)
            counts = {int(r[1]) if r[1] is not None else -1: int(r[2]) for r in row.rows()}
            cells = " ".join(f"q{k}={counts.get(k, 0):>4}" for k in range(6))
            print(f"    {cons:<9} {cells} qNone={counts.get(-1, 0)}")


def print_japan_brief(panel: pl.DataFrame, traj: pl.DataFrame, col: str) -> None:
    r = traj.filter(pl.col("iso3") == JAPAN).row(0, named=True)
    if r["n"] == 0:
        print(f"    JPN {col}: no years left")
        return
    latest = int(str(panel.filter(pl.col(col).is_not_null())["year"].max()))
    rank, n = h1.rank_in_year(panel, col, latest, JAPAN)
    ch = f"{r['change_since_1980']:+.3f}" if r["change_since_1980"] is not None else "n/a"
    print(
        f"    JPN {col}: n={r['n']} eligible={r['eligible']} u_shape={r['u_shape']} "
        f"first {r['first_year']}={r['first']:.3f} trough {r['trough_year']}={r['trough']:.3f} "
        f"last {r['last_year']}={r['last']:.3f} change_since_1980(nearest {r['year_1980']})={ch} "
        f"| rank {latest}: {rank}/{n}"
    )


def run(data_dir: Path, fig_dir: Path) -> None:
    panel = pl.read_parquet(data_dir / h1.MART).sort(["iso3", "year"])
    staged = pl.read_parquet(data_dir / h1.STAGED_SHARES)
    data_points = pl.read_parquet(data_dir / DATA_POINTS)
    fig_dir.mkdir(parents=True, exist_ok=True)
    flags = {col: construction_flags(data_points, col) for col in SERIES}

    print("== inputs ==")
    print(
        f"mart rows={panel.height} data_points rows={data_points.height} "
        f"(variables: {' '.join(sorted(data_points['variable'].unique().to_list()))})"
    )
    print_coverage(panel, flags)
    print_crosstab(staged, flags)

    variants: list[tuple[str, str, set[str] | None, set[str] | None, set[int] | None]] = [
        ("V0", "base (all years, = H1)", None, None, None),
        ("V1", "metadata strict: keep construction == observed", {"observed"}, None, None),
        ("V2", "metadata lenient: drop construction == imputed", None, {"imputed"}, None),
        ("V3", "data_quality proxy: drop data_quality == 0", None, None, {0}),
        ("V4", "data_quality proxy (strong): drop data_quality <= 1", None, None, {0, 1}),
        ("V5", "V2 + V3", None, {"imputed"}, {0}),
    ]
    base_traj: dict[str, pl.DataFrame] = {}
    v1_traj: dict[str, pl.DataFrame] = {}
    for code, name, keep, drop, bad in variants:
        print(f"\n== {code}: {name} ==")
        for col in SERIES:
            p = panel
            if keep is not None or drop is not None:
                p = mask_construction(p, flags[col], col, keep=keep, drop=drop)
            if bad is not None:
                p = h1.drop_quality(p, h1.quality_flags(staged, col), col, bad)
            traj = h1.classify_all(p, col)
            if code == "V0":
                base_traj[col] = traj
            if code == "V1":
                v1_traj[col] = traj
            print("  " + h1.majority_test(traj, f"[M] {code} {col}").line())
            print(
                "  "
                + h1.rise_since_1980_test(traj, f"[A] {code} rise since 1980 > 0: {col}").line()
            )
            elig = traj.filter(pl.col("eligible"))
            # u_shape is an all-null column when nobody is eligible; cast keeps the filter boolean
            u = sorted(elig.filter(pl.col("u_shape").cast(pl.Boolean).fill_null(False))["iso3"])
            print(f"    U-shape countries ({len(u)}): {' '.join(u) or '-'}")
            if code != "V0":
                ch = changed_countries(traj, base_traj[col])
                print(f"    eligibility/U changed vs V0 ({len(ch)}): {' '.join(ch) or '-'}")
                inel = sorted(traj.filter(~pl.col("eligible"))["iso3"].to_list())
                print(f"    ineligible ({len(inel)}): {' '.join(inel) or '-'}")
            print_japan_brief(p, traj, col)

    fig_small_multiples_marked(
        panel,
        flags["top1_wealth_share"],
        v1_traj["top1_wealth_share"],
        "top1_wealth_share",
        fig_dir / "h1b_top1_wealth_small_multiples.png",
        title="Top 1% net personal wealth share (shweal992j p99p100), observed vs imputed",
    )
    fig_small_multiples_marked(
        panel,
        flags["top1_income_share"],
        v1_traj["top1_income_share"],
        "top1_income_share",
        fig_dir / "h1b_top1_income_small_multiples.png",
        title="Top 1% pre-tax national income share (sptinc992j p99p100), observed vs imputed",
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", type=Path, default=REPO_ROOT / "data")
    ap.add_argument("--fig-dir", type=Path, default=THEME_DIR / "reports" / "figures")
    args: Any = ap.parse_args()
    run(args.data_dir, args.fig_dir)


if __name__ == "__main__":
    main()
