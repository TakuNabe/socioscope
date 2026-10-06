"""H4: 超富裕層（上位 0.1% / 0.01%）への集中と、分布全体の分散（Gini・P90/P50・P50/P10・中位 40%）。
記述のみ。因果は主張しない。事前登録: design/themes/wealth-population-distribution.md H4a/H4b
（2026-10-05、分析着手前に記載）。

入力: data/marts/wealth_population_panel.parquet（H4 列を含む）、data/staged/wid/top_shares.parquet
（data_quality、H1c と同じ向きの感度分析）、data/staged/wid/distribution.parquet
（ローレンツ曲線の図）。
乱数なし（2 回実行で stdout・PNG がバイト一致）。H1 の純粋関数（series_in_window, nearest_obs,
wilson_ci, rank_in_year）と H1c の mask_quality は import して使う。

    uv run python themes/wealth-population-distribution/src/theme_wealth_population_distribution/\
analysis/a20261005_h4_superrich_dispersion.py [--data-dir data] [--fig-dir .../reports/figures]

## 事前に固定した仕様（結果を見る前に記載。以下をそのままコードにしている）
共通: 起点 = 1980 年に最も近い観測（窓 1950–2024 内、同距離なら早い年）、終点 = 窓内の最新の観測。
2 つが同じ年なら変化なしとして分母から外す（判定不能として数を報告）。欠損は補完しない。

H4a（超富裕層）
 a1. Δtop1, Δtop0.1, Δtop0.01（所得 sptinc992j、資産 shweal992j）を国別に出す。
 a2. 「トップ内集中」= top0.1 / top1（上位 1% シェアに占める上位 0.1% の割合）。起点→終点の変化
     Δ(top0.1/top1) > 0 の国の数と Wilson 95%。
 a3. 事前基準: Δtop1 > 0 の国（上位 1% が上昇した国）のうち **Δtop0.1 ≥ 0.5 × Δtop1** を満たす国の
     割合（Wilson 95%、片側二項 p は目安）。Δtop1 ≤ 0 の国は別に数える（基準の対象外）。
 a4. 日本: Δtop1, Δtop0.1, Δ(top0.1/top1) の値と、Δ(top0.1/top1) の順位（1 = 最大）と他国中央値。
     事前登録の主張「日本のトップ内集中の上昇は他国の中央値より弱い」を
     Δ(top0.1/top1) < 中央値 で判定。
 a5. 資産は同じ a1–a4 に加え、data_quality ≤ 1 の国×年を欠損化した感度分析
     （H1c の V-A と同じ向き）。
H4b（分布全体の分散）
 b1. 国別の Δ: Gini, bottom50, middle40, top10, top1, P90/P50, P50/P10（所得。資産は閾値が無ければ
     Gini・シェアのみ）。
 b2. 分解: Δtop10 = Δtop1 + Δp90p99（p90p99 = top10 − top1）。Δp90p99 > Δtop1 の国の数。
 b3. 日本の事前登録パターン: **Δtop10 > Δtop1 かつ Δbottom50 < 0**（所得）。日本が満たすか、
     同じパターンの国の数と Wilson 95%。
 b4. 各指標の日本の値 vs 46 か国中央値（日本を除く）。
 b5. WID の Gini は 127 の一般化百分位ブラケットのローレンツ曲線の台形近似（ブラケット内の不平等を
     無視するため真の Gini より小さい）。公式統計の Gini（World Bank 等）との照合は将来課題で、
     本稿では行わない。
 b6. **事後追加（探索的、2026-10-06 に実データを見てから）**: WID の所得 P10 閾値が事実上 0 の国
     （ARG BRA CHL COL CRI MEX RUS の一部年）で P50/P10 が数百〜数千に発散するため、比 > 20 を
     欠損化した P50/P10 の集計を併記する（P50_P10_CAP）。資産は P10 が国×年の 57% で ≤ 0
     （純資産が負）なので P50/P10 を表から外す。事前登録の指標そのものは b1 でそのまま報告する。
図（英語ラベル、日本をオレンジで強調、出典 WID.world CC BY-NC-SA 4.0）:
 h4_top1_vs_top01_income_small_multiples.png, h4_within_top_change_dots.png,
 h4_lorenz_japan_vs_reference.png, h4_who_holds_what_stacked.png, h4_gini_p90p50_trajectories.png。
純粋関数は tests/test_analysis_h4.py で検証する。
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from theme_wealth_population_distribution import distribution as d
from theme_wealth_population_distribution.analysis import a20261004_h1_ushape as h1
from theme_wealth_population_distribution.analysis import a20261005_h1c_quality_corrected as h1c

THEME_DIR = Path(__file__).resolve().parents[3]
REPO_ROOT = THEME_DIR.parents[1]
DISTRIBUTION = Path("staged") / "wid" / "distribution.parquet"

JAPAN = h1.JAPAN
WINDOW = h1.BASE.window  # (1950, 2024)
START = 1980
WITHIN_TOP_FRACTION = 0.5  # a3: Δtop0.1 >= 0.5 × Δtop1
P50_P10_CAP = 20.0  # b6 (post-hoc): P50/P10 above this is treated as undefined (P10 ~ 0)
REFERENCE: tuple[str, ...] = ("USA", "FRA", "SWE")  # Lorenz comparison
STACK_COUNTRIES: tuple[str, ...] = ("JPN", "USA", "FRA", "DEU", "SWE", "GBR")

INCOME_COLS: dict[str, str] = {  # short name -> mart column
    "top1": "top1_income_share",
    "top01": "top01_income_share",
    "top001": "top001_income_share",
    "top10": "top10_income_share",
    "bottom50": "bottom50_income_share",
    "middle40": "middle40_income_share",
    "gini": "gini_income",
    "p90_p50": "p90_p50_income",
    "p50_p10": "p50_p10_income",
}
WEALTH_COLS: dict[str, str] = {
    "top1": "top1_wealth_share",
    "top01": "top01_wealth_share",
    "top001": "top001_wealth_share",
    "top10": "top10_wealth_share",
    "middle40": "middle40_wealth_share",
    "gini": "gini_wealth",
    "p90_p50": "p90_p50_wealth",
    "p50_p10": "p50_p10_wealth",
}
BLUE, ORANGE, INK, MUTED = h1.BLUE, h1.ORANGE, h1.INK, h1.MUTED
AQUA, YELLOW, MAGENTA, GREEN = "#1baf7a", "#eda100", "#e87ba4", "#008300"
REF_COLOR: dict[str, str] = {
    "USA": BLUE,
    "FRA": AQUA,
    "SWE": GREEN,
    "DEU": MAGENTA,
    "GBR": YELLOW,
    JAPAN: ORANGE,
}


# ---------------------------------------------------------------- pure helpers (tested)
def long_change(
    panel: pl.DataFrame, col: str, *, start: int = START, window: tuple[int, int] = WINDOW
) -> pl.DataFrame:
    """国別: start に最も近い観測（year0, v0）と窓内最新の観測（year1, v1）、change = v1 − v0。
    観測が 1 つしか無い（year0 == year1）国は落とす。欠損は補完しない。"""
    rows: list[dict[str, Any]] = []
    for iso3 in sorted(panel["iso3"].unique().to_list()):
        obs = h1.series_in_window(panel, iso3, col, window)
        near = h1.nearest_obs(obs, start)
        if near is None or near[0] == obs[-1][0]:
            continue
        rows.append(
            {
                "iso3": iso3,
                "year0": near[0],
                "v0": near[1],
                "year1": obs[-1][0],
                "v1": obs[-1][1],
                "change": obs[-1][1] - near[1],
            }
        )
    return pl.DataFrame(
        rows,
        schema={
            "iso3": pl.Utf8,
            "year0": pl.Int64,
            "v0": pl.Float64,
            "year1": pl.Int64,
            "v1": pl.Float64,
            "change": pl.Float64,
        },
    )


def change_table(
    panel: pl.DataFrame, cols: list[str], *, start: int = START, how: str = "inner"
) -> pl.DataFrame:
    """iso3 × d_<col> の横持ち。how="inner": 全列に変化がある国だけ。how="full": どれか 1 列でも
    変化がある国を残し、無い列は null（記述表用。補完はしない）。"""
    out: pl.DataFrame | None = None
    for col in cols:
        c = long_change(panel, col, start=start).select("iso3", pl.col("change").alias(f"d_{col}"))
        out = c if out is None else out.join(c, on="iso3", how=how, coalesce=True)  # type: ignore[arg-type]
    assert out is not None
    return out.sort("iso3")


def cap_ratio(panel: pl.DataFrame, col: str, *, cap: float) -> pl.DataFrame:
    """col（閾値比）が cap を超える国×年を欠損化する（行は残す、補完しない）。

    事後的な扱い（結果を見てから追加、report に「探索的」と明記）: WID の P10 閾値が事実上 0
    （数十〜数千の現地通貨単位）の国では P50/P10 が数百〜数十万に発散し、変化量の中央値・順位が
    無意味になるため、cap（既定 20）を超える比は「定義不能」として落とす。
    """
    return panel.with_columns(
        pl.when(pl.col(col) > cap).then(None).otherwise(pl.col(col)).alias(col)
    )


@dataclass(frozen=True)
class WithinTopResult:
    rising: list[str]  # Δtop1 > 0
    not_rising: list[str]  # Δtop1 <= 0 (criterion not applicable)
    concentrated: list[str]  # rising and Δtop0.1 >= frac × Δtop1
    k: int
    n: int
    ci: tuple[float, float]
    p_one_sided: float


def within_top_test(
    t: pl.DataFrame, fine: str, coarse: str, *, frac: float = WITHIN_TOP_FRACTION
) -> WithinTopResult:
    """a3: Δtop1 > 0 の国のうち Δtop0.1 >= frac × Δtop1 を満たす国の割合。"""
    rising = t.filter(pl.col(coarse) > 0)
    not_rising = t.filter(pl.col(coarse) <= 0)["iso3"].to_list()
    conc = rising.filter(pl.col(fine) >= frac * pl.col(coarse))["iso3"].to_list()
    k, n = len(conc), rising.height
    return WithinTopResult(
        rising["iso3"].to_list(),
        not_rising,
        conc,
        k,
        n,
        h1.wilson_ci(k, n),
        h1.binom_test_majority(k, n),
    )


def ratio_change(
    panel: pl.DataFrame, fine: str, coarse: str, *, start: int = START
) -> pl.DataFrame:
    """a2: 起点と終点それぞれで fine/coarse（例 top0.1/top1）を取り、その変化を国別に出す。
    両列が同じ年に観測されている国だけ（起点・終点は coarse に合わせる）。"""
    a = long_change(panel, coarse, start=start)
    rows: list[dict[str, Any]] = []
    for r in a.iter_rows(named=True):
        f = panel.filter(pl.col("iso3") == r["iso3"])
        f0 = f.filter(pl.col("year") == r["year0"])[fine]
        f1 = f.filter(pl.col("year") == r["year1"])[fine]
        if f0.is_empty() or f1.is_empty() or f0[0] is None or f1[0] is None:
            continue
        r0 = d.top_within_share(float(f0[0]), r["v0"])
        r1 = d.top_within_share(float(f1[0]), r["v1"])
        if r0 is None or r1 is None:
            continue
        rows.append(
            {
                "iso3": r["iso3"],
                "year0": r["year0"],
                "ratio0": r0,
                "year1": r["year1"],
                "ratio1": r1,
                "d_ratio": r1 - r0,
            }
        )
    return pl.DataFrame(
        rows,
        schema={
            "iso3": pl.Utf8,
            "year0": pl.Int64,
            "ratio0": pl.Float64,
            "year1": pl.Int64,
            "ratio1": pl.Float64,
            "d_ratio": pl.Float64,
        },
    )


def dispersion_pattern(t: pl.DataFrame, *, suffix: str = "_income_share") -> pl.DataFrame:
    """b3: pattern = (Δtop10 > Δtop1) かつ (Δbottom50 < 0)。"""
    top10, top1, b50 = (f"d_top10{suffix}", f"d_top1{suffix}", f"d_bottom50{suffix}")
    return t.select(
        "iso3", ((pl.col(top10) > pl.col(top1)) & (pl.col(b50) < 0)).alias("pattern")
    ).sort("iso3")


def decompose_top10(t: pl.DataFrame, *, suffix: str = "_income_share") -> pl.DataFrame:
    """b2: Δtop10 = Δtop1 + Δp90p99。"""
    return t.select(
        "iso3",
        pl.col(f"d_top10{suffix}").alias("d_top10"),
        pl.col(f"d_top1{suffix}").alias("d_top1"),
        (pl.col(f"d_top10{suffix}") - pl.col(f"d_top1{suffix}")).alias("d_p90p99"),
    ).sort("iso3")


def rank_desc(t: pl.DataFrame, col: str, iso3: str) -> tuple[int | None, int]:
    """col の降順順位（1 = 最大）と非欠損国数。"""
    df = t.filter(pl.col(col).is_not_null()).sort([col, "iso3"], descending=[True, False])
    codes = df["iso3"].to_list()
    return (codes.index(iso3) + 1 if iso3 in codes else None), len(codes)


def median_others(t: pl.DataFrame, col: str, iso3: str) -> float | None:
    s = t.filter((pl.col("iso3") != iso3) & pl.col(col).is_not_null())[col]
    return None if s.is_empty() else float(str(s.median()))


def lorenz_curve(
    dist: pl.DataFrame, iso3: str, year: int, variable: str
) -> list[tuple[float, float]] | None:
    """staged/wid/distribution の 127 g-percentile ブラケットからローレンツ曲線。欠けると None。"""
    g = frozenset(d.g_percentiles())
    rows = dist.filter(
        (pl.col("iso3") == iso3)
        & (pl.col("year") == year)
        & (pl.col("variable") == variable)
        & pl.col("percentile").is_in(sorted(g))
    )
    if rows.height != len(g):
        return None
    brackets = [
        (float(r["p_lower"]), float(r["p_upper"]), float(r["share"]))
        for r in rows.iter_rows(named=True)
    ]
    try:
        return d.lorenz_points(brackets)
    except ValueError:
        return None


# ---------------------------------------------------------------- figures
def _style(ax: Any) -> None:
    h1._style(ax)


def _src(fig: Any, extra: str = "") -> None:
    fig.text(
        0.01,
        0.005,
        "Source: World Inequality Database (wid.world), CC BY-NC-SA 4.0. " + extra,
        fontsize=7,
        color=MUTED,
        ha="left",
        va="bottom",
    )


def _save(fig: Any, path: Path) -> None:
    import matplotlib.pyplot as plt

    fig.savefig(path, dpi=150, metadata={"Software": None})
    plt.close(fig)


def fig_small_multiples_top1_top01(panel: pl.DataFrame, path: Path) -> None:
    import matplotlib
    import matplotlib.pyplot as plt

    matplotlib.use("Agg")
    codes = sorted(panel["iso3"].unique().to_list())
    ncol = 8
    nrow = math.ceil(len(codes) / ncol)
    fig, axes = plt.subplots(
        nrow, ncol, figsize=(1.9 * ncol, 1.7 * nrow + 0.8), sharex=True, squeeze=False
    )
    flat = [ax for row in axes for ax in row]
    for ax, iso3 in zip(flat, codes, strict=False):
        c = ORANGE if iso3 == JAPAN else BLUE
        t1 = h1.series_in_window(panel, iso3, "top1_income_share", WINDOW)
        t01 = h1.series_in_window(panel, iso3, "top01_income_share", WINDOW)
        ax.plot([y for y, _ in t1], [v for _, v in t1], color=c, linewidth=1.3)
        ax.plot([y for y, _ in t01], [v for _, v in t01], color=c, linewidth=1.0, linestyle="--")
        ax.set_ylim(0, 0.3)
        ax.set_title(f"{iso3} n={len(t1)}", fontsize=8, color=ORANGE if iso3 == JAPAN else INK)
        _style(ax)
    for ax in flat[len(codes) :]:
        ax.axis("off")
    fig.suptitle(
        "Top 1% (solid) and top 0.1% (dashed) pre-tax national income shares, 1950-2024 "
        "(sptinc992j p99p100 / p99.9p100; adults, equal-split; share 0-1)",
        fontsize=9,
        color=INK,
    )
    _src(fig, "Japan in orange. Top 0.1% tails are Pareto-interpolated by WID.")
    fig.tight_layout(rect=(0, 0.02, 1, 0.96))
    _save(fig, path)


def fig_within_top_dots(t: pl.DataFrame, res: WithinTopResult, path: Path, *, title: str) -> None:
    import matplotlib
    import matplotlib.pyplot as plt

    matplotlib.use("Agg")
    df = t.filter(pl.col("iso3").is_in(res.rising)).with_columns(
        (pl.col("d_fine") / pl.col("d_coarse")).alias("share_of_rise")
    )
    df = df.sort("share_of_rise")
    fig, ax = plt.subplots(figsize=(6.8, 0.22 * df.height + 1.8))
    ys = list(range(df.height))
    for y, r in zip(ys, df.iter_rows(named=True), strict=True):
        jp = r["iso3"] == JAPAN
        ax.plot([0, r["share_of_rise"]], [y, y], color="#e5e5e5", linewidth=1, zorder=1)
        ax.scatter(
            r["share_of_rise"], y, s=30 if jp else 16, color=ORANGE if jp else BLUE, zorder=3
        )
    ax.axvline(WITHIN_TOP_FRACTION, color=INK, linewidth=0.9, linestyle="--")
    ax.text(
        WITHIN_TOP_FRACTION + 0.02,
        -0.6,
        f"pre-registered criterion {WITHIN_TOP_FRACTION:.1f}",
        fontsize=7,
        color=INK,
    )
    ax.set_yticks(ys)
    ax.set_yticklabels(df["iso3"].to_list(), fontsize=6.5)
    for lab in ax.get_yticklabels():
        if lab.get_text() == JAPAN:
            lab.set_color(ORANGE)
            lab.set_fontweight("bold")
    ax.set_xlabel("Δ top 0.1% share / Δ top 1% share (1980 → latest)", fontsize=8, color=INK)
    ax.set_title(
        f"{title}: {res.k}/{res.n} countries with a rising top 1% meet the criterion\n"
        f"(Wilson 95% [{res.ci[0]:.2f}, {res.ci[1]:.2f}]); "
        f"{len(res.not_rising)} countries with a non-rising top 1% are excluded",
        fontsize=8,
        color=INK,
        loc="left",
    )
    _style(ax)
    _src(fig)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    _save(fig, path)


def fig_lorenz(dist: pl.DataFrame, panel: pl.DataFrame, path: Path) -> None:
    import matplotlib
    import matplotlib.pyplot as plt

    matplotlib.use("Agg")
    fig, axes = plt.subplots(1, 2, figsize=(9.5, 4.6))
    var = "sptinc992j"
    for ax, (iso3s, head) in zip(
        axes,
        (
            ([JAPAN], "Japan, 1980 vs latest"),
            ([JAPAN, *REFERENCE], "Latest year: Japan vs USA / FRA / SWE"),
        ),
        strict=True,
    ):
        ax.plot([0, 1], [0, 1], color=MUTED, linewidth=0.8, linestyle=":")
        for iso3 in iso3s:
            years = sorted(
                dist.filter((pl.col("iso3") == iso3) & (pl.col("variable") == var))["year"]
                .unique()
                .to_list()
            )
            years = [y for y in years if WINDOW[0] <= y <= WINDOW[1]]
            if not years:
                continue
            picks = (
                [min(years, key=lambda y: abs(y - START)), years[-1]]
                if len(iso3s) == 1
                else [years[-1]]
            )
            for y, style in zip(picks, (":", "-") if len(picks) == 2 else ("-",), strict=True):
                pts = lorenz_curve(dist, iso3, y, var)
                if pts is None:
                    continue
                g = panel.filter((pl.col("iso3") == iso3) & (pl.col("year") == y))["gini_income"]
                gtxt = f", Gini {float(g[0]):.3f}" if not g.is_empty() and g[0] is not None else ""
                ax.plot(
                    [p for p, _ in pts],
                    [v for _, v in pts],
                    color=REF_COLOR.get(iso3, BLUE),
                    linewidth=2.0 if iso3 == JAPAN else 1.3,
                    linestyle=style,
                    label=f"{iso3} {y}{gtxt}",
                )
        ax.set_xlabel("cumulative share of adults", fontsize=8, color=INK)
        ax.set_ylabel("cumulative share of pre-tax national income", fontsize=8, color=INK)
        ax.set_title(head, fontsize=9, color=INK, loc="left")
        ax.legend(frameon=False, fontsize=7)
        _style(ax)
    fig.suptitle(
        "Lorenz curves from WID's 127 generalized percentiles (sptinc992j). "
        "Gini = trapezoid approximation (understates within-bracket inequality)",
        fontsize=9,
        color=INK,
    )
    _src(fig)
    fig.tight_layout(rect=(0, 0.03, 1, 0.94))
    _save(fig, path)


def fig_who_holds_what(panel: pl.DataFrame, path: Path) -> None:
    import matplotlib
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    matplotlib.use("Agg")
    groups = ("bottom 50%", "middle 40%", "p90-p99", "top 1%")
    colors = ("#cde2fb", "#6da7ec", "#256abf", ORANGE)
    fig, ax = plt.subplots(figsize=(9.5, 4.6))
    x = 0.0
    ticks: list[tuple[float, str]] = []
    for iso3 in STACK_COUNTRIES:
        ch = long_change(panel, "top1_income_share").filter(pl.col("iso3") == iso3)
        if ch.is_empty():
            continue
        r = ch.row(0, named=True)
        for y in (r["year0"], r["year1"]):
            row = panel.filter((pl.col("iso3") == iso3) & (pl.col("year") == y)).row(0, named=True)
            vals = [
                row["bottom50_income_share"],
                row["middle40_income_share"],
                row["top10_income_share"] - row["top1_income_share"],
                row["top1_income_share"],
            ]
            if any(v is None for v in vals):
                continue
            bottom = 0.0
            for v, c in zip(vals, colors, strict=True):
                ax.bar(x, v, bottom=bottom, color=c, width=0.8, edgecolor="white", linewidth=0.5)
                ax.text(x, bottom + v / 2, f"{v * 100:.0f}", ha="center", va="center", fontsize=6.5)
                bottom += v
            ticks.append((x, f"{iso3}\n{y}"))
            x += 1
        x += 0.6
    ax.set_xticks([t for t, _ in ticks])
    ax.set_xticklabels([lab for _, lab in ticks], fontsize=7)
    for lab in ax.get_xticklabels():
        if lab.get_text().startswith(JAPAN):
            lab.set_color(ORANGE)
            lab.set_fontweight("bold")
    ax.set_ylim(0, 1)
    ax.set_ylabel("share of pre-tax national income", fontsize=8, color=INK)
    ax.legend(
        handles=[Patch(facecolor=c, label=g) for g, c in zip(groups, colors, strict=True)],
        loc="upper left",
        bbox_to_anchor=(1.0, 1.0),
        frameon=False,
        fontsize=8,
    )
    ax.set_title(
        "Who holds what: income shares by group, ~1980 vs latest (sptinc992j; adults, equal-split)",
        fontsize=9,
        color=INK,
        loc="left",
    )
    _style(ax)
    _src(fig, "Numbers are % of total income.")
    fig.tight_layout(rect=(0, 0.03, 0.86, 1))
    _save(fig, path)


def fig_trajectories(panel: pl.DataFrame, path: Path) -> None:
    import matplotlib
    import matplotlib.pyplot as plt

    matplotlib.use("Agg")
    cols = (("gini_income", "Gini (WID, trapezoid)"), ("p90_p50_income", "P90 / P50"))
    fig, axes = plt.subplots(1, 2, figsize=(9.5, 4.0))
    codes = sorted(panel["iso3"].unique().to_list())
    for ax, (col, label) in zip(axes, cols, strict=True):
        for iso3 in codes:
            if iso3 == JAPAN:
                continue
            obs = h1.series_in_window(panel, iso3, col, WINDOW)
            ax.plot([y for y, _ in obs], [v for _, v in obs], color=BLUE, alpha=0.2, linewidth=0.7)
        med = (
            panel.filter(pl.col(col).is_not_null() & (pl.col("year") >= START))
            .group_by("year")
            .agg(pl.col(col).median().alias("m"), pl.len().alias("n"))
            .sort("year")
        )
        ax.plot(med["year"], med["m"], color=INK, linewidth=1.8, label="cross-country median")
        jp = h1.series_in_window(panel, JAPAN, col, WINDOW)
        ax.plot([y for y, _ in jp], [v for _, v in jp], color=ORANGE, linewidth=2.2, label="Japan")
        n_last = int(med["n"][-1]) if med.height else 0
        ax.set_title(
            f"{label} (n={n_last} countries in last year)", fontsize=9, color=INK, loc="left"
        )
        ax.set_xlabel("year", fontsize=8, color=INK)
        ax.legend(frameon=False, fontsize=7)
        _style(ax)
    fig.suptitle(
        "Pre-tax national income: Japan vs the field, 1950-2024 "
        "(sptinc992j; thresholds tptinc992j)",
        fontsize=9,
        color=INK,
    )
    _src(fig, "WID Gini differs from official (survey-based) Gini; not compared here.")
    fig.tight_layout(rect=(0, 0.03, 1, 0.94))
    _save(fig, path)


# ---------------------------------------------------------------- reporting
def _fmt(v: float | None, *, pct: bool = True) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "n/a"
    return f"{v * 100:+.2f}pp" if pct else f"{v:+.3f}"


def print_coverage(panel: pl.DataFrame, cols: dict[str, str]) -> None:
    lo, hi = WINDOW
    for name, col in cols.items():
        if col not in panel.columns:
            print(f"  {name:<9} {col}: column missing")
            continue
        nn = panel.filter(
            pl.col(col).is_not_null() & (pl.col("year") >= lo) & (pl.col("year") <= hi)
        )
        n_c = nn["iso3"].n_unique()
        yrs = (int(str(nn["year"].min())), int(str(nn["year"].max()))) if nn.height else (0, 0)
        print(
            f"  {name:<9} {col}: country-years={nn.height} countries={n_c} years={yrs[0]}-{yrs[1]}"
        )


def print_changes(panel: pl.DataFrame, cols: dict[str, str], label: str) -> pl.DataFrame:
    present = [c for c in cols.values() if c in panel.columns]
    t = change_table(panel, present, how="full")
    print(f"== {label}: change {START} (nearest) -> latest, per country (pp unless ratio) ==")
    short = {v: k for k, v in cols.items()}
    head = "".join(f"{short[c]:>10}" for c in present)
    print(f"  {'iso3':<5}{head}")

    def cell(c: str, v: float | None) -> str:
        if v is None:
            return f"{'n/a':>10}"
        if "p90" in c or "p50_" in c or "gini" in c:
            return f"{v:>+10.3f}"
        return f"{v * 100:>+9.2f}p"

    for r in t.iter_rows(named=True):
        print(f"  {r['iso3']:<5}" + "".join(cell(c, r[f"d_{c}"]) for c in present))
    print(f"  n={t.height} countries with both endpoints for at least one listed series")
    for c in present:
        col = f"d_{c}"
        med = median_others(t, col, JAPAN)
        jp = t.filter(pl.col("iso3") == JAPAN)
        jpv = float(jp[col][0]) if jp.height and jp[col][0] is not None else None
        rank, n = rank_desc(t, col, JAPAN)
        up = int((t[col] > 0).sum())
        print(
            f"  {short[c]:<9} rose in {up}/{n}; "
            f"median(others)={'n/a' if med is None else f'{med:+.4f}'}; "
            f"JPN={'n/a' if jpv is None else f'{jpv:+.4f}'} rank={rank}/{n} (1 = largest increase)"
        )
    return t


def run_h4a(panel: pl.DataFrame, cols: dict[str, str], label: str, fig_dir: Path | None) -> None:
    print(f"\n== H4a ({label}): within-top concentration ==")
    t = change_table(panel, [cols["top1"], cols["top01"]])
    t = t.rename({f"d_{cols['top1']}": "d_coarse", f"d_{cols['top01']}": "d_fine"})
    res = within_top_test(t, "d_fine", "d_coarse")
    share = res.k / res.n if res.n else math.nan
    print(
        f"  [a3] Δtop1>0: {res.n} countries; Δtop0.1 >= {WITHIN_TOP_FRACTION}×Δtop1: "
        f"{res.k}/{res.n} share={share:.3f} wilson95=[{res.ci[0]:.3f}, {res.ci[1]:.3f}] "
        f"p(one-sided, H0 p=0.5)={res.p_one_sided:.4f}"
    )
    print(f"    concentrated: {' '.join(res.concentrated) or '-'}")
    diffuse = sorted(set(res.rising) - set(res.concentrated))
    print(f"    rising but diffuse: {' '.join(diffuse) or '-'}")
    print(
        f"    Δtop1 <= 0 (criterion n/a, {len(res.not_rising)}): {' '.join(res.not_rising) or '-'}"
    )
    rc = ratio_change(panel, cols["top01"], cols["top1"])
    up = int((rc["d_ratio"] > 0).sum())
    ci = h1.wilson_ci(up, rc.height)
    med_ratio = float(str(rc["d_ratio"].median())) if rc.height else math.nan
    print(
        f"  [a2] Δ(top0.1/top1) > 0: {up}/{rc.height} "
        f"share={up / rc.height if rc.height else math.nan:.3f} "
        f"wilson95=[{ci[0]:.3f}, {ci[1]:.3f}]; median Δ(top0.1/top1)={med_ratio:+.4f}"
    )
    print(f"  {'iso3':<5}{'year0':>6}{'ratio0':>8}{'year1':>6}{'ratio1':>8}{'d_ratio':>9}")
    for r in rc.iter_rows(named=True):
        print(
            f"  {r['iso3']:<5}{r['year0']:>6}{r['ratio0']:>8.3f}{r['year1']:>6}{r['ratio1']:>8.3f}"
            f"{r['d_ratio']:>+9.4f}"
        )
    jp = rc.filter(pl.col("iso3") == JAPAN)
    jt = t.filter(pl.col("iso3") == JAPAN)
    if jp.height and jt.height:
        r = jp.row(0, named=True)
        rank, n = rank_desc(rc, "d_ratio", JAPAN)
        med = median_others(rc, "d_ratio", JAPAN)
        weaker = med is not None and r["d_ratio"] < med
        d1, d01 = _fmt(float(jt["d_coarse"][0])), _fmt(float(jt["d_fine"][0]))
        print(
            f"  [a4] JPN Δtop1={d1} Δtop0.1={d01} "
            f"top0.1/top1 {r['year0']}={r['ratio0']:.3f} -> {r['year1']}={r['ratio1']:.3f} "
            f"Δ={r['d_ratio']:+.4f} rank={rank}/{n} (1 = largest rise) median(others)={med:+.4f} "
            f"-> JPN weaker than median: {weaker}; meets a3 criterion: {JAPAN in res.concentrated}"
        )
    else:
        print("  [a4] JPN: not enough data")
    if cols.get("top001") in panel.columns:
        t2 = change_table(panel, [cols["top1"], cols["top001"]])
        up2 = int((t2[f"d_{cols['top001']}"] > 0).sum())
        print(f"  [a1] Δtop0.01 > 0: {up2}/{t2.height}")
    if fig_dir is not None:
        fig_within_top_dots(
            t, res, fig_dir / f"h4_within_top_change_dots_{label}.png", title=f"H4a {label}"
        )


def run_h4b(panel: pl.DataFrame) -> None:
    print("\n== H4b (income): dispersion across the whole distribution ==")
    t = print_changes(panel, INCOME_COLS, "H4b income")
    dec = decompose_top10(t)
    n_p90 = int((dec["d_p90p99"] > dec["d_top1"]).sum())
    print(
        f"  [b2] Δtop10 = Δtop1 + Δp90p99: Δp90p99 > Δtop1 in {n_p90}/{dec.height}; "
        f"median Δtop1={float(str(dec['d_top1'].median())) * 100:+.2f}pp "
        f"median Δp90p99={float(str(dec['d_p90p99'].median())) * 100:+.2f}pp"
    )
    pat = dispersion_pattern(t)
    k = int(pat["pattern"].sum())
    ci = h1.wilson_ci(k, pat.height)
    jp = pat.filter(pl.col("iso3") == JAPAN)
    print(
        f"  [b3] pattern (Δtop10 > Δtop1 and Δbottom50 < 0): {k}/{pat.height} "
        f"share={k / pat.height:.3f} wilson95=[{ci[0]:.3f}, {ci[1]:.3f}]; "
        f"JPN meets it: {bool(jp['pattern'][0]) if jp.height else 'n/a'}"
    )
    print(f"    countries: {' '.join(pat.filter(pl.col('pattern'))['iso3'].to_list()) or '-'}")
    jd = dec.filter(pl.col("iso3") == JAPAN)
    if jd.height:
        r = jd.row(0, named=True)
        print(
            f"  [b2 JPN] Δtop10={r['d_top10'] * 100:+.2f}pp = Δtop1 {r['d_top1'] * 100:+.2f}pp "
            f"+ Δp90p99 {r['d_p90p99'] * 100:+.2f}pp"
        )
    print(
        "  [b5] WID Gini is a trapezoid approximation over 127 g-percentile brackets; "
        "comparison with official (World Bank / survey) Gini is a future task."
    )
    print(
        f"  [b6, post-hoc/exploratory] P50/P10 with ratios > {P50_P10_CAP} nulled "
        "(WID P10 thresholds near zero make the ratio meaningless):"
    )
    capped = cap_ratio(panel, INCOME_COLS["p50_p10"], cap=P50_P10_CAP)
    tc = change_table(capped, [INCOME_COLS["p50_p10"]])
    col = f"d_{INCOME_COLS['p50_p10']}"
    med = median_others(tc, col, JAPAN)
    rank, n = rank_desc(tc, col, JAPAN)
    jp = tc.filter(pl.col("iso3") == JAPAN)
    up = int((tc[col] > 0).sum())
    dropped = sorted(set(t["iso3"].to_list()) - set(tc["iso3"].to_list()))
    print(
        f"    n={tc.height} (dropped: {' '.join(dropped) or '-'}); rose in {up}/{tc.height}; "
        f"median(others)={'n/a' if med is None else f'{med:+.4f}'}; "
        f"JPN={f'{float(jp[col][0]):+.4f}' if jp.height else 'n/a'} rank={rank}/{n}"
    )


def run(data_dir: Path, fig_dir: Path) -> None:
    panel = pl.read_parquet(data_dir / h1.MART).sort(["iso3", "year"])
    staged = pl.read_parquet(data_dir / h1.STAGED_SHARES)
    dist = pl.read_parquet(data_dir / DISTRIBUTION)
    fig_dir.mkdir(parents=True, exist_ok=True)
    print("== inputs ==")
    print(
        f"mart rows={panel.height} countries={panel['iso3'].n_unique()} "
        f"staged top_shares rows={staged.height} distribution rows={dist.height}"
    )
    print("== coverage (window 1950-2024): income ==")
    print_coverage(panel, INCOME_COLS)
    print("== coverage (window 1950-2024): wealth ==")
    print_coverage(panel, WEALTH_COLS)
    # middle-40 consistency check against WID's own p50p90 bracket
    p5090 = staged.filter(pl.col("percentile") == "p50p90").select(
        "iso3", "year", "variable", pl.col("value").alias("p50p90")
    )
    for var, col in (
        ("sptinc992j", "middle40_income_share"),
        ("shweal992j", "middle40_wealth_share"),
    ):
        j = (
            panel.select("iso3", "year", col)
            .join(p5090.filter(pl.col("variable") == var), on=["iso3", "year"], how="inner")
            .drop_nulls()
        )
        gap = (j[col] - j["p50p90"]).abs()
        worst = float(str(gap.max())) if j.height else math.nan
        print(f"  check {col} vs WID p50p90: n={j.height} max|diff|={worst:.2e}")

    run_h4a(panel, INCOME_COLS, "income", fig_dir)
    run_h4a(panel, WEALTH_COLS, "wealth", fig_dir)
    print("\n== H4a (wealth) sensitivity: null-out data_quality <= 1 (H1c V-A direction) ==")
    masked = panel
    for col in (WEALTH_COLS["top1"], WEALTH_COLS["top01"]):
        flags = h1.quality_flags(staged, "top1_wealth_share")  # same quality for all percentiles
        masked = h1c.mask_quality(masked, flags, col, drop_le=1)
    run_h4a(masked, WEALTH_COLS, "wealth_q>1", None)

    run_h4b(panel)
    print(
        "\n== H4b (wealth, descriptive). P50/P10 omitted: WID wealth P10 is <= 0 in most "
        "country-years (negative net wealth), P90/P50 kept but P50 can be near zero =="
    )
    print_changes(
        panel,
        {
            k: v
            for k, v in WEALTH_COLS.items()
            if k in ("top1", "top10", "middle40", "gini", "p90_p50")
        },
        "H4b wealth",
    )

    fig_small_multiples_top1_top01(panel, fig_dir / "h4_top1_vs_top01_income_small_multiples.png")
    fig_lorenz(dist, panel, fig_dir / "h4_lorenz_japan_vs_reference.png")
    fig_who_holds_what(panel, fig_dir / "h4_who_holds_what_stacked.png")
    fig_trajectories(panel, fig_dir / "h4_gini_p90p50_trajectories.png")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", type=Path, default=REPO_ROOT / "data")
    ap.add_argument("--fig-dir", type=Path, default=THEME_DIR / "reports" / "figures")
    args: Any = ap.parse_args()
    run(args.data_dir, args.fig_dir)


if __name__ == "__main__":
    main()
