"""H6: 意識調査（理想子ども数・将来期待）は北欧の出生率低下を説明するか。

事前登録: design/themes/growth-fertility.md「### H6」（2026-10-06）。結果を見る前に固定した推定量:
  (a) 2011 年の理想（EB 75.4、女性 25–39 の個人理想平均）× WDI TFR 2011 の相関（r > 0.3 整合的）、
      同じ指標 × ΔTFR(2011→2023)。北欧 4 か国の 2011 年の理想が EU-27 中央値より高ければ
      「2011 年の理想ではその後の北欧の低下を予測できない」と整合的
  (b) Δideal = GGS-II（2020–23、女性 30–39）− EB2011（女性 25–39）を作り、ΔTFR と順位相関。
      判定: 北欧 3 か国の Δideal がすべて負かつ下位半分 → 整合的 / 1 か国でも上位半分 → 部分的 /
      北欧の Δideal が正 → 不支持
  (c) Standard EB 2019– の「今後 12 か月の期待（生活全般）」net optimism × ΔTFR(2019→2023)。
      判定: Spearman > 0.3 整合的 / |ρ| <= 0.3 不支持

決定的スクリプト。乱数不使用。補完なし。識別戦略なし（国レベルの相関のみ、n = 10〜27）。

    uv run python themes/growth-fertility/src/theme_growth_fertility/analysis/<this file>
        [--data-dir data] [--fig-dir themes/growth-fertility/reports/figures]

純粋関数（ideal_frame, delta_tfr, ideal_change, verdict_a, verdict_b, mean_optimism, verdict_c）は
tests/test_analysis_h6.py で検証。
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from theme_growth_fertility.analysis.a20261004_h1_income_tfr import (
    BLUE_RAMP,
    INK,
    MUTED,
    ORANGE,
    _style,
)
from theme_growth_fertility.analysis.a20261004_h3_jp_income_class import Coef, spearman, wls

THEME_DIR = Path(__file__).resolve().parents[3]
REPO_ROOT = THEME_DIR.parents[1]
PANEL_MART = Path("marts") / "growth_fertility_panel.parquet"
IDEALS_MART = Path("marts") / "eu_fertility_ideals.parquet"
EXPECT_MART = Path("marts") / "eu_expectations.parquet"

EB_YEAR, GGS_END, EB_DELTA_END = 2011, 2022, 2023
EXP_START, EXP_END = 2019, 2023
COVID_YEARS = (2020, 2021)
NORDIC_EB = ("FIN", "SWE", "NOR", "DNK")  # ISL not in EB; NOR not in EU-27 either (checked at run)
NORDIC_GGS = ("NOR", "DNK", "FIN")
EB_AGE, GGS_AGE = "25-39", "30-39"
GREEN = "#2f9e6e"


# ---------------------------------------------------------------- pure helpers (tested)
def ideal_frame(
    ideals: pl.DataFrame,
    *,
    source: str,
    metric: str,
    sex: str = "F",
    age_class: str,
) -> pl.DataFrame:
    """One row per iso3 with `value` for the given source/metric/sex/age (no imputation)."""
    return (
        ideals.filter(
            (pl.col("source") == source)
            & (pl.col("metric") == metric)
            & (pl.col("sex") == sex)
            & (pl.col("age_class") == age_class)
            & pl.col("value").is_not_null()
        )
        .select("iso3", "value")
        .unique(subset=["iso3"], keep="first")
        .sort("iso3")
    )


def delta_tfr(panel: pl.DataFrame, start: int, end: int) -> pl.DataFrame:
    """iso3, tfr_start, tfr_end, d_tfr for countries observed in both years."""
    a = panel.filter(pl.col("year") == start).select("iso3", pl.col("tfr").alias("tfr_start"))
    b = panel.filter(pl.col("year") == end).select("iso3", pl.col("tfr").alias("tfr_end"))
    return (
        a.join(b, on="iso3", how="inner")
        .filter(pl.col("tfr_start").is_not_null() & pl.col("tfr_end").is_not_null())
        .with_columns((pl.col("tfr_end") - pl.col("tfr_start")).alias("d_tfr"))
        .sort("iso3")
    )


def corr_stats(x: np.ndarray, y: np.ndarray) -> tuple[float, float, Coef]:
    """Pearson r, Spearman rho, OLS slope of y on x (classical SE)."""
    r = float(np.corrcoef(x, y)[0, 1]) if len(x) > 2 else float("nan")
    rho = spearman(x, y)
    slope = wls(np.asarray(x, dtype=float)[:, None], np.asarray(y, dtype=float), None, ["x"]).coefs[
        "x"
    ]
    return r, rho, slope


def verdict_a(r_level: float, nordic_ideals: dict[str, float], median_ideal: float) -> str:
    part1 = "level: consistent (r > 0.3)" if r_level > 0.3 else "level: not supported (r <= 0.3)"
    if not nordic_ideals:
        return f"{part1}; Nordic: undetermined (no Nordic country in EB)"
    above = [k for k, v in nordic_ideals.items() if v > median_ideal]
    part2 = (
        "Nordic 2011 ideals above EU median -> 2011 ideals cannot predict the later Nordic decline"
        if len(above) == len(nordic_ideals)
        else f"Nordic ideals not all above median ({', '.join(sorted(above)) or 'none'} above)"
    )
    return f"{part1}; {part2}"


def ideal_change(eb: pl.DataFrame, ggs: pl.DataFrame) -> pl.DataFrame:
    """Countries in both: ideal_eb (2011), ideal_ggs (2020s), d_ideal, rank (1 = largest fall)."""
    out = (
        eb.rename({"value": "ideal_eb"})
        .join(ggs.rename({"value": "ideal_ggs"}), on="iso3", how="inner")
        .with_columns((pl.col("ideal_ggs") - pl.col("ideal_eb")).alias("d_ideal"))
        .sort("d_ideal")
    )
    return out.with_columns(pl.arange(1, out.height + 1).alias("rank"))


def verdict_b(change: pl.DataFrame, nordic: Sequence[str] = NORDIC_GGS) -> str:
    sub = change.filter(pl.col("iso3").is_in(list(nordic)))
    if sub.height < len(nordic):
        return "undetermined (a Nordic country is missing from the overlap)"
    if (sub["d_ideal"] >= 0).any():
        return "not supported (a Nordic Δideal is >= 0)"
    half = change.height / 2
    if (sub["rank"] <= half).all():
        return (
            "consistent with the preference-shift hypothesis (Nordic falls all in the lower half)"
        )
    return "partial (Nordic ideals fell, but not all in the lower half)"


def mean_optimism(
    exp: pl.DataFrame,
    *,
    item: str,
    start: int = EXP_START,
    end: int = EXP_END,
    exclude_years: Sequence[int] = (),
) -> pl.DataFrame:
    """Country mean of net_optimism over waves in [start, end] (optionally excluding years)."""
    # calendar year of fieldwork start (the wave's season year can differ for winter waves)
    year = (
        pl.col("fieldwork_start").str.slice(0, 4).cast(pl.Int64)
        if "fieldwork_start" in exp.columns
        else pl.col("fieldwork_year")
    )
    sub = exp.with_columns(year.alias("_cal_year")).filter(
        (pl.col("item") == item)
        & (pl.col("_cal_year") >= start)
        & (pl.col("_cal_year") <= end)
        & pl.col("net_optimism").is_not_null()
    )
    if exclude_years:
        sub = sub.filter(~pl.col("_cal_year").is_in(list(exclude_years)))
    return (
        sub.group_by("iso3")
        .agg(pl.col("net_optimism").mean().alias("optimism"), pl.len().alias("waves"))
        .sort("iso3")
    )


def verdict_c(rho: float) -> str:
    if np.isnan(rho):
        return "undetermined"
    return "consistent (rho > 0.3)" if rho > 0.3 else "not supported (|rho| <= 0.3)"


def _print_corr(label: str, x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    r, rho, slope = corr_stats(x, y)
    print(f"  {label}: n={len(x)} pearson={r:+.3f} spearman={rho:+.3f} slope {slope.fmt()}")
    return r, rho


# ---------------------------------------------------------------- figures
def _labelled_scatter(
    ax: Any,
    frame: pl.DataFrame,
    xcol: str,
    ycol: str,
    *,
    highlight: Sequence[str],
    xlabel: str,
    ylabel: str,
    title: str,
) -> None:
    import numpy as np

    x, y = frame[xcol].to_numpy(), frame[ycol].to_numpy()
    colors = [ORANGE if c in highlight else BLUE_RAMP[2] for c in frame["iso3"].to_list()]
    ax.scatter(x, y, s=26, color=colors, edgecolors="none", alpha=0.9)
    for iso3, xi, yi in zip(frame["iso3"].to_list(), x, y, strict=True):
        ax.annotate(
            iso3, (xi, yi), fontsize=7, color=INK, xytext=(3, 2), textcoords="offset points"
        )
    if len(x) > 2:
        b = np.polyfit(x, y, 1)
        xs = np.linspace(float(x.min()), float(x.max()), 20)
        ax.plot(xs, np.polyval(b, xs), color=MUTED, linewidth=1.2, linestyle="--")
    ax.set_xlabel(xlabel, fontsize=8, color=INK)
    ax.set_ylabel(ylabel, fontsize=8, color=INK)
    ax.set_title(title, fontsize=9, color=INK)
    _style(ax)


def fig_ideals(level: pl.DataFrame, change: pl.DataFrame, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.6))
    _labelled_scatter(
        ax1, level, "ideal", "tfr_start", highlight=NORDIC_EB,
        xlabel=f"mean personal ideal number of children, women {EB_AGE}, Eurobarometer 2011",
        ylabel="TFR 2011 (WDI)", title="H6(a): ideals and TFR level, 2011 (orange = Nordic)",
    )  # fmt: skip
    _labelled_scatter(
        ax2, change, "ideal", "d_tfr", highlight=NORDIC_EB,
        xlabel=f"mean personal ideal, women {EB_AGE}, 2011",
        ylabel=f"change in TFR {EB_YEAR}->{EB_DELTA_END}",
        title="H6(a): do 2011 ideals predict the later decline?",
    )  # fmt: skip
    fig.suptitle(
        "Source: Testa (2012) VID EDRP 2 (Eurobarometer 75.4, European Commission); World Bank WDI",
        fontsize=8.5,
        color=INK,
    )
    fig.tight_layout()
    fig.savefig(path, dpi=150, metadata={"Software": None})
    plt.close(fig)


def fig_change(change: pl.DataFrame, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6.6, 4.6))
    _labelled_scatter(
        ax, change, "d_ideal", "d_tfr", highlight=NORDIC_GGS,
        xlabel=f"change in mean ideal: GGS-II women {GGS_AGE} (2020-23) minus EB women {EB_AGE}",
        ylabel=f"change in TFR {EB_YEAR}->{GGS_END}",
        title="H6(b): did ideals fall more where TFR fell more? (orange = Nordic)",
    )  # fmt: skip
    ax.axhline(0, color=MUTED, linewidth=0.8)
    ax.axvline(0, color=MUTED, linewidth=0.8)
    fig.text(
        0.01, 0.005,
        "Levels not comparable (wording, ages differ); only within-country change is used.\n"
        "Source: Testa 2012 (EB 75.4); BiB WP 2025 (GGS-II, CC BY-SA 4.0); WDI",
        fontsize=7, color=MUTED,
    )  # fmt: skip
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    fig.savefig(path, dpi=150, metadata={"Software": None})
    plt.close(fig)


def fig_expectations(frame: pl.DataFrame, path: Path, *, item: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6.6, 4.6))
    _labelled_scatter(
        ax, frame, "optimism", "d_tfr", highlight=("FIN", "SWE", "DNK"),
        xlabel=f"mean net optimism ({item}: better minus worse, pp), {EXP_START}-{EXP_END}",
        ylabel=f"change in TFR {EXP_START}->{EXP_END}",
        title="H6(c): expectations for the next 12 months and the recent TFR change",
    )  # fmt: skip
    ax.axhline(0, color=MUTED, linewidth=0.8)
    fig.text(
        0.01, 0.005, "Source: Standard Eurobarometer (European Commission, CC BY 4.0); WDI",
        fontsize=7, color=MUTED,
    )  # fmt: skip
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(path, dpi=150, metadata={"Software": None})
    plt.close(fig)


# ---------------------------------------------------------------- driver
def run(data_dir: Path, fig_dir: Path) -> None:
    pl.Config.set_tbl_rows(-1)  # print every row so the stdout is the full record
    fig_dir.mkdir(parents=True, exist_ok=True)
    panel = pl.read_parquet(data_dir / PANEL_MART)
    ideals = pl.read_parquet(data_dir / IDEALS_MART)
    print("== ideals mart ==")
    print(
        ideals.group_by(["source", "metric"])
        .agg(pl.len().alias("n"), pl.col("iso3").n_unique().alias("countries"))
        .sort(["source", "metric"])
    )

    # ---------------- (a)
    print("\n== (a) 2011 ideals vs TFR level and later change ==")
    eb = ideal_frame(ideals, source="eb2011", metric="ideal_personal_mean", age_class=EB_AGE)
    d11 = delta_tfr(panel, EB_YEAR, EB_DELTA_END)
    level = eb.rename({"value": "ideal"}).join(d11, on="iso3", how="inner")
    print(f"countries with EB ideal and TFR {EB_YEAR}/{EB_DELTA_END}: {level.height}")
    r_level, _ = _print_corr(
        f"ideal(F {EB_AGE}) vs TFR {EB_YEAR}",
        level["ideal"].to_numpy(),
        level["tfr_start"].to_numpy(),
    )
    _print_corr(
        f"ideal(F {EB_AGE}) vs ΔTFR {EB_YEAR}->{EB_DELTA_END}",
        level["ideal"].to_numpy(),
        level["d_tfr"].to_numpy(),
    )
    median_ideal = float(str(level["ideal"].median()))
    nordic = {
        r["iso3"]: float(r["ideal"])
        for r in level.filter(pl.col("iso3").is_in(list(NORDIC_EB))).iter_rows(named=True)
    }
    print(
        f"  EU median ideal = {median_ideal:.3f}; Nordic: "
        + ", ".join(f"{k} {v:.2f}" for k, v in sorted(nordic.items()))
    )
    print(level.sort("ideal").select("iso3", "ideal", "tfr_start", "tfr_end", "d_tfr"))
    print(f"  -> (a) {verdict_a(r_level, nordic, median_ideal)}")
    fig_ideals(level, level, fig_dir / "h6_ideals_vs_tfr.png")
    print("-- robustness (pre-registered): general ideal, all ages, zero-ideal share")
    for metric, age, sex in (
        ("ideal_general_mean", EB_AGE, "F"),
        ("ideal_personal_mean", "total", "F"),
        ("ideal_personal_mean", "total", "T"),
        ("ideal_zero_share", "total", "T"),
        ("ideal_zero_share", EB_AGE, "F"),
    ):
        fr = ideal_frame(ideals, source="eb2011", metric=metric, sex=sex, age_class=age)
        if fr.height < 5:
            print(f"  {metric} {sex} {age}: skipped (n={fr.height})")
            continue
        m = fr.rename({"value": "x"}).join(d11, on="iso3", how="inner")
        _print_corr(
            f"{metric} ({sex} {age}) vs TFR {EB_YEAR}", m["x"].to_numpy(), m["tfr_start"].to_numpy()
        )
        _print_corr(f"{metric} ({sex} {age}) vs ΔTFR", m["x"].to_numpy(), m["d_tfr"].to_numpy())

    # ---------------- (b)
    print(
        f"\n== (b) change in ideals 2011 -> 2020s (GGS women {GGS_AGE} minus EB women {EB_AGE}) =="
    )
    ggs = ideal_frame(ideals, source="ggs2020", metric="ideal_personal_mean", age_class=GGS_AGE)
    if ggs.height == 0:  # the GGS table may label its ideal column differently
        ggs = ideal_frame(ideals, source="ggs2020", metric="ideal_mean", age_class=GGS_AGE)
    change = ideal_change(eb, ggs).join(delta_tfr(panel, EB_YEAR, GGS_END), on="iso3", how="inner")
    print(change.select("iso3", "ideal_eb", "ideal_ggs", "d_ideal", "rank", "d_tfr"))
    if change.height >= 4:
        _print_corr(
            f"Δideal vs ΔTFR {EB_YEAR}->{GGS_END}",
            change["d_ideal"].to_numpy(),
            change["d_tfr"].to_numpy(),
        )
    if change.height >= 5:
        print("  leave-one-out Spearman (drop one country):")
        for iso3 in change["iso3"].to_list():
            sub = change.filter(pl.col("iso3") != iso3)
            rho_loo = spearman(sub["d_ideal"].to_numpy(), sub["d_tfr"].to_numpy())
            print(f"    without {iso3}: rho={rho_loo:+.3f}")
    print(f"  -> (b) {verdict_b(change)}")
    fig_change(change, fig_dir / "h6_ideal_change.png")
    print("-- robustness: EB all ages (total) vs GGS total")
    eb_t = ideal_frame(ideals, source="eb2011", metric="ideal_personal_mean", age_class="total")
    ggs_t = ideal_frame(ideals, source="ggs2020", metric="ideal_personal_mean", age_class="total")
    if ggs_t.height == 0:
        ggs_t = ideal_frame(ideals, source="ggs2020", metric="ideal_mean", age_class="total")
    ch_t = ideal_change(eb_t, ggs_t).join(
        delta_tfr(panel, EB_YEAR, GGS_END), on="iso3", how="inner"
    )
    print(ch_t.select("iso3", "ideal_eb", "ideal_ggs", "d_ideal", "rank", "d_tfr"))
    print(f"  -> (b, all ages) {verdict_b(ch_t)}")
    print("-- descriptive: GGS intention-outcome gap (intended total 18-29 minus actual 40-49)")
    for metric_i in ("intended_total_mean", "intended_mean"):
        gi = ideal_frame(ideals, source="ggs2020", metric=metric_i, age_class="18-29")
        if gi.height:
            break
    ga = ideal_frame(ideals, source="ggs2020", metric="actual_mean", age_class="40-49")
    print("  (pre-registered descriptive: Nordic = FIN DNK NOR vs others)")
    gap = (
        gi.rename({"value": "intended_18_29"})
        .join(ga.rename({"value": "actual_40_49"}), on="iso3", how="inner")
        .with_columns((pl.col("intended_18_29") - pl.col("actual_40_49")).alias("gap"))
        .sort("gap")
    )
    print(gap)

    # ---------------- (c)
    print(f"\n== (c) expectations ({EXP_START}-{EXP_END}) vs ΔTFR {EXP_START}->{EXP_END} ==")
    exp_path = data_dir / EXPECT_MART
    if not exp_path.exists():
        print("  expectations mart missing: (c) skipped (undetermined)")
        return
    exp = pl.read_parquet(exp_path)
    print(
        exp.group_by(["item"])
        .agg(
            pl.len().alias("rows"),
            pl.col("iso3").n_unique().alias("countries"),
            pl.col("fieldwork_year").min().alias("from"),
            pl.col("fieldwork_year").max().alias("to"),
        )
        .sort("item")
    )
    d19 = delta_tfr(panel, EXP_START, EXP_END)
    main_frame: pl.DataFrame | None = None
    for item in ("life_general", "household_finance", "national_economy", "employment_situation"):
        for excl, tag in ((tuple(), "all waves"), (COVID_YEARS, "excl. 2020-21")):
            m = mean_optimism(exp, item=item, exclude_years=excl).join(d19, on="iso3", how="inner")
            if m.height < 5:
                print(f"  {item} ({tag}): skipped (n={m.height})")
                continue
            _, rho = _print_corr(f"{item} ({tag})", m["optimism"].to_numpy(), m["d_tfr"].to_numpy())
            if item == "life_general" and not excl:
                main_frame = m
                print(f"  -> (c) {verdict_c(rho)}")
    if main_frame is not None:
        print(
            main_frame.sort("optimism").select(
                "iso3", "optimism", "waves", "tfr_start", "tfr_end", "d_tfr"
            )
        )
        fig_expectations(main_frame, fig_dir / "h6_expectations.png", item="life in general")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", type=Path, default=REPO_ROOT / "data")
    ap.add_argument("--fig-dir", type=Path, default=THEME_DIR / "reports" / "figures")
    args = ap.parse_args()
    run(args.data_dir, args.fig_dir)


if __name__ == "__main__":
    main()
