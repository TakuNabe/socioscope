"""H3b: H3（日本の所得階級 × 男性有配偶率の正の勾配）の**年齢調整**版（事前に定めた H3 の精緻化）。

決定的スクリプト。入力は data/marts/jp_income_age_marital.parquet（e-Stat 就業構造基本調査 令和4年
第40表、男女×配偶関係×年齢×所得、有業者）と、比較用に data/marts/jp_income_class_fertility.parquet
（H3 で使った国民生活基礎調査）のみ。乱数は使わない。出力: 標準出力に全推定値、図を
reports/figures/h3b_*.png に保存。

    uv run python themes/growth-fertility/src/theme_growth_fertility/analysis/<this file>
        [--data-dir data] [--fig-dir themes/growth-fertility/reports/figures]

指標の違い（結果を見る前に固定）: 就業構造基本調査の第40表は配偶関係を「総数」「うち未婚」のみ
公表するため、ここでの被説明変数は **ever_married_share = (総数 − 未婚) ÷ 総数**（既婚経験率:
有配偶＋死別・離別）であり、H3 の married_share（配偶者あり ÷（あり＋なし））とは定義が異なる。
母集団は 15 歳以上の**有業者**（H3 と同じ制約）。値は標本から復元した推定人数で、重みは
`denominator`（該当セルの有業者数）。調査は 2022 年の 1 波のみ（2017・2012 年の全国編に同等表は
無い）。所得は主な仕事からの年間収入（調査前 1 年、50 万円刻み〜1500 万円以上で打ち切り）。

事前に決めた推定量（すべて**集計階級レベルの記述的関連**で因果量ではない）:
  (a) 年齢階級内の勾配: 男性について、5 歳階級ごとに ever_married_share を ln(所得階級中点, 万円)
      に回帰した傾き（階級を単位、`denominator` 重みの加重 OLS、古典的 t 分布 95% CI）と Spearman。
      階級中点は H3 と同じ規則（(下限+上限)/2、上限なし階級は 下限 × 1.25。H3 スクリプトの
      `band_midpoint` を import して使う）。主サンプルは **20–59 歳**（8 階級 × 16 所得階級 =
      128 セル。15–19 歳は在学者が大半で既婚経験率がほぼ 0、60 歳以上は退職・年金で所得の意味が
      変わる）。波は 1 つ（2022 年）しかないので「波ごと」は 1 本の線になる。
  (b) 直接法による年齢標準化: 所得階級ごとに Σ_a w_a · share(a, 所得階級)。w_a は**最新波
      （＝2022 年）の男性有業者全体（所得総数列）の年齢分布**を主サンプル年齢に正規化したもの。
      標準化後の割合を ln(中点) に回帰した傾き（所得階級の総人数で加重）を「調整後勾配 (b)」とする。
      ある年齢階級のセルが空（有業者 0）の所得階級があれば、その年齢階級を標準人口から外して
      再正規化し、その旨を出力する（補完はしない）。
  (c) 年齢階級固定効果付きのプール加重 OLS: share ~ ln_mid + 年齢階級ダミー（128 セル、
      `denominator` 重み）。ln_mid の係数と 95% CI を「調整後勾配 (c)」とする。CI は**セル（階級）
      を観測単位とする OLS** の t 分布 CI で、標本抽出誤差は含まない。
  (d) 比較: 調整後勾配 (b)(c) を、(i) 同じ表の年齢「総数」行から得る**未調整**勾配、(ii) H3
      レポートの未調整勾配（国民生活基礎調査 第102表、男性 married_share。所得年 2021（2022 年調査）
      と最新波 2024 を、H3 スクリプトの `band_frame`/`slope_by_wave` を import して再計算）と
      並べる。
      減衰率 = 1 − 調整後/未調整。(ii) は指標・調査・重みが異なるので**符号と大きさの目安**の比較
      に限る。
  (e) 図: h3b_married_share_by_age_income.png（年齢階級ごとの小図、x は ln 所得、1 波 1 本）、
      h3b_adjusted_vs_unadjusted.png（未調整 vs 年齢標準化後の所得階級別割合と各勾配）。
事前に列挙した頑健性（すべて報告）: 上限なし階級の中点 ×1.1 / ×1.5、非加重、15–24 歳の除外に相当する
  **25–59 歳**（主サンプルは既に 15–19 歳を含まないため 20–24 歳を外す）、全年齢 15 歳以上、
  最下位階級（50 万円未満）除外。「所得なし」階級はこの表に存在しないので除外不能（N/A と明記）。
探索的（事前登録外）: 女性について (a)(c) を同様に算出（就業選択と不可分なので参考値）。

純粋関数（age_frame, age_weights, standardise, slopes_by_age, fe_fit, attenuation）は
tests/test_analysis_h3b.py で検証する。
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from pathlib import Path

import numpy as np
import polars as pl

from theme_growth_fertility.analysis import a20261004_h3_jp_income_class as h3

THEME_DIR = Path(__file__).resolve().parents[3]
REPO_ROOT = THEME_DIR.parents[1]
AGE_MART = Path("marts") / "jp_income_age_marital.parquet"
H3_MART = Path("marts") / "jp_income_class_fertility.parquet"

METRIC = "ever_married_share"
MAIN_AGES = (20, 59)  # inclusive bounds on age_lower / age_upper-1 of the 5-year classes
NO_YOUNG_AGES = (25, 59)
ALL_AGES = (15, 200)
H3_COMPARE_YEARS = (2021, 2024)  # income years: closest to the 2022 survey, and the latest wave


# ---------------------------------------------------------------- pure helpers (tested)
def age_frame(
    df: pl.DataFrame,
    *,
    sex: str,
    ages: tuple[int, int] = MAIN_AGES,
    top_factor: float = h3.TOP_FACTOR,
    exclude_lowest: bool = False,
) -> pl.DataFrame:
    """Bounded age × bounded income cells for *sex*: adds mid_man, ln_mid, weight (=denominator).

    Drops age 'total', income 'none'/'total', null values and zero-denominator cells. *ages* bounds
    the 5-year classes by their lower bound (an open-top class such as 85- is kept only when
    ages[1] >= its lower bound, i.e. the all-ages setting).
    """
    lo, hi = ages
    sub = df.filter(
        (pl.col("metric") == METRIC)
        & (pl.col("sex") == sex)
        & pl.col("age_lower").is_not_null()
        & (pl.col("age_lower") >= lo)
        & (pl.col("age_lower") <= hi)
        & pl.col("income_class_lower_yen").is_not_null()
        & pl.col("value").is_not_null()
        & (pl.col("denominator") > 0)
    )
    if exclude_lowest:
        sub = sub.filter(pl.col("income_class") != h3.LOWEST_BAND)
    mids = [
        h3.band_midpoint(a, b, top_factor=top_factor)
        for a, b in zip(
            sub["income_class_lower_yen"].to_list(),
            sub["income_class_upper_yen"].to_list(),
            strict=True,
        )
    ]
    return (
        sub.with_columns(pl.Series("mid_man", mids, dtype=pl.Float64))
        .with_columns(pl.col("mid_man").log().alias("ln_mid"))
        .rename({"denominator": "weight"})
        .sort(["year", "age_lower", "mid_man"])
    )


def age_weights(
    df: pl.DataFrame, *, sex: str, ages: tuple[int, int] = MAIN_AGES
) -> dict[str, float]:
    """Standard age distribution: persons in the income 'total' column per age class, normalised
    over the classes within *ages* (the latest wave; here the only one)."""
    lo, hi = ages
    sub = df.filter(
        (pl.col("metric") == METRIC)
        & (pl.col("sex") == sex)
        & (pl.col("income_class") == "total")
        & pl.col("age_lower").is_not_null()
        & (pl.col("age_lower") >= lo)
        & (pl.col("age_lower") <= hi)
        & (pl.col("year") == pl.col("year").max())
    ).sort("age_lower")
    total = float(sub["denominator"].sum())
    if sub.height == 0 or total <= 0:
        msg = "no age-total rows for the standard population"
        raise ValueError(msg)
    return {
        str(a): float(d) / total for a, d in zip(sub["age_class"], sub["denominator"], strict=True)
    }


def standardise(frame: pl.DataFrame, weights: Mapping[str, float]) -> pl.DataFrame:
    """Direct standardisation: per income class, Σ_a w_a · share(a). Fail-closed: every age class in
    *weights* must be present for the income class (no imputation of missing cells)."""
    if abs(sum(weights.values()) - 1.0) > 1e-9:
        msg = "age weights must sum to 1"
        raise ValueError(msg)
    out: list[dict[str, object]] = []
    for ic, sub in frame.group_by("income_class", maintain_order=True):
        shares = dict(zip(sub["age_class"].to_list(), sub["value"].to_list(), strict=True))
        missing = set(weights) - set(shares)
        if missing:
            msg = f"income class {ic[0]!r} lacks age classes {sorted(missing)}"
            raise ValueError(msg)
        out.append(
            {
                "income_class": ic[0],
                "mid_man": float(sub["mid_man"][0]),
                "ln_mid": float(sub["ln_mid"][0]),
                "value": float(sum(w * float(shares[a]) for a, w in weights.items())),
                "weight": float(sub["weight"].sum()),
            }
        )
    return pl.DataFrame(out).sort("mid_man")


def slopes_by_age(
    frame: pl.DataFrame, *, weighted: bool = True
) -> dict[str, tuple[h3.Coef, float, int]]:
    out: dict[str, tuple[h3.Coef, float, int]] = {}
    for age in frame.sort("age_lower")["age_class"].unique(maintain_order=True).to_list():
        sub = frame.filter(pl.col("age_class") == age)
        x, y = sub["ln_mid"].to_numpy(), sub["value"].to_numpy()
        w = sub["weight"].to_numpy() if weighted else None
        out[str(age)] = (h3.weighted_slope(x, y, w), h3.spearman(x, y), sub.height)
    return out


def fe_fit(frame: pl.DataFrame, *, weighted: bool = True) -> h3.Fit:
    """Pooled WLS share ~ ln_mid + age-class dummies (first age class is the reference)."""
    ages = frame.sort("age_lower")["age_class"].unique(maintain_order=True).to_list()
    ln = frame["ln_mid"].to_numpy()
    dummies = [(frame["age_class"] == a).cast(pl.Float64).to_numpy() for a in ages[1:]]
    x = np.column_stack([ln, *dummies]) if dummies else ln[:, None]
    w = frame["weight"].to_numpy() if weighted else None
    return h3.wls(x, frame["value"].to_numpy(), w, ["ln_mid", *[f"age[{a}]" for a in ages[1:]]])


def complete_ages(frame: pl.DataFrame) -> list[str]:
    """Age classes that have a cell in every income class of *frame* (in age order)."""
    n_bands = frame["income_class"].n_unique()
    counts = frame.group_by("age_class", "age_lower").agg(pl.len().alias("n")).sort("age_lower")
    return [str(a) for a, n in zip(counts["age_class"], counts["n"], strict=True) if n == n_bands]


def restrict_weights(weights: Mapping[str, float], ages: list[str]) -> dict[str, float]:
    """Renormalise the standard age distribution over *ages* (used when a class has empty cells)."""
    kept = {a: w for a, w in weights.items() if a in ages}
    total = sum(kept.values())
    if total <= 0:
        msg = "no age classes left for standardisation"
        raise ValueError(msg)
    return {a: w / total for a, w in kept.items()}


def attenuation(adjusted: h3.Coef, unadjusted: h3.Coef) -> float:
    """1 − adjusted/unadjusted: share of the crude slope removed by age adjustment."""
    if unadjusted.b == 0:
        return float("nan")
    return 1.0 - adjusted.b / unadjusted.b


def crude_slope(
    df: pl.DataFrame, *, sex: str, top_factor: float = h3.TOP_FACTOR, weighted: bool = True
) -> tuple[h3.Coef, float, int]:
    """Unadjusted slope from the age 'total' rows of the same table (bands as units)."""
    frame = h3.band_frame(
        df.filter(pl.col("age_class") == "total"), metric=METRIC, sex=sex, top_factor=top_factor
    )
    res = h3.slope_by_wave(frame, weighted=weighted)
    return res[max(res)]


# ---------------------------------------------------------------- printing
def print_ages(label: str, res: dict[str, tuple[h3.Coef, float, int]]) -> None:
    print(
        f"-- {label} (slope of share on ln(midpoint 万円) within age class; bands as units;"
        " 95% t CI) --"
    )
    for age, (c, rho, n) in res.items():
        print(
            f"  age {age:<6} n_bands={n:>2} slope {c.fmt()} sign={h3.sign_of(c)}"
            f" spearman={rho:+.3f}"
        )


def describe(df: pl.DataFrame) -> None:
    print("== mart jp_income_age_marital ==")
    print(
        f"rows={df.height} source={df['source'].unique().to_list()}"
        f" survey={df['survey'].unique().to_list()}"
        f" survey_year={df['survey_year'].unique().to_list()}"
        f" metric={df['metric'].unique().to_list()}"
    )
    for sex in ("total", "male", "female"):
        sub = df.filter(pl.col("sex") == sex)
        tot = sub.filter((pl.col("age_class") == "total") & (pl.col("income_class") == "total"))
        classes = sub.filter(
            (pl.col("age_class") == "total") & pl.col("income_class_lower_yen").is_not_null()
        )
        reported = float(classes["denominator"].sum())
        total = float(tot["denominator"][0])
        print(
            f"  sex={sex:<6} rows={sub.height:>3} ages={sub['age_class'].n_unique() - 1}"
            f" income_bands={classes.height} persons_total={total:,.0f}"
            f" income_reported={reported:,.0f}"
            f" (unknown income {1 - reported / total:.1%}) null_values={sub['value'].null_count()}"
            f" ever_married_share(all)={float(tot['value'][0]):.4f}"
        )


# ---------------------------------------------------------------- figures
def fig_small_multiples(frame: pl.DataFrame, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ages = frame.sort("age_lower")["age_class"].unique(maintain_order=True).to_list()
    ncol = 5
    nrow = -(-len(ages) // ncol)
    fig, axes = plt.subplots(nrow, ncol, figsize=(2.6 * ncol, 2.3 * nrow), sharex=True, sharey=True)
    for ax, age in zip(axes.flat, ages, strict=False):
        sub = frame.filter(pl.col("age_class") == age)
        for year, color in zip(
            sorted(sub["year"].unique().to_list()), h3.BLUE_RAMP[2:], strict=False
        ):
            s = sub.filter(pl.col("year") == year)
            ax.plot(
                s["mid_man"],
                s["value"],
                color=color,
                linewidth=1.6,
                marker="o",
                markersize=2.5,
                label=f"survey {year}",
            )
        ax.set_xscale("log")
        ax.set_ylim(0, 1)
        ax.set_title(f"age {age} (n={sub.height})", fontsize=8, color=h3.INK)
        h3._style(ax)  # shared plotting style of the H3 script
    for ax in list(axes.flat)[len(ages) :]:
        ax.axis("off")
    axes.flat[0].legend(frameon=False, fontsize=7)
    fig.supxlabel(
        "Income band midpoint (10,000 yen/year, log scale; open top = lower x 1.25)",
        fontsize=8,
        color=h3.INK,
    )
    fig.supylabel("Ever-married share among employed men", fontsize=8, color=h3.INK)
    fig.suptitle(
        "Ever-married share by personal income band within 5-year age classes, "
        "employed men, Japan 2022\n"
        "Source: e-Stat, Employment Status Survey 2022 (MIC), table 40, processed; "
        "cells = estimated persons",
        fontsize=9,
        color=h3.INK,
    )
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def fig_adjusted(
    crude: pl.DataFrame,
    std: pl.DataFrame,
    c_crude: h3.Coef,
    c_std: h3.Coef,
    c_fe: h3.Coef,
    path: Path,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    ax.plot(
        crude["mid_man"],
        crude["value"],
        color=h3.MUTED,
        linewidth=2,
        marker="o",
        markersize=4,
        label=f"unadjusted (all ages 15+): slope {c_crude.b:+.3f}",
    )
    ax.plot(
        std["mid_man"],
        std["value"],
        color=h3.BLUE_RAMP[3],
        linewidth=2,
        marker="o",
        markersize=4,
        label=f"age-standardised (20-59, direct): slope {c_std.b:+.3f}",
    )
    ln = std["ln_mid"].to_numpy()
    xs = np.linspace(float(ln.min()), float(ln.max()), 50)
    w = std["weight"].to_numpy()
    a = float(np.average(std["value"].to_numpy(), weights=w)) - c_fe.b * float(
        np.average(std["ln_mid"].to_numpy(), weights=w)
    )
    ax.plot(
        np.exp(xs),
        a + c_fe.b * xs,
        color=h3.ORANGE,
        linewidth=1.5,
        linestyle="--",
        label=f"age-FE pooled WLS slope {c_fe.b:+.3f} [{c_fe.lo:+.3f}, {c_fe.hi:+.3f}]",
    )
    ax.set_xscale("log")
    ax.set_ylim(0, 1)
    ax.set_xlabel(
        "Income band midpoint (10,000 yen/year, log scale; open top = lower x 1.25)",
        fontsize=8,
        color=h3.INK,
    )
    ax.set_ylabel("Ever-married share among employed men", fontsize=8, color=h3.INK)
    ax.set_title(
        "Unadjusted vs age-adjusted income gradient, employed men, Japan 2022 "
        f"(n={std.height} income bands)\n"
        "Source: e-Stat, Employment Status Survey 2022 (MIC), table 40, processed",
        fontsize=9,
        color=h3.INK,
    )
    ax.legend(frameon=False, fontsize=7.5)
    h3._style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------- main
def _std_slope(
    frame: pl.DataFrame, weights: Mapping[str, float], *, weighted: bool = True
) -> tuple[h3.Coef, pl.DataFrame]:
    std = standardise(frame, weights)
    c = h3.weighted_slope(
        std["ln_mid"].to_numpy(),
        std["value"].to_numpy(),
        std["weight"].to_numpy() if weighted else None,
    )
    return c, std


def _report_spec(
    label: str,
    df: pl.DataFrame,
    *,
    sex: str,
    ages: tuple[int, int],
    top_factor: float = h3.TOP_FACTOR,
    weighted: bool = True,
    exclude_lowest: bool = False,
) -> None:
    frame = age_frame(df, sex=sex, ages=ages, top_factor=top_factor, exclude_lowest=exclude_lowest)
    weights = age_weights(df, sex=sex, ages=ages)
    complete = complete_ages(frame)
    dropped = sorted(set(weights) - set(complete))
    if dropped:
        weights = restrict_weights(weights, complete)
    c_std, _ = _std_slope(frame, weights, weighted=weighted)
    fe = fe_fit(frame, weighted=weighted).coefs["ln_mid"]
    crude = crude_slope(df, sex=sex, top_factor=top_factor, weighted=weighted)[0]
    note = (
        f" (standardised over {len(weights)} ages; {dropped} have empty cells)" if dropped else ""
    )
    print(
        f"  [{label}] cells={frame.height} ages={frame['age_class'].n_unique()}"
        f" | crude {crude.fmt()}"
        f" | standardised {c_std.fmt()} | age-FE {fe.fmt()}"
        f" | attenuation(FE)={attenuation(fe, crude):+.2f}{note}"
    )


def run(data_dir: Path, fig_dir: Path) -> None:
    df = pl.read_parquet(data_dir / AGE_MART)
    jp = pl.read_parquet(data_dir / H3_MART)
    describe(df)
    fig_dir.mkdir(parents=True, exist_ok=True)

    male = age_frame(df, sex="male")
    weights = age_weights(df, sex="male")
    print(f"\n== analysis cells: men, ages {MAIN_AGES[0]}-{MAIN_AGES[1]}, bounded income bands ==")
    print(
        f"  cells={male.height} age_classes={male['age_class'].n_unique()}"
        f" income_bands={male['income_class'].n_unique()} waves={male['year'].unique().to_list()}"
    )
    print(
        "  standard age distribution (men 20-59, income total column, 2022): "
        + ", ".join(f"{a}={w:.3f}" for a, w in weights.items())
    )

    print("\n== (a) within-age-class slopes, men (pre-specified main estimand) ==")
    res_a = slopes_by_age(male)
    print_ages("[A] men, weighted", res_a)

    print("\n== (b) direct age standardisation, men 20-59 ==")
    c_std, std = _std_slope(male, weights)
    for r in std.iter_rows(named=True):
        print(
            f"  band {r['income_class']:<10} mid={r['mid_man']:>7.1f}"
            f" standardised_share={r['value']:.4f} persons={r['weight']:,.0f}"
        )
    print(
        "  slope of standardised share on ln_mid (weighted by band persons):"
        f" {c_std.fmt()} sign={h3.sign_of(c_std)}"
    )

    print("\n== (c) pooled WLS with age-class fixed effects, men 20-59 ==")
    fe = fe_fit(male)
    h3.print_fit("[C] share ~ ln_mid + age FE (weights = persons)", fe)
    c_fe = fe.coefs["ln_mid"]

    print("\n== (d) adjusted vs unadjusted ==")
    crude_c, crude_rho, crude_n = crude_slope(df, sex="male")
    print(
        f"  (i) same table, age total rows (15+): n_bands={crude_n} slope {crude_c.fmt()}"
        f" spearman={crude_rho:+.3f}"
    )
    print(
        f"      standardised (b): {c_std.fmt()}  attenuation = {attenuation(c_std, crude_c):+.3f}"
    )
    print(f"      age-FE (c):       {c_fe.fmt()}  attenuation = {attenuation(c_fe, crude_c):+.3f}")
    h3_male = h3.band_frame(jp, metric="married_share", sex="male")
    h3_res = h3.slope_by_wave(h3_male)
    for y in H3_COMPARE_YEARS:
        c, rho, n = h3_res[y]
        print(
            f"  (ii) H3 report, 国民生活基礎調査 married_share men 15+, income year {y}:"
            f" n_bands={n} slope {c.fmt()} spearman={rho:+.3f}"
        )
    print(
        "      (different survey, outcome = 配偶者あり share, weights per 100k;"
        " sign and rough size only)"
    )

    print("\n== robustness (pre-listed; all shown; men) ==")
    print(
        "  columns: crude = age-total rows of the same table; standardised = direct method (b);"
        " age-FE = (c)"
    )
    _report_spec("base: ages 20-59, top x1.25, weighted", df, sex="male", ages=MAIN_AGES)
    for tf in h3.TOP_FACTOR_ALTS:
        _report_spec(f"top-code x{tf}", df, sex="male", ages=MAIN_AGES, top_factor=tf)
    _report_spec("unweighted", df, sex="male", ages=MAIN_AGES, weighted=False)
    _report_spec(
        "ages 25-59 (drop 20-24; 15-19 already excluded)", df, sex="male", ages=NO_YOUNG_AGES
    )
    _report_spec("all ages 15+ (incl. 15-19 and 60+)", df, sex="male", ages=ALL_AGES)
    _report_spec("excluding lowest band 0-50", df, sex="male", ages=MAIN_AGES, exclude_lowest=True)
    print(
        "  excluding 所得なし: N/A (the table has no 所得なし class; 50万円未満 is the lowest band)"
    )
    print_ages("[R] men, within-age slopes, unweighted", slopes_by_age(male, weighted=False))
    print_ages(
        "[R] men, within-age slopes, all ages 15+",
        slopes_by_age(age_frame(df, sex="male", ages=ALL_AGES)),
    )

    print("\n== EXPLORATORY (not pre-registered): women ==")
    female = age_frame(df, sex="female")
    print_ages("[X] women, weighted, ages 20-59", slopes_by_age(female))
    h3.print_fit("[X] women share ~ ln_mid + age FE", fe_fit(female))
    _report_spec("women, ages 20-59", df, sex="female", ages=MAIN_AGES)

    fig_small_multiples(
        age_frame(df, sex="male", ages=ALL_AGES), fig_dir / "h3b_married_share_by_age_income.png"
    )
    crude = h3.band_frame(df.filter(pl.col("age_class") == "total"), metric=METRIC, sex="male")
    fig_adjusted(crude, std, crude_c, c_std, c_fe, fig_dir / "h3b_adjusted_vs_unadjusted.png")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", type=Path, default=REPO_ROOT / "data")
    ap.add_argument("--fig-dir", type=Path, default=THEME_DIR / "reports" / "figures")
    args = ap.parse_args()
    run(args.data_dir, args.fig_dir)


if __name__ == "__main__":
    main()
