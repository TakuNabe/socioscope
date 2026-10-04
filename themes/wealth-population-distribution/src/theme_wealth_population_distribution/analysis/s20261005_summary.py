"""総括レポート用の図（一般読者向け、日本語）を生成する決定的スクリプト。

H1（a20261004_h1_ushape）・H1b（a20261004_h1b_observed_only）・H1c（a20261005_h1c_quality_corrected）・
H2（a20261004_h2_institutions）の結果を、同じ mart と同じ純粋関数から**再計算**して図にする。
新しい分析はしない（数値は各レポートの stdout と一致するはず。差があれば本スクリプトのバグ）。

入力: data/marts/wealth_population_panel.parquet, data/staged/wid/top_shares.parquet,
data/staged/wid/data_points.parquet, data/marts/wealth_institutions_panel.parquet。
出力: reports/figures/summary/*.png（150 dpi）と、図に使った数値の標準出力。乱数・現在時刻は使わない
（PNG は 2 回実行でバイト一致）。

    uv run python themes/wealth-population-distribution/src/theme_wealth_population_distribution/\
analysis/s20261005_summary.py [--data-dir data] [--fig-dir .../reports/figures/summary]

日本語フォントは FONT_CANDIDATES の順に探し、無ければ DejaVu に落として stderr に警告する。
純粋なデータ整形関数は tests/test_summary.py で検証する（描画はテストしない）。
"""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import polars as pl

from theme_wealth_population_distribution.analysis import a20261004_h1_ushape as h1
from theme_wealth_population_distribution.analysis import a20261004_h1b_observed_only as h1b
from theme_wealth_population_distribution.analysis import a20261004_h2_institutions as h2

THEME_DIR = Path(__file__).resolve().parents[3]
REPO_ROOT = THEME_DIR.parents[1]
DATA_POINTS = Path("staged") / "wid" / "data_points.parquet"
INSTITUTIONS = Path("marts") / "wealth_institutions_panel.parquet"

JAPAN = h1.JAPAN
FONT_CANDIDATES: tuple[str, ...] = (
    "Hiragino Sans",
    "Hiragino Maru Gothic Pro",
    "Noto Sans CJK JP",
    "IPAexGothic",
    "Yu Gothic",
)
ICONIC: tuple[str, ...] = ("USA", "FRA", "GBR", "DEU", "SWE", "JPN", "CHN", "IND")
LONG_RUN_WINDOW = (1900, 2024)
DECADES: tuple[tuple[int, int], ...] = (
    (1950, 1959),
    (1960, 1969),
    (1970, 1979),
    (1980, 1989),
    (1990, 1999),
    (2000, 2009),
    (2010, 2024),
)
CONSTRUCTION_ORDER: tuple[str, ...] = ("observed", "partial", "imputed", "unknown")

SRC_WID = "出典: WID.world (CC BY-NC-SA 4.0)　分析: socioscope"
SRC_WID_OECD = (
    "出典: WID.world (CC BY-NC-SA 4.0), OECD (Tax Database / SOCX / Revenue Statistics)"
    "　分析: socioscope"
)

# dataviz reference palette (fixed slot order; Japan is always slot 2 orange)
BLUE = "#2a78d6"
ORANGE = "#eb6834"
AQUA = "#1baf7a"
YELLOW = "#eda100"
MAGENTA = "#e87ba4"
GREEN = "#008300"
VIOLET = "#4a3aa7"
RED = "#e34948"
INK = "#333333"
MUTED = "#8a8a8a"
GRID = "#e5e5e5"
FIELD = "#c9d6e8"
SEQ_BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95"]
UNKNOWN_GREY = "#d9d9d9"
COUNTRY_COLOR: dict[str, str] = {
    "USA": BLUE,
    "JPN": ORANGE,
    "FRA": AQUA,
    "GBR": YELLOW,
    "DEU": MAGENTA,
    "SWE": GREEN,
    "CHN": VIOLET,
    "IND": RED,
}
JP_LABEL: dict[str, str] = {
    "top1_income_share": "上位 1% 所得シェア",
    "top10_income_share": "上位 10% 所得シェア",
    "top1_wealth_share": "上位 1% 資産シェア",
    "top10_wealth_share": "上位 10% 資産シェア",
}
COUNTRY_JA: dict[str, str] = {
    "USA": "アメリカ",
    "FRA": "フランス",
    "GBR": "イギリス",
    "DEU": "ドイツ",
    "SWE": "スウェーデン",
    "JPN": "日本",
    "CHN": "中国",
    "IND": "インド",
}


# ---------------------------------------------------------------- pure helpers (tested)
def pick_font(available: Iterable[str], candidates: Sequence[str] = FONT_CANDIDATES) -> str | None:
    """候補の順に、利用可能なフォント名の集合から最初に見つかったものを返す。無ければ None。"""
    names = set(available)
    for c in candidates:
        if c in names:
            return c
    return None


def income_groups(top1: float, top10: float, bottom50: float) -> dict[str, float]:
    """上位 1% / 次の 9% / 中間 40% / 下位 50% のシェア（合計 1）。入力は 0–1 のシェア。"""
    if not (0 <= top1 <= top10 <= 1 - bottom50 <= 1):
        msg = f"inconsistent shares top1={top1} top10={top10} bottom50={bottom50}"
        raise ValueError(msg)
    return {
        "上位 1%": top1,
        "次の 9%": top10 - top1,
        "中間 40%": 1 - top10 - bottom50,
        "下位 50%": bottom50,
    }


def allocate_cells(groups: dict[str, float], n: int = 100) -> dict[str, int]:
    """シェアを n 個のセルに最大剰余法で配分する（合計はちょうど n、順序は入力順）。"""
    total = sum(groups.values())
    raw = {k: v / total * n for k, v in groups.items()}
    base = {k: math.floor(v) for k, v in raw.items()}
    rest = n - sum(base.values())
    order = sorted(groups, key=lambda k: (-(raw[k] - base[k]), list(groups).index(k)))
    for k in order[:rest]:
        base[k] += 1
    return base


def changes_table(traj_a: pl.DataFrame, traj_b: pl.DataFrame, a: str, b: str) -> pl.DataFrame:
    """2 系列の 1980 年比の変化（pp）を国ごとに並べる。欠損国は落とす。"""
    ca = traj_a.select("iso3", (pl.col("change_since_1980") * 100).alias(a))
    cb = traj_b.select("iso3", (pl.col("change_since_1980") * 100).alias(b))
    return ca.join(cb, on="iso3", how="inner").drop_nulls().sort("iso3")


def trough_year_bins(
    traj: pl.DataFrame, bins: Sequence[tuple[int, int]] = DECADES
) -> list[tuple[str, int]]:
    """適格国の谷の年を 10 年刻みに数える。bins の外（例: 1950 年以前）は無い前提（窓 1950–）。"""
    years = traj.filter(pl.col("eligible"))["trough_year"].drop_nulls().to_list()
    out: list[tuple[str, int]] = []
    for lo, hi in bins:
        out.append((f"{lo}–{hi}" if hi - lo != 9 else f"{lo}s", sum(lo <= y <= hi for y in years)))
    return out


def median_by_year(panel: pl.DataFrame, col: str, window: tuple[int, int]) -> pl.DataFrame:
    """年ごとの国横断中央値と観測国数（欠損は数えない。補完しない）。"""
    lo, hi = window
    return (
        panel.filter(pl.col(col).is_not_null() & (pl.col("year") >= lo) & (pl.col("year") <= hi))
        .group_by("year")
        .agg(pl.col(col).median().alias("median"), pl.len().alias("n"))
        .sort("year")
    )


def rank_series(
    panel: pl.DataFrame, col: str, iso3: str, window: tuple[int, int], *, full_n: int
) -> list[tuple[int, int]]:
    """各年の iso3 の順位（1 = 最大）。その年に full_n か国すべて観測がある年だけ返す。"""
    lo, hi = window
    out: list[tuple[int, int]] = []
    for year in range(lo, hi + 1):
        rank, n = h1.rank_in_year(panel, col, year, iso3)
        if rank is not None and n == full_n:
            out.append((year, rank))
    return out


def shares_by_decade(
    labelled: pl.DataFrame,
    label_col: str,
    order: Sequence[str],
    bins: Sequence[tuple[int, int]] = DECADES,
) -> pl.DataFrame:
    """iso3×year×label の表を 10 年刻み × label の割合（各期で合計 1）にする。

    label の null は 'unknown' として数える。
    """
    df = labelled.with_columns(pl.col(label_col).cast(pl.Utf8).fill_null("unknown").alias("lab"))
    rows: list[dict[str, Any]] = []
    for lo, hi in bins:
        d = df.filter((pl.col("year") >= lo) & (pl.col("year") <= hi))
        n = d.height
        counts = dict(d.group_by("lab").len().iter_rows()) if n else {}
        rows.append(
            {
                "period": f"{lo}–{hi}" if hi - lo != 9 else f"{lo}s",
                "n": n,
                **{lab: (counts.get(lab, 0) / n if n else 0.0) for lab in order},
            }
        )
    return pl.DataFrame(rows)


def construction_labels(
    panel: pl.DataFrame, data_points: pl.DataFrame, col: str, window: tuple[int, int]
) -> pl.DataFrame:
    """窓内で col が非欠損の iso3×year に construction（observed/partial/imputed/null）を付ける。"""
    lo, hi = window
    flags = h1b.construction_flags(data_points, col)
    return (
        panel.filter(pl.col(col).is_not_null() & (pl.col("year") >= lo) & (pl.col("year") <= hi))
        .select("iso3", "year")
        .join(flags, on=["iso3", "year"], how="left")
    )


def quality_labels(
    panel: pl.DataFrame, staged: pl.DataFrame, col: str, window: tuple[int, int]
) -> pl.DataFrame:
    """窓内で col が非欠損の iso3×year に data_quality（'q0'..'q5' / null）を付ける。"""
    lo, hi = window
    flags = h1.quality_flags(staged, col)
    return (
        panel.filter(pl.col(col).is_not_null() & (pl.col("year") >= lo) & (pl.col("year") <= hi))
        .select("iso3", "year")
        .join(flags, on=["iso3", "year"], how="left")
        .with_columns(
            pl.when(pl.col("data_quality").is_null())
            .then(None)
            .otherwise(pl.concat_str([pl.lit("q"), pl.col("data_quality").cast(pl.Utf8)]))
            .alias("q")
        )
        .select("iso3", "year", "q")
    )


def coef_rows(fit: h2.Fit, label: str) -> list[dict[str, Any]]:
    """Fit から定数項を除いた係数・95% 区間の行（図用）。"""
    return [
        {
            "label": label,
            "y": fit.y,
            "x": k,
            "b": fit.coef[k],
            "lo": fit.coef[k] - 1.96 * fit.se[k],
            "hi": fit.coef[k] + 1.96 * fit.se[k],
            "p": fit.pval[k],
            "n": fit.n,
        }
        for k in fit.coef
        if k != "const"
    ]


# ---------------------------------------------------------------- plotting setup
def configure_matplotlib() -> str:
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import font_manager

    font = pick_font(f.name for f in font_manager.fontManager.ttflist)
    if font is None:
        print(
            "warning: no Japanese-capable font found "
            f"({', '.join(FONT_CANDIDATES)}); falling back to DejaVu Sans (tofu likely)",
            file=sys.stderr,
        )
        font = "DejaVu Sans"
    matplotlib.rcParams.update(
        {
            "font.family": [font],
            "axes.unicode_minus": False,
            "figure.dpi": 150,
            "savefig.dpi": 150,
            "text.color": INK,
            "axes.labelcolor": INK,
            "xtick.color": INK,
            "ytick.color": INK,
        }
    )
    return font


def _style(ax: Any, *, grid_axis: str = "y") -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(MUTED)
        ax.spines[side].set_linewidth(0.6)
    ax.tick_params(colors=INK, labelsize=8, length=2)
    if grid_axis != "none":
        ax.grid(axis=grid_axis, color=GRID, linewidth=0.5)
    ax.set_axisbelow(True)


def _save(fig: Any, path: Path, source: str) -> None:
    fig.text(0.01, 0.005, source, fontsize=7, color=MUTED, ha="left", va="bottom")
    fig.savefig(path, dpi=150, metadata={"Software": None})
    import matplotlib.pyplot as plt

    plt.close(fig)
    print(f"  wrote {path.name}")


def _pct(ax: Any, axis: str = "y") -> None:
    from matplotlib.ticker import FuncFormatter

    fmt = FuncFormatter(lambda v, _: f"{v * 100:.0f}%")
    (ax.yaxis if axis == "y" else ax.xaxis).set_major_formatter(fmt)


# ---------------------------------------------------------------- figures
def fig01_explainer(panel: pl.DataFrame, path: Path) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch, Rectangle

    r = panel.filter((pl.col("iso3") == JAPAN) & (pl.col("year") == 2024)).row(0, named=True)
    groups = income_groups(
        r["top1_income_share"], r["top10_income_share"], r["bottom50_income_share"]
    )
    people = {"上位 1%": 1, "次の 9%": 9, "中間 40%": 40, "下位 50%": 50}
    money = allocate_cells(groups)
    colors = dict(zip(groups, [ORANGE, BLUE, SEQ_BLUE[2], SEQ_BLUE[0]], strict=True))
    print("  fig01 JPN 2024 groups:", {k: round(v, 4) for k, v in groups.items()}, "cells:", money)

    fig, axes = plt.subplots(1, 2, figsize=(8.5, 4.6))
    for ax, cells, head in zip(
        axes,
        (people, money),
        ("100 人の大人を所得順に並べると…", "…100 のパイ（所得全体）はこう分かれる"),
        strict=True,
    ):
        i = 0
        for k, cnt in cells.items():
            for _ in range(cnt):
                row, col = divmod(i, 10)
                ax.add_patch(
                    Rectangle(
                        (col + 0.08, 9 - row + 0.08),
                        0.84,
                        0.84,
                        facecolor=colors[k],
                        edgecolor="none",
                    )
                )
                i += 1
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 10)
        ax.set_aspect("equal")
        ax.axis("off")
        ax.set_title(head, fontsize=10, color=INK, loc="left")
    handles = [
        Patch(facecolor=colors[k], label=f"{k}: 人数 {people[k]}  →  所得 {groups[k] * 100:.1f}%")
        for k in groups
    ]
    fig.legend(
        handles=handles,
        loc="lower center",
        ncol=2,
        frameon=False,
        fontsize=8.5,
        bbox_to_anchor=(0.5, 0.03),
    )
    fig.suptitle(
        "「上位 1% シェア」とは: 日本 2024 年、上位 1 人が所得全体の "
        f"{groups['上位 1%'] * 100:.1f}% を受け取る",
        fontsize=11,
        color=INK,
        x=0.01,
        ha="left",
    )
    fig.tight_layout(rect=(0, 0.14, 1, 0.93))
    _save(fig, path, SRC_WID + "　税引前国民所得、成人・カップル均等割")


def fig_longrun(panel: pl.DataFrame, col: str, path: Path, *, title: str) -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8.5, 5.0))
    lo, hi = LONG_RUN_WINDOW
    ends: list[tuple[float, str, str]] = []
    for iso3 in ICONIC:
        obs = h1.series_in_window(panel, iso3, col, (lo, hi))
        if not obs:
            continue
        c = COUNTRY_COLOR[iso3]
        lw = 2.6 if iso3 == JAPAN else 1.6
        ax.plot(
            [y for y, _ in obs], [v for _, v in obs], color=c, linewidth=lw, label=COUNTRY_JA[iso3]
        )
        ends.append((obs[-1][1], COUNTRY_JA[iso3], c))
        print(
            f"  {col} {iso3}: first {obs[0][0]}={obs[0][1]:.3f} last {obs[-1][0]}={obs[-1][1]:.3f}"
        )
    # direct labels at the right edge, nudged apart
    ends.sort(key=lambda t: t[0])
    min_gap = 0.012 if "income" in col else 0.02
    ys = [e[0] for e in ends]
    for i in range(1, len(ys)):
        if ys[i] - ys[i - 1] < min_gap:
            ys[i] = ys[i - 1] + min_gap
    for (v, name, c), y in zip(ends, ys, strict=True):
        ax.annotate(
            name, (hi, v), xytext=(hi + 2, y), fontsize=8.5, color=c, va="center", textcoords="data"
        )
    ax.axvspan(1965, 1995, color="#f2f2f2", zorder=0)
    ax.text(
        1980,
        ax.get_ylim()[1] * 0.98,
        "H1 が「谷」を想定した期間\n(1965–1995)",
        fontsize=7.5,
        color=MUTED,
        ha="center",
        va="top",
    )
    ax.set_xlim(lo, hi + 16)
    ax.set_xlabel("年", fontsize=9)
    ax.set_ylabel(JP_LABEL[col], fontsize=9)
    _pct(ax)
    _style(ax)
    ax.set_title(title, fontsize=11, color=INK, loc="left")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    _save(
        fig,
        path,
        SRC_WID + "　1950–70 年は 10 年刻みの国が多く、点を直線で結んだだけ（間を埋めていない）",
    )


def fig_small_multiples(
    panel: pl.DataFrame, traj: pl.DataFrame, col: str, path: Path, *, title: str
) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    lo, hi = h1.BASE.window
    codes = sorted(panel["iso3"].unique().to_list())
    ncol = 8
    nrow = math.ceil(len(codes) / ncol)
    fig, axes = plt.subplots(
        nrow, ncol, figsize=(1.9 * ncol, 1.65 * nrow + 0.9), sharex=True, sharey=True
    )
    flat = [ax for row in axes for ax in row]
    tmap = {r["iso3"]: r for r in traj.iter_rows(named=True)}
    for ax, iso3 in zip(flat, codes, strict=False):
        obs = h1.series_in_window(panel, iso3, col, (lo, hi))
        t = tmap[iso3]
        is_u = bool(t["u_shape"])
        color = ORANGE if iso3 == JAPAN else (BLUE if is_u else MUTED)
        ax.plot([y for y, _ in obs], [v for _, v in obs], color=color, linewidth=1.3)
        if t["trough_year"] is not None and is_u:
            ax.axvline(t["trough_year"], color=BLUE, linewidth=0.6, linestyle=":")
        tag = "U" if is_u else "–"
        ax.set_title(f"{iso3} {tag}", fontsize=8, color=color if iso3 == JAPAN else INK)
        _style(ax)
        ax.tick_params(labelsize=6)
        _pct(ax)
    for ax in flat[len(codes) :]:
        ax.axis("off")
    k = int(traj.filter(pl.col("eligible"))["u_shape"].sum())
    handles = [
        Line2D([], [], color=BLUE, linewidth=1.5, label=f"U 字の基準を満たす（{k} か国）"),
        Line2D([], [], color=MUTED, linewidth=1.5, label=f"満たさない（{len(codes) - k} か国）"),
        Line2D([], [], color=ORANGE, linewidth=2, label="日本"),
        Line2D([], [], color=BLUE, linewidth=0.8, linestyle=":", label="谷の年（U 字の国のみ）"),
    ]
    fig.legend(
        handles=handles,
        loc="lower right",
        ncol=4,
        frameon=False,
        fontsize=8,
        bbox_to_anchor=(0.99, 0.0),
    )
    fig.suptitle(title, fontsize=11, color=INK, x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0.04, 1, 0.96))
    _save(fig, path, SRC_WID + f"　{lo}–{hi} 年、縦軸はシェア")


def fig_change_dots(changes: pl.DataFrame, a: str, b: str, path: Path) -> None:
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(9.5, 8.2))
    for ax, col in zip(axes, (a, b), strict=True):
        d = changes.sort(col)
        ys = list(range(d.height))
        vals = d[col].to_list()
        codes = d["iso3"].to_list()
        med = float(str(d.filter(pl.col("iso3") != JAPAN)[col].median()))
        for y, v, c in zip(ys, vals, codes, strict=True):
            jp = c == JAPAN
            ax.plot([0, v], [y, y], color=GRID, linewidth=1.0, zorder=1)
            ax.scatter(v, y, s=34 if jp else 18, color=ORANGE if jp else BLUE, zorder=3)
        ax.set_yticks(ys)
        ax.set_yticklabels(codes, fontsize=6.5)
        for lab in ax.get_yticklabels():
            if lab.get_text() == JAPAN:
                lab.set_color(ORANGE)
                lab.set_fontweight("bold")
        ax.axvline(0, color=MUTED, linewidth=0.8)
        ax.axvline(med, color=INK, linewidth=0.8, linestyle="--")
        ax.text(
            med + 0.3,
            0.2,
            f"他国の中央値 {med:+.1f} pp",
            fontsize=7.5,
            color=INK,
            ha="left",
            va="center",
        )
        jp_v = float(d.filter(pl.col("iso3") == JAPAN)[col][0])
        ax.set_title(f"{JP_LABEL[col]}（日本 {jp_v:+.1f} pp）", fontsize=10, color=INK, loc="left")
        ax.set_xlabel("1980 年 → 2024 年の変化（ポイント）", fontsize=9)
        ax.set_ylim(-0.8, d.height - 0.2)
        _style(ax, grid_axis="x")
        up = int((pl.Series(vals) > 0).sum())
        print(
            f"  change since 1980 {col}: up {up}/{d.height}, "
            f"median(others)={med:+.2f}, JPN={jp_v:+.2f}"
        )
    fig.suptitle(
        "1980 年以降、上位 1% シェアは大半の国で上がった。日本の上昇幅は中央値より小さい",
        fontsize=11,
        color=INK,
        x=0.01,
        ha="left",
    )
    fig.tight_layout(rect=(0, 0.03, 1, 0.96))
    _save(fig, path, SRC_WID + "　1980 年に観測が無い国は最も近い年を使用")


def fig_trough_hist(trajs: dict[str, pl.DataFrame], path: Path) -> None:
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(9.0, 3.8), sharey=True)
    for ax, col in zip(axes, ("top1_wealth_share", "top1_income_share"), strict=True):
        bins = trough_year_bins(trajs[col])
        labels = [b[0] for b in bins]
        counts = [b[1] for b in bins]
        colors = [BLUE if lab in ("1960s", "1970s", "1980s", "1990s") else MUTED for lab in labels]
        ax.bar(range(len(bins)), counts, color=colors, width=0.7)
        for i, c in enumerate(counts):
            ax.text(i, c + 0.4, str(c), ha="center", fontsize=8, color=INK)
        ax.set_xticks(range(len(bins)))
        ax.set_xticklabels(labels, fontsize=8, rotation=0)
        ax.set_title(JP_LABEL[col], fontsize=10, color=INK, loc="left")
        ax.set_xlabel("最も低かった年（谷）の年代", fontsize=9)
        _style(ax)
        inside = sum(c for lab, c in bins if lab in ("1960s", "1970s", "1980s", "1990s"))
        print(f"  trough bins {col}: {bins} in 1960s-1990s={inside}")
    axes[0].set_ylabel("国の数", fontsize=9)
    fig.suptitle(
        "「谷」の時期は 1970–90 年代に集まるが、2000 年以降が谷（ずっと下がり続けた）国も多い",
        fontsize=11,
        color=INK,
        x=0.01,
        ha="left",
    )
    fig.text(
        0.99,
        0.9,
        "青 = 1960–90 年代（H1 の想定 1965–1995 とほぼ重なる）",
        fontsize=7.5,
        color=MUTED,
        ha="right",
    )
    fig.tight_layout(rect=(0, 0.04, 1, 0.9))
    _save(fig, path, SRC_WID + "　46 か国、1950–2024 年の最小値の年")


def fig_majority_bars(trajs: dict[str, pl.DataFrame], path: Path) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    cols = list(h1.SERIES)
    w = 0.36
    for i, col in enumerate(cols):
        m = h1.majority_test(trajs[col], col)
        r = h1.rise_since_1980_test(trajs[col], col)
        for off, t, color in ((-w / 2, m, BLUE), (w / 2, r, SEQ_BLUE[1])):
            x = i + off
            ax.bar(x, t.share, width=w - 0.04, color=color)
            ax.errorbar(
                x,
                t.share,
                yerr=[[t.share - t.ci[0]], [t.ci[1] - t.share]],
                color=INK,
                capsize=3,
                linewidth=1,
            )
            ax.text(
                x,
                0.03,
                f"{t.k}/{t.eligible}",
                ha="center",
                fontsize=8,
                color="white" if color == BLUE else INK,
            )
        print(
            f"  majority {col}: U {m.k}/{m.eligible} [{m.ci[0]:.2f},{m.ci[1]:.2f}]; "
            f"rise {r.k}/{r.eligible} [{r.ci[0]:.2f},{r.ci[1]:.2f}]"
        )
    ax.axhline(0.5, color=INK, linewidth=0.9, linestyle="--")
    ax.text(len(cols) - 0.55, 0.51, "半数 (50%)", fontsize=8, color=INK, ha="right", va="bottom")
    ax.set_xticks(range(len(cols)))
    ax.set_xticklabels([JP_LABEL[c] for c in cols], fontsize=9)
    ax.set_ylim(0, 1)
    _pct(ax)
    ax.set_ylabel("46 か国のうち基準を満たす国の割合", fontsize=9)
    handles = [
        Patch(facecolor=BLUE, label="U 字の基準を満たす（谷 1965–95、下降・上昇とも 1 pt 以上）"),
        Patch(facecolor=SEQ_BLUE[1], label="1980 年 → 2024 年に上昇した（弱い形）"),
    ]
    ax.legend(handles=handles, loc="upper left", frameon=False, fontsize=8)
    _style(ax)
    ax.set_title(
        "U 字は多数派ではないが、「1980 年以降の上昇」は多数派（ひげ = 95% 信頼区間）",
        fontsize=11,
        color=INK,
        loc="left",
    )
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    _save(fig, path, SRC_WID + "　信頼区間は Wilson 法、国を独立とみなした目安")


def fig_quality_stacks(
    cons: dict[str, pl.DataFrame], qual: dict[str, pl.DataFrame], path: Path
) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    fig, axes = plt.subplots(2, 2, figsize=(9.5, 7.2), sharex=True)
    cons_colors = {
        "observed": SEQ_BLUE[4],
        "partial": SEQ_BLUE[2],
        "imputed": SEQ_BLUE[0],
        "unknown": UNKNOWN_GREY,
    }
    cons_ja = {
        "observed": "観測（調査・税データ）",
        "partial": "一部推計",
        "imputed": "推計・外挿",
        "unknown": "記述なし（不明）",
    }
    q_order = [f"q{k}" for k in range(6)]
    q_colors = dict(zip(q_order, SEQ_BLUE, strict=True))
    for j, col in enumerate(("top1_wealth_share", "top1_income_share")):
        for i, (table, order, colors) in enumerate(
            ((cons[col], CONSTRUCTION_ORDER, cons_colors), (qual[col], q_order, q_colors))
        ):
            ax = axes[i][j]
            bottom = [0.0] * table.height
            for lab in order:
                vals = table[lab].to_list()
                ax.bar(range(table.height), vals, bottom=bottom, color=colors[lab], width=0.78)
                bottom = [b + v for b, v in zip(bottom, vals, strict=True)]
            ax.set_xticks(range(table.height))
            ax.set_xticklabels(table["period"].to_list(), fontsize=7, rotation=30, ha="right")
            ax.set_ylim(0, 1)
            _pct(ax)
            _style(ax)
            kind = (
                "構築方法（WID の説明文）"
                if i == 0
                else "品質スコア\n（0 = 推計寄り … 5 = 一次データに近い）"
            )
            ax.set_title(f"{JP_LABEL[col]}: {kind}", fontsize=8.5, color=INK, loc="left")
            print(f"  stacks {col} {'construction' if i == 0 else 'quality'}:")
            for r in table.iter_rows(named=True):
                print("   ", r["period"], f"n={r['n']}", {k: round(r[k], 3) for k in order})
    axes[0][0].set_ylabel("国×年の割合", fontsize=9)
    axes[1][0].set_ylabel("国×年の割合", fontsize=9)
    h1_ = [Patch(facecolor=cons_colors[k], label=cons_ja[k]) for k in CONSTRUCTION_ORDER]
    h2_ = [Patch(facecolor=q_colors[k], label=k) for k in q_order]
    axes[0][1].legend(
        handles=h1_, loc="upper left", bbox_to_anchor=(1.0, 1.0), frameon=False, fontsize=7.5
    )
    axes[1][1].legend(
        handles=h2_, loc="upper left", bbox_to_anchor=(1.0, 1.0), frameon=False, fontsize=7.5
    )
    fig.suptitle(
        "資産データは「観測」と明示された年が 1 つも無く、7 割が最低品質。確信が持てない理由",
        fontsize=11,
        color=INK,
        x=0.01,
        ha="left",
    )
    fig.tight_layout(rect=(0, 0.03, 0.86, 0.96))
    _save(fig, path, SRC_WID + "　46 か国の国×年、1950–2024 年。品質スコアの定義は WID 非公開")


def fig_japan_vs_median(panel: pl.DataFrame, path: Path) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    cols = ("top1_income_share", "top10_income_share", "top1_wealth_share")
    lo, hi = h1.BASE.window
    fig, axes = plt.subplots(1, 3, figsize=(10.5, 4.2))
    codes = sorted(panel["iso3"].unique().to_list())
    for ax, col in zip(axes, cols, strict=True):
        for iso3 in codes:
            if iso3 == JAPAN:
                continue
            obs = h1.series_in_window(panel, iso3, col, (lo, hi))
            ax.plot([y for y, _ in obs], [v for _, v in obs], color=FIELD, linewidth=0.6, zorder=1)
        med = median_by_year(panel, col, (lo, hi))
        ax.plot(med["year"], med["median"], color=INK, linewidth=1.8, zorder=2)
        jp = h1.series_in_window(panel, JAPAN, col, (lo, hi))
        ax.plot([y for y, _ in jp], [v for _, v in jp], color=ORANGE, linewidth=2.4, zorder=3)
        m80 = med.filter(pl.col("year") == 1980).row(0, named=True)
        m24 = med.filter(pl.col("year") == hi).row(0, named=True)
        print(
            f"  {col}: JPN 1980={dict(jp).get(1980, float('nan')):.3f} {hi}={jp[-1][1]:.3f}; "
            f"median 1980={m80['median']:.3f} (n={m80['n']}) "
            f"{hi}={m24['median']:.3f} (n={m24['n']})"
        )
        ax.set_title(JP_LABEL[col], fontsize=10, color=INK, loc="left")
        ax.set_xlabel("年", fontsize=9)
        _pct(ax)
        _style(ax)
    handles = [
        Line2D([], [], color=ORANGE, linewidth=2.4, label="日本"),
        Line2D([], [], color=INK, linewidth=1.8, label="46 か国の中央値（その年に観測がある国）"),
        Line2D([], [], color=FIELD, linewidth=1, label="他の 45 か国"),
    ]
    fig.legend(
        handles=handles,
        loc="lower right",
        ncol=3,
        frameon=False,
        fontsize=8,
        bbox_to_anchor=(0.99, 0.035),
    )
    fig.suptitle(
        "日本: 上位 1% は中央値付近で上昇が緩やか。上位 10% 所得は 1990 年代後半から中央値を上回る",
        fontsize=11,
        color=INK,
        x=0.01,
        ha="left",
    )
    fig.tight_layout(rect=(0, 0.1, 1, 0.94))
    _save(
        fig,
        path,
        SRC_WID
        + "　日本の所得は 2017–24 年、資産は 2013 年以降がほぼ同一値（WID 側の繰り越しの可能性）",
    )


def fig_japan_rank(panel: pl.DataFrame, path: Path) -> None:
    import matplotlib.pyplot as plt

    cols = ("top1_income_share", "top10_income_share", "top1_wealth_share")
    colors = (BLUE, SEQ_BLUE[2], ORANGE)
    n = panel["iso3"].n_unique()
    fig, ax = plt.subplots(figsize=(8.5, 4.4))
    for col, c in zip(cols, colors, strict=True):
        rs = rank_series(panel, col, JAPAN, (1980, 2024), full_n=n)
        ax.plot([y for y, _ in rs], [r for _, r in rs], color=c, linewidth=2, label=JP_LABEL[col])
        ax.annotate(
            f"{rs[-1][1]} 位",
            (rs[-1][0], rs[-1][1]),
            xytext=(4, 0),
            textcoords="offset points",
            fontsize=8,
            color=c,
            va="center",
        )
        print(f"  JPN rank {col}: 1980={rs[0][1]}/{n} 2024={rs[-1][1]}/{n}")
    ax.invert_yaxis()
    ax.set_ylim(n + 1, 0)
    ax.axhline(n / 2 + 0.5, color=MUTED, linewidth=0.7, linestyle="--")
    ax.text(2026, n / 2 + 0.5, "中位", fontsize=7.5, color=MUTED, va="center")
    ax.set_xlim(1979, 2029)
    ax.set_xlabel("年", fontsize=9)
    ax.set_ylabel("46 か国中の順位（1 = シェアが最も高い）", fontsize=9)
    ax.legend(frameon=False, fontsize=8, loc="lower left")
    _style(ax)
    ax.set_title(
        "日本の順位: 上位 1% は所得・資産とも 1980 年より下がった（偏りが相対的に小さくなった）",
        fontsize=11,
        color=INK,
        loc="left",
    )
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    _save(fig, path, SRC_WID + "　46 か国すべてに値がある 1980 年以降のみ")


def fig_h2_scatter(
    a1: pl.DataFrame, fit_a1: h2.Fit, a2: pl.DataFrame, fit_a2: h2.Fit, end: int, path: Path
) -> None:
    import matplotlib.pyplot as plt
    import numpy as np

    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.8))
    specs = (
        (
            axes[0],
            a1,
            fit_a1,
            "d_social_expenditure_gdp",
            f"社会支出 (GDP 比) の変化 1980→{end}（ポイント）",
            f"1980→{end} 年、n={fit_a1.n}",
        ),
        (
            axes[1],
            a2,
            fit_a2,
            "d_top_pit_rate",
            f"最高所得税率の変化 2000→{end}（ポイント）",
            f"2000→{end} 年、n={fit_a2.n}",
        ),
    )
    y = "d_top1_income_share"
    for ax, diff, fit, x, xlabel, head in specs:
        for r in diff.iter_rows(named=True):
            jp = r["iso3"] == JAPAN
            ax.scatter(r[x], r[y], s=40 if jp else 20, color=ORANGE if jp else BLUE, zorder=3)
            ax.annotate(
                r["iso3"],
                (r[x], r[y]),
                fontsize=7,
                color=ORANGE if jp else MUTED,
                xytext=(3, 2),
                textcoords="offset points",
                fontweight="bold" if jp else "normal",
            )
        xs = np.linspace(float(str(diff[x].min())), float(str(diff[x].max())), 50)
        b = fit.coef
        others = sum(b[k] * float(str(diff[k].mean())) for k in b if k not in ("const", x))
        ax.plot(xs, b["const"] + others + b[x] * xs, color=INK, linewidth=1.2, linestyle="--")
        ax.axhline(0, color=MUTED, linewidth=0.6)
        ax.axvline(0, color=MUTED, linewidth=0.6)
        ax.set_xlabel(xlabel, fontsize=9)
        ax.set_ylabel("上位 1% 所得シェアの変化（ポイント）", fontsize=9)
        ax.set_title(
            f"{head}　傾き {b[x]:+.2f}（p = {fit.pval[x]:.2f}）",
            fontsize=9.5,
            color=INK,
            loc="left",
        )
        _style(ax, grid_axis="both")
        print(
            f"  scatter {x}: b={b[x]:+.4f} se={fit.se[x]:.4f} p={fit.pval[x]:.3f} "
            f"n={fit.n} R2={fit.r2:.3f}"
        )
    fig.suptitle(
        "税制・社会支出の変化と上位 1% シェアの変化: 関連は弱く不安定（因果ではない）",
        fontsize=11,
        color=INK,
        x=0.01,
        ha="left",
    )
    fig.tight_layout(rect=(0, 0.04, 1, 0.94))
    _save(
        fig,
        path,
        SRC_WID_OECD
        + "　OECD 38 か国のうち両年に値がある国。破線 = 他の説明変数を平均に固定した回帰直線",
    )


def fig_h2_coefs(rows: list[dict[str, Any]], path: Path) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    x_ja = {
        "top_pit_rate": "最高所得税率",
        "social_expenditure_gdp": "社会支出 (GDP 比)",
        "tax_revenue_gdp": "総税収 (GDP 比)",
    }
    fig, ax = plt.subplots(figsize=(9.0, 0.36 * len(rows) + 1.9))
    for i, r in enumerate(rows):
        c = ORANGE if "wealth" in r["y"] else BLUE
        ax.plot([r["lo"], r["hi"]], [i, i], color=c, linewidth=1.4)
        ax.scatter(r["b"], i, color=c, s=28, zorder=3)
        ax.text(ax.get_xlim()[1], i, "", fontsize=7)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([f"{r['label']} | {x_ja[r['x']]} (n={r['n']})" for r in rows], fontsize=8)
    ax.invert_yaxis()
    ax.axvline(0, color=INK, linewidth=0.9)
    ax.set_xlabel(
        "説明変数が 1 ポイント動いたときの上位 1% シェアの変化（ポイント）と 95% 信頼区間",
        fontsize=9,
    )
    handles = [
        Line2D([], [], color=BLUE, marker="o", linewidth=1.4, label="上位 1% 所得シェア"),
        Line2D([], [], color=ORANGE, marker="o", linewidth=1.4, label="上位 1% 資産シェア"),
    ]
    ax.legend(handles=handles, frameon=False, fontsize=8, loc="lower right")
    _style(ax, grid_axis="x")
    ax.set_title(
        "ほとんどの区間が 0 をまたぐ。1980 年起点で見えた関連も 1990 年起点では消える",
        fontsize=11,
        color=INK,
        loc="left",
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    _save(
        fig,
        path,
        SRC_WID_OECD + "　国横断の長期差分 OLS、HC3 標準誤差。関連の分析であり因果ではない",
    )


def fig_method(path: Path) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

    steps = [
        ("① データ", "WID.world の 46 か国\n上位 1%/10% の所得・資産シェア\n1950–2024 年"),
        (
            "② 基準を先に決める",
            "「U 字」= 谷が 1965–95 年、\n谷までの下降・谷からの上昇が\nともに 1 ポイント以上",
        ),
        ("③ 1 国ずつ判定", "各国の系列に基準を当てて\nU 字 / 非 U 字 に二値分類"),
        ("④ 数える", "46 か国のうち何か国か。\n半数を超えるかを信頼区間で確認"),
        ("⑤ 疑って再計算", "推計年を外す、品質の低い年を\n外す（H1b・H1c）。\n結論が動くかを見る"),
    ]
    fig, ax = plt.subplots(figsize=(10.5, 3.6))
    ax.set_xlim(0, 10.5)
    ax.set_ylim(0, 3.6)
    ax.axis("off")
    w, h = 1.85, 2.3
    for i, (head, body) in enumerate(steps):
        x = 0.2 + i * 2.1
        ax.add_patch(
            FancyBboxPatch(
                (x, 0.6),
                w,
                h,
                boxstyle="round,pad=0.04,rounding_size=0.12",
                facecolor="#f4f7fc",
                edgecolor=BLUE,
                linewidth=1.2,
            )
        )
        ax.text(
            x + w / 2,
            0.6 + h - 0.25,
            head,
            ha="center",
            va="top",
            fontsize=10,
            color=BLUE,
            fontweight="bold",
        )
        ax.text(
            x + w / 2,
            0.6 + h / 2 - 0.15,
            body,
            ha="center",
            va="center",
            fontsize=8,
            color=INK,
            linespacing=1.5,
        )
        if i < len(steps) - 1:
            ax.add_patch(
                FancyArrowPatch(
                    (x + w + 0.03, 0.6 + h / 2),
                    (x + 2.1 - 0.03, 0.6 + h / 2),
                    arrowstyle="-|>",
                    mutation_scale=12,
                    color=MUTED,
                    linewidth=1,
                )
            )
    ax.set_title(
        "分析の進め方: 結果を見る前に基準を決め、その基準で数える（事前登録）",
        fontsize=11,
        color=INK,
        loc="left",
    )
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    _save(fig, path, "分析: socioscope（H1・H1b・H1c レポートの手順）")


# ---------------------------------------------------------------- main
def run(data_dir: Path, fig_dir: Path) -> None:
    font = configure_matplotlib()
    print(f"== font: {font} ==")
    panel = pl.read_parquet(data_dir / h1.MART).sort(["iso3", "year"])
    staged = pl.read_parquet(data_dir / h1.STAGED_SHARES)
    data_points = pl.read_parquet(data_dir / DATA_POINTS)
    inst = pl.read_parquet(data_dir / INSTITUTIONS).sort(["iso3", "year"])
    fig_dir.mkdir(parents=True, exist_ok=True)
    print(
        f"== inputs == panel={panel.height} staged={staged.height} "
        f"data_points={data_points.height} "
        f"institutions={inst.height} countries={panel['iso3'].n_unique()}"
    )

    trajs = {col: h1.classify_all(panel, col) for col in h1.SERIES}

    print("== fig01 explainer ==")
    fig01_explainer(panel, fig_dir / "s01_explainer_top1_share.png")
    print("== fig02/03 long-run ==")
    fig_longrun(
        panel,
        "top1_income_share",
        fig_dir / "s02_longrun_top1_income.png",
        title="上位 1% 所得シェアの 120 年: 戦前の高さ → 戦後の低下 → "
        "1980 年頃からの上昇（国により差）",
    )
    fig_longrun(
        panel,
        "top1_wealth_share",
        fig_dir / "s03_longrun_top1_wealth.png",
        title="上位 1% 資産シェアの 120 年: 欧州は大きく低下して一部回復、"
        "米国は再上昇、中国・インドは上昇",
    )
    print("== fig04/05 small multiples ==")
    fig_small_multiples(
        panel,
        trajs["top1_wealth_share"],
        "top1_wealth_share",
        fig_dir / "s04_small_multiples_top1_wealth.png",
        title="46 か国の上位 1% 資産シェア: 事前に決めた U 字の基準を満たすのは 12 か国",
    )
    fig_small_multiples(
        panel,
        trajs["top1_income_share"],
        "top1_income_share",
        fig_dir / "s05_small_multiples_top1_income.png",
        title="46 か国の上位 1% 所得シェア: U 字の基準を満たすのは 22 か国（半数弱）",
    )
    print("== fig06 change dots ==")
    ch = changes_table(
        trajs["top1_income_share"],
        trajs["top1_wealth_share"],
        "top1_income_share",
        "top1_wealth_share",
    )
    fig_change_dots(
        ch, "top1_income_share", "top1_wealth_share", fig_dir / "s06_change_since_1980_dots.png"
    )
    print("== fig07 trough histogram ==")
    fig_trough_hist(trajs, fig_dir / "s07_trough_year_hist.png")
    print("== fig08 majority bars ==")
    fig_majority_bars(trajs, fig_dir / "s08_ushape_vs_rise_bars.png")
    print("== fig09 quality stacks ==")
    cons = {
        col: shares_by_decade(
            construction_labels(panel, data_points, col, h1.BASE.window),
            "construction",
            CONSTRUCTION_ORDER,
        )
        for col in ("top1_wealth_share", "top1_income_share")
    }
    qual = {
        col: shares_by_decade(
            quality_labels(panel, staged, col, h1.BASE.window), "q", [f"q{k}" for k in range(6)]
        )
        for col in ("top1_wealth_share", "top1_income_share")
    }
    fig_quality_stacks(cons, qual, fig_dir / "s09_data_quality_stacks.png")
    print("== fig10 japan vs median ==")
    fig_japan_vs_median(panel, fig_dir / "s10_japan_vs_median.png")
    print("== fig11 japan rank ==")
    fig_japan_rank(panel, fig_dir / "s11_japan_rank.png")

    print("== fig12/13 H2 ==")
    inst_pp = h2.to_pp(inst)
    end = h2.end_year(inst_pp, (*h2.OUTCOMES, *h2.INST_ALL), h2.MIN_COUNTRIES_FOR_END)
    a1 = h2.long_difference(inst_pp, 1980, end, (*h2.OUTCOMES, *h2.INST_NO_PIT))
    a2 = h2.long_difference(inst_pp, 2000, end, (*h2.OUTCOMES, *h2.INST_ALL))
    r1 = h2.long_difference(inst_pp, 1990, end, (*h2.OUTCOMES, *h2.INST_NO_PIT))
    xs_a1 = tuple(f"d_{c}" for c in h2.INST_NO_PIT)
    xs_a2 = tuple(f"d_{c}" for c in h2.INST_ALL)
    fit_a1_inc = h2.fit_ols_hc3(a1, "d_top1_income_share", xs_a1, "A1")
    fit_a2_inc = h2.fit_ols_hc3(a2, "d_top1_income_share", xs_a2, "A2")
    print(f"  end year T={end}; A1 n={fit_a1_inc.n} A2 n={fit_a2_inc.n}")
    fig_h2_scatter(a1, fit_a1_inc, a2, fit_a2_inc, end, fig_dir / "s12_h2_scatter.png")
    rows: list[dict[str, Any]] = []
    for label, diff, xs in (
        (f"1980→{end}", a1, xs_a1),
        (f"1990→{end}（頑健性）", r1, xs_a1),
        (f"2000→{end}", a2, xs_a2),
    ):
        for y in h2.OUTCOMES:
            fit = h2.fit_ols_hc3(diff, f"d_{y}", xs, label)
            for r in coef_rows(fit, label):
                r["x"] = r["x"].removeprefix("d_")
                rows.append(r)
                print(
                    f"  coef {label} {y} {r['x']}: b={r['b']:+.4f} "
                    f"[{r['lo']:+.3f}, {r['hi']:+.3f}] p={r['p']:.3f} n={r['n']}"
                )
    fig_h2_coefs(rows, fig_dir / "s13_h2_coefficients.png")
    print("== fig14 method ==")
    fig_method(fig_dir / "s14_method_flow.png")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", type=Path, default=REPO_ROOT / "data")
    ap.add_argument("--fig-dir", type=Path, default=THEME_DIR / "reports" / "figures" / "summary")
    args: Any = ap.parse_args()
    run(args.data_dir, args.fig_dir)


if __name__ == "__main__":
    main()
