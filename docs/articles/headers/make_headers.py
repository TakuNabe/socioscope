"""note 記事のヘッダー画像（1280×670）を marts から決定的に生成する。

実行: uv run python docs/articles/headers/make_headers.py
出力: docs/articles/headers/<article>.png
"""

from __future__ import annotations

import math
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import polars as pl
from matplotlib.patches import FancyBboxPatch

ROOT = Path(__file__).resolve().parents[3]
MARTS = ROOT / "data" / "marts"
OUT = Path(__file__).resolve().parent

W, H, DPI = 1280, 670, 100
BLUE, ORANGE, INK, MUTED, PAPER = "#256abf", "#eb6834", "#1f2a37", "#8a94a3", "#f7f5f0"
FONT = "Hiragino Sans"

matplotlib.rcParams["font.family"] = FONT
matplotlib.rcParams["axes.unicode_minus"] = False


def canvas() -> tuple[plt.Figure, plt.Axes]:
    fig = plt.figure(figsize=(W / DPI, H / DPI), dpi=DPI)
    fig.patch.set_facecolor(PAPER)
    bg = fig.add_axes([0, 0, 1, 1])
    bg.set_axis_off()
    bg.patch.set_alpha(0)
    bg.set_zorder(10)
    bg.set_xlim(0, W)
    bg.set_ylim(0, H)
    return fig, bg


def title_block(bg: plt.Axes, title: str, sub: str, *, y: float = 600) -> None:
    bg.text(64, y, title, fontsize=40, fontweight=900, color=INK, va="top", ha="left")
    bg.text(66, y - 70, sub, fontsize=17, color=MUTED, va="top", ha="left")


def tag(bg: plt.Axes, x: float, y: float, text: str, color: str) -> None:
    bg.text(
        x,
        y,
        text,
        fontsize=15,
        fontweight="bold",
        color="white",
        va="center",
        ha="left",
        bbox={"boxstyle": "round,pad=0.5,rounding_size=0.9", "fc": color, "ec": "none"},
    )


def growth_fertility() -> Path:
    panel = pl.read_parquet(MARTS / "growth_fertility_panel.parquet")
    w = panel.filter(
        (pl.col("year") == 2024)
        & pl.col("tfr").is_not_null()
        & pl.col("gdp_pcap_ppp").is_not_null()
    ).filter(pl.col("population") >= 1_000_000)
    jp = (
        pl.read_parquet(MARTS / "jp_income_class_fertility.parquet")
        .filter(
            (pl.col("metric") == "married_share")
            & (pl.col("sex") == "male")
            & (pl.col("year") == 2024)
            & pl.col("income_class_lower_yen").is_not_null()
        )
        .sort("income_class_lower_yen")
    )

    fig, bg = canvas()
    title_block(
        bg,
        "豊かになると、子どもは減るのか？",
        "世界 217 か国と日本の所得階層を同じ物差しで見たら、向きが逆だった",
    )

    # left: between countries
    ax1 = fig.add_axes([0.07, 0.12, 0.38, 0.55])
    x = np.log(w["gdp_pcap_ppp"].to_numpy())
    y = w["tfr"].to_numpy()
    s = np.sqrt(w["population"].to_numpy() / 1e6) * 3 + 8
    is_jp = (w["iso3"] == "JPN").to_numpy()
    ax1.scatter(x[~is_jp], y[~is_jp], s=s[~is_jp], c=BLUE, alpha=0.35, lw=0)
    ax1.scatter(x[is_jp], y[is_jp], s=s[is_jp] + 40, c=ORANGE, lw=0, zorder=5)
    b, a = np.polyfit(x, y, 1)
    xs = np.linspace(x.min(), x.max(), 2)
    ax1.plot(xs, a + b * xs, color=BLUE, lw=5, solid_capstyle="round")
    ax1.annotate(
        "日本",
        (x[is_jp][0], y[is_jp][0]),
        xytext=(12, -14),
        textcoords="offset points",
        fontsize=13,
        color=ORANGE,
        fontweight="bold",
    )
    ax1.set_xticks([math.log(v) for v in (1000, 10000, 100000)])
    ax1.set_xticklabels(["$1,000", "$10,000", "$100,000"], fontsize=11, color=MUTED)
    ax1.set_yticks([1, 2, 3, 4, 5, 6])
    ax1.tick_params(colors=MUTED, labelsize=11, length=0)
    ax1.set_ylim(0.5, 7)
    for sp in ax1.spines.values():
        sp.set_visible(False)
    ax1.set_facecolor(PAPER)
    tag(bg, 92, 470, "国の間：豊かな国ほど、子どもが少ない", BLUE)

    # right: within Japan
    ax2 = fig.add_axes([0.59, 0.12, 0.36, 0.55])
    vals = jp["value"].to_numpy() * 100
    labels = jp["income_class"].to_list()
    idx = np.arange(len(vals))
    ax2.bar(idx, vals, color=ORANGE, width=0.72, alpha=0.9)
    ax2.set_xticks([0, 5, 10, len(vals) - 1])
    ax2.set_xticklabels(["〜50 万円", "300 万", "600 万", "1,000 万〜"], fontsize=11, color=MUTED)
    ax2.set_yticks([25, 50, 75])
    ax2.set_yticklabels(["25%", "50%", "75%"], fontsize=11, color=MUTED)
    ax2.tick_params(colors=MUTED, length=0)
    ax2.set_ylim(0, 100)
    for sp in ax2.spines.values():
        sp.set_visible(False)
    ax2.set_facecolor(PAPER)
    ax2.grid(axis="y", color="#e2ddd3", lw=1)
    ax2.set_axisbelow(True)
    tag(bg, 720, 470, "日本の中：所得が高いほど、結婚している", ORANGE)

    bg.text(
        612,
        250,
        "≠",
        fontsize=72,
        fontweight="bold",
        color=INK,
        ha="center",
        va="center",
        alpha=0.85,
    )
    bg.text(
        W - 40,
        18,
        "出典: World Bank WDI, 国民生活基礎調査 / socioscope",
        fontsize=9,
        color=MUTED,
        ha="right",
    )
    out = OUT / "2026-10-05-note-growth-fertility.png"
    fig.savefig(out, dpi=DPI, facecolor=PAPER)
    plt.close(fig)
    return out


def wealth() -> Path:
    panel = (
        pl.read_parquet(MARTS / "wealth_population_panel.parquet")
        .filter(
            (pl.col("year") >= 1950)
            & (pl.col("year") <= 2024)
            & pl.col("top1_wealth_share").is_not_null()
        )
        .sort(["iso3", "year"])
    )
    fig, bg = canvas()
    title_block(
        bg,
        "「金持ちはますます金持ちに」は本当か？",
        "46 か国・75 年分の「上位 1% の資産シェア」を、同じ基準で数えてみた",
    )

    ax = fig.add_axes([0.06, 0.10, 0.60, 0.58])
    for iso3, g in panel.group_by("iso3", maintain_order=True):
        yrs = g["year"].to_numpy()
        v = g["top1_wealth_share"].to_numpy() * 100
        if len(yrs) < 10:
            continue
        key = iso3[0]
        if key == "JPN":
            ax.plot(yrs, v, color=ORANGE, lw=3.5, zorder=6)
            ax.annotate(
                "日本",
                (yrs[-1], v[-1]),
                xytext=(8, 0),
                textcoords="offset points",
                fontsize=13,
                color=ORANGE,
                fontweight="bold",
                va="center",
            )
        elif key == "USA":
            ax.plot(yrs, v, color=BLUE, lw=3.5, zorder=5)
            ax.annotate(
                "アメリカ",
                (yrs[-1], v[-1]),
                xytext=(8, 0),
                textcoords="offset points",
                fontsize=13,
                color=BLUE,
                fontweight="bold",
                va="center",
            )
        else:
            ax.plot(yrs, v, color=MUTED, lw=1.2, alpha=0.3)
    ax.set_xlim(1950, 2034)
    ax.set_ylim(5, 75)
    ax.set_xticks([1950, 1980, 2024])
    ax.set_yticks([20, 40, 60])
    ax.set_yticklabels(["20%", "40%", "60%"])
    ax.tick_params(colors=MUTED, labelsize=11, length=0)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.set_facecolor(PAPER)
    ax.grid(axis="y", color="#e2ddd3", lw=1)
    ax.set_axisbelow(True)
    tag(bg, 80, 470, "上位 1% が持つ資産の割合、46 か国（1950〜2024 年）", INK)

    # stat tile
    bg.add_patch(
        FancyBboxPatch(
            (880, 120), 340, 300, boxstyle="round,pad=0,rounding_size=18", fc="white", ec="#e2ddd3"
        )
    )
    bg.text(1050, 385, "「U 字型」に戻った国は", fontsize=15, color=MUTED, ha="center", va="center")
    bg.text(1050, 290, "12", fontsize=86, fontweight=900, color=BLUE, ha="center", va="center")
    bg.text(
        1050, 215, "／ 46 か国", fontsize=22, fontweight="bold", color=INK, ha="center", va="center"
    )
    bg.text(
        1050,
        160,
        "多数派ではなかった。\nでも「1980 年以降に上がった」は 76%。",
        fontsize=12,
        color=MUTED,
        ha="center",
        va="center",
        linespacing=1.6,
    )
    bg.text(
        W - 40,
        18,
        "出典: WID.world（CC BY-NC-SA 4.0）/ socioscope",
        fontsize=9,
        color=MUTED,
        ha="right",
    )
    out = OUT / "2026-10-05-note-wealth-population-distribution.png"
    fig.savefig(out, dpi=DPI, facecolor=PAPER)
    plt.close(fig)
    return out


if __name__ == "__main__":
    for p in (growth_fertility(), wealth()):
        print(p)
