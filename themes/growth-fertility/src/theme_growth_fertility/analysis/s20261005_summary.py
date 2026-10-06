"""総括レポート（note.com 向け、日本語・一般読者）用の図を生成する決定的スクリプト。

H1〜H5 の 6 レポートの数値を、同じ mart から**再計算**して 18 枚の図にする（新しい推定は行わない。
既存スクリプト a20261004_h1 / h2 / h3 / h3b / a20261005_h4 / a20261006_h5 の関数で再計算し、
標準出力に数値を出す。乱数は使わない）。

    uv run python themes/growth-fertility/src/theme_growth_fertility/analysis/s20261005_summary.py \
        [--data-dir data] [--fig-dir themes/growth-fertility/reports/figures/summary]

図は日本語フォント（Hiragino Sans → Hiragino Maru Gothic Pro → Noto Sans CJK JP → IPAexGothic →
Yu Gothic の順に検出。無ければ DejaVu Sans で警告）、150 dpi、PNG メタデータの Software を落として
バイト単位で再現可能にする。純粋なデータ準備ヘルパ（choose_font, year_slice, country_trails,
tfr_in_year, japan_series, dollar_ticks, wave_curves, sign_word, ladder_items, band_profiles）は
tests/test_summary.py で検証する。
"""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from theme_growth_fertility.analysis import a20261004_h1_income_tfr as h1
from theme_growth_fertility.analysis import a20261004_h2_growth_shocks as h2
from theme_growth_fertility.analysis import a20261004_h3_jp_income_class as h3
from theme_growth_fertility.analysis import a20261004_h3b_age_adjusted as h3b
from theme_growth_fertility.analysis import a20261005_h4_stage_vs_gdp as h4
from theme_growth_fertility.analysis import a20261006_h5_europe_korea_policy as h5

THEME_DIR = Path(__file__).resolve().parents[3]
REPO_ROOT = THEME_DIR.parents[1]
PANEL = Path("marts") / "growth_fertility_panel.parquet"
JP_MART = Path("marts") / "jp_income_class_fertility.parquet"
AGE_MART = Path("marts") / "jp_income_age_marital.parquet"
DHS_MART = Path("marts") / "dhs_tfr_by_wealth_quintile.parquet"
SPEND_MART = Path("marts") / "oecd_family_spending.parquet"
CENSUS_MART = Path("marts") / "eu_census_marital_by_education.parquet"
ORDER_MART = Path("marts") / "eu_tfr_by_birth_order.parquet"
KR_MART = Path("marts") / "kr_newlywed_income_children.parquet"

PREFERRED_FONTS = (
    "Hiragino Sans",
    "Hiragino Maru Gothic Pro",
    "Noto Sans CJK JP",
    "IPAexGothic",
    "Yu Gothic",
)
FALLBACK_FONT = "DejaVu Sans"

SRC_WB = "出典: World Bank WDI (CC BY 4.0)　分析: socioscope"
SRC_ESTAT_KISO = (
    "出典: 政府統計の総合窓口(e-Stat) 国民生活基礎調査（厚生労働省）を加工　分析: socioscope"
)
SRC_ESTAT_SHUGYO = (
    "出典: 政府統計の総合窓口(e-Stat) 就業構造基本調査（総務省）を加工　分析: socioscope"
)
SRC_BOTH = "出典: World Bank WDI (CC BY 4.0) / e-Stat 国民生活基礎調査を加工　分析: socioscope"
SRC_DHS = "出典: The DHS Program Indicator Data API (ICF) / World Bank WDI　分析: socioscope"
SRC_SOCX = "出典: OECD SOCX（家族関連公的支出）/ World Bank WDI　分析: socioscope"
SRC_EUROSTAT = "出典: Eurostat（cens_21me_r2 / demo_fordagec / demo_pjan）　分析: socioscope"
SRC_KOSTAT = "出典: 国家データ処（韓国）新婚夫婦統計 報道資料（KOGL 第1類型）　分析: socioscope"
SRC_ORDERS_KOSTAT = (
    "出典: Eurostat（demo_fordagec / demo_pjan）/ 国家データ処（韓国）新婚夫婦統計 報道資料"
    + "　分析: socioscope"
)
EU_NAMES_JA = {
    "FIN": "フィンランド", "SWE": "スウェーデン", "NOR": "ノルウェー", "DNK": "デンマーク",
    "ISL": "アイスランド",
    "ITA": "イタリア", "ESP": "スペイン", "PRT": "ポルトガル", "GRC": "ギリシャ", "FRA": "フランス",
    "DEU": "ドイツ", "NLD": "オランダ", "POL": "ポーランド", "CZE": "チェコ", "HUN": "ハンガリー",
}  # fmt: skip
BAND_NAMES_JA = {
    "U5MR 0-10": "5歳未満死亡率 10 未満",
    "U5MR 10-25": "10〜25",
    "U5MR 25-50": "25〜50",
    "U5MR 50-100": "50〜100",
    "U5MR >= 100": "100 以上（出生千対）",
}

# palette (shared with H1–H3b): blue ramp for ordered series, orange for Japan / emphasis
BLUE_RAMP = ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281"]
BLUE = "#256abf"
ORANGE = "#eb6834"
GREEN = "#2e8b57"
INK = "#333333"
MUTED = "#8a8a8a"
LIGHT = "#d9d9d9"
TRAIL_COLORS = {
    "JPN": ORANGE,
    "KOR": "#b5451b",
    "USA": "#256abf",
    "FRA": "#5598e7",
    "SWE": "#86b6ef",
    "CHN": "#2e8b57",
    "IND": "#7bb661",
    "NGA": "#8a8a8a",
}
TRAIL_NAMES = {
    "JPN": "日本",
    "KOR": "韓国",
    "USA": "米国",
    "FRA": "フランス",
    "SWE": "スウェーデン",
    "CHN": "中国",
    "IND": "インド",
    "NGA": "ナイジェリア",
}
TRAIL_LABEL_OFFSETS = {"USA": (7, 8), "FRA": (-70, 10), "SWE": (7, -12)}  # avoid overlaps
REPLACEMENT = 2.1
SCATTER_YEARS = (1990, 2007, 2024)  # GDP pc PPP exists from 1990 only (H1)
DPI = 150


# ---------------------------------------------------------------- pure helpers (tested)
def choose_font(available: Iterable[str], preferred: Sequence[str]) -> str | None:
    """First font of *preferred* present in *available* (exact family-name match), else None."""
    names = set(available)
    for name in preferred:
        if name in names:
            return name
    return None


def year_slice(panel: pl.DataFrame, year: int) -> pl.DataFrame:
    """Countries with both TFR and GDP pc observed in *year*; adds ln_gdp and is_japan."""
    return (
        panel.filter(
            (pl.col("year") == year)
            & pl.col("tfr").is_not_null()
            & pl.col("gdp_pcap_ppp").is_not_null()
            & (pl.col("gdp_pcap_ppp") > 0)
        )
        .with_columns(
            pl.col("gdp_pcap_ppp").log().alias("ln_gdp"),
            (pl.col("iso3") == "JPN").alias("is_japan"),
        )
        .sort("iso3")
    )


def country_trails(
    panel: pl.DataFrame, iso3s: Sequence[str], *, start: int, end: int
) -> pl.DataFrame:
    """Year-ordered (iso3, year, tfr, gdp_pcap_ppp, ln_gdp) for *iso3s*; both variables needed."""
    return (
        panel.filter(
            pl.col("iso3").is_in(list(iso3s))
            & (pl.col("year") >= start)
            & (pl.col("year") <= end)
            & pl.col("tfr").is_not_null()
            & pl.col("gdp_pcap_ppp").is_not_null()
            & (pl.col("gdp_pcap_ppp") > 0)
        )
        .select("iso3", "year", "tfr", "gdp_pcap_ppp")
        .with_columns(pl.col("gdp_pcap_ppp").log().alias("ln_gdp"))
        .sort(["iso3", "year"])
    )


def tfr_in_year(panel: pl.DataFrame, iso3s: Sequence[str], year: int) -> list[tuple[str, float]]:
    """(iso3, tfr) in the order of *iso3s*, skipping countries without a value in *year*."""
    sub = panel.filter((pl.col("year") == year) & pl.col("tfr").is_not_null())
    lookup = dict(zip(sub["iso3"].to_list(), sub["tfr"].to_list(), strict=True))
    return [(c, float(lookup[c])) for c in iso3s if c in lookup]


def japan_series(panel: pl.DataFrame) -> pl.DataFrame:
    """Japan's TFR and GDP pc by year (GDP may be null before 1990; not imputed)."""
    return (
        panel.filter((pl.col("iso3") == "JPN") & pl.col("tfr").is_not_null())
        .select("year", "tfr", "gdp_pcap_ppp")
        .sort("year")
    )


def dollar_ticks(ln_lo: float, ln_hi: float) -> list[int]:
    """Round dollar values (1-2-5 series) whose logs fall inside [ln_lo, ln_hi]."""
    candidates = [m * 10**e for e in range(2, 7) for m in (1, 2, 5)]
    lo, hi = math.exp(ln_lo) * (1 - 1e-9), math.exp(ln_hi) * (1 + 1e-9)
    return [c for c in candidates if lo <= c <= hi]


@dataclass(frozen=True)
class Curve:
    year: int
    x: list[float]
    y: list[float]


def wave_curves(frame: pl.DataFrame) -> list[Curve]:
    """One income-sorted curve (mid_man, value) per survey wave (year ascending)."""
    out: list[Curve] = []
    for year in sorted(frame["year"].unique().to_list()):
        sub = frame.filter(pl.col("year") == year).sort("mid_man")
        out.append(Curve(int(year), sub["mid_man"].to_list(), sub["value"].to_list()))
    return out


def sign_word(b: float, lo: float, hi: float) -> str:
    """Japanese direction label decided by the 95% CI, not the point estimate."""
    if lo > 0:
        return "正（上向き）"
    if hi < 0:
        return "負（下向き）"
    return "ゼロと区別できない"


@dataclass(frozen=True)
class LadderItem:
    label: str
    note: str
    rung: int  # 0 = 記述, 1 = 関連, 2 = 因果

    def __post_init__(self) -> None:
        if not 0 <= self.rung <= 2:
            msg = f"rung must be 0..2, got {self.rung}"
            raise ValueError(msg)


def ladder_items() -> list[LadderItem]:
    """Where each headline result of H1–H3b sits (fixed list; no result reaches the causal rung)."""
    return [
        LadderItem("H1 豊かな国ほど TFR が低い（国の間）", "相関 −0.74〜−0.82、全仕様で頑健", 1),
        LadderItem(
            "H1 国の中では所得と TFR の関連はほぼ消える", "二元固定効果 +0.10（CI は 0 を含む）", 1
        ),
        LadderItem("H1 J 字反転", "国間では見えない／国内は仕様依存 → 主張しない", 0),
        LadderItem("H2 景気後退で TFR はほとんど動かない", "年 −0.005〜−0.01、形は仕様で逆転", 1),
        LadderItem(
            "H3 日本: 所得が高いほど結婚・子どもが多い", "階級レベルの記述的勾配 +0.18〜+0.20", 1
        ),
        LadderItem("H3b 年齢を調整しても勾配は残る", "年齢固定効果 +0.169", 1),
        LadderItem("H3 国間と国内で向きが逆（フラクタルではない）", "5 波すべてで符号が逆", 0),
    ]


# ---------------------------------------------------------------- plotting setup
def band_profiles(dhs: pl.DataFrame, merged: pl.DataFrame) -> pl.DataFrame:
    """Mean TFR per wealth quintile, surveys grouped by the country's U5MR band at survey year.

    Columns: u5_band_order, u5_band, quintile, tfr, surveys. Surveys outside the bands (U5MR
    missing) are dropped. Pure; deterministic order.
    """
    banded = (
        h4.u5_band(merged)
        .filter(pl.col("u5_band").is_not_null())
        .select("survey_id", "u5_band", "u5_band_order")
    )
    return (
        dhs.join(banded, on="survey_id", how="inner")
        .group_by(["u5_band_order", "u5_band", "quintile"])
        .agg(pl.col("value").mean().alias("tfr"), pl.col("survey_id").n_unique().alias("surveys"))
        .sort(["u5_band_order", "quintile"])
    )


def setup_matplotlib() -> str:
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import font_manager

    available = {f.name for f in font_manager.fontManager.ttflist}
    font = choose_font(available, PREFERRED_FONTS)
    if font is None:
        print(
            "warning: no Japanese-capable font found; falling back to DejaVu Sans (tofu expected)",
            file=sys.stderr,
        )
        font = FALLBACK_FONT
    matplotlib.rcParams["font.family"] = [font]
    matplotlib.rcParams["axes.unicode_minus"] = False
    matplotlib.rcParams["figure.dpi"] = DPI
    matplotlib.rcParams["savefig.dpi"] = DPI
    matplotlib.rcParams["text.color"] = INK
    matplotlib.rcParams["axes.labelcolor"] = INK
    return font


def _num(x: object) -> float:
    """Narrow a polars scalar aggregate (typed as a wide union) to float."""
    return float(x)  # type: ignore[arg-type]


def _plt() -> Any:
    import matplotlib.pyplot as plt

    return plt


def _style(ax: Any) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(MUTED)
    ax.tick_params(colors=INK, labelsize=9)
    ax.grid(axis="y", color="#e5e5e5", linewidth=0.6)
    ax.set_axisbelow(True)


def _save(fig: Any, path: Path, source: str) -> None:
    fig.text(0.01, 0.005, source, fontsize=7.5, color=MUTED, ha="left", va="bottom")
    fig.savefig(path, dpi=DPI, metadata={"Software": None})
    _plt().close(fig)
    print(f"figure: {path.name}")


def _log_x(ax: Any, ln_lo: float, ln_hi: float, *, sparse: bool = False) -> None:
    ticks = dollar_ticks(ln_lo, ln_hi)
    if sparse:  # keep the 1 of each decade only (narrow panels)
        ticks = [t for t in ticks if str(t)[0] == "1"]
    ax.set_xticks([math.log(t) for t in ticks])
    ax.set_xticklabels([f"{t:,}" for t in ticks])


def _ci_dots(
    ax: Any, rows: Sequence[tuple[str, float, float, float, str]], *, zero: bool = True
) -> None:
    """Horizontal dot-and-whisker rows: (label, b, lo, hi, color)."""
    ys = list(range(len(rows)))[::-1]
    for y, (_label, b, lo, hi, color) in zip(ys, rows, strict=True):
        ax.plot([lo, hi], [y, y], color=color, linewidth=2.5, solid_capstyle="round")
        ax.plot([b], [y], marker="o", markersize=8, color=color)
        ax.annotate(
            f"{b:+.2f}",
            (hi, y),
            xytext=(6, 0),
            textcoords="offset points",
            va="center",
            fontsize=9,
            color=color,
        )
    ax.set_yticks(ys)
    ax.set_yticklabels([r[0] for r in rows], fontsize=9)
    if zero:
        ax.axvline(0, color=MUTED, linewidth=0.8, linestyle="--")
    _style(ax)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color="#e5e5e5", linewidth=0.6)


# ---------------------------------------------------------------- figures
def fig01_tfr_explainer(panel: pl.DataFrame, path: Path) -> None:
    plt = _plt()
    order = ["NGA", "IND", "USA", "FRA", "SWE", "CHN", "JPN", "KOR"]
    vals = tfr_in_year(panel, order, 2024)
    fig, ax = plt.subplots(figsize=(8, 4.6))
    names = [TRAIL_NAMES[c] for c, _ in vals]
    colors = [ORANGE if c == "JPN" else BLUE for c, _ in vals]
    bars = ax.bar(names, [v for _, v in vals], color=colors, width=0.62)
    for bar, (_, v) in zip(bars, vals, strict=True):
        ax.annotate(
            f"{v:.2f}",
            (bar.get_x() + bar.get_width() / 2, v),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center",
            fontsize=9,
        )
    ax.axhline(REPLACEMENT, color=GREEN, linewidth=1.5, linestyle="--")
    ax.annotate(
        "2.1 = 人口がほぼ一定に保たれる水準（置換水準）",
        (len(vals) - 0.5, REPLACEMENT),
        xytext=(0, 5),
        textcoords="offset points",
        ha="right",
        fontsize=9,
        color=GREEN,
    )
    ax.set_ylabel("合計特殊出生率 TFR（女性 1 人が生涯に産む子どもの数の目安）")
    ax.set_title(
        "TFR とは「女性 1 人あたりの子どもの数」。日本は 2024 年に 1.15（2024 年の値、8 か国）",
        fontsize=11,
        loc="left",
    )
    ax.set_ylim(0, max(v for _, v in vals) * 1.18)
    _style(ax)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    _save(fig, path, SRC_WB)


def fig02_scatter_three_years(panel: pl.DataFrame, path: Path) -> None:
    plt = _plt()
    fig, axes = plt.subplots(1, 3, figsize=(12, 4.6), sharey=True)
    for ax, year in zip(axes, SCATTER_YEARS, strict=True):
        sl = year_slice(panel, year)
        r = float(np.corrcoef(sl["ln_gdp"].to_numpy(), sl["tfr"].to_numpy())[0, 1])
        ax.scatter(sl["ln_gdp"], sl["tfr"], s=14, color=BLUE, alpha=0.55, edgecolors="none")
        jp = sl.filter(pl.col("is_japan"))
        if jp.height:
            ax.scatter(jp["ln_gdp"], jp["tfr"], s=90, color=ORANGE, zorder=5)
            ax.annotate(
                "日本",
                (float(jp["ln_gdp"][0]), float(jp["tfr"][0])),
                xytext=(8, 6),
                textcoords="offset points",
                color=ORANGE,
                fontsize=10,
                fontweight="bold",
            )
        ax.axhline(REPLACEMENT, color=GREEN, linewidth=1, linestyle="--")
        ax.set_title(f"{year} 年（{sl.height} か国、相関 {r:+.2f}）", fontsize=10)
        _log_x(ax, _num(sl["ln_gdp"].min()), _num(sl["ln_gdp"].max()), sparse=True)
        _style(ax)
    axes[0].set_ylabel("合計特殊出生率 TFR")
    fig.supxlabel(
        "一人当たり GDP（購買力平価、2021 年国際ドル）※目盛は等比（対数軸: 1 目盛ごとに数倍）",
        fontsize=9.5,
        y=0.06,
    )
    fig.suptitle(
        "豊かな国ほど子どもが少ない。この「国の間」の負の関係は 1990 年から 2024 年まで一貫している"
        "（点 = 1 か国）",
        fontsize=12,
        x=0.01,
        ha="left",
    )
    fig.tight_layout(rect=(0, 0.08, 1, 0.95))
    _save(fig, path, SRC_WB)


def fig03_trails(panel: pl.DataFrame, path: Path) -> None:
    plt = _plt()
    codes = list(TRAIL_COLORS)
    tr = country_trails(panel, codes, start=1990, end=2024)
    fig, ax = plt.subplots(figsize=(9, 6))
    for code in codes:
        sub = tr.filter(pl.col("iso3") == code)
        if sub.height == 0:
            continue
        x, y = sub["ln_gdp"].to_numpy(), sub["tfr"].to_numpy()
        color = TRAIL_COLORS[code]
        ax.plot(x, y, color=color, linewidth=2 if code == "JPN" else 1.4, alpha=0.9)
        ax.scatter(x[0], y[0], color=color, s=22, marker="s", zorder=4)
        ax.scatter(x[-1], y[-1], color=color, s=48, zorder=5)
        ax.annotate(
            f"{TRAIL_NAMES[code]} {int(sub['year'][-1])}",
            (x[-1], y[-1]),
            xytext=TRAIL_LABEL_OFFSETS.get(code, (7, -3)),
            textcoords="offset points",
            fontsize=9,
            color=color,
        )
    ax.axhline(REPLACEMENT, color=GREEN, linewidth=1, linestyle="--")
    ax.annotate(
        "置換水準 2.1",
        (_num(tr["ln_gdp"].min()), REPLACEMENT),
        xytext=(0, 4),
        textcoords="offset points",
        fontsize=8,
        color=GREEN,
    )
    _log_x(ax, _num(tr["ln_gdp"].min()), _num(tr["ln_gdp"].max()))
    ax.set_xlabel("一人当たり GDP（購買力平価、2021 年国際ドル、対数軸）　■ = 1990 年、● = 2024 年")
    ax.set_ylabel("合計特殊出生率 TFR")
    ax.set_title(
        "同じ国を 1990→2024 年と追うと、各国は「豊かになりながら下がる」が、\n"
        "豊かな国同士は横並び（8 か国）",
        fontsize=11,
        loc="left",
    )
    _style(ax)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    _save(fig, path, SRC_WB)


def fig04_between_within(between: h1.Est, within: h1.Est, path: Path) -> None:
    plt = _plt()
    b, _, lo, hi = between.coefs["ln_gdp"]
    w, _, wlo, whi = within.coefs["ln_gdp"]
    fig, ax = plt.subplots(figsize=(9, 3.6))
    rows = [
        ("国の間の違い\n（豊かな国 vs 貧しい国を比べる）", b, lo, hi, BLUE),
        ("国の中での変化\n（同じ国が豊かになった年を比べる）", w, wlo, whi, ORANGE),
    ]
    _ci_dots(ax, rows)
    ax.set_ylim(-0.6, 1.6)
    ax.set_xlabel("一人当たり GDP が 2.7 倍（対数で 1）違うと TFR は何人違うか（95% 信頼区間つき）")
    ax.set_title(
        "「豊かさと少子化」は国の間の違いとしては強い（−1.0）が、国の中での変化としては消える\n"
        f"（n={between.n:,}、{between.countries} か国、1990–2024 年）",
        fontsize=10.5,
        loc="left",
    )
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    _save(fig, path, SRC_WB)


def fig05_jcurve(
    cross: Sequence[tuple[str, h1.Est]], spline: h1.Est, knot: float, path: Path
) -> None:
    plt = _plt()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.4))
    rows = [
        (f"{lab} 年代（{e.countries} か国）", *e.coefs["ln_gdp"][:1], *e.coefs["ln_gdp"][2:], BLUE)
        for lab, e in cross
    ]
    _ci_dots(ax1, rows)
    ax1.set_title("(a) 豊かな国同士（2 万ドル以上）を横に比べた傾き", fontsize=10, loc="left")
    ax1.set_xlabel("傾き（対数 GDP 1 単位あたりの TFR）。上向き（正）なら「反転」")
    b1, _, lo1, hi1 = spline.coefs["ln_gdp"]
    bh, _, _, _ = spline.coefs["ln_gdp_hinge"]
    above = spline.extra["slope_above_knot"]
    xs = np.linspace(knot - 1.6, knot + 1.2, 100)
    ys = np.where(xs < knot, b1 * (xs - knot), above * (xs - knot))
    ax2.plot(xs, ys, color=ORANGE, linewidth=2.5)
    ax2.axvline(knot, color=MUTED, linewidth=0.8, linestyle="--")
    ax2.axhline(0, color=MUTED, linewidth=0.6)
    ax2.annotate(
        f"2 万ドル未満: 傾き {b1:+.2f}\n[{lo1:+.2f}, {hi1:+.2f}]",
        (knot - 1.5, b1 * (-1.5)),
        xytext=(0, 12),
        textcoords="offset points",
        fontsize=9,
    )
    ax2.annotate(
        f"2 万ドル以上: 傾き {above:+.2f}\n（折れ曲がり {bh:+.2f}、仕様により +0.2〜+2.3）",
        (knot + 0.3, above * 0.3),
        xytext=(6, -28),
        textcoords="offset points",
        fontsize=9,
        color=ORANGE,
    )
    _log_x(ax2, knot - 1.6, knot + 1.2)
    ax2.set_xlabel("一人当たり GDP（対数軸）。国と年の平均からのずれで見た形")
    ax2.set_ylabel("TFR のずれ（国・年の平均からの差）")
    ax2.set_title(
        f"(b) 同じ国の中での変化（折れ線あてはめ、n={spline.n:,}）", fontsize=10, loc="left"
    )
    _style(ax2)
    fig.suptitle(
        "「豊かになりすぎると出生率が戻る（J 字反転）」は国の間では見えない。"
        "国の中では上向きだが仕様で揺れ、主張しない",
        fontsize=11.5,
        x=0.01,
        ha="left",
    )
    fig.tight_layout(rect=(0, 0.05, 1, 0.93))
    _save(fig, path, SRC_WB)


def fig06_recessions(
    profiles: Sequence[tuple[str, pl.DataFrame]], es: h2.FitResult, sd_dtfr: float, path: Path
) -> None:
    plt = _plt()
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.4), gridspec_kw={"width_ratios": [1, 1, 1.25]})
    for ax, (label, prof) in zip(axes[:2], profiles, strict=True):
        yrs = prof["year"].to_numpy()
        ax.fill_between(
            yrs,
            prof["q25_d_tfr"].to_numpy(),
            prof["q75_d_tfr"].to_numpy(),
            color=BLUE,
            alpha=0.15,
            label="国々の中央 50%",
        )
        ax.plot(
            yrs,
            prof["mean_d_tfr"].to_numpy(),
            color=BLUE,
            linewidth=2,
            marker="o",
            markersize=4,
            label="国の平均",
        )
        for y, s in zip(yrs, prof["share_recession"].to_numpy(), strict=True):
            if s > 0.3:
                ax.axvspan(y - 0.5, y + 0.5, color=ORANGE, alpha=0.18)
                ax.annotate(
                    f"{int(y)}: {s:.0%} の国が不況",
                    (y, _num(prof["q75_d_tfr"].max())),
                    ha="center",
                    fontsize=8,
                    color=ORANGE,
                )
        ax.axhline(0, color=MUTED, linewidth=0.6)
        ax.set_title(f"{label}（年ごとの各国 TFR の前年差、記述）", fontsize=9.5, loc="left")
        ax.set_ylabel("TFR の前年からの変化")
        ax.set_ylim(-0.1, 0.06)
        _style(ax)
    axes[0].legend(frameon=False, fontsize=8, loc="lower left")
    ax = axes[2]
    ks = [k for k in range(h2.K_MIN, h2.K_MAX + 1)]
    xs, bs, los, his = [], [], [], []
    for k in ks:
        if k == h2.K_REF:
            xs.append(k)
            bs.append(0.0)
            los.append(0.0)
            his.append(0.0)
            continue
        b, _, lo, hi = es.est.coefs[h2.dummy_name(k)]
        xs.append(k)
        bs.append(b)
        los.append(lo)
        his.append(hi)
    ax.errorbar(
        xs,
        bs,
        yerr=[np.array(bs) - np.array(los), np.array(his) - np.array(bs)],
        fmt="o",
        color=ORANGE,
        ecolor=ORANGE,
        capsize=3,
        linewidth=1.5,
    )
    ax.axhline(0, color=MUTED, linewidth=0.8)
    ax.axhspan(-sd_dtfr, sd_dtfr, color=LIGHT, alpha=0.5)
    ax.annotate(
        f"灰色の帯 = 各国の TFR 変化の\n「ふつうのばらつき」（±{sd_dtfr:.3f}）",
        (h2.K_MIN, sd_dtfr * 0.9),
        fontsize=8,
        color=MUTED,
        va="top",
    )
    ax.set_xticks(ks)
    ax.set_xticklabels(
        ["3 年前\n以前", "−2", "−1\n(基準)", "0\n不況の年", "+1", "+2", "+3", "+4", "5 年後\n以降"],
        fontsize=8,
    )
    ax.set_xlabel("不況（成長率 −2% 未満）からの年数")
    ax.set_title(
        f"不況の前後の差（{es.est.countries} か国、国と年の固定効果つき）",
        fontsize=9.5,
        loc="left",
    )
    _style(ax)
    fig.suptitle(
        "景気後退で出生率はほとんど動かない: 2008–09 も 2020 も平年並みの下がり方で、"
        "推定された差は年 0.01 人未満",
        fontsize=11.5,
        x=0.01,
        ha="left",
    )
    fig.tight_layout(rect=(0, 0.05, 1, 0.92))
    _save(fig, path, SRC_WB)


def fig07_within_r2(bars: Sequence[tuple[str, float]], n: int, countries: int, path: Path) -> None:
    plt = _plt()
    fig, ax = plt.subplots(figsize=(9, 4.2))
    labels = [b[0] for b in bars]
    vals = [b[1] * 100 for b in bars]
    colors = [ORANGE if "GDP" in lab and "成長" not in lab else BLUE for lab in labels]
    bs = ax.bar(labels, vals, color=colors, width=0.62)
    for bar, v in zip(bs, vals, strict=True):
        ax.annotate(
            f"{v:.2f}%",
            (bar.get_x() + bar.get_width() / 2, v),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center",
            fontsize=9,
        )
    ax.axhline(100, color=GREEN, linewidth=1, linestyle="--")
    ax.annotate(
        "100% = 国の中の TFR の動きを全部説明",
        (len(bars) - 0.5, 100),
        xytext=(0, -12),
        textcoords="offset points",
        ha="right",
        fontsize=8.5,
        color=GREEN,
    )
    ax.set_yscale("symlog", linthresh=1)
    ax.set_yticks([0, 0.25, 0.5, 1, 10, 100])
    ax.set_yticklabels(["0", "0.25%", "0.5%", "1%", "10%", "100%"])
    ax.set_ylabel("国の中の TFR の変動のうち説明できる割合（within-R²）")
    ax.set_title(
        "所得水準も成長率も、同じ国の中での出生率の動きの 1% 未満しか説明しない"
        f"（n={n:,}、{countries} か国、1990–2024 年）",
        fontsize=10.5,
        loc="left",
    )
    ax.tick_params(axis="x", labelsize=8.5)
    _style(ax)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    _save(fig, path, SRC_WB)


def _wave_plot(ax: Any, frame: pl.DataFrame, *, ylabel: str) -> None:
    curves = wave_curves(frame)
    for curve, color in zip(curves, BLUE_RAMP, strict=False):
        ax.plot(
            curve.x,
            curve.y,
            color=color,
            linewidth=1.8,
            marker="o",
            markersize=3.5,
            label=f"{curve.year} 年（所得年）",
        )
    ax.set_xscale("log")
    ticks = [50, 100, 200, 300, 500, 1000, 2000]
    lo, hi = _num(frame["mid_man"].min()), _num(frame["mid_man"].max())
    ticks = [t for t in ticks if lo <= t * 1.3 and t <= hi * 1.3]
    ax.set_xticks(ticks)
    ax.set_xticklabels([f"{t:,}" for t in ticks])
    ax.minorticks_off()
    ax.set_ylabel(ylabel)
    ax.legend(frameon=False, fontsize=8)
    _style(ax)


def fig08_married_by_income(
    male: pl.DataFrame, slopes: dict[int, tuple[h3.Coef, float, int]], path: Path
) -> None:
    plt = _plt()
    fig, ax = plt.subplots(figsize=(9, 5.2))
    _wave_plot(ax, male, ylabel="配偶者がいる割合（男性・働いている人、15 歳以上）")
    ax.set_xlabel("本人の年間所得（万円、階級の中点、対数軸）")
    lo = min(c.b for c, _, _ in slopes.values())
    hi = max(c.b for c, _, _ in slopes.values())
    ax.set_title(
        "日本では所得が高い男性ほど結婚している割合が高い"
        f"（5 回の調査すべてで同じ形。傾き +{lo:.2f}〜+{hi:.2f}）",
        fontsize=10.5,
        loc="left",
    )
    ax.set_ylim(0, 1)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    _save(fig, path, SRC_ESTAT_KISO)


def fig09_children_by_income(children: pl.DataFrame, path: Path) -> None:
    plt = _plt()
    fig, ax = plt.subplots(figsize=(9, 5.2))
    _wave_plot(ax, children, ylabel="18 歳未満の子どもがいる世帯の割合")
    ax.set_xlabel("世帯の年間所得（万円、階級の中点、対数軸）")
    ax.set_title(
        "世帯所得が高いほど子どものいる世帯が多い。曲線は年を追うごとに右（高所得側）へずれている",
        fontsize=10.5,
        loc="left",
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    _save(fig, path, SRC_ESTAT_KISO)


def fig10_fractal_contrast(
    between: h1.Est, frame_b: pl.DataFrame, male24: pl.DataFrame, slope24: h3.Coef, path: Path
) -> None:
    plt = _plt()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.8))
    b, _, lo, hi = between.coefs["ln_gdp"]
    ax1.scatter(frame_b["ln_gdp"], frame_b["tfr"], s=8, color=BLUE, alpha=0.3, edgecolors="none")
    xs = np.linspace(_num(frame_b["ln_gdp"].min()), _num(frame_b["ln_gdp"].max()), 50)
    xbar, ybar = _num(frame_b["ln_gdp"].mean()), _num(frame_b["tfr"].mean())
    ax1.plot(xs, ybar + b * (xs - xbar), color=ORANGE, linewidth=2.5)
    ax1.annotate(
        f"右下がり（負）　傾き {b:+.2f} [{lo:+.2f}, {hi:+.2f}]",
        (0.03, 0.92),
        xycoords="axes fraction",
        fontsize=11,
        color=ORANGE,
        fontweight="bold",
    )
    _log_x(ax1, _num(frame_b["ln_gdp"].min()), _num(frame_b["ln_gdp"].max()))
    ax1.set_xlabel("一人当たり GDP（国、対数軸）")
    ax1.set_ylabel("TFR（国）")
    ax1.set_title(
        f"国の間（{between.countries} か国 × 2012–2024 年、n={between.n:,}）",
        fontsize=10,
        loc="left",
    )
    _style(ax1)
    sizes = 400 * male24["weight"].to_numpy() / male24["weight"].max()
    ax2.scatter(
        male24["ln_mid"], male24["value"], s=sizes, color=BLUE, alpha=0.5, edgecolors="none"
    )
    xs2 = np.linspace(_num(male24["ln_mid"].min()), _num(male24["ln_mid"].max()), 50)
    w = male24["weight"].to_numpy()
    xbar2 = float(np.average(male24["ln_mid"].to_numpy(), weights=w))
    ybar2 = float(np.average(male24["value"].to_numpy(), weights=w))
    ax2.plot(xs2, ybar2 + slope24.b * (xs2 - xbar2), color=ORANGE, linewidth=2.5)
    ax2.annotate(
        f"右上がり（正）　傾き {slope24.b:+.2f} [{slope24.lo:+.2f}, {slope24.hi:+.2f}]",
        (0.03, 0.92),
        xycoords="axes fraction",
        fontsize=11,
        color=ORANGE,
        fontweight="bold",
    )
    ticks = [50, 100, 200, 500, 1000]
    ax2.set_xticks([math.log(t) for t in ticks])
    ax2.set_xticklabels([f"{t:,}" for t in ticks])
    ax2.set_xlabel("本人の年間所得（万円、階級中点、対数軸）。丸の大きさ = 人数")
    ax2.set_ylabel("配偶者がいる割合（男性・有業者）")
    ax2.set_title(f"日本の中（所得階級 {male24.height}、所得年 2024）", fontsize=10, loc="left")
    _style(ax2)
    fig.suptitle(
        "国の間では「豊かなほど少ない」、日本の中では「豊かなほど多い」。"
        "向きが逆なので、同じ形（フラクタル）ではない",
        fontsize=11.5,
        x=0.01,
        ha="left",
    )
    fig.tight_layout(rect=(0, 0.05, 1, 0.92))
    _save(fig, path, SRC_BOTH)


def fig11_age_adjusted(
    men: pl.DataFrame,
    by_age: dict[str, tuple[h3.Coef, float, int]],
    crude: h3.Coef,
    std: h3.Coef,
    fe: h3.Coef,
    path: Path,
) -> None:
    plt = _plt()
    fig = plt.figure(figsize=(13, 7.2))
    gs = fig.add_gridspec(2, 5, width_ratios=[1, 1, 1, 1, 1.6], hspace=0.5, wspace=0.35)
    ages = list(by_age)
    for i, age in enumerate(ages):
        ax = fig.add_subplot(gs[i // 4, i % 4])
        sub = men.filter(pl.col("age_class") == age).sort("mid_man")
        ax.plot(sub["mid_man"], sub["value"], color=BLUE, marker="o", markersize=3, linewidth=1.5)
        ax.set_xscale("log")
        ax.set_xticks([100, 300, 1000])
        ax.set_xticklabels(["100", "300", "1000"])
        ax.minorticks_off()
        ax.set_ylim(0, 1)
        c = by_age[age][0]
        ax.set_title(f"{age} 歳　傾き {c.b:+.2f}", fontsize=9)
        if i % 4 == 0:
            ax.set_ylabel("結婚経験のある割合", fontsize=8)
        if i // 4 == 1:
            ax.set_xlabel("所得（万円、対数軸）", fontsize=8)
        _style(ax)
    ax = fig.add_subplot(gs[:, 4])
    rows = [
        ("年齢をそろえない（15 歳以上まとめて）", crude.b, crude.lo, crude.hi, MUTED),
        ("年齢構成をそろえる（直接法標準化、20–59 歳）", std.b, std.lo, std.hi, BLUE),
        ("年齢ごとに比べる（年齢固定効果、20–59 歳）", fe.b, fe.lo, fe.hi, ORANGE),
    ]
    _ci_dots(ax, rows)
    ax.set_yticklabels([])  # labels drawn inside the panel so they do not spill into the grid
    for y, (label, *_rest, color) in zip(range(len(rows) - 1, -1, -1), rows, strict=True):
        ax.text(0.005, y + 0.22, label, fontsize=9, color=color, va="bottom")
    ax.set_ylim(-0.6, 2.9)
    ax.set_xlim(0, 0.3)
    ax.set_xlabel("所得の傾き（対数 1 単位あたり）")
    ax.set_title("年齢をそろえても傾きは残る（むしろ増える）", fontsize=10, loc="left")
    fig.suptitle(
        "「所得が高い人は年齢が高いだけ」ではない: 20–59 歳のどの年齢層でも、"
        "所得が高いほど結婚経験のある割合が高い（男性・有業者、2022 年）",
        fontsize=11.5,
        x=0.01,
        ha="left",
    )
    fig.text(0.01, 0.005, SRC_ESTAT_SHUGYO, fontsize=7.5, color=MUTED)
    fig.savefig(path, dpi=DPI, metadata={"Software": None})
    plt.close(fig)
    print(f"figure: {path.name}")


def fig12_evidence_ladder(path: Path) -> None:
    plt = _plt()
    items = ladder_items()
    fig, ax = plt.subplots(figsize=(12, 6.2))
    rung_names = ["記述\n「こうなっている」", "関連\n「一緒に動く」", "因果\n「これが原因で動く」"]
    rung_x = [0.12, 0.47, 0.84]
    for x, name, color in zip(rung_x, rung_names, [LIGHT, BLUE_RAMP[1], BLUE_RAMP[4]], strict=True):
        ax.add_patch(plt.Rectangle((x - 0.1, 0.86), 0.2, 0.12, color=color, alpha=0.9))
        ax.text(
            x,
            0.92,
            name,
            ha="center",
            va="center",
            fontsize=10,
            color=INK if color == LIGHT else "white",
            fontweight="bold",
        )
    ax.annotate(
        "",
        xy=(0.97, 0.80),
        xytext=(0.03, 0.80),
        arrowprops={"arrowstyle": "->", "color": MUTED, "lw": 1.5},
    )
    ax.text(
        0.5,
        0.815,
        "右へ行くほど「言い切れる」ことが増える。この分析はすべて左 2 段（識別戦略なし）",
        ha="center",
        fontsize=9,
        color=MUTED,
    )
    ys = np.linspace(0.70, 0.08, len(items))
    for item, y in zip(items, ys, strict=True):
        x = rung_x[item.rung]
        ax.scatter([x], [y], s=120, color=ORANGE if item.rung == 0 else BLUE, zorder=5)
        ax.text(x + 0.025, y, f"{item.label}\n", ha="left", va="center", fontsize=9.5, color=INK)
        ax.text(x + 0.025, y - 0.025, item.note, ha="left", va="center", fontsize=8, color=MUTED)
    ax.text(
        rung_x[2],
        0.4,
        "ここに置ける結果は\nひとつもない",
        ha="center",
        va="center",
        fontsize=10,
        color=BLUE_RAMP[4],
        style="italic",
    )
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.set_title(
        "どこまで確か？ 本記事の結果はすべて「記述」か「関連」であり、「因果」の段には届いていない",
        fontsize=12,
        loc="left",
    )
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    _save(fig, path, "分析: socioscope（H1〜H3b レポートの結論の位置づけ）")


def fig13_japan_timeline(jp: pl.DataFrame, path: Path) -> None:
    plt = _plt()
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(jp["year"], jp["tfr"], color=ORANGE, linewidth=2.2, label="TFR（左軸）")
    ax.axhline(REPLACEMENT, color=GREEN, linewidth=1, linestyle="--")
    ax.set_ylabel("合計特殊出生率 TFR", color=ORANGE)
    ax.set_ylim(0.8, 2.4)
    ax2 = ax.twinx()
    g = jp.filter(pl.col("gdp_pcap_ppp").is_not_null())
    ax2.plot(
        g["year"],
        g["gdp_pcap_ppp"] / 1000,
        color=BLUE,
        linewidth=2.2,
        label="一人当たり GDP（右軸、1990 年以降のみ）",
    )
    ax2.set_ylabel("一人当たり GDP（千 国際ドル、購買力平価）", color=BLUE)
    ax2.set_ylim(0, 60)
    ax2.spines["top"].set_visible(False)
    lookup = dict(zip(jp["year"].to_list(), jp["tfr"].to_list(), strict=True))
    for year, text in (
        (1966, "1966 ひのえうま"),
        (1973, "1973 石油危機"),
        (1990, "1990 バブル崩壊"),
        (2008, "2008 金融危機"),
        (2020, "2020 コロナ"),
    ):
        ax.axvline(year, color=MUTED, linewidth=0.7, linestyle=":")
        ax.annotate(
            f"{text}\nTFR {lookup[year]:.2f}",
            (year, lookup[year]),
            xytext=(4, -26) if year == 1966 else (4, 14),
            textcoords="offset points",
            fontsize=8.5,
            color=INK,
        )
    ax.set_xlabel("年")
    ax.set_title(
        f"日本の TFR は 1960 年の {lookup[1960]:.2f} から 2024 年の {lookup[2024]:.2f} へ。"
        "豊かになる間ずっと下がり、不況の年に目立った折れはない",
        fontsize=11,
        loc="left",
    )
    _style(ax)
    h1_, l1 = ax.get_legend_handles_labels()
    h2_, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1_ + h2_, l1 + l2, frameon=False, fontsize=8.5, loc="upper right")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    _save(fig, path, SRC_WB)


# ---------------------------------------------------------------- run
def fig14_stage_controls(res: dict[str, h1.Est], path: Path) -> None:
    plt = _plt()
    fig, ax = plt.subplots(figsize=(9, 4.4))
    rows = []
    for key, label, color in (
        ("A0", "国の間: 所得だけ", BLUE),
        (
            "A_all",
            "国の間: 人口転換の段階をそろえる\n（死亡率・女子教育・都市化・女性就業・寿命）",
            BLUE,
        ),
        ("B0", "国の中: 所得だけ", ORANGE),
        ("B_all", "国の中: 段階をそろえる", ORANGE),
    ):
        b, _, lo, hi = res[key].coefs["ln_gdp"]
        rows.append((label, b, lo, hi, color))
    _ci_dots(ax, rows)
    ax.set_ylim(-0.6, 3.6)
    ax.set_xlabel("一人当たり GDP が 2.7 倍（対数で 1）違うと TFR は何人違うか（95% 信頼区間つき）")
    n, g = res["A0"].n, res["A0"].countries
    ax.set_title(
        "人口転換の段階をそろえると、国の間の「豊かさ → 少子化」は 5 分の 1 に縮み、\n"
        "国の中では所得の向きが正になる"
        f"（同じサンプル n={n:,}、{g} か国、1990–2024 年）",
        fontsize=10.5,
        loc="left",
    )
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    _save(fig, path, SRC_WB)


def fig15_dhs_quintiles(
    prof: pl.DataFrame, merged: pl.DataFrame, pooled: h1.Est, japan_ln_gdp: float, path: Path
) -> None:
    plt = _plt()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.6))
    for i in sorted(prof["u5_band_order"].unique().to_list()):
        sub = prof.filter(pl.col("u5_band_order") == i)
        ax1.plot(
            sub["quintile"],
            sub["tfr"],
            marker="o",
            color=BLUE_RAMP[int(i)],
            linewidth=2,
            label=f"{BAND_NAMES_JA[str(sub['u5_band'][0])]}（{int(sub['surveys'][0])} 調査）",
        )
    ax1.set_xticks([1, 2, 3, 4, 5])
    ax1.set_xticklabels(["最貧 20%", "2", "3", "4", "最富裕 20%"])
    ax1.set_ylabel("TFR（五分位ごとの平均）")
    ax1.set_title("途上国の中では、豊かな層ほど子どもが少ない", fontsize=10.5, loc="left")
    ax1.legend(frameon=False, fontsize=8, title="国の人口転換の段階", title_fontsize=8)
    _style(ax1)
    x, y = merged["ln_gdp"].to_numpy(), merged["gap"].to_numpy()
    ax2.scatter(x, y, s=14, alpha=0.55, color=BLUE, edgecolors="none")
    b, _, lo, hi = pooled.coefs["ln_gdp"]
    xs = np.linspace(float(x.min()), float(x.max()), 20)
    ax2.plot(xs, float(y.mean()) + b * (xs - float(x.mean())), color=ORANGE, linewidth=2)
    ax2.axhline(0, color=MUTED, linewidth=0.8)
    ax2.axvline(japan_ln_gdp, color=GREEN, linewidth=1.2, linestyle=":")
    ax2.annotate(
        "日本 2022 の豊かさ\n（DHS に無い。H3 の指標は別物）",
        (japan_ln_gdp, float(y.max())),
        fontsize=8,
        color=GREEN,
        ha="right",
        va="top",
        xytext=(-4, 0),
        textcoords="offset points",
    )
    _log_x(ax2, float(x.min()), japan_ln_gdp + 0.3, sparse=True)
    ax2.set_xlabel("調査年の一人当たり GDP（購買力平価、対数軸）")
    ax2.set_ylabel("最富裕 20% の TFR − 最貧 20% の TFR")
    ax2.set_title(
        f"差の深さは国の豊かさとほぼ無関係（傾き {b:+.2f} [{lo:+.2f}, {hi:+.2f}]）",
        fontsize=10.5,
        loc="left",
    )
    _style(ax2)
    fig.suptitle(
        f"DHS 調査 {merged.height} 件・{merged['iso3'].n_unique()} か国"
        f"（{h4._span(merged['survey_year'])} 年）の富裕五分位別 TFR",
        fontsize=10.5,
        x=0.01,
        ha="left",
    )
    fig.tight_layout(rect=(0, 0.05, 1, 0.95))
    _save(fig, path, SRC_DHS)


def fig16_policy(res: dict[str, h1.Est], d: pl.DataFrame, path: Path) -> None:
    plt = _plt()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.6))
    rows = [
        ("家族支出 合計", res["total"].coefs["family_total"], BLUE),
        ("うち現金給付（児童手当・育休給付）", res["split"].coefs["cash"], BLUE_RAMP[1]),
        ("うち現物給付（保育など）", res["split"].coefs["inkind"], BLUE_RAMP[1]),
    ]
    _ci_dots(ax1, [(lab, b, lo, hi, c) for lab, (b, _, lo, hi), c in rows])
    ax1.set_ylim(-0.6, 2.6)
    ax1.set_xlabel(
        "支出が GDP 比 1 ポイント増えると TFR は何人変わるか\n"
        f"二元固定効果、n={res['total'].n:,}、{res['total'].countries} か国、1980–2021 年"
    )
    ax1.set_title(
        "同じ国の中では、家族支出と出生率の関連は小さい（95% 信頼区間）",
        fontsize=10.5,
        loc="left",
    )
    x, y = d["spend_start"].to_numpy(), d["d_tfr"].to_numpy()
    colors = [
        ORANGE if c in h5.NORDIC5 else (GREEN if c in ("KOR", "JPN") else BLUE)
        for c in d["iso3"].to_list()
    ]
    ax2.scatter(x, y, s=24, color=colors, edgecolors="none", alpha=0.85)
    for iso3, xi, yi in zip(d["iso3"].to_list(), x, y, strict=True):
        if iso3 in h5.NORDIC5 or iso3 in ("KOR", "JPN", "HUN", "CZE", "USA", "FRA", "DEU"):
            ax2.annotate(
                EU_NAMES_JA.get(
                    iso3, {"KOR": "韓国", "JPN": "日本", "USA": "米国"}.get(iso3, iso3)
                ),
                (xi, yi),
                fontsize=8,
                color=INK,
                xytext=(4, 2),
                textcoords="offset points",
            )
    ax2.axhline(0, color=MUTED, linewidth=0.8)
    ax2.set_xlabel("2010 年の家族関連公的支出（GDP 比 %）　橙 = 北欧、緑 = 韓国・日本")
    ax2.set_ylabel("TFR の変化（2010 → 2021 年）")
    ax2.set_title("手厚い国ほど持ちこたえた、という関係はない", fontsize=10.5, loc="left")
    _style(ax2)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    _save(fig, path, SRC_SOCX)


def fig17_census(g: pl.DataFrame, path: Path) -> None:
    plt = _plt()
    fig, axes = plt.subplots(1, 2, figsize=(11, 6.6))
    for ax, sex, title in zip(axes, ("M", "F"), ("男性", "女性"), strict=True):
        sub = g.filter(pl.col("sex") == sex).sort("b")
        ys = list(range(sub.height))
        for yi, r in zip(ys, sub.iter_rows(named=True), strict=True):
            color = (
                ORANGE if r["iso3"] in h5.NORDIC5 else (GREEN if r["iso3"] in h5.SOUTH else BLUE)
            )
            ax.plot([r["lo"], r["hi"]], [yi, yi], color=color, linewidth=1.6)
            ax.plot([r["b"]], [yi], "o", color=color, markersize=4)
        ax.set_yticks(ys)
        ax.set_yticklabels(
            [EU_NAMES_JA.get(c, c) for c in sub["iso3"].to_list()], fontsize=7.5, color=INK
        )
        ax.axvline(0, color=MUTED, linewidth=0.8)
        ax.set_title(
            f"{title}: 学歴が 1 段階上がると有配偶率は何ポイント違うか", fontsize=10, loc="left"
        )
        ax.set_xlabel("年齢をそろえた学歴勾配（95% 信頼区間）")
        _style(ax)
        ax.grid(axis="y", visible=False)
        ax.grid(axis="x", color="#e5e5e5", linewidth=0.6)
    fig.suptitle(
        "欧州 31 か国の 2021 年センサス: 25–59 歳、法律婚のみ。橙 = 北欧、緑 = 南欧",
        fontsize=10.5,
        x=0.01,
        ha="left",
    )
    fig.tight_layout(rect=(0, 0.05, 1, 0.95))
    _save(fig, path, SRC_EUROSTAT)


def fig18_orders_korea(dec: dict[str, dict[str, float]], kr: pl.DataFrame, path: Path) -> None:
    plt = _plt()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.6))
    isos = [i for i in ("FIN", "SWE", "NOR", "ISL", "NLD", "ESP", "ITA", "POL") if i in dec]
    pos = np.zeros(len(isos))
    neg = np.zeros(len(isos))
    for o, color, lab in (
        ("1", BLUE_RAMP[4], "第 1 子"),
        ("2", BLUE_RAMP[3], "第 2 子"),
        ("3", BLUE_RAMP[2], "第 3 子"),
        ("GE4", BLUE_RAMP[0], "第 4 子以上"),
    ):
        vals = np.array([dec[i][f"d_{o}"] for i in isos])
        base = np.where(vals >= 0, pos, neg)
        ax1.bar(
            [EU_NAMES_JA.get(i, i) for i in isos],
            vals,
            bottom=base,
            color=color,
            label=lab,
            width=0.7,
        )
        pos = pos + np.where(vals >= 0, vals, 0)
        neg = neg + np.where(vals < 0, vals, 0)
    for i, iso3 in enumerate(isos):
        ax1.annotate(
            f"{dec[iso3]['first_share']:.0%}",
            (i, neg[i]),
            fontsize=7.5,
            color=INK,
            ha="center",
            va="top",
            xytext=(0, -2),
            textcoords="offset points",
        )
    ax1.axhline(0, color=MUTED, linewidth=0.8)
    ax1.tick_params(axis="x", labelsize=8, rotation=25)
    ax1.set_ylim(min(neg) - 0.12, max(0.08, max(pos) + 0.02))
    ax1.set_ylabel("出生順位別 TFR の変化（2010 → 2024 年）")
    ax1.set_title(
        "北欧の低下は第 1 子だけではない（数字 = 第 1 子の寄与率）", fontsize=10.5, loc="left"
    )
    ax1.legend(frameon=False, fontsize=8, ncol=2, loc="lower right")
    _style(ax1)
    years = sorted(kr["ref_year"].unique().to_list())
    for yr, color in zip(years, BLUE_RAMP * 3, strict=False):
        sub = kr.filter(
            (pl.col("ref_year") == yr)
            & (pl.col("metric") == "with_children_share")
            & (pl.col("income_class") != "total")
            & (pl.col("income_concept") == "earned_business")
        ).sort("income_lower_10k_krw")
        mids = [
            float(m)
            for m in (
                h5.krw_midpoint(lo, hi)
                for lo, hi in zip(
                    sub["income_lower_10k_krw"].to_list(),
                    sub["income_upper_10k_krw"].to_list(),
                    strict=True,
                )
            )
            if m is not None
        ]
        ax2.plot(
            mids, sub["value"].to_list(), marker="o", color=color, linewidth=1.6, label=str(yr)
        )
    ax2.set_xscale("log")
    ax2.set_xticks([500, 2000, 4000, 6000, 8500, 15000])
    ax2.set_xticklabels(
        ["<1千万", "1–3千万", "3–5千万", "5–7千万", "7千万–1億", "1億以上"], fontsize=8, rotation=20
    )
    ax2.minorticks_off()
    ax2.set_xlabel("夫婦合算の年間所得（ウォン、勤労＋事業所得）")
    ax2.set_ylabel("子どもがいる夫婦の割合")
    ax2.set_title(
        "韓国: 新婚 5 年以内の初婚夫婦では、所得が高いほど子どもがいない", fontsize=10.5, loc="left"
    )
    ax2.legend(frameon=False, fontsize=7, title="基準年", title_fontsize=7, ncol=2)
    _style(ax2)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    _save(fig, path, SRC_ORDERS_KOSTAT)


def run(data_dir: Path, fig_dir: Path) -> None:
    font = setup_matplotlib()
    print(f"font={font}")
    fig_dir.mkdir(parents=True, exist_ok=True)
    panel = pl.read_parquet(data_dir / PANEL)
    jp = pl.read_parquet(data_dir / JP_MART)
    age = pl.read_parquet(data_dir / AGE_MART)
    print(f"panel rows={panel.height} jp rows={jp.height} age rows={age.height}")

    # 1 explainer, 2 scatter, 3 trails, 13 timeline (descriptive, from mart)
    print("== TFR 2024 (fig01) ==")
    for code, v in tfr_in_year(panel, list(TRAIL_COLORS), 2024):
        print(f"  {code}: {v:.2f}")
    fig01_tfr_explainer(panel, fig_dir / "s01_tfr_explainer.png")
    print("== scatter years (fig02) ==")
    for year in SCATTER_YEARS:
        sl = year_slice(panel, year)
        r = float(np.corrcoef(sl["ln_gdp"].to_numpy(), sl["tfr"].to_numpy())[0, 1])
        print(f"  {year}: countries={sl.height} corr(ln_gdp,tfr)={r:+.3f}")
    fig02_scatter_three_years(panel, fig_dir / "s02_scatter_three_years.png")
    fig03_trails(panel, fig_dir / "s03_trails_eight_countries.png")
    jps = japan_series(panel)
    print("== Japan (fig13) ==")
    for year in (1960, 1973, 1990, 2008, 2020, 2024):
        row = jps.filter(pl.col("year") == year)
        print(f"  {year}: tfr={row['tfr'][0]:.2f} gdp_pcap_ppp={row['gdp_pcap_ppp'][0]}")
    fig13_japan_timeline(jps, fig_dir / "s13_japan_timeline.png")

    # H1 recomputed: between / within / cross-section high-income by decade / FE spline
    frame = h1.build_regression_frame(panel)
    print(f"== H1 sample: n={frame.height} countries={frame['iso3'].n_unique()} ==")
    between = h1.fit(frame, "tfr ~ ln_gdp", label="[M1] pooled OLS", fe=False)
    within = h1.fit(frame, "tfr ~ ln_gdp", label="[M2] two-way FE", fe=True)
    print(between.line())
    print(within.line())
    fig04_between_within(between, within, fig_dir / "s04_between_vs_within.png")
    knot = h1.HIGH_INCOME_THRESHOLDS["gdp20k"]
    high = frame.filter(pl.col("ln_gdp") >= knot)
    cross: list[tuple[str, h1.Est]] = []
    for dec in (1990, 2000, 2010, 2020):
        sub = high.filter(pl.col("decade") == dec)
        est = h1.fit(
            sub,
            "tfr ~ ln_gdp + C(year)",
            label=f"[X-{dec}s] high-income, pooled + year FE",
            fe=False,
        )
        print(est.line())
        cross.append((f"{dec}", est))
    spline = h1.fit(
        h1.piecewise_terms(frame, knot),
        "tfr ~ ln_gdp + ln_gdp_hinge",
        label="[S-gdp20k] FE spline",
        fe=True,
    )
    print(spline.line())
    fig05_jcurve(cross, spline, knot, fig_dir / "s05_jcurve_check.png")

    # H2 recomputed: descriptive shocks, event study (main), within-R2 bars
    full = h2.build_growth_frame(panel)
    sd_dtfr = _num(full["d_tfr"].std())
    n_c = full["iso3"].n_unique()
    print(f"== H2 sample: n={full.height} countries={n_c} sd(d_tfr)={sd_dtfr:.4f} ==")
    profiles = [
        ("2008–09 金融危機の前後", h2.shock_profile(full, list(range(2004, 2014)))),
        ("2020 コロナ不況の前後", h2.shock_profile(full, list(range(2016, 2025)))),
    ]
    for label, prof in profiles:
        print(f"-- descriptive: {label} --")
        print(prof)
    events = h2.detect_events(
        panel.with_columns(pl.col("year").cast(pl.Int64)), threshold=h2.MAIN_THRESHOLD
    )
    es = h2.fit(
        h2.event_dummies(full, events),
        "d_tfr",
        [h2.dummy_name(k) for k in h2.event_ks()],
        label="[C] d_tfr, threshold -2%, binned",
    )
    print(es.est.line())
    fig06_recessions(profiles, es, sd_dtfr, fig_dir / "s06_recessions.png")
    level = h2.build_growth_frame(panel, start_year=h2.LEVEL_START_YEAR).filter(
        pl.col("ln_gdp").is_not_null()
    )
    bars: list[tuple[str, float]] = []
    specs = [
        ("所得水準\n(ln GDP)", ["ln_gdp"]),
        ("成長率\n当年", ["g_l0"]),
        ("成長率\n1 年前", ["g_l1"]),
        ("成長率\n2 年前", ["g_l2"]),
        ("成長率\n3 年前", ["g_l3"]),
        ("成長率\n0〜3 年前 合算", list(h2.LAG_COLS)),
    ]
    for name, xs in specs:
        fr = h2.fit(
            level, "tfr", xs, label=f"[A] tfr ~ {name.replace(chr(10), ' ')}", within_stats=True
        )
        print(fr.est.line())
        bars.append((name, fr.est.extra["within_r2"]))
    fig07_within_r2(bars, level.height, level["iso3"].n_unique(), fig_dir / "s07_within_r2.png")

    # H3 recomputed
    male = h3.band_frame(jp, metric="married_share", sex="male")
    slopes = h3.slope_by_wave(male)
    print("== H3 male married_share slopes by wave ==")
    for year, (c, rho, n) in slopes.items():
        print(f"  {year}: n={n} slope {c.fmt()} spearman={rho:+.3f}")
    fig08_married_by_income(male, slopes, fig_dir / "s08_married_share_by_income.png")
    children = h3.band_frame(jp, metric="children_household_share", sex=None)
    print("== H3 children_household_share slopes by wave ==")
    for year, (c, rho, n) in h3.slope_by_wave(children).items():
        print(f"  {year}: n={n} slope {c.fmt()} spearman={rho:+.3f}")
    fig09_children_by_income(children, fig_dir / "s09_children_household_by_income.png")
    frame_b = h1.build_regression_frame(
        panel, start_year=h3.CROSS_YEARS[0], end_year=h3.CROSS_YEARS[1]
    )
    between_b = h1.fit(frame_b, "tfr ~ ln_gdp", label="[E] between 2012-2024 pooled", fe=False)
    print(between_b.line())
    male24 = male.filter(pl.col("year") == 2024)
    slope24 = slopes[2024][0]
    b, _, lo, hi = between_b.coefs["ln_gdp"]
    jp_sign = sign_word(slope24.b, slope24.lo, slope24.hi)
    print(f"  sign: between={sign_word(b, lo, hi)} within-JP male 2024={jp_sign}")
    fig10_fractal_contrast(
        between_b, frame_b, male24, slope24, fig_dir / "s10_fractal_contrast.png"
    )

    # H3b recomputed
    men = h3b.age_frame(age, sex="male")
    by_age = h3b.slopes_by_age(men)
    print(f"== H3b men 20-59 cells={men.height} ==")
    for a, (c, rho, n) in by_age.items():
        print(f"  age {a}: n={n} slope {c.fmt()} spearman={rho:+.3f}")
    weights = h3b.age_weights(age, sex="male")
    std_frame = h3b.standardise(men, weights)
    std = h3.weighted_slope(
        std_frame["ln_mid"].to_numpy(),
        std_frame["value"].to_numpy(),
        std_frame["weight"].to_numpy(),
    )
    fe = h3b.fe_fit(men).coefs["ln_mid"]
    crude = h3b.crude_slope(age, sex="male")[0]
    print(f"  crude (age total rows): {crude.fmt()}")
    print(f"  standardised: {std.fmt()}  attenuation={h3b.attenuation(std, crude):+.3f}")
    print(f"  age-FE: {fe.fmt()}  attenuation={h3b.attenuation(fe, crude):+.3f}")
    fig11_age_adjusted(men, by_age, crude, std, fe, fig_dir / "s11_age_adjusted.png")

    fig12_evidence_ladder(fig_dir / "s12_evidence_ladder.png")

    # H4 recomputed: stage controls (a)(b) and DHS wealth-quintile gradient (d)
    dhs = pl.read_parquet(data_dir / DHS_MART)
    h4_frame = h4.stage_frame(panel)
    print(f"== H4 sample: n={h4_frame.height} countries={h4_frame['iso3'].n_unique()} ==")
    res = h4.block_a_b(h4_frame, h4.STAGE_VARS, "S")
    for key in ("A0", "A_all", "B0", "B_all"):
        print(res[key].line())
    fig14_stage_controls(res, fig_dir / "s14_stage_controls.png")
    merged = h4.merge_stage(h4.quintile_gradients(dhs), panel)
    neg = merged.filter(pl.col("gap") < 0).height
    print(
        f"== H4 DHS: surveys={merged.height} countries={merged['iso3'].n_unique()} gap<0: {neg} =="
    )
    pooled = h1.fit(merged, "gap ~ ln_gdp", label="[D-pooled] gap ~ ln_gdp", fe=False)
    print(pooled.line())
    prof = band_profiles(dhs, merged)
    print(prof)
    jpn = panel.filter((pl.col("iso3") == "JPN") & (pl.col("year") == 2022))
    japan_ln_gdp = math.log(float(jpn["gdp_pcap_ppp"][0]))
    print(f"  Japan 2022 ln_gdp={japan_ln_gdp:.3f}")
    fig15_dhs_quintiles(prof, merged, pooled, japan_ln_gdp, fig_dir / "s15_dhs_quintiles.png")

    # H5 recomputed: policy × TFR (a), census gradients (b), birth-order decomposition (c1), Korea
    spend = pl.read_parquet(data_dir / SPEND_MART)
    pframe = h5.policy_frame(panel, spend)
    print(f"== H5 policy sample: n={pframe.height} countries={pframe['iso3'].n_unique()} ==")
    pres = h5.block_a1(pframe, "S")
    d, _ = h5.block_a2(pframe, h5.BASE_YEAR, h5.END_YEAR, "S")
    fig16_policy(pres, d, fig_dir / "s16_policy_vs_tfr.png")
    census = pl.read_parquet(data_dir / CENSUS_MART)
    g = h5.census_gradients(census)
    h5.print_gradients(g, "summary")
    fig17_census(g, fig_dir / "s17_census_gradients.png")
    orders = pl.read_parquet(data_dir / ORDER_MART)
    order_dec: dict[str, dict[str, float]] = {}
    for iso3 in sorted(orders["iso3"].unique().to_list()):
        od = h5.order_decomposition(orders, iso3, h5.BASE_YEAR)
        if od is not None:
            order_dec[iso3] = od
            print(f"  {iso3}: d_known={od['d_known']:+.3f} first_share={od['first_share']:.2f}")
    kr = pl.read_parquet(data_dir / KR_MART)
    for yr in sorted(kr["ref_year"].unique().to_list()):
        c, _n = h5.korea_slope(kr, yr)
        print(f"  KR {yr}: {c.fmt()}")
    fig18_orders_korea(order_dec, kr, fig_dir / "s18_birth_order_korea.png")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=REPO_ROOT / "data")
    parser.add_argument(
        "--fig-dir", type=Path, default=THEME_DIR / "reports" / "figures" / "summary"
    )
    args = parser.parse_args()
    run(args.data_dir, args.fig_dir)


if __name__ == "__main__":
    main()
