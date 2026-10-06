"""H4: 国間の「所得水準 × TFR」の負の勾配は、人口転換の段階が作る見かけの関係か。

事前登録: design/themes/growth-fertility.md「### H4」（2026-10-05）。結果を見る前に固定した推定量:
  (a) 減衰      同一サンプルで国間（pooled＋年 FE）の ln_gdp 係数が段階指標 5 本で何倍に縮むか
                判定: 比 <= 0.5 整合的 / 0.5–0.8 部分的 / > 0.8 不支持
  (b) 段階固定  二元 FE（国 + 年）で段階指標を揃えた ln_gdp 係数の 95% CI
                判定: 下限 >= 0 整合的 / 0 を含む 判定不能 / 上限 < 0 不支持
  (c) 層別      5 歳未満死亡率の層（<10, 10–25, 25–50, 50–100, >=100 /千）内の国間勾配 vs 全体勾配
                判定: 全層で |層内| <= |全体|/2 なら整合的
  (d) DHS       調査ごとの富裕五分位 TFR 勾配 gap = Q5 − Q1 を、調査年の ln_gdp に回帰
                判定: pooled と 国 FE の両方で CI 下限 > 0 整合的 / 片方 部分的 / それ以外 不支持
  (e) 日本      記述のみ（図に段階の範囲外として示す。外挿しない）

決定的スクリプト。入力は data/marts/growth_fertility_panel.parquet と
data/marts/dhs_tfr_by_wealth_quintile.parquet のみ。乱数は使わない。補完しない（listwise）。
識別戦略はない: 結果は「関連」「整合的」までで、因果効果とは書かない。

    uv run python themes/growth-fertility/src/theme_growth_fertility/analysis/<this file>
        [--data-dir data] [--fig-dir themes/growth-fertility/reports/figures]

純粋関数（stage_frame, u5_band, quintile_gradients, merge_stage, verdict_*）は tests/ で検証。
"""

from __future__ import annotations

import argparse
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import polars as pl

from theme_growth_fertility.analysis.a20261004_h1_income_tfr import (
    BLUE_RAMP,
    INK,
    MUTED,
    OIL_STATES,
    ORANGE,
    SMALL_POP,
    Est,
    _style,
    build_regression_frame,
    fit,
)

THEME_DIR = Path(__file__).resolve().parents[3]
REPO_ROOT = THEME_DIR.parents[1]
PANEL_MART = Path("marts") / "growth_fertility_panel.parquet"
DHS_MART = Path("marts") / "dhs_tfr_by_wealth_quintile.parquet"

STAGE_VARS: tuple[str, ...] = (
    "u5_mortality",
    "fem_sec_enrol",
    "urban_share",
    "fem_lfp",
    "life_exp",
)
STAGE_VARS_NO_ENROL: tuple[str, ...] = tuple(v for v in STAGE_VARS if v != "fem_sec_enrol")
# 事前固定した層（5 歳未満死亡率、出生千対）。上限は排他的。
U5_BANDS: tuple[tuple[float, float], ...] = (
    (0, 10),
    (10, 25),
    (25, 50),
    (50, 100),
    (100, math.inf),
)
QUINTILES = (1, 2, 3, 4, 5)
GREEN = "#2f9e6e"


def _span(s: pl.Series, digits: int = 0) -> str:
    """'min-max' of a numeric series as text (for printing; typed so mypy is happy)."""
    lo, hi = float(str(s.min())), float(str(s.max()))
    return f"{lo:.{digits}f}-{hi:.{digits}f}"


# ---------------------------------------------------------------- pure helpers (tested)
def stage_frame(
    panel: pl.DataFrame, *, stage_vars: Sequence[str] = STAGE_VARS, **kw: Any
) -> pl.DataFrame:
    """H1 のフレーム（tfr・gdp 観測、1990–）を段階指標 listwise で絞る。補完しない。"""
    frame = build_regression_frame(panel, **kw)
    for v in stage_vars:
        frame = frame.filter(pl.col(v).is_not_null())
    return frame


def band_label(lo: float, hi: float) -> str:
    return f"U5MR >= {lo:g}" if math.isinf(hi) else f"U5MR {lo:g}-{hi:g}"


def u5_band(frame: pl.DataFrame, bands: Sequence[tuple[float, float]] = U5_BANDS) -> pl.DataFrame:
    """Adds `u5_band` (label) and `u5_band_order` (int) from `u5_mortality`; None outside bands."""
    expr: Any = pl.lit(None, dtype=pl.Utf8)
    order: Any = pl.lit(None, dtype=pl.Int64)
    for i, (lo, hi) in reversed(list(enumerate(bands))):
        cond = (pl.col("u5_mortality") >= lo) & (pl.col("u5_mortality") < hi)
        expr = pl.when(cond).then(pl.lit(band_label(lo, hi))).otherwise(expr)
        order = pl.when(cond).then(pl.lit(i)).otherwise(order)
    return frame.with_columns(expr.alias("u5_band"), order.alias("u5_band_order"))


def attenuation_ratio(b_adjusted: float, b_base: float) -> float | None:
    return None if abs(b_base) < 1e-12 else b_adjusted / b_base


def verdict_a(ratio: float | None) -> str:
    if ratio is None:
        return "undetermined (base slope ~ 0)"
    if ratio <= 0.5:
        return "consistent with H4(a) (ratio <= 0.5)"
    if ratio <= 0.8:
        return "partial (0.5 < ratio <= 0.8)"
    return "not supported (ratio > 0.8)"


def verdict_b(lo: float, hi: float) -> str:
    if lo >= 0:
        return "consistent with H4(b) (CI lower bound >= 0)"
    if hi < 0:
        return "not supported (CI upper bound < 0)"
    return "undetermined (CI includes 0)"


def verdict_c(overall: float, within_bands: Sequence[float]) -> str:
    if not within_bands:
        return "undetermined (no bands)"
    ok = all(abs(b) <= abs(overall) / 2 for b in within_bands)
    return "consistent with H4(c) (all |band| <= |overall|/2)" if ok else "not supported"


def verdict_d(pooled_lo: float, fe_lo: float) -> str:
    n = int(pooled_lo > 0) + int(fe_lo > 0)
    return {
        2: "consistent with H4(d) (pooled and country-FE lower bounds > 0)",
        1: "partial (one of two lower bounds > 0)",
        0: "not supported",
    }[n]


def quintile_gradients(dhs: pl.DataFrame) -> pl.DataFrame:
    """One row per survey with all 5 quintiles observed: gap = Q5 − Q1, slope on rank, ratio Q5/Q1.

    Surveys with a missing quintile are dropped (no imputation). Sorted by iso3, survey_year.
    """
    complete = (
        dhs.filter(pl.col("value").is_not_null() & pl.col("quintile").is_in(list(QUINTILES)))
        .group_by("survey_id")
        .agg(pl.col("quintile").n_unique().alias("nq"))
        .filter(pl.col("nq") == len(QUINTILES))
        .select("survey_id")
    )
    sub = dhs.join(complete, on="survey_id", how="inner")
    out = (
        sub.group_by("survey_id")
        .agg(
            pl.col("iso3").first(),
            pl.col("country").first(),
            pl.col("survey_year").first(),
            pl.col("survey_type").first(),
            pl.col("value").filter(pl.col("quintile") == 1).first().alias("q1"),
            pl.col("value").filter(pl.col("quintile") == 5).first().alias("q5"),
            pl.col("value").mean().alias("q_mean"),
            # OLS slope of value on rank 1..5: Σ(r−3)(v−v̄)/Σ(r−3)² with Σ(r−3)² = 10
            (((pl.col("quintile") - 3) * pl.col("value")).sum() / 10.0).alias("slope"),
        )
        .with_columns(
            (pl.col("q5") - pl.col("q1")).alias("gap"),
            (pl.col("q5") / pl.col("q1")).alias("ratio"),
        )
        .sort(["iso3", "survey_year"])
    )
    return out


def merge_stage(gradients: pl.DataFrame, panel: pl.DataFrame) -> pl.DataFrame:
    """Join WDI stage variables of the survey year (iso3 × year). No imputation: rows whose
    year has no ln_gdp are dropped; other stage variables stay None."""
    stage = panel.select(
        "iso3",
        pl.col("year").alias("survey_year"),
        pl.col("tfr").alias("national_tfr"),
        pl.when(pl.col("gdp_pcap_ppp") > 0).then(pl.col("gdp_pcap_ppp").log()).alias("ln_gdp"),
        "u5_mortality",
        "fem_sec_enrol",
        "population",
    )
    return (
        gradients.join(stage, on=["iso3", "survey_year"], how="left")
        .filter(pl.col("ln_gdp").is_not_null())
        .sort(["iso3", "survey_year"])
    )


def latest_per_country(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.sort("survey_year").group_by("iso3", maintain_order=True).last().sort("iso3")


def repeated_countries(frame: pl.DataFrame) -> pl.DataFrame:
    counts = frame.group_by("iso3").agg(pl.len().alias("k")).filter(pl.col("k") >= 2)
    return frame.join(counts.select("iso3"), on="iso3", how="inner").sort(["iso3", "survey_year"])


def wls_fit(frame: pl.DataFrame, formula: str, *, label: str, weight: str) -> Est:
    """WLS with *weight* (e.g. population), SE clustered by iso3. Rows with null weight dropped."""
    import statsmodels.formula.api as smf

    pdf = frame.filter(pl.col(weight).is_not_null()).to_pandas()
    res = smf.wls(formula, data=pdf, weights=pdf[weight]).fit(
        cov_type="cluster", cov_kwds={"groups": pdf["iso3"]}
    )
    ci = res.conf_int()
    coefs = {
        name: (
            float(res.params[name]),
            float(res.bse[name]),
            float(ci.loc[name, 0]),
            float(ci.loc[name, 1]),
        )
        for name in res.params.index
        if not name.startswith("C(") and name != "Intercept"
    }
    return Est(label, int(res.nobs), int(pdf["iso3"].nunique()), coefs, {"r2": float(res.rsquared)})


# ---------------------------------------------------------------- estimation blocks
def between(frame: pl.DataFrame, rhs: str, label: str) -> Est:
    return fit(frame, f"tfr ~ {rhs} + C(year)", label=label, fe=False)


def within(frame: pl.DataFrame, rhs: str, label: str) -> Est:
    return fit(frame, f"tfr ~ {rhs}", label=label, fe=True)


def block_a_b(frame: pl.DataFrame, stage_vars: Sequence[str], tag: str) -> dict[str, Est]:
    """(a) between attenuation and (b) within with stage controls, same sample."""
    out: dict[str, Est] = {}
    base = between(frame, "ln_gdp", f"[{tag} A0] between: ln_gdp only")
    out["A0"] = base
    for v in stage_vars:
        out[f"A+{v}"] = between(frame, f"ln_gdp + {v}", f"[{tag} A+{v}] between: ln_gdp + {v}")
    full_rhs = " + ".join(("ln_gdp", *stage_vars))
    out["A_all"] = between(frame, full_rhs, f"[{tag} A_all] between: ln_gdp + all stage vars")
    out["A_stage_only"] = between(
        frame, " + ".join(stage_vars), f"[{tag} A_stage] between: stage vars only (no ln_gdp)"
    )
    out["B0"] = within(frame, "ln_gdp", f"[{tag} B0] two-way FE: ln_gdp only")
    out["B_all"] = within(frame, full_rhs, f"[{tag} B_all] two-way FE: ln_gdp + all stage vars")
    return out


def print_a_b(res: dict[str, Est]) -> None:
    for k, est in res.items():
        print(est.line())
        _ = k
    b0 = res["A0"].coefs["ln_gdp"][0]
    b1 = res["A_all"].coefs["ln_gdp"][0]
    ratio = attenuation_ratio(b1, b0)
    r_txt = "nan" if ratio is None else f"{ratio:.3f}"
    print(f"  -> (a) attenuation ratio = {b1:+.4f} / {b0:+.4f} = {r_txt}: {verdict_a(ratio)}")
    _, _, lo, hi = res["B_all"].coefs["ln_gdp"]
    print(f"  -> (b) within ln_gdp | stage: CI [{lo:+.4f}, {hi:+.4f}]: {verdict_b(lo, hi)}")


def block_c(frame: pl.DataFrame, tag: str) -> tuple[Est, list[tuple[str, Est]]]:
    banded = u5_band(frame).filter(pl.col("u5_band").is_not_null())
    overall = between(banded, "ln_gdp", f"[{tag} C-all] between, all bands pooled")
    print(overall.line())
    per: list[tuple[str, Est]] = []
    for i, (lo, hi) in enumerate(U5_BANDS):
        sub = banded.filter(pl.col("u5_band_order") == i)
        if sub["iso3"].n_unique() < 5:
            print(f"  [{tag} C-{band_label(lo, hi)}] skipped: < 5 countries")
            continue
        est = between(sub, "ln_gdp", f"[{tag} C-{band_label(lo, hi)}] between within band")
        print(est.line())
        per.append((band_label(lo, hi), est))
    v = verdict_c(overall.coefs["ln_gdp"][0], [e.coefs["ln_gdp"][0] for _, e in per])
    print(f"  -> (c) {v}")
    return overall, per


def block_d(merged: pl.DataFrame, *, outcome: str, stage: str, tag: str) -> tuple[Est, Est | None]:
    pooled = fit(
        merged, f"{outcome} ~ {stage}", label=f"[{tag} D-pooled] {outcome} ~ {stage}", fe=False
    )
    print(pooled.line())
    pooled_t = fit(
        merged,
        f"{outcome} ~ {stage} + survey_year",
        label=f"[{tag} D-pooled+trend] {outcome} ~ {stage} + survey_year",
        fe=False,
    )
    print(pooled_t.line())
    rep = repeated_countries(merged)
    fe_est: Est | None = None
    if rep["iso3"].n_unique() >= 5:
        fe_est = fit(
            rep,
            f"{outcome} ~ {stage} + C(iso3)",
            label=f"[{tag} D-countryFE] {outcome} ~ {stage} + C(iso3), countries with >= 2 surveys",
            fe=False,
        )
        print(fe_est.line())
    if stage == "ln_gdp" and outcome == "gap":
        fe_lo = fe_est.coefs[stage][2] if fe_est is not None else float("-inf")
        print(f"  -> (d) {verdict_d(pooled.coefs[stage][2], fe_lo)}")
    return pooled, fe_est


def describe_dhs(dhs: pl.DataFrame, grads: pl.DataFrame, merged: pl.DataFrame) -> None:
    print("== DHS: TFR by wealth quintile ==")
    print(f"rows={dhs.height} surveys={dhs['survey_id'].n_unique()} G={dhs['iso3'].n_unique()}")
    print(
        f"surveys with all 5 quintiles={grads.height}; merged with WDI (ln_gdp at survey year)="
        f"{merged.height} ({merged['iso3'].n_unique()} countries, "
        f"{_span(merged['survey_year'])})"
    )
    print(merged.group_by("survey_type").agg(pl.len().alias("n")).sort("survey_type"))
    neg = merged.filter(pl.col("gap") < 0).height
    print(f"gap < 0 in {neg}/{merged.height} surveys ({neg / merged.height:.1%})")
    print("surveys with gap >= 0:")
    print(
        merged.filter(pl.col("gap") >= 0).select(
            "iso3",
            "country",
            "survey_year",
            "survey_type",
            "q1",
            "q5",
            "gap",
            "ln_gdp",
            "national_tfr",
        )
    )
    print("gap / slope / ratio summary:")
    print(
        merged.select(
            ["gap", "slope", "ratio", "ln_gdp", "u5_mortality", "national_tfr"]
        ).describe()
    )


# ---------------------------------------------------------------- figures
def fig_attenuation(res: dict[str, Est], path: Path, *, n: int, g: int) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    order = ["A0", *[f"A+{v}" for v in STAGE_VARS], "A_all", "B0", "B_all"]
    names = {
        "A0": "between: ln GDP only",
        "A_all": "between: + all 5 stage vars",
        "B0": "within (2-way FE): ln GDP only",
        "B_all": "within (2-way FE): + all 5 stage vars",
    }
    for v in STAGE_VARS:
        names[f"A+{v}"] = f"between: + {v}"
    ys = list(range(len(order)))[::-1]
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    for y, k in zip(ys, order, strict=True):
        b, _, lo, hi = res[k].coefs["ln_gdp"]
        color = ORANGE if k in ("A0", "A_all") else (GREEN if k.startswith("B") else BLUE_RAMP[2])
        ax.plot([lo, hi], [y, y], color=color, linewidth=2)
        ax.plot([b], [y], "o", color=color, markersize=5)
    ax.axvline(0, color=MUTED, linewidth=0.8)
    ax.set_yticks(ys)
    ax.set_yticklabels([names[k] for k in order], fontsize=8, color=INK)
    ax.set_xlabel(
        "coefficient on ln GDP per capita (TFR per log point), 95% CI", fontsize=8, color=INK
    )
    ax.set_title(
        f"H4(a)(b): income slope with stage controls (same sample, n={n}, G={g})\n"
        "Source: World Bank WDI (CC BY 4.0). SE clustered by country.",
        fontsize=9,
        color=INK,
    )
    _style(ax)
    ax.grid(axis="x", color="#e5e5e5", linewidth=0.6)
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    fig.savefig(path, dpi=150, metadata={"Software": None})
    plt.close(fig)


def fig_strata(frame: pl.DataFrame, overall: Est, per: list[tuple[str, Est]], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    banded = u5_band(frame).filter(pl.col("u5_band").is_not_null())
    colors = [*BLUE_RAMP, "#0a2a55"]
    fig, ax = plt.subplots(figsize=(7.0, 4.6))
    slopes = dict(per)
    for i, (lo, hi) in enumerate(U5_BANDS):
        sub = banded.filter(pl.col("u5_band_order") == i)
        if sub.height == 0:
            continue
        lab = band_label(lo, hi)
        x, y = sub["ln_gdp"].to_numpy(), sub["tfr"].to_numpy()
        ax.scatter(x, y, s=7, alpha=0.3, color=colors[i], edgecolors="none")
        if lab in slopes:
            b = slopes[lab].coefs["ln_gdp"][0]
            xs = np.linspace(float(x.min()), float(x.max()), 20)
            ax.plot(
                xs,
                float(y.mean()) + b * (xs - float(x.mean())),
                color=colors[i],
                linewidth=2,
                label=f"{lab}: slope {b:+.2f}",
            )
    b_all = overall.coefs["ln_gdp"][0]
    xa, ya = banded["ln_gdp"].to_numpy(), banded["tfr"].to_numpy()
    xs = np.linspace(float(xa.min()), float(xa.max()), 20)
    ax.plot(
        xs,
        float(ya.mean()) + b_all * (xs - float(xa.mean())),
        color=ORANGE,
        linewidth=2.5,
        linestyle="--",
        label=f"all bands pooled: slope {b_all:+.2f}",
    )
    ax.set_xlabel("ln(GDP per capita, PPP, constant intl $)", fontsize=8, color=INK)
    ax.set_ylabel("TFR (births per woman)", fontsize=8, color=INK)
    ax.set_title(
        f"H4(c): cross-country slope within under-5 mortality bands vs pooled. n={banded.height}, "
        f"G={banded['iso3'].n_unique()}\nSlopes: pooled OLS + year FE. Source: World Bank WDI",
        fontsize=9,
        color=INK,
    )
    ax.legend(frameon=False, fontsize=7.5)
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=150, metadata={"Software": None})
    plt.close(fig)


def fig_dhs_gradient(
    merged: pl.DataFrame, pooled: Est, path: Path, *, japan_ln_gdp: float | None
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    fig, ax = plt.subplots(figsize=(7.0, 4.6))
    x, y = merged["ln_gdp"].to_numpy(), merged["gap"].to_numpy()
    ax.scatter(
        x, y, s=14, alpha=0.55, color=BLUE_RAMP[2], edgecolors="none", label="one DHS survey"
    )
    b, _, lo, hi = pooled.coefs["ln_gdp"]
    xs = np.linspace(float(x.min()), float(x.max()), 20)
    ax.plot(
        xs,
        float(y.mean()) + b * (xs - float(x.mean())),
        color=ORANGE,
        linewidth=2,
        label=f"pooled fit: {b:+.2f} per log point [{lo:+.2f}, {hi:+.2f}]",
    )
    ax.axhline(0, color=MUTED, linewidth=0.8)
    if japan_ln_gdp is not None:
        ax.axvline(japan_ln_gdp, color=GREEN, linewidth=1.2, linestyle=":")
        ax.annotate(
            "Japan 2022 (ln GDP), not in DHS.\nH3 male married-share\ngradient > 0 (other metric)",
            (japan_ln_gdp, float(y.max())),
            fontsize=7,
            color=GREEN,
            ha="right",
            va="top",
            xytext=(-4, 0),
            textcoords="offset points",
        )
    ax.set_xlabel(
        "ln(GDP per capita, PPP) of the country in the survey year (WDI)", fontsize=8, color=INK
    )
    ax.set_ylabel("TFR(richest quintile) − TFR(poorest quintile)", fontsize=8, color=INK)
    ax.set_title(
        f"H4(d): within-country wealth gradient of TFR vs development. {merged.height} surveys, "
        f"{merged['iso3'].n_unique()} countries, {_span(merged['survey_year'])}\n"
        "Source: DHS Program Indicator Data API (FE_FRTR_W_TFR × wealth quintile); World Bank WDI",
        fontsize=9,
        color=INK,
    )
    ax.legend(frameon=False, fontsize=7.5, loc="lower right")
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=150, metadata={"Software": None})
    plt.close(fig)


def fig_quintile_profiles(dhs: pl.DataFrame, merged: pl.DataFrame, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    banded = (
        u5_band(merged)
        .filter(pl.col("u5_band").is_not_null())
        .select("survey_id", "u5_band", "u5_band_order")
    )
    prof = (
        dhs.join(banded, on="survey_id", how="inner")
        .group_by(["u5_band_order", "u5_band", "quintile"])
        .agg(pl.col("value").mean().alias("tfr"), pl.col("survey_id").n_unique().alias("surveys"))
        .sort(["u5_band_order", "quintile"])
    )
    colors = [*BLUE_RAMP, "#0a2a55"]
    fig, ax = plt.subplots(figsize=(6.4, 4.4))
    for i in sorted(prof["u5_band_order"].unique().to_list()):
        sub = prof.filter(pl.col("u5_band_order") == i)
        ax.plot(
            sub["quintile"],
            sub["tfr"],
            marker="o",
            color=colors[int(i)],
            linewidth=2,
            label=f"{sub['u5_band'][0]} ({sub['surveys'][0]} surveys)",
        )
    ax.set_xticks(list(QUINTILES))
    ax.set_xticklabels(["Q1 poorest", "Q2", "Q3", "Q4", "Q5 richest"], fontsize=8)
    ax.set_ylabel("mean TFR of the quintile across surveys", fontsize=8, color=INK)
    ax.set_title(
        "H4(d): TFR by wealth quintile, surveys grouped by the country's under-5 mortality\n"
        "Source: DHS Program Indicator Data API; World Bank WDI (U5MR at survey year)",
        fontsize=9,
        color=INK,
    )
    ax.legend(frameon=False, fontsize=7.5)
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=150, metadata={"Software": None})
    plt.close(fig)


# ---------------------------------------------------------------- driver
def run(data_dir: Path, fig_dir: Path) -> None:
    panel = pl.read_parquet(data_dir / PANEL_MART)
    dhs = pl.read_parquet(data_dir / DHS_MART)
    fig_dir.mkdir(parents=True, exist_ok=True)

    h1_frame = build_regression_frame(panel)
    frame = stage_frame(panel)
    print("== sample ==")
    print(f"H1 frame: n={h1_frame.height} countries={h1_frame['iso3'].n_unique()}")
    print(
        f"H4 frame (listwise on stage vars): n={frame.height} G={frame['iso3'].n_unique()} "
        f"years {_span(frame['year'])}"
    )
    print("stage variable coverage within H1 frame (non-null rows):")
    print(h1_frame.select([pl.col(v).is_not_null().sum().alias(v) for v in STAGE_VARS]))
    print("correlations with ln_gdp in the H4 frame:")
    print(frame.select([pl.corr("ln_gdp", v).alias(v) for v in STAGE_VARS]))

    print("\n== (a)(b) main: between attenuation and within with stage controls (same sample) ==")
    main = block_a_b(frame, STAGE_VARS, "M")
    print_a_b(main)
    fig_attenuation(
        main, fig_dir / "h4_attenuation.png", n=frame.height, g=frame["iso3"].n_unique()
    )

    print("\n== (a)(b) standardised stage variables (coefficients per 1 SD) ==")
    std = frame.with_columns(
        [((pl.col(v) - pl.col(v).mean()) / pl.col(v).std()).alias(v) for v in STAGE_VARS]
    )
    print(
        between(
            std, " + ".join(("ln_gdp", *STAGE_VARS)), "[M std] between: ln_gdp + stage (1 SD units)"
        ).line()
    )
    print(
        within(
            std,
            " + ".join(("ln_gdp", *STAGE_VARS)),
            "[M std] two-way FE: ln_gdp + stage (1 SD units)",
        ).line()
    )

    print("\n== (c) cross-country slope within under-5 mortality bands (same H4 sample) ==")
    overall, per = block_c(frame, "M")
    fig_strata(frame, overall, per, fig_dir / "h4_strata_slopes.png")
    print("\n== (c) on the larger H1 frame restricted only to u5_mortality (robustness) ==")
    block_c(stage_frame(panel, stage_vars=("u5_mortality",)), "R-u5only")

    print("\n== (a)(b)(c) robustness (pre-registered list) ==")
    variants: list[tuple[str, pl.DataFrame, tuple[str, ...]]] = [
        ("drop oil states", stage_frame(panel, exclude_iso3=OIL_STATES), STAGE_VARS),
        (
            f"drop population < {SMALL_POP:,}",
            stage_frame(panel, min_population=SMALL_POP),
            STAGE_VARS,
        ),
        ("drop 2020-2024", stage_frame(panel, end_year=2019), STAGE_VARS),
        (
            "4 stage vars (no fem_sec_enrol)",
            stage_frame(panel, stage_vars=STAGE_VARS_NO_ENROL),
            STAGE_VARS_NO_ENROL,
        ),
    ]
    for name, sub, vars_ in variants:
        print(f"-- {name}: n={sub.height} countries={sub['iso3'].n_unique()}")
        res = block_a_b(sub, vars_, f"R {name}")
        print_a_b({k: v for k, v in res.items() if k in ("A0", "A_all", "B0", "B_all")})
        block_c(sub, f"R {name}")

    print("\n")
    grads = quintile_gradients(dhs)
    merged = merge_stage(grads, panel)
    describe_dhs(dhs, grads, merged)

    print("\n== (d) main: gap = TFR(Q5) − TFR(Q1) vs ln GDP of the survey year ==")
    pooled, _ = block_d(merged, outcome="gap", stage="ln_gdp", tag="M")
    jpn = panel.filter(
        (pl.col("iso3") == "JPN") & (pl.col("year") == 2022) & pl.col("gdp_pcap_ppp").is_not_null()
    )
    japan_ln_gdp = math.log(float(jpn["gdp_pcap_ppp"][0])) if jpn.height else None
    print(f"Japan 2022 ln_gdp = {japan_ln_gdp}; DHS ln_gdp range = {_span(merged['ln_gdp'], 2)}")
    fig_dhs_gradient(
        merged, pooled, fig_dir / "h4_dhs_gradient_vs_gdp.png", japan_ln_gdp=japan_ln_gdp
    )
    fig_quintile_profiles(dhs, merged, fig_dir / "h4_dhs_quintile_profiles.png")

    print("\n== (d) other stage proxies (pre-registered): u5_mortality (expect <0), fem_sec_enrol")
    for stage in ("u5_mortality", "fem_sec_enrol"):
        sub = merged.filter(pl.col(stage).is_not_null())
        print(f"-- stage={stage}: n={sub.height}")
        block_d(sub, outcome="gap", stage=stage, tag="M")
    print("\n== (d) national TFR as stage proxy (descriptive only: floor effect, outcome-based) ==")
    block_d(
        merged.filter(pl.col("national_tfr").is_not_null()),
        outcome="gap",
        stage="national_tfr",
        tag="X",
    )

    print("\n== (d) robustness (pre-registered list) ==")
    for name, sub in [
        ("SurveyType = DHS only", merged.filter(pl.col("survey_type") == "DHS")),
        ("latest survey per country", latest_per_country(merged)),
    ]:
        print(f"-- {name}: n={sub.height} countries={sub['iso3'].n_unique()}")
        block_d(sub, outcome="gap", stage="ln_gdp", tag=f"R {name}")
    for outcome in ("slope", "ratio"):
        print(f"-- outcome={outcome}")
        block_d(merged, outcome=outcome, stage="ln_gdp", tag=f"R {outcome}")
    print("-- population-weighted WLS (weight = WDI population at survey year)")
    print(
        wls_fit(
            merged, "gap ~ ln_gdp", label="[R wls D-pooled] gap ~ ln_gdp", weight="population"
        ).line()
    )
    print(
        wls_fit(
            repeated_countries(merged),
            "gap ~ ln_gdp + C(iso3)",
            label="[R wls D-countryFE] gap ~ ln_gdp + C(iso3)",
            weight="population",
        ).line()
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", type=Path, default=REPO_ROOT / "data")
    ap.add_argument("--fig-dir", type=Path, default=THEME_DIR / "reports" / "figures")
    args = ap.parse_args()
    run(args.data_dir, args.fig_dir)


if __name__ == "__main__":
    main()
