"""H5: 韓国・欧州の国内階層勾配と「手厚い政策でも回復しない北欧」。

事前登録: design/themes/growth-fertility.md「### H5」（2026-10-06）。結果を見る前に固定した推定量:
  (a) 政策 × TFR   OECD SOCX 家族支出（合計／現金／現物、%GDP）× WDI TFR、1980–2021、OECD 38
      (a1) 二元 FE（国＋年、国クラスタ SE）、同時と 3 年ラグ
      (a2) 横断: ΔTFR(2010→2021) ~ 2010 年水準 + Δ支出
      (a3) 分解: within 係数 × Δ支出 =「政策で説明できる ΔTFR」vs 実際（FIN SWE NOR DNK KOR JPN）
           判定: 北欧 4 か国すべてで説明割合 < 1/4 整合的 / いずれか >= 1/2 不支持 / それ以外 部分的
  (b) 国内階層勾配  欧州 2021 センサス: 性 × 25–59 歳 5 歳階級 × 学歴 3 群の有配偶率を
      年齢 FE 付き加重 OLS で学歴順位（0,1,2）に回帰。判定: 男性で正が 31 か国中 25 以上
      韓国: 新婚夫婦の所得区間別有子率の ln 所得勾配（記述のみ、共稼ぎ交絡）
  (c) 北欧低下の解剖 (c1) 出生順位別 TFR の 2010→最新の変化、第 1 子寄与率 >= 0.5（北欧 5 か国）
                     (c2) 学歴別 TFR（北欧 4）の 2010→最新 変化、3 群すべて低下

決定的スクリプト。乱数不使用、補完なし（listwise）。識別戦略なし: 関連・整合性の記述のみ。

    uv run python themes/growth-fertility/src/theme_growth_fertility/analysis/<this file>
        [--data-dir data] [--fig-dir themes/growth-fertility/reports/figures]

純粋関数（spending_wide, add_lag, delta_frame, explained_share, verdict_a3, census_gradient,
krw_midpoint, order_decomposition, education_change）は tests/test_analysis_h5.py で検証。
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import polars as pl

from theme_growth_fertility.analysis.a20261004_h1_income_tfr import (
    BLUE_RAMP,
    INK,
    MUTED,
    ORANGE,
    Est,
    _style,
    fit,
)
from theme_growth_fertility.analysis.a20261004_h3_jp_income_class import Coef, wls

THEME_DIR = Path(__file__).resolve().parents[3]
REPO_ROOT = THEME_DIR.parents[1]
PANEL_MART = Path("marts") / "growth_fertility_panel.parquet"
SPEND_MART = Path("marts") / "oecd_family_spending.parquet"
CENSUS_MART = Path("marts") / "eu_census_marital_by_education.parquet"
KR_MART = Path("marts") / "kr_newlywed_income_children.parquet"
ORDER_MART = Path("marts") / "eu_tfr_by_birth_order.parquet"
EDU_MART = Path("marts") / "eu_tfr_by_education.parquet"

SPEND_TYPES = {"_T": "family_total", "C": "cash", "K": "inkind"}
LAG = 3
BASE_YEAR, END_YEAR, PRE_COVID = 2010, 2021, 2019
NORDIC4 = ("FIN", "SWE", "NOR", "DNK")
NORDIC5 = ("FIN", "SWE", "NOR", "DNK", "ISL")
DECOMP_COUNTRIES = ("FIN", "SWE", "NOR", "DNK", "KOR", "JPN")
SOUTH = ("ITA", "ESP", "PRT", "GRC")
EDU_RANK = {"ED0-2": 0, "ED3-4": 1, "ED5-8": 2}
CENSUS_AGES = (25, 59)
MIN_WOMEN_THOUSAND = 20.0
TOP_FACTOR = 1.5  # open-top income band midpoint = lower × 1.5 (same rule as H3)
GREEN = "#2f9e6e"


# ---------------------------------------------------------------- pure helpers (tested)
def spending_wide(spend: pl.DataFrame) -> pl.DataFrame:
    """Long (iso3, year, spending_type, value) -> wide (iso3, year, family_total, cash, inkind)."""
    out = (
        spend.filter(pl.col("spending_type").is_in(list(SPEND_TYPES)))
        .with_columns(pl.col("spending_type").replace_strict(SPEND_TYPES).alias("col"))
        .pivot(on="col", index=["iso3", "year"], values="value", aggregate_function="first")
    )
    for c in SPEND_TYPES.values():
        if c not in out.columns:
            out = out.with_columns(pl.lit(None, dtype=pl.Float64).alias(c))
    return out.select("iso3", "year", *SPEND_TYPES.values()).sort(["iso3", "year"])


def policy_frame(panel: pl.DataFrame, spend: pl.DataFrame) -> pl.DataFrame:
    """iso3×year rows with tfr and all three spending series observed (OECD members only)."""
    wide = spending_wide(spend)
    return (
        panel.select("iso3", "country", "year", "tfr", "population")
        .join(wide, on=["iso3", "year"], how="inner")
        .filter(
            pl.col("tfr").is_not_null()
            & pl.col("family_total").is_not_null()
            & pl.col("cash").is_not_null()
            & pl.col("inkind").is_not_null()
        )
        .with_columns(pl.col("year").cast(pl.Int64))
        .filter(pl.col("year") <= END_YEAR)  # pre-registered window 1980-2021
        .sort(["iso3", "year"])
    )


def add_lag(frame: pl.DataFrame, cols: Sequence[str], lag: int = LAG) -> pl.DataFrame:
    """x_{t-lag} per iso3, only when the row for year t-lag exists (no interpolation)."""
    lagged = frame.select(
        "iso3",
        (pl.col("year") + lag).alias("year"),
        *[pl.col(c).alias(f"{c}_l{lag}") for c in cols],
    )
    return frame.join(lagged, on=["iso3", "year"], how="left")


def delta_frame(frame: pl.DataFrame, start: int, end: int) -> pl.DataFrame:
    """Per-country changes start->end for tfr and spending, plus start levels. Needs both years."""
    a = frame.filter(pl.col("year") == start).select(
        "iso3",
        pl.col("tfr").alias("tfr_start"),
        pl.col("family_total").alias("spend_start"),
        pl.col("cash").alias("cash_start"),
        pl.col("inkind").alias("inkind_start"),
    )
    b = frame.filter(pl.col("year") == end).select(
        "iso3",
        pl.col("tfr").alias("tfr_end"),
        pl.col("family_total").alias("spend_end"),
        pl.col("cash").alias("cash_end"),
        pl.col("inkind").alias("inkind_end"),
    )
    return (
        a.join(b, on="iso3", how="inner")
        .with_columns(
            (pl.col("tfr_end") - pl.col("tfr_start")).alias("d_tfr"),
            (pl.col("spend_end") - pl.col("spend_start")).alias("d_spend"),
            (pl.col("cash_end") - pl.col("cash_start")).alias("d_cash"),
            (pl.col("inkind_end") - pl.col("inkind_start")).alias("d_inkind"),
        )
        .sort("iso3")
    )


def explained_share(b_within: float, d_spend: float, d_tfr: float) -> float | None:
    """(b × Δspend) / ΔTFR; None when ΔTFR is ~0. Negative = policy moved the other way."""
    if abs(d_tfr) < 1e-9:
        return None
    return (b_within * d_spend) / d_tfr


def verdict_a3(shares: dict[str, float | None]) -> str:
    vals = [v for k, v in shares.items() if k in NORDIC4 and v is not None]
    if len(vals) < len(NORDIC4):
        return "undetermined (a Nordic country lacks both years)"
    if all(v < 0.25 for v in vals):
        return "consistent with H5(a) (policy explains < 1/4 of the Nordic decline)"
    if any(v >= 0.5 for v in vals):
        return "not supported (policy explains >= 1/2 in at least one Nordic country)"
    return "partial"


def census_gradient(cells: pl.DataFrame) -> Coef:
    """Education-rank slope of married_share with age-class fixed effects, weights = total.

    cells: rows of one country × sex with columns age_class, isced_group, married_share, total.
    """
    sub = cells.filter(pl.col("isced_group").is_in(list(EDU_RANK)) & (pl.col("total") > 0)).sort(
        ["age_class", "isced_group"]
    )
    ages = sorted(sub["age_class"].unique().to_list())
    rank = np.array([EDU_RANK[g] for g in sub["isced_group"].to_list()], dtype=float)
    dummies = (
        np.column_stack([(sub["age_class"] == a).cast(pl.Float64).to_numpy() for a in ages[1:]])
        if len(ages) > 1
        else np.empty((sub.height, 0))
    )
    x = np.column_stack([rank, dummies])
    names = ["edu_rank", *[f"age_{a}" for a in ages[1:]]]
    return wls(x, sub["married_share"].to_numpy(), sub["total"].to_numpy(), names).coefs["edu_rank"]


def krw_midpoint(
    lower: float | None, upper: float | None, *, top_factor: float = TOP_FACTOR
) -> float | None:
    """Midpoint of an income band in 10k KRW; open top -> lower × top_factor; None if no bounds."""
    if lower is None:
        return None
    mid = lower * top_factor if upper is None else (lower + upper) / 2
    return None if mid <= 0 else mid


def korea_slope(
    kr: pl.DataFrame, ref_year: int, *, metric: str = "with_children_share"
) -> tuple[Coef, int]:
    """Weighted (couples) slope of *metric* on ln income midpoint across the 6 bands of one year."""
    y = kr.filter((pl.col("ref_year") == ref_year) & (pl.col("income_class") != "total"))
    val = y.filter(pl.col("metric") == metric).select(
        "income_class", "income_lower_10k_krw", "income_upper_10k_krw", "value"
    )
    w = y.filter(pl.col("metric") == "couples").select(
        "income_class", pl.col("value").alias("couples")
    )
    d = (
        val.join(w, on="income_class", how="left")
        .with_columns(
            pl.struct("income_lower_10k_krw", "income_upper_10k_krw")
            .map_elements(
                lambda s: krw_midpoint(s["income_lower_10k_krw"], s["income_upper_10k_krw"]),
                return_dtype=pl.Float64,
            )
            .alias("mid")
        )
        .filter(pl.col("mid").is_not_null() & pl.col("value").is_not_null())
    )
    weights = d["couples"].to_numpy() if d["couples"].null_count() == 0 else None
    return wls(
        np.log(d["mid"].to_numpy())[:, None], d["value"].to_numpy(), weights, ["ln_income"]
    ).coefs["ln_income"], d.height


def order_decomposition(
    orders: pl.DataFrame, iso3: str, start: int, end: int | None = None
) -> dict[str, float] | None:
    """ΔTFR by birth order start->end (end = latest year with orders 1,2,3,GE4 all present).

    Returns dict with end year, Δ per order, total of known orders and first-birth share
    (Δ1 / Δknown). UNK is excluded from the total (pre-registered). None if data missing.
    """
    known = ["1", "2", "3", "GE4"]
    sub = orders.filter(
        (pl.col("iso3") == iso3) & pl.col("order").is_in(known) & pl.col("tfr").is_not_null()
    )
    complete = (
        sub.group_by("year").agg(pl.col("order").n_unique().alias("k")).filter(pl.col("k") == 4)
    )
    years = sorted(complete["year"].to_list())
    if start not in years:
        return None
    end_year = end if end is not None else years[-1]
    if end_year not in years or end_year <= start:
        return None
    s = {r["order"]: r["tfr"] for r in sub.filter(pl.col("year") == start).iter_rows(named=True)}
    e = {r["order"]: r["tfr"] for r in sub.filter(pl.col("year") == end_year).iter_rows(named=True)}
    deltas = {o: float(e[o]) - float(s[o]) for o in known}
    total = sum(deltas.values())
    share = deltas["1"] / total if abs(total) > 1e-9 else float("nan")
    return {
        "end_year": float(end_year),
        **{f"d_{o}": v for o, v in deltas.items()},
        "d_known": total,
        "tfr_known_start": sum(float(s[o]) for o in known),
        "first_share": share,
    }


def education_change(
    edu: pl.DataFrame, iso3: str, start: int, *, min_women: float = MIN_WOMEN_THOUSAND
) -> pl.DataFrame:
    """TFR by ISCED group at start and at the latest year where all 3 groups exist; change."""
    sub = edu.filter(
        (pl.col("iso3") == iso3)
        & pl.col("isced_group").is_in(list(EDU_RANK))
        & pl.col("tfr").is_not_null()
        & (pl.col("women_total_thousand") >= min_women)
    )
    complete = (
        sub.group_by("year")
        .agg(pl.col("isced_group").n_unique().alias("k"))
        .filter(pl.col("k") == 3)
    )
    years = sorted(complete["year"].to_list())
    if start not in years or years[-1] <= start:
        return pl.DataFrame(
            schema={
                "iso3": pl.Utf8,
                "isced_group": pl.Utf8,
                "start": pl.Int64,
                "end": pl.Int64,
                "tfr_start": pl.Float64,
                "tfr_end": pl.Float64,
                "change": pl.Float64,
            }
        )
    end = years[-1]
    a = sub.filter(pl.col("year") == start).select(
        "iso3", "isced_group", pl.col("tfr").alias("tfr_start")
    )
    b = sub.filter(pl.col("year") == end).select("isced_group", pl.col("tfr").alias("tfr_end"))
    return (
        a.join(b, on="isced_group", how="inner")
        .with_columns(
            pl.lit(start).cast(pl.Int64).alias("start"),
            pl.lit(end).cast(pl.Int64).alias("end"),
            (pl.col("tfr_end") - pl.col("tfr_start")).alias("change"),
        )
        .select("iso3", "isced_group", "start", "end", "tfr_start", "tfr_end", "change")
        .sort("isced_group")
    )


def _span(s: pl.Series) -> str:
    return f"{int(str(s.min()))}-{int(str(s.max()))}"


# ---------------------------------------------------------------- (a) policy × TFR
def block_a1(frame: pl.DataFrame, tag: str) -> dict[str, Est]:
    out: dict[str, Est] = {}
    out["total"] = fit(
        frame, "tfr ~ family_total", label=f"[{tag} a1] FE: tfr ~ family_total", fe=True
    )
    out["split"] = fit(
        frame, "tfr ~ cash + inkind", label=f"[{tag} a1] FE: tfr ~ cash + inkind", fe=True
    )
    lagged = add_lag(frame, ["family_total", "cash", "inkind"]).filter(
        pl.col(f"family_total_l{LAG}").is_not_null()
    )
    out["total_lag"] = fit(
        lagged,
        f"tfr ~ family_total_l{LAG}",
        label=f"[{tag} a1] FE: tfr ~ family_total (t-{LAG})",
        fe=True,
    )
    out["split_lag"] = fit(
        lagged,
        f"tfr ~ cash_l{LAG} + inkind_l{LAG}",
        label=f"[{tag} a1] FE: tfr ~ cash + inkind (t-{LAG})",
        fe=True,
    )
    for e in out.values():
        print(e.line())
    return out


def block_a2(frame: pl.DataFrame, start: int, end: int, tag: str) -> tuple[pl.DataFrame, Est]:
    d = delta_frame(frame, start, end)
    est = fit(
        d,
        "d_tfr ~ spend_start + d_spend",
        label=f"[{tag} a2] cross-section ΔTFR {start}->{end} ~ level_{start} + Δspend",
        fe=False,
    )
    print(est.line())
    print(
        fit(
            d, "d_tfr ~ spend_start", label=f"[{tag} a2] ΔTFR ~ level_{start} only", fe=False
        ).line()
    )
    print(
        fit(
            d,
            "d_tfr ~ cash_start + inkind_start + d_cash + d_inkind",
            label=f"[{tag} a2] ΔTFR ~ cash/in-kind levels + changes",
            fe=False,
        ).line()
    )
    return d, est


def block_a3(d: pl.DataFrame, b_within: float, tag: str) -> dict[str, float | None]:
    print(f"[{tag} a3] decomposition with within coefficient b = {b_within:+.4f} TFR per 1 pp GDP")
    print(f"  {'iso3':<5}{'ΔTFR':>8}{'Δspend':>9}{'b×Δspend':>10}{'share':>8}")
    shares: dict[str, float | None] = {}
    for iso3 in DECOMP_COUNTRIES:
        row = d.filter(pl.col("iso3") == iso3)
        if row.height == 0:
            print(f"  {iso3:<5}  (missing)")
            shares[iso3] = None
            continue
        d_tfr, d_spend = float(row["d_tfr"][0]), float(row["d_spend"][0])
        share = explained_share(b_within, d_spend, d_tfr)
        shares[iso3] = share
        s_txt = "nan" if share is None else f"{share:+.2f}"
        print(f"  {iso3:<5}{d_tfr:>+8.3f}{d_spend:>+9.3f}{b_within * d_spend:>+10.3f}{s_txt:>8}")
    print(f"  -> (a3) {verdict_a3(shares)}")
    return shares


# ---------------------------------------------------------------- (b) gradients
def census_gradients(census: pl.DataFrame) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    sub = census.filter(
        (pl.col("age_lower") >= CENSUS_AGES[0]) & (pl.col("age_lower") <= CENSUS_AGES[1] - 4)
    )
    for (iso3, sex), cells in sub.group_by(["iso3", "sex"], maintain_order=True):
        try:
            c = census_gradient(cells)
        except (ValueError, np.linalg.LinAlgError) as e:  # too few cells / singular
            print(f"  {iso3} {sex}: skipped ({e})")
            continue
        rows.append(
            {
                "iso3": iso3,
                "sex": sex,
                "b": c.b,
                "lo": c.lo,
                "hi": c.hi,
                "cells": cells.height,
                "sign": "positive" if c.lo > 0 else ("negative" if c.hi < 0 else "zero"),
            }
        )
    return pl.DataFrame(rows).sort(["sex", "b"])


def print_gradients(g: pl.DataFrame, label: str) -> None:
    print(f"== (b) census 2021 education gradient of married share ({label}) ==")
    for sex in ("M", "F"):
        s = g.filter(pl.col("sex") == sex)
        pos = s.filter(pl.col("sign") == "positive").height
        neg = s.filter(pl.col("sign") == "negative").height
        print(
            f"  sex={sex}: countries={s.height} positive={pos} negative={neg} "
            f"zero={s.height - pos - neg}"
        )
        for r in s.iter_rows(named=True):
            print(f"    {r['iso3']} {r['b']:+.4f} [{r['lo']:+.4f}, {r['hi']:+.4f}] {r['sign']}")
    men = g.filter(pl.col("sex") == "M")
    pos = men.filter(pl.col("sign") == "positive").height
    verdict = "consistent with H5(b) men" if pos >= 25 else "not supported"
    print(f"  -> (b) men positive in {pos}/{men.height}: {verdict} (bar: >= 25)")
    women = g.filter(pl.col("sex") == "F")
    for name, group in (("Nordic", NORDIC5), ("South", SOUTH)):
        sub = women.filter(pl.col("iso3").is_in(list(group)))
        print(
            f"  women {name}: "
            + ", ".join(
                f"{r['iso3']} {r['b']:+.3f} ({r['sign']})" for r in sub.iter_rows(named=True)
            )
        )


# ---------------------------------------------------------------- figures
def fig_policy(res: dict[str, Est], path: Path, *, n: int, g: int) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = [
        ("family total (t)", res["total"].coefs["family_total"], ORANGE),
        ("cash (t)", res["split"].coefs["cash"], BLUE_RAMP[2]),
        ("in-kind (t)", res["split"].coefs["inkind"], BLUE_RAMP[2]),
        (f"family total (t-{LAG})", res["total_lag"].coefs[f"family_total_l{LAG}"], ORANGE),
        (f"cash (t-{LAG})", res["split_lag"].coefs[f"cash_l{LAG}"], BLUE_RAMP[2]),
        (f"in-kind (t-{LAG})", res["split_lag"].coefs[f"inkind_l{LAG}"], BLUE_RAMP[2]),
    ]
    fig, ax = plt.subplots(figsize=(6.8, 3.8))
    ys = list(range(len(rows)))[::-1]
    for y, (_lab, (b, _, lo, hi), color) in zip(ys, rows, strict=True):
        ax.plot([lo, hi], [y, y], color=color, linewidth=2)
        ax.plot([b], [y], "o", color=color, markersize=5)
    ax.axvline(0, color=MUTED, linewidth=0.8)
    ax.set_yticks(ys)
    ax.set_yticklabels([r[0] for r in rows], fontsize=8, color=INK)
    ax.set_xlabel(
        "TFR per 1 pp of GDP in public family spending, two-way FE, 95% CI", fontsize=8, color=INK
    )
    ax.set_title(
        f"H5(a1): within-country association of family spending and TFR. n={n}, countries={g}\n"
        "Source: OECD SOCX (TP51, public), World Bank WDI. SE clustered by country.",
        fontsize=9,
        color=INK,
    )
    _style(ax)
    ax.grid(axis="x", color="#e5e5e5", linewidth=0.6)
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    fig.savefig(path, dpi=150, metadata={"Software": None})
    plt.close(fig)


def fig_paradox(d: pl.DataFrame, est: Est, path: Path, *, start: int, end: int) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6.8, 4.6))
    x, y = d["spend_start"].to_numpy(), d["d_tfr"].to_numpy()
    colors = [
        ORANGE if c in NORDIC5 else (GREEN if c in ("KOR", "JPN") else BLUE_RAMP[2])
        for c in d["iso3"].to_list()
    ]
    ax.scatter(x, y, s=22, color=colors, edgecolors="none", alpha=0.85)
    for iso3, xi, yi in zip(d["iso3"].to_list(), x, y, strict=True):
        ax.annotate(
            iso3, (xi, yi), fontsize=6.5, color=INK, xytext=(3, 2), textcoords="offset points"
        )
    ax.axhline(0, color=MUTED, linewidth=0.8)
    b = est.coefs["spend_start"]
    ax.set_xlabel(f"public family spending, % of GDP, {start}", fontsize=8, color=INK)
    ax.set_ylabel(f"change in TFR {start}->{end}", fontsize=8, color=INK)
    ax.set_title(
        f"H5(a2): did high spenders hold up better? slope on {start} level "
        f"{b[0]:+.3f} [{b[2]:+.3f}, {b[3]:+.3f}], Δspend held fixed\n"
        f"Orange: Nordic. Green: KOR/JPN. n={d.height}. Source: OECD SOCX, WDI",
        fontsize=9,
        color=INK,
    )
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=150, metadata={"Software": None})
    plt.close(fig)


def fig_census(g: pl.DataFrame, path: Path, *, jp_men: float | None) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(9.5, 6.2), sharey=False)
    for ax, sex, title in zip(axes, ("M", "F"), ("men", "women"), strict=True):
        s = g.filter(pl.col("sex") == sex).sort("b")
        ys = list(range(s.height))
        for yi, r in zip(ys, s.iter_rows(named=True), strict=True):
            color = (
                ORANGE if r["iso3"] in NORDIC5 else (GREEN if r["iso3"] in SOUTH else BLUE_RAMP[2])
            )
            ax.plot([r["lo"], r["hi"]], [yi, yi], color=color, linewidth=1.6)
            ax.plot([r["b"]], [yi], "o", color=color, markersize=4)
        ax.set_yticks(ys)
        ax.set_yticklabels(s["iso3"].to_list(), fontsize=7, color=INK)
        ax.axvline(0, color=MUTED, linewidth=0.8)
        if sex == "M" and jp_men is not None:
            ax.axvline(jp_men, color="#b5451b", linewidth=1.0, linestyle=":")
            ax.annotate(
                "Japan H3b\n(income axis,\nnot comparable)",
                (jp_men, 0.5),
                fontsize=6.5,
                color="#b5451b",
                ha="left",
                xytext=(3, 0),
                textcoords="offset points",
            )
        ax.set_title(
            f"{title}: married share per education step (ED0-2 -> ED3-4 -> ED5-8)",
            fontsize=8.5,
            color=INK,
        )
        ax.set_xlabel("slope, age-FE weighted OLS, 95% CI", fontsize=8, color=INK)
        _style(ax)
        ax.grid(axis="y", visible=False)
        ax.grid(axis="x", color="#e5e5e5", linewidth=0.6)
    fig.suptitle(
        "H5(b): education gradient of legal marriage, ages 25-59, Census 2021. "
        "Orange: Nordic, green: South. "
        "Source: Eurostat cens_21me_r2",
        fontsize=9,
        color=INK,
    )
    fig.tight_layout()
    fig.savefig(path, dpi=150, metadata={"Software": None})
    plt.close(fig)


def fig_korea(kr: pl.DataFrame, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    years = sorted(kr["ref_year"].unique().to_list())
    for yr, color in zip(years, BLUE_RAMP * 3, strict=False):
        s = kr.filter(
            (pl.col("ref_year") == yr)
            & (pl.col("metric") == "with_children_share")
            & (pl.col("income_class") != "total")
        ).sort("income_lower_10k_krw")
        mids = [
            krw_midpoint(lo, hi)
            for lo, hi in zip(
                s["income_lower_10k_krw"].to_list(),
                s["income_upper_10k_krw"].to_list(),
                strict=True,
            )
        ]
        xs = [float(m) for m in mids if m is not None]
        ax.plot(xs, s["value"].to_list(), marker="o", color=color, linewidth=1.8, label=str(yr))
    ax.set_xscale("log")
    ax.set_xlabel(
        "couple's annual earned + business income, 10k KRW (band midpoint, log)",
        fontsize=8,
        color=INK,
    )
    ax.set_ylabel("share of couples with a child", fontsize=8, color=INK)
    ax.set_title(
        "H5(b) Korea: first-marriage couples within 5 years of marriage, "
        "share with children by income band\n"
        "Source: 국가데이터처 신혼부부통계 (KOGL type 1). Dual-earner status not adjusted.",
        fontsize=9,
        color=INK,
    )
    ax.legend(frameon=False, fontsize=7, title="reference year", title_fontsize=7)
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=150, metadata={"Software": None})
    plt.close(fig)


def fig_orders(dec: dict[str, dict[str, float]], path: Path, *, start: int) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    isos = list(dec)
    fig, ax = plt.subplots(figsize=(8.0, 4.2))
    bottom_pos = np.zeros(len(isos))
    bottom_neg = np.zeros(len(isos))
    for o, color, lab in (
        ("1", BLUE_RAMP[3], "1st"),
        ("2", BLUE_RAMP[2], "2nd"),
        ("3", BLUE_RAMP[1], "3rd"),
        ("GE4", BLUE_RAMP[0], "4th+"),
    ):
        vals = np.array([dec[i][f"d_{o}"] for i in isos])
        base = np.where(vals >= 0, bottom_pos, bottom_neg)
        ax.bar(isos, vals, bottom=base, color=color, label=lab, width=0.7)
        bottom_pos = bottom_pos + np.where(vals >= 0, vals, 0)
        bottom_neg = bottom_neg + np.where(vals < 0, vals, 0)
    for i, iso3 in enumerate(isos):
        ax.annotate(
            f"{dec[iso3]['first_share']:.0%}\n'{int(dec[iso3]['end_year']) % 100:02d}",
            (i, bottom_neg[i]),
            fontsize=6.5,
            color=INK,
            ha="center",
            va="top",
            xytext=(0, -2),
            textcoords="offset points",
        )
    ax.axhline(0, color=MUTED, linewidth=0.8)
    ax.set_ylabel(f"change in order-specific TFR since {start}", fontsize=8, color=INK)
    ax.set_title(
        f"H5(c1): change in TFR by birth order, {start} -> latest year "
        "(label: first-birth share of the change, end year)\n"
        "Source: Eurostat demo_fordagec, demo_pjan. Unknown order excluded.",
        fontsize=9,
        color=INK,
    )
    ax.legend(frameon=False, fontsize=7.5, ncol=4)
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=150, metadata={"Software": None})
    plt.close(fig)


def fig_education(edu: pl.DataFrame, isos: Sequence[str], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator

    fig, axes = plt.subplots(1, len(isos), figsize=(3.0 * len(isos), 3.6), sharey=True)
    for ax, iso3 in zip(np.atleast_1d(axes), isos, strict=True):
        sub = edu.filter(
            (pl.col("iso3") == iso3)
            & pl.col("isced_group").is_in(list(EDU_RANK))
            & (pl.col("women_total_thousand") >= MIN_WOMEN_THOUSAND)
        )
        for grp, color in zip(EDU_RANK, (BLUE_RAMP[0], BLUE_RAMP[2], BLUE_RAMP[3]), strict=True):
            s = sub.filter(pl.col("isced_group") == grp).sort("year")
            ax.plot(s["year"], s["tfr"], color=color, linewidth=1.8, label=grp)
        ax.set_title(iso3, fontsize=9, color=INK)
        ax.set_xlabel("year", fontsize=8, color=INK)
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        _style(ax)
    np.atleast_1d(axes)[0].set_ylabel("TFR by mother's education (approx.)", fontsize=8, color=INK)
    np.atleast_1d(axes)[0].legend(frameon=False, fontsize=7)
    fig.suptitle(
        "H5(c2): TFR by education, Nordic countries. Numerator: register births (demo_faeduc); "
        "denominator: LFS population "
        "(lfsa_pgaed). Cells with < 20k women dropped.",
        fontsize=8.5,
        color=INK,
    )
    fig.tight_layout()
    fig.savefig(path, dpi=150, metadata={"Software": None})
    plt.close(fig)


# ---------------------------------------------------------------- driver
def run(data_dir: Path, fig_dir: Path) -> None:
    fig_dir.mkdir(parents=True, exist_ok=True)
    panel = pl.read_parquet(data_dir / PANEL_MART)

    # ---------------- (a)
    spend = pl.read_parquet(data_dir / SPEND_MART)
    frame = policy_frame(panel, spend)
    print("== (a) policy × TFR sample ==")
    print(f"n={frame.height} countries={frame['iso3'].n_unique()} years {_span(frame['year'])}")
    print(frame.select(["family_total", "cash", "inkind", "tfr"]).describe())
    print("\n== (a1) two-way FE (main) ==")
    main = block_a1(frame, "M")
    fig_policy(main, fig_dir / "h5_policy_within.png", n=frame.height, g=frame["iso3"].n_unique())

    print(f"\n== (a2) cross-section {BASE_YEAR}->{END_YEAR} ==")
    d, est = block_a2(frame, BASE_YEAR, END_YEAR, "M")
    print(
        d.select("iso3", "tfr_start", "tfr_end", "d_tfr", "spend_start", "d_spend").filter(
            pl.col("iso3").is_in(list(DECOMP_COUNTRIES))
        )
    )
    fig_paradox(d, est, fig_dir / "h5_paradox_scatter.png", start=BASE_YEAR, end=END_YEAR)

    print(f"\n== (a3) decomposition {BASE_YEAR}->{END_YEAR} ==")
    shares = block_a3(d, main["total"].coefs["family_total"][0], "M")
    print("  (using the lagged coefficient instead):")
    block_a3(d, main["total_lag"].coefs[f"family_total_l{LAG}"][0], "M-lag")
    _ = shares

    print("\n== (a) robustness (pre-registered) ==")
    variants = [
        ("1995+", frame.filter(pl.col("year") >= 1995)),
        ("drop Nordic 5", frame.filter(~pl.col("iso3").is_in(list(NORDIC5)))),
        ("drop KOR+JPN", frame.filter(~pl.col("iso3").is_in(["KOR", "JPN"]))),
    ]
    for name, sub in variants:
        print(f"-- {name}: n={sub.height} countries={sub['iso3'].n_unique()}")
        block_a1(sub, f"R {name}")
    print("-- population-weighted WLS (weight = population), two-way FE")
    import statsmodels.formula.api as smf

    pdf = frame.filter(pl.col("population").is_not_null()).to_pandas()
    res = smf.wls(
        "tfr ~ family_total + C(iso3) + C(year)", data=pdf, weights=pdf["population"]
    ).fit(cov_type="cluster", cov_kwds={"groups": pdf["iso3"]})
    ci = res.conf_int()
    print(
        f"[R wls a1] family_total: {res.params['family_total']:+.4f} "
        f"[{ci.loc['family_total', 0]:+.4f}, {ci.loc['family_total', 1]:+.4f}] n={int(res.nobs)}"
    )
    print(f"-- (a2) {BASE_YEAR}->{PRE_COVID} (pre-COVID)")
    d19, _ = block_a2(frame, BASE_YEAR, PRE_COVID, "R pre-COVID")
    block_a3(d19, main["total"].coefs["family_total"][0], "R pre-COVID")

    # ---------------- (b)
    print("\n")
    census = pl.read_parquet(data_dir / CENSUS_MART)
    print(f"== (b) census mart: rows={census.height} countries={census['iso3'].n_unique()} ==")
    g = census_gradients(census)
    print_gradients(g, "main: ages 25-59, 3 groups")
    fig_census(
        g, fig_dir / "h5_census_gradients.png", jp_men=0.169
    )  # H3b age-FE slope (income axis, sign only)
    print("-- robustness: ages 30-49")
    g3049 = census_gradients(
        census.filter((pl.col("age_lower") >= 30) & (pl.col("age_lower") <= 45))
    )
    print_gradients(g3049, "ages 30-49")
    print("-- robustness: 2 groups (ED5-8 vs ED0-4), ages 25-59")
    two = (
        census.with_columns(
            pl.when(pl.col("isced_group") == "ED5-8")
            .then(pl.lit("ED5-8"))
            .otherwise(pl.lit("ED0-2"))
            .alias("isced_group")
        )
        .group_by(["iso3", "sex", "age_class", "age_lower", "isced_group"])
        .agg(pl.col("married").sum(), pl.col("total").sum())
        .with_columns((pl.col("married") / pl.col("total")).alias("married_share"))
    )
    print_gradients(census_gradients(two), "2 groups")

    kr_path = data_dir / KR_MART
    if kr_path.exists():
        kr = pl.read_parquet(kr_path)
        print(
            f"\n== (b) Korea newlywed mart: rows={kr.height} "
            f"years={sorted(kr['ref_year'].unique().to_list())} =="
        )
        for yr in sorted(kr["ref_year"].unique().to_list()):
            concept = kr.filter(pl.col("ref_year") == yr)["income_concept"][0]
            try:
                c, n = korea_slope(kr, yr)
                cm, _ = korea_slope(kr, yr, metric="mean_children")
                print(
                    f"  {yr} ({concept}): with_children_share ~ ln income: {c.fmt()} "
                    f"(bands={n}); mean_children: {cm.fmt()}"
                )
            except ValueError as e:
                print(f"  {yr}: skipped ({e})")
        print(
            kr.filter(pl.col("metric") == "with_children_share")
            .select("ref_year", "income_class", "value")
            .sort(["ref_year", "income_class"])
        )
        fig_korea(kr, fig_dir / "h5_korea_newlywed.png")
    else:
        print("\n== (b) Korea newlywed mart missing: skipped ==")

    # ---------------- (c)
    print("\n")
    orders = pl.read_parquet(data_dir / ORDER_MART)
    print(
        f"== (c1) birth-order mart: rows={orders.height} "
        f"countries={orders['iso3'].n_unique()} years {_span(orders['year'])} =="
    )
    dec: dict[str, dict[str, float]] = {}
    for iso3 in sorted(orders["iso3"].unique().to_list()):
        r = order_decomposition(orders, iso3, BASE_YEAR)
        if r is None:
            print(f"  {iso3}: skipped (missing {BASE_YEAR} or later complete year)")
            continue
        dec[iso3] = r
        print(
            f"  {iso3} {BASE_YEAR}->{int(r['end_year'])}: ΔTFR(known orders)={r['d_known']:+.3f} "
            f"(from {r['tfr_known_start']:.2f}); Δ1={r['d_1']:+.3f} Δ2={r['d_2']:+.3f} "
            f"Δ3={r['d_3']:+.3f} Δ4+={r['d_GE4']:+.3f}; first share={r['first_share']:.2f}"
        )
    nordic_ok = [i for i in NORDIC5 if i in dec]
    passed = [i for i in nordic_ok if dec[i]["first_share"] >= 0.5 and dec[i]["d_known"] < 0]
    verdict = (
        "consistent with H5(c1)"
        if len(nordic_ok) == len(NORDIC5) and len(passed) == len(NORDIC5)
        else (
            "undetermined (Nordic country missing)"
            if len(nordic_ok) < len(NORDIC5)
            else "not supported"
        )
    )
    print(f"  -> (c1) Nordic first-birth share >= 0.5 in {len(passed)}/{len(nordic_ok)}: {verdict}")
    if dec:
        fig_orders(dec, fig_dir / "h5_birth_order_decomp.png", start=BASE_YEAR)
    for start, end in ((2008, None), (BASE_YEAR, PRE_COVID), (2012, None)):
        tag = "robustness" if start != 2012 else "EXPLORATORY (post-hoc: DNK/FRA lack 2010)"
        print(f"-- {tag}: start={start} end={end or 'latest'}")
        for iso3 in NORDIC5 if start != 2012 else (*NORDIC5, "FRA"):
            r = order_decomposition(orders, iso3, start, end)
            print(
                f"  {iso3}: "
                + (
                    "skipped"
                    if r is None
                    else f"Δknown={r['d_known']:+.3f} first share={r['first_share']:.2f} "
                    f"(end {int(r['end_year'])})"
                )
            )

    # the education mart spells the middle group "ED3_4" (Eurostat code); align with the census mart
    edu = pl.read_parquet(data_dir / EDU_MART).with_columns(
        pl.col("isced_group").replace({"ED3_4": "ED3-4"})
    )
    print(
        f"\n== (c2) education mart: rows={edu.height} "
        f"countries={sorted(edu['iso3'].unique().to_list())} years {_span(edu['year'])} =="
    )
    all_down: dict[str, bool] = {}
    for iso3 in NORDIC4:
        ch = education_change(edu, iso3, BASE_YEAR)
        if ch.height == 0:
            print(f"  {iso3}: skipped (no complete {BASE_YEAR} or later year)")
            continue
        print(ch)
        all_down[iso3] = bool((ch["change"] < 0).all()) and ch.height == 3
        worst = ch.sort("change").row(0, named=True)
        print(
            f"  {iso3}: all 3 groups down={all_down[iso3]}; "
            f"largest fall: {worst['isced_group']} ({worst['change']:+.3f})"
        )
    ok = sum(all_down.values())
    print(
        f"  -> (c2) all groups fell in {ok}/{len(all_down)} Nordic countries: "
        + (
            "consistent with H5(c2)"
            if all_down and ok == len(all_down)
            else "not supported / undetermined"
        )
    )
    present = [i for i in NORDIC4 if i in edu["iso3"].unique().to_list()]
    if present:
        fig_education(edu, present, fig_dir / "h5_edu_tfr_nordic.png")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", type=Path, default=REPO_ROOT / "data")
    ap.add_argument("--fig-dir", type=Path, default=THEME_DIR / "reports" / "figures")
    args = ap.parse_args()
    run(args.data_dir, args.fig_dir)


if __name__ == "__main__":
    main()
