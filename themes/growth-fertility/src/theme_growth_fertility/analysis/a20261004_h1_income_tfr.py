"""H1: 国間の所得水準（ln GDP per capita, PPP）と TFR の関連（記述 + 二元固定効果）。

決定的スクリプト。入力は data/marts/growth_fertility_panel.parquet のみ、乱数は使わない。
出力: 標準出力に全推定値、図を reports/figures/ に保存。

    uv run python themes/growth-fertility/src/theme_growth_fertility/analysis/<this file>
        [--data-dir data] [--fig-dir themes/growth-fertility/reports/figures]

純粋関数（build_regression_frame, decade_summary, demean_two_way, ...）は tests/ で検証する。
"""

from __future__ import annotations

import argparse
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

THEME_DIR = Path(__file__).resolve().parents[3]
REPO_ROOT = THEME_DIR.parents[1]
MART = Path("marts") / "growth_fertility_panel.parquet"

START_YEAR = 1990  # GDP per capita PPP (constant) starts in 1990 in WDI
HIGH_INCOME_THRESHOLDS = {"gdp20k": math.log(20_000), "gdp30k": math.log(30_000)}
SMALL_POP = 1_000_000
# 石油・ガス輸出が GDP の大半を占める国（所得が人口転換と独立に動く）。事前に固定したリスト。
OIL_STATES = frozenset(
    {
        "AGO", "ARE", "AZE", "BHR", "BRN", "DZA", "GAB", "GNQ", "IRN", "IRQ", "KAZ", "KWT",
        "LBY", "NGA", "OMN", "QAT", "SAU", "TKM", "TTO", "VEN",
    }
)  # fmt: skip

# dataviz palette (default instance): sequential blue ramp for ordered decades, orange for fits.
BLUE_RAMP = ["#86b6ef", "#5598e7", "#256abf", "#104281"]
ORANGE = "#eb6834"
INK = "#333333"
MUTED = "#8a8a8a"


# ---------------------------------------------------------------- pure helpers (tested)
def decade_of(year: int) -> int:
    return (year // 10) * 10


def build_regression_frame(
    panel: pl.DataFrame,
    *,
    start_year: int = START_YEAR,
    end_year: int | None = None,
    exclude_iso3: Iterable[str] = (),
    min_population: float | None = None,
) -> pl.DataFrame:
    """Rows with both TFR and GDP pc PPP observed; adds ln_gdp and decade. No imputation."""
    excluded = set(exclude_iso3)
    df = panel.filter(
        pl.col("tfr").is_not_null()
        & pl.col("gdp_pcap_ppp").is_not_null()
        & (pl.col("gdp_pcap_ppp") > 0)
        & (pl.col("year") >= start_year)
    )
    if end_year is not None:
        df = df.filter(pl.col("year") <= end_year)
    if excluded:
        df = df.filter(~pl.col("iso3").is_in(sorted(excluded)))
    if min_population is not None:
        # 人口欠損の行は落とさない（補完もしない）: 条件は「観測されていて閾値未満」のみ除外
        df = df.filter(pl.col("population").is_null() | (pl.col("population") >= min_population))
    return df.with_columns(
        pl.col("gdp_pcap_ppp").log().alias("ln_gdp"),
        ((pl.col("year") // 10) * 10).alias("decade"),
        pl.col("year").cast(pl.Int64),
    ).sort(["iso3", "year"])


def decade_summary(frame: pl.DataFrame) -> pl.DataFrame:
    """queries/panel_by_decade.sql と同じ定義（n, 国数, 中央値, corr(ln gdp, tfr)）。"""
    return (
        frame.group_by("decade")
        .agg(
            pl.len().alias("n"),
            pl.col("iso3").n_unique().alias("countries"),
            pl.col("gdp_pcap_ppp").median().alias("median_gdp_pcap_ppp"),
            pl.col("tfr").median().alias("median_tfr"),
            pl.corr("ln_gdp", "tfr").alias("corr_log_gdp_tfr"),
        )
        .sort("decade")
    )


def demean_two_way(frame: pl.DataFrame, cols: Sequence[str]) -> pl.DataFrame:
    """Two-way (iso3, year) within transformation: x - mean_i - mean_t + grand mean.

    Exact for balanced panels; for unbalanced ones it is the one-step approximation used
    only for the within-scatter figure (the regressions use explicit dummies).
    """
    out = frame
    for c in cols:
        out = out.with_columns(
            (
                pl.col(c)
                - pl.col(c).mean().over("iso3")
                - pl.col(c).mean().over("year")
                + pl.col(c).mean()
            ).alias(f"{c}_dm")
        )
    return out


def piecewise_terms(frame: pl.DataFrame, knot: float) -> pl.DataFrame:
    """Linear spline: ln_gdp plus hinge max(ln_gdp - knot, 0). Slope above knot = b1 + b2."""
    return frame.with_columns((pl.col("ln_gdp") - knot).clip(lower_bound=0.0).alias("ln_gdp_hinge"))


def turning_point(b_lin: float, b_sq: float) -> float | None:
    """Vertex of b_lin*x + b_sq*x^2 in ln GDP; None if (near) linear."""
    if abs(b_sq) < 1e-12:
        return None
    return -b_lin / (2 * b_sq)


# ---------------------------------------------------------------- estimation (statsmodels)
@dataclass(frozen=True)
class Est:
    label: str
    n: int
    countries: int
    coefs: dict[str, tuple[float, float, float, float]]  # name -> (b, se, lo, hi)
    extra: dict[str, float]

    def line(self) -> str:
        parts = [f"{self.label:<58} n={self.n:>5} G={self.countries:>3}"]
        for k, (b, se, lo, hi) in self.coefs.items():
            parts.append(f"  {k}: {b:+.4f} (se {se:.4f}) [{lo:+.4f}, {hi:+.4f}]")
        for k, v in self.extra.items():
            parts.append(f"  {k}={v:.4f}")
        return "\n".join(parts)


def fit(frame: pl.DataFrame, formula: str, *, label: str, fe: bool) -> Est:
    import statsmodels.formula.api as smf

    pdf = frame.to_pandas()
    if fe:
        formula = f"{formula} + C(iso3) + C(year)"
    res = smf.ols(formula, data=pdf).fit(cov_type="cluster", cov_kwds={"groups": pdf["iso3"]})
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
    extra: dict[str, float] = {"r2": float(res.rsquared)}
    if "sq" in coefs and "ln_gdp" in coefs:
        tp = turning_point(coefs["ln_gdp"][0], coefs["sq"][0])
        if tp is not None:
            extra["turning_point_ln_gdp"] = tp
            extra["turning_point_gdp"] = math.exp(tp)
        extra["p_sq"] = float(res.pvalues["sq"])
    if "ln_gdp_hinge" in coefs:
        extra["slope_above_knot"] = coefs["ln_gdp"][0] + coefs["ln_gdp_hinge"][0]
        extra["p_hinge"] = float(res.pvalues["ln_gdp_hinge"])
    return Est(label, int(res.nobs), int(pdf["iso3"].nunique()), coefs, extra)


def with_sq(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.with_columns((pl.col("ln_gdp") ** 2).alias("sq"))


def high_income(frame: pl.DataFrame, rule: str) -> pl.DataFrame:
    if rule == "wb_group":
        return frame.filter(pl.col("income_group") == "High income")
    return frame.filter(pl.col("ln_gdp") >= HIGH_INCOME_THRESHOLDS[rule])


# ---------------------------------------------------------------- figures
def _style(ax: Any) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(MUTED)
    ax.tick_params(colors=INK, labelsize=8)
    ax.grid(axis="y", color="#e5e5e5", linewidth=0.6)
    ax.set_axisbelow(True)


def fig_scatter_by_decade(frame: pl.DataFrame, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    decades = sorted(frame["decade"].unique().to_list())
    fig, axes = plt.subplots(1, len(decades), figsize=(3.2 * len(decades), 3.6), sharey=True)
    for ax, dec, color in zip(axes, decades, BLUE_RAMP, strict=False):
        sub = frame.filter(pl.col("decade") == dec)
        ax.scatter(sub["ln_gdp"], sub["tfr"], s=9, alpha=0.35, color=color, edgecolors="none")
        r = float(sub.select(pl.corr("ln_gdp", "tfr")).item()) if sub.height > 2 else float("nan")
        ax.set_title(
            f"{dec}s  n={sub.height}, countries={sub['iso3'].n_unique()}, r={r:.2f}",
            fontsize=9,
            color=INK,
        )
        ax.set_xlabel("ln(GDP per capita, PPP, constant 2021 intl $)", fontsize=8, color=INK)
        _style(ax)
    axes[0].set_ylabel("TFR (births per woman)", fontsize=8, color=INK)
    fig.suptitle(
        "Income level vs TFR, country-year by decade. "
        "Source: World Bank WDI (SP.DYN.TFRT.IN, NY.GDP.PCAP.PP.KD), CC BY 4.0",
        fontsize=9,
        color=INK,
    )
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def fig_binned_means(frame: pl.DataFrame, path: Path, *, n_bins: int = 12) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    lo, hi = float(frame["ln_gdp"].min()), float(frame["ln_gdp"].max())  # type: ignore[arg-type]
    edges = [lo + (hi - lo) * i / n_bins for i in range(n_bins + 1)]
    binned = (
        frame.with_columns(
            pl.col("ln_gdp").cut(edges[1:-1], labels=[str(i) for i in range(n_bins)]).alias("bin")
        )
        .group_by(["decade", "bin"])
        .agg(
            pl.col("ln_gdp").mean().alias("x"), pl.col("tfr").mean().alias("y"), pl.len().alias("n")
        )
        .filter(pl.col("n") >= 5)
        .sort(["decade", "x"])
    )
    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    decades = sorted(frame["decade"].unique().to_list())
    for dec, color in zip(decades, BLUE_RAMP, strict=False):
        sub = binned.filter(pl.col("decade") == dec)
        ax.plot(
            sub["x"], sub["y"], color=color, linewidth=2, marker="o", markersize=4, label=f"{dec}s"
        )
        ax.annotate(
            f"{dec}s",
            (float(sub["x"][-1]), float(sub["y"][-1])),
            fontsize=8,
            color=color,
            xytext=(4, 0),
            textcoords="offset points",
        )
    ax.set_xlabel("ln(GDP per capita, PPP, constant 2021 intl $), bin mean", fontsize=8, color=INK)
    ax.set_ylabel("TFR, bin mean (bins with n >= 5 only)", fontsize=8, color=INK)
    ax.set_title(
        f"Binned-mean curves by decade. n={frame.height}, countries={frame['iso3'].n_unique()}. "
        "Source: World Bank WDI",
        fontsize=9,
        color=INK,
    )
    ax.legend(frameon=False, fontsize=8)
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def fig_within_high_income(frame: pl.DataFrame, path: Path, *, label: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    dm = demean_two_way(frame, ["ln_gdp", "tfr"])
    x = dm["ln_gdp_dm"].to_numpy()
    y = dm["tfr_dm"].to_numpy()
    fig, ax = plt.subplots(figsize=(6.0, 4.0))
    ax.scatter(x, y, s=9, alpha=0.35, color=BLUE_RAMP[2], edgecolors="none")
    coef = np.polyfit(x, y, 2)
    xs = np.linspace(float(x.min()), float(x.max()), 100)
    ax.plot(
        xs, np.polyval(coef, xs), color=ORANGE, linewidth=2, label="quadratic fit (illustrative)"
    )
    ax.axhline(0, color=MUTED, linewidth=0.6)
    ax.set_xlabel("ln GDP per capita, deviation from country and year means", fontsize=8, color=INK)
    ax.set_ylabel("TFR, deviation from country and year means", fontsize=8, color=INK)
    ax.set_title(
        f"Within scatter, high-income ({label})\n"
        f"n={frame.height}, countries={frame['iso3'].n_unique()}. Source: World Bank WDI",
        fontsize=9,
        color=INK,
    )
    ax.legend(frameon=False, fontsize=8)
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------- main
def describe_panel(panel: pl.DataFrame, frame: pl.DataFrame) -> None:
    def span(df: pl.DataFrame) -> str:
        y0, y1 = int(str(df["year"].min())), int(str(df["year"].max()))
        return f"rows={df.height} countries={df['iso3'].n_unique()} years={y0}-{y1}"

    print("== mart ==")
    print(span(panel))
    for c in ("tfr", "gdp_pcap_ppp", "gdp_growth", "population"):
        nn = panel[c].null_count()
        print(f"  {c}: non-null={panel.height - nn} null_rate={nn / panel.height:.3f}")
    print(f"== analysis sample (tfr & gdp_pcap_ppp observed, year >= {START_YEAR}) ==")
    print(span(frame))
    obs = frame.group_by("iso3").len()["len"].to_list()
    print(f"  obs per country: min={min(obs)} median={sorted(obs)[len(obs) // 2]} max={max(obs)}")
    print(f"  income_group null rows: {frame['income_group'].null_count()}")
    print("== decade summary ==")
    print(decade_summary(frame))


def run(data_dir: Path, fig_dir: Path) -> None:
    panel = pl.read_parquet(data_dir / MART)
    frame = build_regression_frame(panel)
    describe_panel(panel, frame)
    fig_dir.mkdir(parents=True, exist_ok=True)

    fig_scatter_by_decade(frame, fig_dir / "h1_scatter_by_decade.png")
    fig_binned_means(frame, fig_dir / "h1_binned_means_by_decade.png")

    print("\n== main specifications (SE clustered by iso3, 95% CI) ==")
    results: list[Est] = [
        fit(frame, "tfr ~ ln_gdp", label="[M1] pooled OLS, linear", fe=False),
        fit(frame, "tfr ~ ln_gdp", label="[M2] two-way FE (iso3 + year), linear", fe=True),
        fit(with_sq(frame), "tfr ~ ln_gdp + sq", label="[M3] pooled OLS, quadratic", fe=False),
        fit(with_sq(frame), "tfr ~ ln_gdp + sq", label="[M4] two-way FE, quadratic", fe=True),
    ]
    for r in results:
        print(r.line())

    print("\n== J-curve test: high-income subsamples ==")
    for rule in ("gdp20k", "gdp30k", "wb_group"):
        hi = high_income(frame, rule)
        for est in (
            fit(hi, "tfr ~ ln_gdp", label=f"[H-{rule}] pooled, linear", fe=False),
            fit(hi, "tfr ~ ln_gdp", label=f"[H-{rule}] two-way FE, linear", fe=True),
            fit(
                with_sq(hi), "tfr ~ ln_gdp + sq", label=f"[H-{rule}] two-way FE, quadratic", fe=True
            ),
        ):
            print(est.line())
    fig_within_high_income(
        high_income(frame, "gdp20k"),
        fig_dir / "h1_within_high_income.png",
        label="ln GDP >= ln 20,000",
    )

    print(
        "\n== J-curve test: cross-sectional (pooled + year FE) slope among high-income by decade =="
    )
    hi20 = high_income(frame, "gdp20k")
    for dec in sorted(hi20["decade"].unique().to_list()):
        sub = hi20.filter(pl.col("decade") == dec)
        print(
            fit(
                sub,
                "tfr ~ ln_gdp + C(year)",
                label=f"[X-{dec}s] high-income(gdp20k), pooled + year FE",
                fe=False,
            ).line()
        )
        print(
            fit(
                with_sq(sub),
                "tfr ~ ln_gdp + sq + C(year)",
                label=f"[X-{dec}s] high-income(gdp20k), pooled quadratic + year FE",
                fe=False,
            ).line()
        )

    print("\n== J-curve test: piecewise-linear (hinge) on full sample, two-way FE ==")
    for rule, knot in HIGH_INCOME_THRESHOLDS.items():
        print(
            fit(
                piecewise_terms(frame, knot),
                "tfr ~ ln_gdp + ln_gdp_hinge",
                label=f"[S-{rule}] FE spline, knot={knot:.3f}",
                fe=True,
            ).line()
        )

    print("\n== robustness (two-way FE, linear; and high-income FE quadratic where noted) ==")
    variants: list[tuple[str, pl.DataFrame]] = [
        ("period 1990-2007", build_regression_frame(panel, end_year=2007)),
        ("period 2008-2024", build_regression_frame(panel, start_year=2008)),
        ("drop 2020-2024 (COVID years)", build_regression_frame(panel, end_year=2019)),
        (
            f"drop population < {SMALL_POP:,}",
            build_regression_frame(panel, min_population=SMALL_POP),
        ),
        ("drop oil states", build_regression_frame(panel, exclude_iso3=OIL_STATES)),
        (
            "drop small + oil",
            build_regression_frame(panel, exclude_iso3=OIL_STATES, min_population=SMALL_POP),
        ),
    ]
    for name, sub in variants:
        print(fit(sub, "tfr ~ ln_gdp", label=f"[R] {name}: pooled linear", fe=False).line())
        print(fit(sub, "tfr ~ ln_gdp", label=f"[R] {name}: FE linear", fe=True).line())
        print(
            fit(
                with_sq(high_income(sub, "gdp20k")),
                "tfr ~ ln_gdp + sq",
                label=f"[R] {name}: high-income(gdp20k) FE quadratic",
                fe=True,
            ).line()
        )
        print(
            fit(
                high_income(sub, "gdp20k"),
                "tfr ~ ln_gdp",
                label=f"[R] {name}: high-income(gdp20k) FE linear",
                fe=True,
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
