"""H2: 成長「率」と TFR の関連は水準より弱く、景気後退ショックへの短期反応として現れるか。

決定的スクリプト。入力は data/marts/growth_fertility_panel.parquet のみ、乱数は使わない。
出力: 標準出力に全推定値、図を reports/figures/h2_*.png に保存。

    uv run python themes/growth-fertility/src/theme_growth_fertility/analysis/<this file>
        [--data-dir data] [--fig-dir themes/growth-fertility/reports/figures]

事前登録（結果を見る前に固定。design/themes/growth-fertility.md の H2 節と対応）
---------------------------------------------------------------------------
識別戦略: なし（固定効果パネルによる記述的関連 + 記述的イベントスタディ）。景気後退は外生ではなく、
予期・測定誤差・逆の因果がありうるため、結果は「〜と整合的」までで因果効果とは書かない。
TFR は期間指標で、受胎→出生の遅れ（約 1 年）があるため、同時点の成長率より t−1 の成長率に
反応が出ると予想する。

サンプル:
  (a) 水準 vs 成長率の比較は、ln GDP pc (PPP, 1990 年以降のみ存在) と成長率・そのラグ 1–3 が
      すべて観測される国×年（1990–2024）。同一サンプルで比較する。
  (b)(c)(d) は成長率（1961 年以降）と TFR が観測される全期間を主サンプル、1990 年以降を頑健性。
  ラグ・差分は「前年の行が実際に存在する」ときだけ作る（year−k の自己結合。欠損年を飛ばして
  詰めない。補完しない）。

(a) 水準 vs 成長率: 二元 FE（国 + 年、国クラスタ SE）で
      tfr ~ ln_gdp;  tfr ~ g_t;  tfr ~ g_{t-1};  tfr ~ g_{t-2};  tfr ~ g_{t-3};
      tfr ~ g_t + g_{t-1} + g_{t-2} + g_{t-3}
    比較指標: 標準化係数 = b × sd(x̃)/sd(ỹ)（x̃, ỹ は国・年ダミーで残差化した within 偏差。
    FWL により厳密）と within-R²（残差化した ỹ の分散のうち説明される割合）。
    H2 前半の判定: 成長率（単独・ラグ合算）の標準化係数の絶対値と within-R² が ln GDP の値より
    小さければ「水準より弱い」と整合的。
(b) 分布ラグ: ΔTFR_t ~ g_t + g_{t-1} + g_{t-2} + g_{t-3} + 国 FE（国クラスタ SE）。
    累積反応 C_j = Σ_{k≤j} b_k を分散共分散行列から区間推定し、図示（成長率 1 %pt あたりの
    出生数/女性）。追加で年 FE 入りも報告（共通ショックを除いた版）。
(c) イベントスタディ: 景気後退イベント = GDP 成長率 < −2 %（主）、< 0 % と < −5 % は頑健性。
    同一国で前のイベントから 5 年未満のものは数えない（年を昇順に走査する貪欲法。多年にわたる
    後退は初年のみ）。各国×年の event time k は「最も近いイベント」との差（同距離なら後退後の
    k > 0 を採用）。k を −3..+5 に端点ビン化（k ≤ −3 → −3, k ≥ +5 → +5）、参照 k = −1。
    イベントの無い国は全ダミー 0。被説明変数は ΔTFR_t（主）と Δ ln TFR_t（頑健性）。
    国 FE + 年 FE、国クラスタ SE。係数と 95% CI を図示。
    k = −3, −2 の係数は pre-trend の確認（0 と区別できないことを期待するが、保証はない）。
(d) 異質性（事前リスト）: WB 高所得 vs 非高所得（取得時点の分類、時間不変）、観測年 2000 年
    未満 vs 以降、産油国除外・人口 100 万人未満の行除外（H1 スクリプトの OIL_STATES / SMALL_POP
    を import）。
頑健性（事前リスト）: 閾値（0 %, −5 %）、2020–2021 年（COVID）除外、Δ ln TFR、人口加重（WLS、
    人口欠損行は除外）、1990 年以降サンプル。
記述図: 2008–09 と 2020 の世界共通ショックは年 FE に吸収されるため、各年の国間平均 ΔTFR（と
    四分位範囲）を 2008 と 2020 の前後で別々に描く（記述。回帰ではない）。

探索的（事前登録外。結果を見た後に追加、report で明記）: 端点ビンは「イベントから遠い年」を
    すべて含み長期トレンド差を拾うため、ビン化せず窓 −3..+5 の外を 0 とする版も (c) の主閾値で
    報告する。

純粋関数（build_growth_frame, detect_events, nearest_event_time, event_dummies, cumulative,
shock_profile ...）は tests/test_analysis_h2.py で検証する。
"""

from __future__ import annotations

import argparse
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from theme_growth_fertility.analysis.a20261004_h1_income_tfr import (
    BLUE_RAMP,
    INK,
    MUTED,
    OIL_STATES,
    ORANGE,
    SMALL_POP,
    THEME_DIR,
    Est,
    _style,
    in_sample_split,
    small_country_breakdown,
)

REPO_ROOT = THEME_DIR.parents[1]
MART = Path("marts") / "growth_fertility_panel.parquet"

LEVEL_START_YEAR = 1990  # GDP pc PPP exists from 1990 only (H1)
MAX_LAG = 3
MAIN_THRESHOLD = -2.0
THRESHOLDS = (-2.0, 0.0, -5.0)
MIN_GAP_YEARS = 5
K_MIN, K_MAX, K_REF = -3, 5, -1
LAG_COLS = tuple(f"g_l{k}" for k in range(MAX_LAG + 1))  # g_l0 = contemporaneous
HIGH = "High income"
SPLIT_YEAR = 2000


# ---------------------------------------------------------------- pure helpers (tested)
def build_growth_frame(
    panel: pl.DataFrame,
    *,
    start_year: int | None = None,
    exclude_iso3: Iterable[str] = (),
    min_population: float | None = None,
    drop_years: Iterable[int] = (),
    max_lag: int = MAX_LAG,
) -> pl.DataFrame:
    """Country-years with TFR, ΔTFR (t−1 row present) and growth at t..t−max_lag all observed.

    Lags are built by self-joining on (iso3, year − k): a missing year is a missing lag, never
    the nearest earlier value. Adds ln_gdp (may be null before 1990), d_tfr, d_ln_tfr.
    ``drop_years`` removes rows whose own year is listed (lags/leads keep using them).
    """
    base = panel.select("iso3", "year", "tfr", "gdp_growth", "gdp_pcap_ppp").with_columns(
        pl.col("year").cast(pl.Int64)
    )
    df = panel.with_columns(pl.col("year").cast(pl.Int64))
    for k in range(max_lag + 1):
        lag = base.select(
            "iso3", (pl.col("year") + k).alias("year"), pl.col("gdp_growth").alias(f"g_l{k}")
        )
        df = df.join(lag, on=["iso3", "year"], how="left")
    prev = base.select("iso3", (pl.col("year") + 1).alias("year"), pl.col("tfr").alias("tfr_prev"))
    df = df.join(prev, on=["iso3", "year"], how="left")
    df = df.filter(
        pl.col("tfr").is_not_null()
        & pl.col("tfr_prev").is_not_null()
        & pl.all_horizontal([pl.col(f"g_l{k}").is_not_null() for k in range(max_lag + 1)])
    )
    if start_year is not None:
        df = df.filter(pl.col("year") >= start_year)
    excluded = sorted(set(exclude_iso3))
    if excluded:
        df = df.filter(~pl.col("iso3").is_in(excluded))
    if min_population is not None:
        df = df.filter(pl.col("population").is_null() | (pl.col("population") >= min_population))
    dropped = sorted(set(drop_years))
    if dropped:
        df = df.filter(~pl.col("year").is_in(dropped))
    return df.with_columns(
        pl.when(pl.col("gdp_pcap_ppp") > 0).then(pl.col("gdp_pcap_ppp").log()).alias("ln_gdp"),
        (pl.col("tfr") - pl.col("tfr_prev")).alias("d_tfr"),
        (pl.col("tfr").log() - pl.col("tfr_prev").log()).alias("d_ln_tfr"),
    ).sort(["iso3", "year"])


def detect_events(
    growth: pl.DataFrame, *, threshold: float, min_gap: int = MIN_GAP_YEARS
) -> pl.DataFrame:
    """Recession events: growth < threshold, greedy forward scan, >= min_gap years after the last.

    ``growth`` needs iso3, year, gdp_growth (nulls ignored). Returns iso3, event_year sorted.
    Scanning the full growth series (not the regression sample) so that events are defined
    identically across sub-samples.
    """
    rows: list[tuple[str, int]] = []
    obs = growth.filter(pl.col("gdp_growth").is_not_null()).sort(["iso3", "year"])
    for iso3, sub in obs.group_by("iso3", maintain_order=True):
        last: int | None = None
        for year, g in zip(sub["year"].to_list(), sub["gdp_growth"].to_list(), strict=True):
            if g < threshold and (last is None or year - last >= min_gap):
                rows.append((str(iso3[0]), int(year)))
                last = int(year)
    return pl.DataFrame(
        {"iso3": [r[0] for r in rows], "event_year": [r[1] for r in rows]},
        schema={"iso3": pl.String, "event_year": pl.Int64},
    ).sort(["iso3", "event_year"])


def nearest_event_time(year: int, event_years: Sequence[int]) -> int | None:
    """k = year − nearest event year; ties resolved toward the post-event side (k > 0)."""
    if not event_years:
        return None
    best: int | None = None
    for e in event_years:
        k = year - e
        if best is None or abs(k) < abs(best) or (abs(k) == abs(best) and k > best):
            best = k
    return best


def event_dummies(
    frame: pl.DataFrame,
    events: pl.DataFrame,
    *,
    k_min: int = K_MIN,
    k_max: int = K_MAX,
    k_ref: int = K_REF,
    bin_endpoints: bool = True,
) -> pl.DataFrame:
    """Add binned event-time dummies ev_m3 .. ev_p5 (reference k_ref omitted) and column k_bin.

    Countries without events get all zeros (k_bin null). Endpoints are binned:
    k <= k_min -> k_min, k >= k_max -> k_max. With ``bin_endpoints=False`` (exploratory)
    rows outside the window get k_bin null, i.e. all dummies zero.
    """
    ev_map: dict[str, list[int]] = {}
    for iso3, ey in zip(events["iso3"].to_list(), events["event_year"].to_list(), strict=True):
        ev_map.setdefault(str(iso3), []).append(int(ey))
    ks: list[int | None] = []
    for iso3, year in zip(frame["iso3"].to_list(), frame["year"].to_list(), strict=True):
        k = nearest_event_time(int(year), ev_map.get(str(iso3), []))
        if k is None or (not bin_endpoints and not (k_min <= k <= k_max)):
            ks.append(None)
        else:
            ks.append(max(k_min, min(k_max, k)))
    out = frame.with_columns(pl.Series("k_bin", ks, dtype=pl.Int64))
    for k in range(k_min, k_max + 1):
        if k == k_ref:
            continue
        out = out.with_columns(
            (pl.col("k_bin") == k).fill_null(False).cast(pl.Int64).alias(dummy_name(k))
        )
    return out


def dummy_name(k: int) -> str:
    return f"ev_m{-k}" if k < 0 else f"ev_p{k}"


def event_ks(k_min: int = K_MIN, k_max: int = K_MAX, k_ref: int = K_REF) -> list[int]:
    return [k for k in range(k_min, k_max + 1) if k != k_ref]


def cumulative(
    b: Sequence[float], cov: np.ndarray[Any, Any]
) -> list[tuple[float, float, float, float]]:
    """Cumulative sums C_j = Σ_{k<=j} b_k with SE from cov; returns (C, se, lo, hi) per j (95%)."""
    out = []
    for j in range(len(b)):
        w = np.zeros(len(b))
        w[: j + 1] = 1.0
        c = float(np.dot(w, np.asarray(b)))
        se = float(math.sqrt(max(0.0, float(w @ cov @ w))))
        out.append((c, se, c - 1.96 * se, c + 1.96 * se))
    return out


def shock_profile(frame: pl.DataFrame, years: Sequence[int]) -> pl.DataFrame:
    """Descriptive: cross-country mean / quartiles of ΔTFR and mean growth by calendar year."""
    return (
        frame.filter(pl.col("year").is_in(list(years)))
        .group_by("year")
        .agg(
            pl.len().alias("n"),
            pl.col("d_tfr").mean().alias("mean_d_tfr"),
            pl.col("d_tfr").quantile(0.25).alias("q25_d_tfr"),
            pl.col("d_tfr").quantile(0.75).alias("q75_d_tfr"),
            pl.col("g_l0").mean().alias("mean_growth"),
            (pl.col("g_l0") < MAIN_THRESHOLD).mean().alias("share_recession"),
        )
        .sort("year")
    )


def event_time_means(frame: pl.DataFrame) -> pl.DataFrame:
    """Descriptive: mean of country-demeaned d_tfr and of growth by k_bin (null k_bin = outside)."""
    return (
        frame.with_columns(
            (pl.col("d_tfr") - pl.col("d_tfr").mean().over("iso3")).alias("d_tfr_dm"),
            pl.col("k_bin").fill_null(99),
        )
        .group_by("k_bin")
        .agg(
            pl.len().alias("n"),
            pl.col("d_tfr_dm").mean().alias("mean_d_tfr_within"),
            pl.col("g_l0").mean().alias("mean_growth"),
        )
        .sort("k_bin")
    )


def standardized(b: float, sd_x: float, sd_y: float) -> float:
    return b * sd_x / sd_y if sd_y > 0 else float("nan")


# ---------------------------------------------------------------- estimation (statsmodels)
def _residualize(pdf: Any, cols: Sequence[str], fe: Sequence[str]) -> dict[str, Any]:
    """FWL: residualize each column on the fixed-effect dummies (exact within transformation)."""
    import statsmodels.formula.api as smf

    rhs = " + ".join(f"C({f})" for f in fe)
    return {c: smf.ols(f"{c} ~ {rhs}", data=pdf).fit().resid.to_numpy() for c in cols}


@dataclass(frozen=True)
class FitResult:
    est: Est
    params: dict[str, float]
    cov: np.ndarray[Any, Any]
    names: list[str]


def fit(
    frame: pl.DataFrame,
    y: str,
    xs: Sequence[str],
    *,
    label: str,
    fe: Sequence[str] = ("iso3", "year"),
    weights: str | None = None,
    within_stats: bool = False,
) -> FitResult:
    import statsmodels.formula.api as smf

    pdf = frame.to_pandas()
    rhs = " + ".join([*xs, *(f"C({f})" for f in fe)])
    formula = f"{y} ~ {rhs}"
    if weights is None:
        model = smf.ols(formula, data=pdf)
    else:
        model = smf.wls(formula, data=pdf, weights=pdf[weights])
    res = model.fit(cov_type="cluster", cov_kwds={"groups": pdf["iso3"]})
    ci = res.conf_int()
    coefs = {
        x: (float(res.params[x]), float(res.bse[x]), float(ci.loc[x, 0]), float(ci.loc[x, 1]))
        for x in xs
    }
    extra: dict[str, float] = {"r2": float(res.rsquared)}
    if within_stats:
        resid = _residualize(pdf, [y, *xs], fe)
        sd_y = float(np.std(resid[y]))
        for x in xs:
            extra[f"std_{x}"] = standardized(coefs[x][0], float(np.std(resid[x])), sd_y)
        yhat = sum(coefs[x][0] * resid[x] for x in xs)
        extra["within_r2"] = 1.0 - float(np.var(resid[y] - yhat) / np.var(resid[y]))
    if len(xs) > 1:
        extra["p_joint"] = float(res.f_test(" = 0, ".join(xs) + " = 0").pvalue)
    names = list(xs)
    cov = np.asarray(res.cov_params().loc[names, names].to_numpy(), dtype=float)
    return FitResult(
        Est(label, int(res.nobs), int(pdf["iso3"].nunique()), coefs, extra),
        {x: coefs[x][0] for x in xs},
        cov,
        names,
    )


def print_cumulative(fr: FitResult) -> list[tuple[float, float, float, float]]:
    cum = cumulative([fr.params[n] for n in fr.names], fr.cov)
    parts = [
        f"    cumulative: {n}: {c:+.5f} [{lo:+.5f}, {hi:+.5f}]"
        for n, (c, _se, lo, hi) in zip(fr.names, cum, strict=True)
    ]
    print("\n".join(parts))
    return cum


# ---------------------------------------------------------------- figures
def _plt() -> Any:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def fig_level_vs_growth(
    rows: list[tuple[str, float, float]], path: Path, *, n: int, g: int
) -> None:
    plt = _plt()
    fig, axes = plt.subplots(1, 2, figsize=(8.0, 3.6))
    labels = [r[0] for r in rows]
    axes[0].barh(
        labels, [abs(r[1]) for r in rows], color=[ORANGE, *([BLUE_RAMP[2]] * (len(rows) - 1))]
    )
    axes[0].set_xlabel(
        "|standardized within coefficient| (SD of TFR per SD of x)", fontsize=8, color=INK
    )
    axes[1].barh(labels, [r[2] for r in rows], color=[ORANGE, *([BLUE_RAMP[2]] * (len(rows) - 1))])
    axes[1].set_xlabel("within R-squared (after country and year FE)", fontsize=8, color=INK)
    for ax in axes:
        ax.invert_yaxis()
        _style(ax)
    fig.suptitle(
        "Level vs growth as predictors of TFR, two-way FE, same sample "
        f"(n={n}, countries={g}, 1990-2024)\n"
        "Source: World Bank WDI (SP.DYN.TFRT.IN, NY.GDP.PCAP.PP.KD, NY.GDP.MKTP.KD.ZG), CC BY 4.0",
        fontsize=9,
        color=INK,
    )
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def fig_cumulative(
    cum: Sequence[tuple[float, float, float, float]], path: Path, *, n: int, g: int, label: str
) -> None:
    plt = _plt()
    xs = list(range(len(cum)))
    fig, ax = plt.subplots(figsize=(5.6, 3.6))
    ax.fill_between(
        xs,
        [c[2] for c in cum],
        [c[3] for c in cum],
        color=BLUE_RAMP[0],
        alpha=0.4,
        label="95% CI (country-clustered)",
    )
    ax.plot(
        xs,
        [c[0] for c in cum],
        color=BLUE_RAMP[3],
        marker="o",
        linewidth=2,
        label="cumulative response",
    )
    ax.axhline(0, color=MUTED, linewidth=0.6)
    ax.set_xticks(xs)
    ax.set_xlabel(
        "horizon j (years): sum of coefficients on growth at lags 0..j", fontsize=8, color=INK
    )
    ax.set_ylabel(
        "cumulative change in TFR per +1 pp GDP growth\n(births per woman)", fontsize=8, color=INK
    )
    ax.set_title(
        f"Distributed lag: dTFR_t on growth_t..t-3, country FE\n"
        f"{label}, n={n}, countries={g}. Source: World Bank WDI, CC BY 4.0",
        fontsize=9,
        color=INK,
    )
    ax.legend(frameon=False, fontsize=8)
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def fig_event_study(
    series: Sequence[tuple[str, FitResult]], path: Path, *, ylabel: str, title: str
) -> None:
    plt = _plt()
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    ks = event_ks()
    colors = [BLUE_RAMP[3], BLUE_RAMP[1], ORANGE]
    for i, (name, fr) in enumerate(series):
        off = (i - (len(series) - 1) / 2) * 0.15
        pts = [fr.est.coefs[dummy_name(k)] for k in ks]
        x = [k + off for k in ks] + [K_REF + off]
        b = [p[0] for p in pts] + [0.0]
        lo = [p[0] - p[2] for p in pts] + [0.0]
        hi = [p[3] - p[0] for p in pts] + [0.0]
        ax.errorbar(
            x,
            b,
            yerr=[lo, hi],
            fmt="o",
            color=colors[i % 3],
            markersize=4,
            capsize=2,
            linewidth=1,
            label=f"{name} (n={fr.est.n}, G={fr.est.countries})",
        )
    ax.axhline(0, color=MUTED, linewidth=0.6)
    ax.axvline(-0.5, color=MUTED, linewidth=0.6, linestyle="--")
    ax.set_xticks([*ks, K_REF])
    ax.set_xticklabels(
        [("<=" if k == K_MIN else ">=" if k == K_MAX else "") + str(k) for k in [*ks, K_REF]]
    )
    ax.set_xlabel(
        "event time k (years since recession onset; k=-1 is the reference)", fontsize=8, color=INK
    )
    ax.set_ylabel(ylabel, fontsize=8, color=INK)
    ax.set_title(title, fontsize=9, color=INK)
    ax.legend(frameon=False, fontsize=7)
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def fig_global_shocks(profiles: Sequence[tuple[str, pl.DataFrame, int]], path: Path) -> None:
    plt = _plt()
    fig, axes = plt.subplots(1, len(profiles), figsize=(4.2 * len(profiles), 3.6), sharey=True)
    for ax, (name, prof, shock) in zip(axes, profiles, strict=True):
        yrs = prof["year"].to_list()
        ax.fill_between(
            yrs,
            prof["q25_d_tfr"].to_list(),
            prof["q75_d_tfr"].to_list(),
            color=BLUE_RAMP[0],
            alpha=0.4,
            label="interquartile range",
        )
        ax.plot(
            yrs,
            prof["mean_d_tfr"].to_list(),
            color=BLUE_RAMP[3],
            marker="o",
            linewidth=2,
            label="cross-country mean dTFR",
        )
        ax.axvline(shock, color=ORANGE, linewidth=1, linestyle="--", label=f"shock year {shock}")
        ax.axhline(0, color=MUTED, linewidth=0.6)
        ax.set_title(
            f"{name} (n per year {int(str(prof['n'].min()))}-{int(str(prof['n'].max()))})",
            fontsize=9,
            color=INK,
        )
        ax.set_xlabel("calendar year", fontsize=8, color=INK)
        _style(ax)
    axes[0].set_ylabel("dTFR = TFR_t - TFR_t-1 (births per woman)", fontsize=8, color=INK)
    axes[0].legend(frameon=False, fontsize=7)
    fig.suptitle(
        "DESCRIPTIVE: annual change in TFR around the global recessions "
        "(absorbed by year FE in the regressions)\n"
        "Unweighted across economies. Source: World Bank WDI, CC BY 4.0",
        fontsize=9,
        color=INK,
    )
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------- main
def describe(panel: pl.DataFrame, full: pl.DataFrame, level: pl.DataFrame) -> None:
    def span(df: pl.DataFrame) -> str:
        y0, y1 = int(str(df["year"].min())), int(str(df["year"].max()))
        return f"rows={df.height} countries={df['iso3'].n_unique()} years={y0}-{y1}"

    print("== mart ==")
    print(span(panel))
    for c in ("tfr", "gdp_pcap_ppp", "gdp_growth", "population"):
        nn = panel[c].null_count()
        print(f"  {c}: non-null={panel.height - nn} null_rate={nn / panel.height:.3f}")
    gy = panel.filter(pl.col("gdp_growth").is_not_null())
    print(f"  gdp_growth observed years: {int(str(gy['year'].min()))}-{int(str(gy['year'].max()))}")
    print(f"== main sample (tfr, tfr_t-1, growth t..t-{MAX_LAG} observed) ==")
    print(span(full))
    obs = full.group_by("iso3").len()["len"].to_list()
    print(f"  obs per country: min={min(obs)} median={sorted(obs)[len(obs) // 2]} max={max(obs)}")
    d, g = full["d_tfr"], full["g_l0"]
    print(f"  d_tfr: mean={float(str(d.mean())):.4f} sd={float(str(d.std())):.4f}")
    print(
        f"  growth: mean={float(str(g.mean())):.3f} sd={float(str(g.std())):.3f} "
        f"min={float(str(g.min())):.2f} max={float(str(g.max())):.2f}"
    )
    n_high = full.filter(pl.col("income_group") == HIGH).height
    print(
        f"  income_group null rows: {full['income_group'].null_count()}; high-income rows: {n_high}"
    )
    print(f"== level-vs-growth sample (+ ln_gdp observed, year >= {LEVEL_START_YEAR}) ==")
    print(span(level))
    oil_in, oil_out = in_sample_split(full, OIL_STATES)
    print(f"== oil states: listed={len(OIL_STATES)} in_sample={len(oil_in)} absent={oil_out} ==")
    small = small_country_breakdown(full, SMALL_POP)
    print(
        f"== population < {SMALL_POP:,}: fully_dropped_countries={small['fully_dropped']} "
        f"partially_dropped_countries={small['partially_dropped']} =="
    )


def describe_events(panel: pl.DataFrame, full: pl.DataFrame) -> dict[float, pl.DataFrame]:
    print(
        "\n== recession events (growth < threshold, >= 5 years since previous; "
        "scanned on full growth series) =="
    )
    out: dict[float, pl.DataFrame] = {}
    for th in THRESHOLDS:
        ev = detect_events(panel, threshold=th)
        in_sample = ev.join(
            full.select("iso3", pl.col("year").alias("event_year")),
            on=["iso3", "event_year"],
            how="semi",
        )
        by_year = in_sample.group_by("event_year").len().sort("len", descending=True).head(5)
        top = ", ".join(f"{int(y)}:{int(n)}" for y, n in by_year.rows())
        no_event = full["iso3"].n_unique() - in_sample["iso3"].n_unique()
        print(
            f"  threshold {th:+.0f}%: events={ev.height} countries={ev['iso3'].n_unique()} "
            f"in_sample_events={in_sample.height} countries_without_event_in_sample={no_event} "
            f"top event years={top}"
        )
        out[th] = ev
    return out


def run_event_study(
    frame: pl.DataFrame,
    events: pl.DataFrame,
    *,
    y: str,
    label: str,
    weights: str | None = None,
    bin_endpoints: bool = True,
) -> FitResult:
    df = event_dummies(frame, events, bin_endpoints=bin_endpoints)
    fr = fit(df, y, [dummy_name(k) for k in event_ks()], label=label, weights=weights)
    print(fr.est.line())
    post = [fr.params[dummy_name(k)] for k in range(0, K_MAX + 1)]
    names = [dummy_name(k) for k in range(0, K_MAX + 1)]
    idx = [fr.names.index(n) for n in names]
    cum = cumulative(post, fr.cov[np.ix_(idx, idx)])
    print(
        "    cumulative from k=0: "
        + "; ".join(
            f"k={k}: {c:+.4f} [{lo:+.4f}, {hi:+.4f}]"
            for k, (c, _s, lo, hi) in zip(range(0, K_MAX + 1), cum, strict=True)
        )
    )
    return fr


def run(data_dir: Path, fig_dir: Path) -> None:
    panel = pl.read_parquet(data_dir / MART)
    full = build_growth_frame(panel)
    level = build_growth_frame(panel, start_year=LEVEL_START_YEAR).filter(
        pl.col("ln_gdp").is_not_null()
    )
    describe(panel, full, level)
    fig_dir.mkdir(parents=True, exist_ok=True)
    events = describe_events(panel, full)

    # (a) level vs growth
    print(
        "\n== (a) level vs growth: two-way FE (iso3 + year), SE clustered by iso3, same sample =="
    )
    specs: list[tuple[str, list[str]]] = (
        [("ln GDP pc", ["ln_gdp"])]
        + [(f"growth t-{k}" if k else "growth t", [f"g_l{k}"]) for k in range(MAX_LAG + 1)]
        + [("growth t..t-3 (joint)", list(LAG_COLS))]
    )
    bars: list[tuple[str, float, float]] = []
    for name, xs in specs:
        fr = fit(level, "tfr", xs, label=f"[A] tfr ~ {name}", within_stats=True)
        print(fr.est.line())
        if len(xs) == 1:
            bars.append((name, fr.est.extra[f"std_{xs[0]}"], fr.est.extra["within_r2"]))
        else:
            # joint: report the sum of lag coefficients (long-run level response per 1 pp)
            c, _se, lo, hi = cumulative([fr.params[x] for x in xs], fr.cov)[-1]
            print(f"    sum of growth coefficients: {c:+.5f} [{lo:+.5f}, {hi:+.5f}]")
            bars.append((name, float("nan"), fr.est.extra["within_r2"]))
    fr_both = fit(
        level,
        "tfr",
        ["ln_gdp", *LAG_COLS],
        label="[A] tfr ~ ln GDP pc + growth t..t-3",
        within_stats=True,
    )
    print(fr_both.est.line())
    fig_level_vs_growth(
        [b for b in bars if not math.isnan(b[1])] + [(bars[-1][0], float("nan"), bars[-1][2])],
        fig_dir / "h2_level_vs_growth.png",
        n=level.height,
        g=level["iso3"].n_unique(),
    )

    # (b) distributed lag
    print("\n== (b) distributed lag: d_tfr ~ growth t..t-3, SE clustered by iso3 ==")
    fr_dl = fit(full, "d_tfr", list(LAG_COLS), label="[B] country FE (main)", fe=("iso3",))
    print(fr_dl.est.line())
    cum_main = print_cumulative(fr_dl)
    fig_cumulative(
        cum_main,
        fig_dir / "h2_cumulative_response.png",
        n=fr_dl.est.n,
        g=fr_dl.est.countries,
        label="1961-2024, country FE",
    )
    fr_dl2 = fit(full, "d_tfr", list(LAG_COLS), label="[B] country + year FE", fe=("iso3", "year"))
    print(fr_dl2.est.line())
    print_cumulative(fr_dl2)
    fr_dl3 = fit(full, "d_ln_tfr", list(LAG_COLS), label="[B] d_ln_tfr, country FE", fe=("iso3",))
    print(fr_dl3.est.line())
    print_cumulative(fr_dl3)

    # (c) event study
    print(
        "\n== (c) event study: d_tfr on binned event-time dummies (k=-3..+5, ref k=-1), "
        "iso3 + year FE, clustered SE =="
    )
    es: dict[float, FitResult] = {}
    for th in THRESHOLDS:
        es[th] = run_event_study(
            full, events[th], y="d_tfr", label=f"[C] d_tfr, threshold {th:+.0f}%"
        )
    fig_event_study(
        [(f"growth < {th:+.0f}%", es[th]) for th in THRESHOLDS],
        fig_dir / "h2_event_study.png",
        ylabel="dTFR relative to k=-1 (births per woman)",
        title=(
            "Event study: dTFR around recession onsets, country + year FE, 95% CI (clustered)\n"
            "Source: World Bank WDI, CC BY 4.0. Descriptive; recessions are not exogenous."
        ),
    )
    es_ln = run_event_study(
        full,
        events[MAIN_THRESHOLD],
        y="d_ln_tfr",
        label=f"[C] d_ln_tfr, threshold {MAIN_THRESHOLD:+.0f}%",
    )
    print("  -- exploratory (not pre-registered): no endpoint bins, rows outside k=-3..+5 = 0 --")
    es_nb = run_event_study(
        full,
        events[MAIN_THRESHOLD],
        y="d_tfr",
        label=f"[C-explor] d_tfr, threshold {MAIN_THRESHOLD:+.0f}%, unbinned window",
        bin_endpoints=False,
    )
    print("  -- exploratory descriptive: within-country-demeaned mean d_tfr by event time k --")
    print(event_time_means(event_dummies(full, events[MAIN_THRESHOLD], bin_endpoints=False)))
    fig_event_study(
        [
            ("binned endpoints (pre-registered)", es[MAIN_THRESHOLD]),
            ("unbinned window (exploratory)", es_nb),
        ],
        fig_dir / "h2_event_study_binning.png",
        ylabel="dTFR relative to k=-1 (births per woman)",
        title=(
            "Event study, growth < -2%: endpoint binning vs window-only dummies, "
            "country + year FE\n"
            "Source: World Bank WDI, CC BY 4.0. Descriptive."
        ),
    )

    # (d) heterogeneity (pre-listed), main threshold, d_tfr
    print(
        "\n== (d) heterogeneity (pre-listed): DL cumulative (country FE) and event study "
        "(iso3 + year FE), threshold -2% =="
    )
    het: list[tuple[str, pl.DataFrame]] = [
        ("high income (WB, time-invariant)", full.filter(pl.col("income_group") == HIGH)),
        ("non-high income", full.filter(pl.col("income_group") != HIGH)),
        (f"years < {SPLIT_YEAR}", full.filter(pl.col("year") < SPLIT_YEAR)),
        (f"years >= {SPLIT_YEAR}", full.filter(pl.col("year") >= SPLIT_YEAR)),
        ("drop oil states", build_growth_frame(panel, exclude_iso3=OIL_STATES)),
        (f"drop population < {SMALL_POP:,}", build_growth_frame(panel, min_population=SMALL_POP)),
        (
            "drop oil + small",
            build_growth_frame(panel, exclude_iso3=OIL_STATES, min_population=SMALL_POP),
        ),
    ]
    het_es: list[tuple[str, FitResult]] = []
    for name, sub in het:
        fr = fit(sub, "d_tfr", list(LAG_COLS), label=f"[D] DL {name}", fe=("iso3",))
        print(fr.est.line())
        print_cumulative(fr)
        het_es.append(
            (name, run_event_study(sub, events[MAIN_THRESHOLD], y="d_tfr", label=f"[D] ES {name}"))
        )
    fig_event_study(
        het_es[:2],
        fig_dir / "h2_event_study_income.png",
        ylabel="dTFR relative to k=-1 (births per woman)",
        title=(
            "Event study by WB income group (time-invariant classification), growth < -2%, "
            "country + year FE\nSource: World Bank WDI, CC BY 4.0. Descriptive."
        ),
    )

    # robustness
    print("\n== robustness (pre-listed) ==")
    rob: list[tuple[str, pl.DataFrame, str | None]] = [
        ("drop 2020-2021 (COVID)", build_growth_frame(panel, drop_years=(2020, 2021)), None),
        (
            f"years >= {LEVEL_START_YEAR}",
            build_growth_frame(panel, start_year=LEVEL_START_YEAR),
            None,
        ),
        (
            "population-weighted (WLS)",
            full.filter(pl.col("population").is_not_null()),
            "population",
        ),
    ]
    for name, sub, w in rob:
        fr = fit(sub, "d_tfr", list(LAG_COLS), label=f"[R] DL {name}", fe=("iso3",), weights=w)
        print(fr.est.line())
        print_cumulative(fr)
        run_event_study(sub, events[MAIN_THRESHOLD], y="d_tfr", label=f"[R] ES {name}", weights=w)
    print(f"[R] ES d_ln_tfr (shown above): {es_ln.est.label}")

    # descriptive global shocks
    print("\n== descriptive: cross-country mean dTFR around 2008-09 and 2020 (not a regression) ==")
    p08 = shock_profile(full, range(2004, 2014))
    p20 = shock_profile(full, range(2016, 2025))
    print(p08)
    print(p20)
    fig_global_shocks(
        [("2008-09 global recession", p08, 2009), ("2020 COVID recession", p20, 2020)],
        fig_dir / "h2_global_shocks_descriptive.png",
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", type=Path, default=REPO_ROOT / "data")
    ap.add_argument("--fig-dir", type=Path, default=THEME_DIR / "reports" / "figures")
    args = ap.parse_args()
    run(args.data_dir, args.fig_dir)


if __name__ == "__main__":
    main()
