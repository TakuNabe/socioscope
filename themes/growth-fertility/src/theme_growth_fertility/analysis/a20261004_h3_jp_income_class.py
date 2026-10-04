"""H3: 日本国内の所得階級と有配偶率・児童世帯割合の勾配（記述）と、国間勾配との符号比較。

決定的スクリプト。入力は data/marts/jp_income_class_fertility.parquet（e-Stat 国民生活基礎調査）と
data/marts/growth_fertility_panel.parquet（World Bank WDI）のみ。乱数は使わない。
出力: 標準出力に全推定値、図を reports/figures/h3_*.png に保存。

    uv run python themes/growth-fertility/src/theme_growth_fertility/analysis/<this file>
        [--data-dir data] [--fig-dir themes/growth-fertility/reports/figures]

事前に決めた推定量（結果を見る前に固定。すべて**集計階級レベルの記述的関連**であり因果量ではない）:
  (a) 男性 `married_share`（15 歳以上有業者、配偶者あり÷(あり+なし)）の所得階級勾配。
      各調査波ごとに、married_share を ln(階級中点, 万円) に回帰した傾き（階級を単位、
      `denominator`＝人員 10 万対の重みで加重 OLS）と Spearman 順位相関。
      階級中点 = (下限+上限)/2、上限なし階級（1000 万円以上）は 下限×1.25。
      「所得なし」「総数」は勾配から除外し、別途 married_share を報告する。
  (b) 女性について同じ（就業選択と絡むため報告のみ、主指標ではない）。
  (c) `children_household_share`（児童のいる世帯÷全世帯、世帯所得階級、世帯数 1 万対で加重）の
      ln(階級中点) 勾配、各波。上限なし階級（2000 万円以上）は 下限×1.25。
  (d) 波をまたぐ変化: 波別の傾きと 95% CI に加え、5 波をプールした 加重 OLS
      `value ~ ln_mid + wave_c + ln_mid:wave_c`（wave_c = (所得年−2018)/3、2018 が 0）の交互作用項。
  (e) 国間との比較: `growth_fertility_panel` から 2012–2024 年のプール OLS `tfr ~ ln_gdp`
      （国クラスタ SE）と、各波の所得年における横断 OLS の傾き。比較は**符号のみ**
      （有配偶率と TFR は単位が異なる）。
事前に列挙した頑健性: 上限なし階級の中点 ×1.1 と ×1.5、非加重、最下位階級（0–50 万円）除外、
  COVID 後の 2 波（2022・2025 年調査＝所得年 2021・2024）のみ。
探索的（事前登録外）: 1985–2024 の相対度数分布比（児童のいる世帯の分布 ÷ 全世帯の分布）の順位相関。

CI は「階級を観測単位とする OLS」の t 分布 CI であり、標本抽出誤差（公表表は重みのみで実数が無い）は
反映していない。純粋関数（band_midpoint, wls, weighted_slope, spearman, sign_of, compare_signs）は
tests/test_analysis_h3.py で検証する。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

THEME_DIR = Path(__file__).resolve().parents[3]
REPO_ROOT = THEME_DIR.parents[1]
JP_MART = Path("marts") / "jp_income_class_fertility.parquet"
WB_MART = Path("marts") / "growth_fertility_panel.parquet"

MAN_YEN = 10_000
TOP_FACTOR = 1.25  # open-top band midpoint = lower × TOP_FACTOR (pre-specified)
TOP_FACTOR_ALTS = (1.1, 1.5)
WAVE_CENTER = 2018  # income year of the middle wave
WAVE_STEP = 3
POST_COVID_YEARS = (2021, 2024)
CROSS_YEARS = (2012, 2024)
LOWEST_BAND = "0-50"

# dataviz palette (default instance): ordinal blue ramp (steps 250..650) for 5 waves, orange = fits.
BLUE_RAMP = ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281"]
ORANGE = "#eb6834"
INK = "#333333"
MUTED = "#8a8a8a"


# ---------------------------------------------------------------- pure helpers (tested)
def band_midpoint(
    lower_yen: int | None, upper_yen: int | None, *, top_factor: float = TOP_FACTOR
) -> float | None:
    """Midpoint of an income band in 万円. Open-top band -> lower × top_factor.

    Returns None for bands without bounds ('none', 'total'); raises on a zero-width or
    lower-only-zero band (ln would be undefined).
    """
    if lower_yen is None:
        return None
    mid = lower_yen * top_factor if upper_yen is None else (lower_yen + upper_yen) / 2
    if mid <= 0:
        msg = f"non-positive midpoint for band ({lower_yen}, {upper_yen})"
        raise ValueError(msg)
    return mid / MAN_YEN


@dataclass(frozen=True)
class Coef:
    b: float
    se: float
    lo: float
    hi: float

    def fmt(self) -> str:
        return f"{self.b:+.4f} (se {self.se:.4f}) [{self.lo:+.4f}, {self.hi:+.4f}]"


@dataclass(frozen=True)
class Fit:
    n: int
    coefs: dict[str, Coef]
    r2: float


def wls(x: np.ndarray, y: np.ndarray, w: np.ndarray | None, names: list[str]) -> Fit:
    """Weighted least squares with an intercept prepended. Classical (homoskedastic) SE, t CI.

    x: (n, k) regressors without intercept; names: k names. Weights are normalised to mean 1 so
    that the residual variance is on the scale of the observations (sum of weights = n).
    """
    from scipy import stats

    n, k = x.shape
    if len(names) != k:
        msg = "names must match regressors"
        raise ValueError(msg)
    if n <= k + 1:
        msg = f"need at least {k + 2} observations, got {n}"
        raise ValueError(msg)
    wn = np.ones(n) if w is None else np.asarray(w, dtype=float) * n / float(np.sum(w))
    xx = np.column_stack([np.ones(n), x])
    sw = np.sqrt(wn)
    xw, yw = xx * sw[:, None], y * sw
    beta, *_ = np.linalg.lstsq(xw, yw, rcond=None)
    resid = yw - xw @ beta
    df = n - (k + 1)
    sigma2 = float(resid @ resid) / df
    cov = sigma2 * np.linalg.inv(xw.T @ xw)
    se = np.sqrt(np.diag(cov))
    tcrit = float(stats.t.ppf(0.975, df))
    ybar = float(np.sum(wn * y) / n)
    tss = float(np.sum(wn * (y - ybar) ** 2))
    r2 = 1 - float(resid @ resid) / tss if tss > 0 else float("nan")
    coefs = {
        name: Coef(float(b), float(s), float(b - tcrit * s), float(b + tcrit * s))
        for name, b, s in zip(["intercept", *names], beta, se, strict=True)
    }
    return Fit(n, coefs, r2)


def weighted_slope(x: np.ndarray, y: np.ndarray, w: np.ndarray | None = None) -> Coef:
    """Slope of y on x (bands as units), weighted by w if given."""
    return wls(np.asarray(x, dtype=float)[:, None], np.asarray(y, dtype=float), w, ["x"]).coefs["x"]


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    """Spearman rank correlation (average ranks for ties)."""
    from scipy.stats import rankdata

    rx, ry = rankdata(x), rankdata(y)
    if np.std(rx) == 0 or np.std(ry) == 0:
        return float("nan")
    return float(np.corrcoef(rx, ry)[0, 1])


def sign_of(c: Coef) -> str:
    """'positive' / 'negative' when the 95% CI excludes 0, else 'indistinguishable from 0'."""
    if c.lo > 0:
        return "positive"
    if c.hi < 0:
        return "negative"
    return "indistinguishable from 0"


def compare_signs(between: Coef, within: Coef) -> str:
    """Level comparison of directions: 'opposite', 'same', or 'undetermined' (a CI covers 0)."""
    sb, sw = sign_of(between), sign_of(within)
    if sb.startswith("indistinguishable") or sw.startswith("indistinguishable"):
        return "undetermined"
    return "opposite" if sb != sw else "same"


def band_frame(
    jp: pl.DataFrame,
    *,
    metric: str,
    sex: str | None,
    top_factor: float = TOP_FACTOR,
    exclude_lowest: bool = False,
) -> pl.DataFrame:
    """Bounded income bands (drops 'none'/'total' and null values) with ln_mid and weight."""
    df = jp.filter(pl.col("metric") == metric)
    df = df.filter(pl.col("sex") == sex) if sex is not None else df.filter(pl.col("sex").is_null())
    df = df.filter(pl.col("income_class_lower_yen").is_not_null() & pl.col("value").is_not_null())
    if exclude_lowest:
        df = df.filter(pl.col("income_class") != LOWEST_BAND)
    mids = [
        band_midpoint(lo, hi, top_factor=top_factor)
        for lo, hi in zip(
            df["income_class_lower_yen"].to_list(),
            df["income_class_upper_yen"].to_list(),
            strict=True,
        )
    ]
    return (
        df.with_columns(pl.Series("mid_man", mids, dtype=pl.Float64))
        .with_columns(pl.col("mid_man").log().alias("ln_mid"))
        .rename({"denominator": "weight"})
        .sort(["year", "mid_man"])
    )


def wave_centered(year: int) -> float:
    return (year - WAVE_CENTER) / WAVE_STEP


# ---------------------------------------------------------------- estimation
def slope_by_wave(
    frame: pl.DataFrame, *, weighted: bool = True
) -> dict[int, tuple[Coef, float, int]]:
    out: dict[int, tuple[Coef, float, int]] = {}
    for year in sorted(frame["year"].unique().to_list()):
        sub = frame.filter(pl.col("year") == year)
        x, y = sub["ln_mid"].to_numpy(), sub["value"].to_numpy()
        w = sub["weight"].to_numpy() if weighted else None
        out[int(year)] = (weighted_slope(x, y, w), spearman(x, y), sub.height)
    return out


def wave_interaction(frame: pl.DataFrame, *, weighted: bool = True) -> Fit:
    """Pooled WLS: value ~ ln_mid + wave_c + ln_mid:wave_c."""
    wc = np.array([wave_centered(int(y)) for y in frame["year"].to_list()])
    ln = frame["ln_mid"].to_numpy()
    x = np.column_stack([ln, wc, ln * wc])
    w = frame["weight"].to_numpy() if weighted else None
    return wls(x, frame["value"].to_numpy(), w, ["ln_mid", "wave_c", "ln_mid:wave_c"])


def print_waves(label: str, res: dict[int, tuple[Coef, float, int]]) -> None:
    print(f"-- {label} (slope of share on ln(midpoint 万円); bands as units; 95% t CI) --")
    for year, (c, rho, n) in res.items():
        print(
            f"  income year {year}: n_bands={n:>2} slope {c.fmt()} sign={sign_of(c)}"
            f" spearman={rho:+.3f}"
        )


def print_fit(label: str, f: Fit) -> None:
    print(f"-- {label}: n={f.n} r2={f.r2:.4f} --")
    for k, c in f.coefs.items():
        print(f"  {k:<14} {c.fmt()}")


def cross_country(panel: pl.DataFrame) -> tuple[Coef, int, int, dict[int, tuple[Coef, int]]]:
    """Pooled OLS tfr ~ ln_gdp (SE clustered by iso3), CROSS_YEARS, plus per-year cross sections."""
    import statsmodels.formula.api as smf

    df = (
        panel.filter(
            pl.col("tfr").is_not_null()
            & pl.col("gdp_pcap_ppp").is_not_null()
            & (pl.col("gdp_pcap_ppp") > 0)
            & (pl.col("year") >= CROSS_YEARS[0])
            & (pl.col("year") <= CROSS_YEARS[1])
        )
        .with_columns(pl.col("gdp_pcap_ppp").log().alias("ln_gdp"))
        .sort(["iso3", "year"])
    )
    pdf = df.to_pandas()
    res = smf.ols("tfr ~ ln_gdp", data=pdf).fit(
        cov_type="cluster", cov_kwds={"groups": pdf["iso3"]}
    )
    ci = res.conf_int()
    pooled = Coef(
        float(res.params["ln_gdp"]),
        float(res.bse["ln_gdp"]),
        float(ci.loc["ln_gdp", 0]),
        float(ci.loc["ln_gdp", 1]),
    )
    per_year: dict[int, tuple[Coef, int]] = {}
    for year in sorted(df["year"].unique().to_list()):
        sub = df.filter(pl.col("year") == year)
        per_year[int(year)] = (
            weighted_slope(sub["ln_gdp"].to_numpy(), sub["tfr"].to_numpy()),
            sub.height,
        )
    return pooled, df.height, int(pdf["iso3"].nunique()), per_year


# ---------------------------------------------------------------- figures
def _style(ax: Any) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(MUTED)
    ax.tick_params(colors=INK, labelsize=8)
    ax.grid(axis="y", color="#e5e5e5", linewidth=0.6)
    ax.set_axisbelow(True)


SOURCE_JP = "Source: e-Stat, Comprehensive Survey of Living Conditions (MHLW), processed"


def _plot_waves(ax: Any, frame: pl.DataFrame, *, ylabel: str, title: str) -> None:
    years = sorted(frame["year"].unique().to_list())
    for year, color in zip(years, BLUE_RAMP, strict=True):
        sub = frame.filter(pl.col("year") == year)
        ax.plot(
            sub["mid_man"],
            sub["value"],
            color=color,
            linewidth=2,
            marker="o",
            markersize=4,
            label=f"income year {year} (n={sub.height} bands)",
        )
    ax.set_xscale("log")
    ax.set_xlabel(
        "Income band midpoint (10,000 yen, log scale; open top = lower x 1.25)",
        fontsize=8,
        color=INK,
    )
    ax.set_ylabel(ylabel, fontsize=8, color=INK)
    ax.set_title(title, fontsize=9, color=INK)
    ax.legend(frameon=False, fontsize=7)
    _style(ax)


def fig_married(male: pl.DataFrame, female: pl.DataFrame, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.2), sharey=True)
    _plot_waves(axes[0], male, ylabel="Married share among employed persons 15+", title="Men")
    _plot_waves(
        axes[1], female, ylabel="", title="Women (confounded with labour-force participation)"
    )
    fig.suptitle(
        "Married share by personal income band, employed persons 15+, Japan "
        f"(weights per 100k, no age adjustment)\n{SOURCE_JP}",
        fontsize=9,
        color=INK,
    )
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def fig_children(frame: pl.DataFrame, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6.8, 4.2))
    _plot_waves(
        ax,
        frame,
        ylabel="Share of households with children under 18",
        title=f"Households with children by household income band, Japan\n{SOURCE_JP}",
    )
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def fig_sign_contrast(
    panel_frame: pl.DataFrame, between: Coef, male: pl.DataFrame, within: Coef, path: Path
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.2))
    ax = axes[0]
    x, y = panel_frame["ln_gdp"].to_numpy(), panel_frame["tfr"].to_numpy()
    ax.scatter(x, y, s=9, alpha=0.3, color=BLUE_RAMP[2], edgecolors="none")
    xs = np.linspace(float(x.min()), float(x.max()), 50)
    a = float(np.mean(y)) - between.b * float(np.mean(x))
    ax.plot(
        xs,
        a + between.b * xs,
        color=ORANGE,
        linewidth=2,
        label=f"pooled OLS slope {between.b:+.2f}",
    )
    ax.set_xlabel("ln(GDP per capita, PPP, constant 2021 intl $)", fontsize=8, color=INK)
    ax.set_ylabel("TFR (births per woman)", fontsize=8, color=INK)
    ax.set_title(
        f"BETWEEN countries, {CROSS_YEARS[0]}-{CROSS_YEARS[1]}: n={panel_frame.height}, "
        f"countries={panel_frame['iso3'].n_unique()}\nSource: World Bank WDI, CC BY 4.0",
        fontsize=8.5,
        color=INK,
    )
    ax.legend(frameon=False, fontsize=8)
    _style(ax)

    ax = axes[1]
    sub = male.filter(pl.col("year") == male["year"].max())
    x2, y2 = sub["ln_mid"].to_numpy(), sub["value"].to_numpy()
    ax.scatter(
        x2,
        y2,
        s=np.sqrt(sub["weight"].to_numpy()) * 1.2,
        alpha=0.6,
        color=BLUE_RAMP[3],
        edgecolors="none",
    )
    xs2 = np.linspace(float(x2.min()), float(x2.max()), 50)
    w = sub["weight"].to_numpy()
    a2 = float(np.average(y2, weights=w)) - within.b * float(np.average(x2, weights=w))
    ax.plot(
        xs2,
        a2 + within.b * xs2,
        color=ORANGE,
        linewidth=2,
        label=f"weighted OLS slope {within.b:+.2f}",
    )
    ax.set_xlabel(
        "ln(personal income band midpoint, 10,000 yen); marker area ~ weight", fontsize=8, color=INK
    )
    ax.set_ylabel("Married share, employed men 15+", fontsize=8, color=INK)
    ax.set_title(
        f"WITHIN Japan, income year {int(sub['year'][0])}: n={sub.height} income bands.\n"
        f"{SOURCE_JP}",
        fontsize=8.5,
        color=INK,
    )
    ax.legend(frameon=False, fontsize=8)
    _style(ax)
    fig.suptitle(
        "Direction only: different levels (country vs income band) and different outcomes "
        "(TFR vs married share)",
        fontsize=9,
        color=INK,
    )
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------- main
def describe(jp: pl.DataFrame) -> None:
    print("== mart jp_income_class_fertility ==")
    print(
        f"rows={jp.height} source={jp['source'].unique().to_list()}"
        f" survey={jp['survey'].unique().to_list()}"
    )
    summary = (
        jp.group_by("metric", "sex")
        .agg(
            pl.len().alias("rows"),
            pl.col("year").min().alias("year_min"),
            pl.col("year").max().alias("year_max"),
            pl.col("income_class").n_unique().alias("classes"),
            pl.col("value").null_count().alias("null_values"),
        )
        .sort("metric", "sex")
    )
    for r in summary.iter_rows(named=True):
        print(
            f"  {r['metric']:<30} sex={r['sex']!s:<6} rows={r['rows']:>4}"
            f" years={r['year_min']}-{r['year_max']}"
            f" classes={r['classes']:>2} null_values={r['null_values']}"
        )
    nulls = jp.filter(pl.col("value").is_null())["year"].unique().sort().to_list()
    print(f"  years with null values (survey cancelled): {nulls}")


def print_none_total(jp: pl.DataFrame, sex: str) -> None:
    sub = jp.filter(
        (pl.col("metric") == "married_share")
        & (pl.col("sex") == sex)
        & pl.col("income_class").is_in(["none", "total"])
    ).sort(["year", "income_class"])
    print(f"-- married_share ({sex}), excluded classes, reported separately --")
    for r in sub.iter_rows(named=True):
        print(
            f"  income year {r['year']}: {r['income_class']:<5} share={r['value']:.4f}"
            f" weight={r['denominator']:.0f}"
        )


def exploratory_distribution_ratio(jp: pl.DataFrame) -> None:
    print(
        "\n== EXPLORATORY (not pre-registered): "
        "children-household / all-household distribution ratio =="
    )
    all_hh = band_frame(jp, metric="household_share_pct", sex=None)
    kids = band_frame(jp, metric="children_household_share_pct", sex=None)
    merged = all_hh.join(
        kids.select("year", "income_class", pl.col("value").alias("kids_pct")),
        on=["year", "income_class"],
    ).filter(pl.col("value") > 0)
    merged = merged.with_columns((pl.col("kids_pct") / pl.col("value")).alias("ratio"))
    for year in (1985, 1990, 1995, 2000, 2005, 2010, 2015, 2018, 2021, 2024):
        sub = merged.filter(pl.col("year") == year)
        if sub.height == 0:
            print(f"  income year {year}: no data")
            continue
        rho = spearman(sub["ln_mid"].to_numpy(), sub["ratio"].to_numpy())
        print(f"  income year {year}: n_bands={sub.height:>2} spearman(ln_mid, ratio)={rho:+.3f}")


def run(data_dir: Path, fig_dir: Path) -> None:
    jp = pl.read_parquet(data_dir / JP_MART)
    panel = pl.read_parquet(data_dir / WB_MART)
    describe(jp)
    fig_dir.mkdir(parents=True, exist_ok=True)

    male = band_frame(jp, metric="married_share", sex="male")
    female = band_frame(jp, metric="married_share", sex="female")
    kids = band_frame(jp, metric="children_household_share", sex=None)
    print(
        f"== analysis bands (bounded classes only; open top = lower x {TOP_FACTOR}) ==\n"
        f"  male married_share: {male.height} rows, {male['income_class'].n_unique()} bands"
        f" x {male['year'].n_unique()} waves\n  female married_share: {female.height} rows\n"
        f"  children_household_share: {kids.height} rows,"
        f" {kids['income_class'].n_unique()} bands x {kids['year'].n_unique()} waves"
    )

    print("\n== (a) male married_share: pre-specified main estimand ==")
    male_res = slope_by_wave(male)
    print_waves("[A] male, weighted", male_res)
    print_none_total(jp, "male")
    print("\n== (b) female married_share (reported, confounded with labour-force participation) ==")
    female_res = slope_by_wave(female)
    print_waves("[B] female, weighted", female_res)
    print_none_total(jp, "female")
    print("\n== (c) children_household_share by household income band ==")
    kids_res = slope_by_wave(kids)
    print_waves("[C] households with children, weighted", kids_res)

    print(
        "\n== (d) trend across waves: pooled WLS with wave interaction (wave_c = (year-2018)/3) =="
    )
    print_fit("[D-a] male married_share", wave_interaction(male))
    print_fit("[D-b] female married_share", wave_interaction(female))
    print_fit("[D-c] children_household_share", wave_interaction(kids))

    print(
        f"\n== (e) between-country: tfr ~ ln_gdp, {CROSS_YEARS[0]}-{CROSS_YEARS[1]}"
        " (SE clustered by iso3) =="
    )
    between, n_cc, g_cc, per_year = cross_country(panel)
    print(f"  pooled OLS: n={n_cc} countries={g_cc} slope {between.fmt()} sign={sign_of(between)}")
    print("  cross-section slope by income year of each JP wave (classical OLS SE):")
    for year in sorted(male_res):
        c, n = per_year[year]
        print(f"    {year}: n={n} slope {c.fmt()} sign={sign_of(c)}")

    print(
        "\n== sign table (directions only; levels and outcomes differ, magnitudes not comparable)"
        " =="
    )
    print(
        f"  {'wave':<6} {'between: TFR~lnGDP':<30} {'within JP male married':<30}"
        f" {'within JP children hh':<30} verdict(male)"
    )
    for year in sorted(male_res):
        cb = per_year[year][0]
        cm, ck = male_res[year][0], kids_res[year][0]
        print(
            f"  {year:<6} {sign_of(cb):<30} {sign_of(cm):<30} {sign_of(ck):<30}"
            f" {compare_signs(cb, cm)}"
        )
    pooled_male = wls(
        male["ln_mid"].to_numpy()[:, None],
        male["value"].to_numpy(),
        male["weight"].to_numpy(),
        ["ln_mid"],
    )
    pm = pooled_male.coefs["ln_mid"]
    print(
        f"  pooled 2012-2024: between {sign_of(between)} vs within-JP male (5 waves pooled,"
        f" no wave term) {pm.fmt()} {sign_of(pm)} -> {compare_signs(between, pm)}"
    )

    print("\n== robustness (pre-listed; all shown) ==")
    for tf in TOP_FACTOR_ALTS:
        print_waves(
            f"[R] male, top-code x{tf}",
            slope_by_wave(band_frame(jp, metric="married_share", sex="male", top_factor=tf)),
        )
        print_waves(
            f"[R] children hh, top-code x{tf}",
            slope_by_wave(
                band_frame(jp, metric="children_household_share", sex=None, top_factor=tf)
            ),
        )
    print_waves("[R] male, unweighted", slope_by_wave(male, weighted=False))
    print_waves("[R] female, unweighted", slope_by_wave(female, weighted=False))
    print_waves("[R] children hh, unweighted", slope_by_wave(kids, weighted=False))
    print_waves(
        "[R] male, excluding 0-50 band",
        slope_by_wave(band_frame(jp, metric="married_share", sex="male", exclude_lowest=True)),
    )
    print_waves(
        "[R] female, excluding 0-50 band",
        slope_by_wave(band_frame(jp, metric="married_share", sex="female", exclude_lowest=True)),
    )
    print_waves(
        "[R] children hh, excluding 0-50 band",
        slope_by_wave(
            band_frame(jp, metric="children_household_share", sex=None, exclude_lowest=True)
        ),
    )
    post = male.filter(pl.col("year").is_in(list(POST_COVID_YEARS)))
    print_fit(
        "[R] male, post-COVID waves only (2021, 2024), wave interaction", wave_interaction(post)
    )
    post_k = kids.filter(pl.col("year").is_in(list(POST_COVID_YEARS)))
    print_fit("[R] children hh, post-COVID waves only, wave interaction", wave_interaction(post_k))
    print_fit("[R-D] male, unweighted wave interaction", wave_interaction(male, weighted=False))
    print_fit(
        "[R-D] children hh, unweighted wave interaction", wave_interaction(kids, weighted=False)
    )

    exploratory_distribution_ratio(jp)

    fig_married(male, female, fig_dir / "h3_married_share_by_income.png")
    fig_children(kids, fig_dir / "h3_children_household_share_by_income.png")
    panel_frame = panel.filter(
        pl.col("tfr").is_not_null()
        & pl.col("gdp_pcap_ppp").is_not_null()
        & (pl.col("year") >= CROSS_YEARS[0])
        & (pl.col("year") <= CROSS_YEARS[1])
    ).with_columns(pl.col("gdp_pcap_ppp").log().alias("ln_gdp"))
    latest = max(male_res)
    fig_sign_contrast(
        panel_frame, between, male, male_res[latest][0], fig_dir / "h3_sign_contrast.png"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", type=Path, default=REPO_ROOT / "data")
    ap.add_argument("--fig-dir", type=Path, default=THEME_DIR / "reports" / "figures")
    args = ap.parse_args()
    run(args.data_dir, args.fig_dir)


if __name__ == "__main__":
    main()
