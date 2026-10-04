"""H2（限定版・関連のみ）: 上位 1% シェアの上昇幅は、制度変数（税制・福祉）の変化と関連しているか。

決定的スクリプト。入力は data/marts/wealth_institutions_panel.parquet（OECD 38 か国 × 1980–）。
乱数は使わない。出力: 標準出力に全数値、図を reports/figures/ に保存。

    uv run python themes/wealth-population-distribution/src/theme_wealth_population_distribution/\
analysis/<this file> [--data-dir data] \
        [--fig-dir themes/wealth-population-distribution/reports/figures]

## 事前登録（結果を見る前に固定。以下をそのままコードにしている）
対象: OECD 加盟 38 か国（OECD データの範囲。WID mart の 46 か国のうち非 OECD G20 8 か国は対象外）。
被説明変数: top1_income_share / top1_wealth_share（WID, 0–1 → pp に換算）。
制度変数（OECD, いずれも %）: top_pit_rate（最高限界所得税率）、
social_expenditure_gdp（公的社会支出 %GDP）、tax_revenue_gdp（総税収 %GDP）。
補助: inheritance_tax_rev_gdp（相続・遺産・贈与税収 %GDP）。
終点年 T: 5 変数（top1 所得・資産シェア、3 制度変数）が揃う国が 36 か国以上ある最大の年
（`end_year`）。

(a) 国横断の長期差分 OLS（HC3 SE）。Δ = x_T − x_base。
    A1: base=1980。Δtop1 ~ Δsocx + Δtaxrev
        （最高税率は OECD SDMX で 2000 年以降しか無いため含めない）。
    A2: base=2000。Δtop1 ~ Δpit + Δsocx + Δtaxrev。
    A2+: A2 に Δinheritance_tax_rev を追加（補助）。
    いずれも base 年と T 年の両方に観測がある国のみ（欠損は補完しない）。n を報告。
(b) 二方向固定効果パネル（国 FE ＋ 年 FE、国クラスタ SE）。y_it ~ x_{i,t−L}（L = 0, 5）。
    B1: 1980–T、x = socx, taxrev。B2: 2000–T、x = pit, socx, taxrev。
(c) (a) の R²（＝ Δ の国間分散のうち制度変数の変化で説明される割合）と調整済み R² を報告。
(d) 図: Δtop1 所得シェア (2000→T) vs Δ最高税率 の散布図（国ラベル、日本を強調）、FE 係数プロット。
頑健性（事前に列挙、全部報告）: A1 の base=1990、top1 → top10、米国除外、
R4: WID data_quality が**低い**（q ≤ 1）国を base 年の品質で除外。
  訂正記録: 初版は「q 4–5 = 推計・外挿」と誤解して 4–5 を落としていた。WID の data_quality は
  高いほど一次データに近い（USA DINA 1962 年以降 = 5、JPN/SAU 資産 = 0; theme CLAUDE.md）と
  判明したため、結果を見た後だが**意味の訂正として**向きを反転した（結果に合わせた選択ではない）。
R5（この改訂で追加、事前列挙に無かった変種）: base 年の WID 値が metadata 上 imputed
  （`top1_*_observed == False`）の国を除外。null（不明）は残す。

これは**関連**の分析。政策は内生（格差が政策を変える逆の因果）、省略変数（グローバル化・技術・資本所得化）、
WID の推計誤差があり、因果効果は主張しない。純粋関数（end_year, long_difference, fit_ols_hc3,
lagged, fit_twoway_fe, ...）は tests/test_analysis_h2.py で検証する。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import statsmodels.api as sm

THEME_DIR = Path(__file__).resolve().parents[3]
REPO_ROOT = THEME_DIR.parents[1]
MART = Path("marts") / "wealth_institutions_panel.parquet"

OUTCOMES = ("top1_income_share", "top1_wealth_share")
OUTCOMES_TOP10 = ("top10_income_share", "top10_wealth_share")
INST_ALL = ("top_pit_rate", "social_expenditure_gdp", "tax_revenue_gdp")
INST_NO_PIT = ("social_expenditure_gdp", "tax_revenue_gdp")
INHERITANCE = "inheritance_tax_rev_gdp"
QUALITY = {"top1_income_share": "top1_income_quality", "top1_wealth_share": "top1_wealth_quality"}
OBSERVED = {
    "top1_income_share": "top1_income_observed",
    "top1_wealth_share": "top1_wealth_observed",
}
LOW_QUALITY = {0, 1}  # WID data_quality: higher = closer to primary data (theme CLAUDE.md)
MIN_COUNTRIES_FOR_END = 36
JAPAN = "JPN"
SHORT = {
    "top_pit_rate": "pit",
    "social_expenditure_gdp": "socx",
    "tax_revenue_gdp": "taxrev",
    "inheritance_tax_rev_gdp": "inh",
}

BLUE = "#5598e7"
ORANGE = "#eb6834"
INK = "#333333"
MUTED = "#8a8a8a"


@dataclass(frozen=True)
class Fit:
    label: str
    y: str
    n: int
    coef: dict[str, float]
    se: dict[str, float]
    pval: dict[str, float]
    r2: float
    r2_adj: float
    n_groups: int | None = None

    def lines(self) -> list[str]:
        head = f"{self.label}  y={self.y}  n={self.n}"
        if self.n_groups is not None:
            head += f" countries={self.n_groups}"
        head += f"  R2={self.r2:.3f} adjR2={self.r2_adj:.3f}"
        out = [head]
        for k in self.coef:
            out.append(
                f"    {k:<28} b={self.coef[k]:+8.4f}  se={self.se[k]:7.4f}  "
                f"p={self.pval[k]:6.3f}  95%=[{self.coef[k] - 1.96 * self.se[k]:+.4f}, "
                f"{self.coef[k] + 1.96 * self.se[k]:+.4f}]"
            )
        return out


# ---------------------------------------------------------------- pure helpers (tested)
def to_pp(panel: pl.DataFrame) -> pl.DataFrame:
    """WID のシェア（0–1）を pp に換算。制度変数はもともと %。"""
    return panel.with_columns([(pl.col(c) * 100).alias(c) for c in (*OUTCOMES, *OUTCOMES_TOP10)])


def end_year(panel: pl.DataFrame, cols: tuple[str, ...], min_countries: int) -> int:
    """cols が全て非欠損の国が min_countries 以上ある最大の年。無ければ ValueError。"""
    ok = panel.filter(pl.all_horizontal([pl.col(c).is_not_null() for c in cols]))
    counts = ok.group_by("year").len().filter(pl.col("len") >= min_countries)
    if counts.height == 0:
        msg = f"no year with >= {min_countries} complete countries for {cols}"
        raise ValueError(msg)
    return int(str(counts["year"].max()))


def long_difference(
    panel: pl.DataFrame, base: int, end: int, cols: tuple[str, ...]
) -> pl.DataFrame:
    """iso3 ごとの Δcol = col[end] − col[base]。両年に全列の観測がある国のみ。

    quality 列（WID data_quality）は base 年の値を付ける。
    """
    qcols = [c for c in (*QUALITY.values(), *OBSERVED.values()) if c in panel.columns]
    b = panel.filter(pl.col("year") == base).select("iso3", *cols, *qcols)
    e = panel.filter(pl.col("year") == end).select("iso3", *cols)
    joined = b.join(e, on="iso3", suffix="_end", how="inner")
    out = joined.select(
        "iso3",
        *[(pl.col(f"{c}_end") - pl.col(c)).alias(f"d_{c}") for c in cols],
        *qcols,
    )
    return out.drop_nulls([f"d_{c}" for c in cols]).sort("iso3")


def fit_ols_hc3(df: pl.DataFrame, y: str, xs: tuple[str, ...], label: str) -> Fit:
    d = df.drop_nulls([y, *xs])
    x_mat = sm.add_constant(d.select(xs).to_numpy().astype(float), has_constant="add")
    res = sm.OLS(d[y].to_numpy().astype(float), x_mat).fit(cov_type="HC3")
    names = ["const", *xs]
    return Fit(
        label=label,
        y=y,
        n=int(res.nobs),
        coef=dict(zip(names, (float(v) for v in res.params), strict=True)),
        se=dict(zip(names, (float(v) for v in res.bse), strict=True)),
        pval=dict(zip(names, (float(v) for v in res.pvalues), strict=True)),
        r2=float(res.rsquared),
        r2_adj=float(res.rsquared_adj),
    )


def lagged(panel: pl.DataFrame, cols: tuple[str, ...], lag: int) -> pl.DataFrame:
    """各 col に L 年前の値 `<col>_lag<L>` を付ける（同一国内、暦年ベース。欠損年は欠損のまま）。"""
    if lag == 0:
        return panel.with_columns([pl.col(c).alias(f"{c}_lag0") for c in cols])
    shifted = panel.select(
        "iso3",
        (pl.col("year") + lag).alias("year"),
        *[pl.col(c).alias(f"{c}_lag{lag}") for c in cols],
    )
    return panel.join(shifted, on=["iso3", "year"], how="left")


def fit_twoway_fe(df: pl.DataFrame, y: str, xs: tuple[str, ...], label: str) -> Fit:
    """国 FE ＋ 年 FE の OLS（ダミー変数法）、国クラスタ SE。R² は within（二方向 demean 後）。"""
    d = df.drop_nulls([y, *xs]).sort(["iso3", "year"])
    pdf = d.select("iso3", "year", y, *xs).to_pandas()
    rhs = " + ".join(f"Q('{x}')" for x in xs)
    model = sm.OLS.from_formula(f"Q('{y}') ~ {rhs} + C(iso3) + C(year)", data=pdf)
    res = model.fit(
        cov_type="cluster", cov_kwds={"groups": pdf["iso3"].astype("category").cat.codes}
    )
    # within R2: demean y and x by country and year (two-way), then R2 of the slope-only fit
    g = d.to_pandas()
    for c in (y, *xs):
        g[c] = (
            g[c]
            - g.groupby("iso3")[c].transform("mean")
            - g.groupby("year")[c].transform("mean")
            + g[c].mean()
        )
    within = sm.OLS(g[y].to_numpy(), g[list(xs)].to_numpy()).fit()
    names = [f"Q('{x}')" for x in xs]
    return Fit(
        label=label,
        y=y,
        n=int(res.nobs),
        coef={x: float(res.params[k]) for x, k in zip(xs, names, strict=True)},
        se={x: float(res.bse[k]) for x, k in zip(xs, names, strict=True)},
        pval={x: float(res.pvalues[k]) for x, k in zip(xs, names, strict=True)},
        r2=float(within.rsquared),
        r2_adj=float(res.rsquared_adj),
        n_groups=int(d["iso3"].n_unique()),
    )


def drop_low_quality(diff: pl.DataFrame, y: str) -> pl.DataFrame:
    """base 年の WID data_quality が低い（q ≤ 1）国を落とす（y に対応する品質列）。null は残す。"""
    q = QUALITY[y.replace("top10", "top1")]
    return diff.filter(~pl.col(q).is_in(sorted(LOW_QUALITY)) | pl.col(q).is_null())


def drop_unobserved(diff: pl.DataFrame, y: str) -> pl.DataFrame:
    """base 年の WID 値が metadata 上 imputed（observed == False）の国を落とす。

    null（不明）は残す。observed 列が無ければそのまま返す。
    """
    o = OBSERVED[y.replace("top10", "top1")]
    if o not in diff.columns:
        return diff
    return diff.filter(pl.col(o).is_null() | pl.col(o))


# ---------------------------------------------------------------- figures
def _style(ax: Any) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(MUTED)
    ax.tick_params(colors=INK, labelsize=8)
    ax.grid(color="#e5e5e5", linewidth=0.5)
    ax.set_axisbelow(True)


def fig_scatter(diff: pl.DataFrame, fit: Fit, base: int, end: int, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    x, y = "d_top_pit_rate", "d_top1_income_share"
    fig, ax = plt.subplots(figsize=(6.8, 4.8))
    for r in diff.iter_rows(named=True):
        jp = r["iso3"] == JAPAN
        ax.scatter(r[x], r[y], s=36 if jp else 18, color=ORANGE if jp else BLUE, zorder=3)
        ax.annotate(
            r["iso3"], (r[x], r[y]), fontsize=8 if jp else 7, color=ORANGE if jp else INK,
            xytext=(3, -9 if jp else 2), textcoords="offset points",
            fontweight="bold" if jp else "normal",
        )  # fmt: skip
    xs = np.linspace(float(diff[x].min()), float(diff[x].max()), 50)  # type: ignore[arg-type]
    b = fit.coef
    # partial line at sample means of the other regressors
    others = 0.0
    for k in b:
        if k not in ("const", x):
            others += b[k] * float(str(diff[k].mean()))
    ax.plot(xs, b["const"] + others + b[x] * xs, color=INK, linewidth=1.2, linestyle="--")
    ax.axhline(0, color=MUTED, linewidth=0.6)
    ax.axvline(0, color=MUTED, linewidth=0.6)
    ax.set_xlabel(f"Δ top statutory PIT rate {base}→{end} (pp, OECD)", fontsize=9, color=INK)
    ax.set_ylabel(f"Δ top 1% pre-tax income share {base}→{end} (pp, WID)", fontsize=9, color=INK)
    ax.set_title(
        f"Long difference {base}→{end}, OECD members, n={fit.n}. Japan in orange.\n"
        f"Dashed: OLS fit A2 (other regressors at mean), b={b[x]:+.3f}, HC3 se {fit.se[x]:.3f}. "
        "Association only.\nSources: WID.world (CC BY-NC-SA 4.0); "
        "OECD Tax Database / SOCX / Revenue Statistics (OECD T&C 2024)",
        fontsize=8,
        color=INK,
        loc="left",
    )
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def fig_coefs(fits: list[Fit], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = [(f.label, f.y, k, f.coef[k], f.se[k]) for f in fits for k in f.coef]
    fig, ax = plt.subplots(figsize=(8.5, 0.32 * len(rows) + 1.8))
    for i, (_, y, _, b, se) in enumerate(rows):
        color = ORANGE if "wealth" in y else BLUE
        ax.errorbar(
            b, i, xerr=1.96 * se, fmt="o", color=color, markersize=4, capsize=2, linewidth=1
        )
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels(
        [
            f"{label} | {'wealth' if 'wealth' in y else 'income'} | {SHORT.get(k, k)}"
            for label, y, k, *_ in rows
        ],
        fontsize=7,
    )
    ax.invert_yaxis()
    ax.axvline(0, color=MUTED, linewidth=0.8)
    ax.set_xlabel(
        "coefficient on institutional variable (pp of top-1% share per 1 pp of regressor), 95% CI",
        fontsize=8,
        color=INK,
    )
    ax.set_title(
        "Two-way FE (country + year FE), country-clustered 95% CI. OECD members.\n"
        "Blue = top 1% pre-tax income share, orange = top 1% net wealth share (pp). "
        "B1: 1980-T, B2: 2000-T; L = lag in years.\n"
        "Association only. Sources: WID.world; OECD SDMX (Tax Database, SOCX, Revenue Statistics)",
        fontsize=8,
        color=INK,
        loc="left",
    )
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------- reporting
def print_fit(fit: Fit) -> None:
    for line in fit.lines():
        print(line)


def describe(panel: pl.DataFrame, end: int) -> None:
    print("== mart ==")
    print(
        f"rows={panel.height} countries={panel['iso3'].n_unique()} "
        f"years={int(str(panel['year'].min()))}-{int(str(panel['year'].max()))} end_year(T)={end}"
    )
    for c in (*OUTCOMES, *INST_ALL, INHERITANCE):
        nn = panel.filter(pl.col(c).is_not_null())
        print(
            f"  {c:<26} non-null={nn.height:>5} "
            f"years={int(str(nn['year'].min()))}-{int(str(nn['year'].max()))} "
            f"countries={nn['iso3'].n_unique()}"
        )
    for y in (1980, 1990, 2000, end):
        r = panel.filter(pl.col("year") == y)
        counts = {SHORT.get(c, c): int(r[c].is_not_null().sum()) for c in (*OUTCOMES, *INST_ALL)}
        print(f"  countries with data in {y}: {counts}")
    for c in (*INST_ALL, INHERITANCE):
        late = (
            panel.filter(pl.col(c).is_not_null())
            .group_by("iso3")
            .agg(pl.col("year").min().alias("first"))
            .filter(pl.col("first") > 1980)
            .sort("first", "iso3")
        )
        print(f"  {c}: series starting after 1980: {late.rows() or '-'}")


def print_diff_table(diff: pl.DataFrame, cols: tuple[str, ...]) -> None:
    print(f"  {'iso3':<5}" + "".join(f"{'d_' + SHORT.get(c, c[:12]):>16}" for c in cols))
    for r in diff.iter_rows(named=True):
        print(f"  {r['iso3']:<5}" + "".join(f"{r['d_' + c]:>+16.3f}" for c in cols))
    print(
        "  median: "
        + " ".join(f"d_{SHORT.get(c, c)}={float(str(diff[f'd_{c}'].median())):+.3f}" for c in cols)
    )


def run(data_dir: Path, fig_dir: Path) -> None:
    panel = to_pp(pl.read_parquet(data_dir / MART)).sort(["iso3", "year"])
    fig_dir.mkdir(parents=True, exist_ok=True)
    end = end_year(panel, (*OUTCOMES, *INST_ALL), MIN_COUNTRIES_FOR_END)
    describe(panel, end)

    print("\n== (a) long differences, OLS with HC3 SE (pre-registered A1, A2, A2+) ==")
    d80 = long_difference(panel, 1980, end, (*OUTCOMES, *OUTCOMES_TOP10, *INST_NO_PIT))
    print(f"-- A1: 1980 -> {end}, n={d80.height}")
    print_diff_table(d80, (*OUTCOMES, *INST_NO_PIT))
    a1 = {
        y: fit_ols_hc3(d80, f"d_{y}", tuple(f"d_{x}" for x in INST_NO_PIT), "A1") for y in OUTCOMES
    }
    for f in a1.values():
        print_fit(f)
    d00 = long_difference(panel, 2000, end, (*OUTCOMES, *OUTCOMES_TOP10, *INST_ALL, INHERITANCE))
    print(f"-- A2: 2000 -> {end}, n={d00.height}")
    print_diff_table(d00, (*OUTCOMES, *INST_ALL, INHERITANCE))
    a2 = {y: fit_ols_hc3(d00, f"d_{y}", tuple(f"d_{x}" for x in INST_ALL), "A2") for y in OUTCOMES}
    for f in a2.values():
        print_fit(f)
    for y in OUTCOMES:
        print_fit(
            fit_ols_hc3(d00, f"d_{y}", tuple(f"d_{x}" for x in (*INST_ALL, INHERITANCE)), "A2+")
        )
    jp = d00.filter(pl.col("iso3") == JAPAN).row(0, named=True)
    print(
        f"  Japan 2000->{end}: "
        + " ".join(
            f"d_{SHORT.get(c, c)}={jp['d_' + c]:+.3f}" for c in (*OUTCOMES, *INST_ALL, INHERITANCE)
        )
    )

    print("\n== (c) share of cross-country variance in Δ explained (R2 / adj. R2 of (a)) ==")
    for f in (*a1.values(), *a2.values()):
        print(f"  {f.label} {f.y}: R2={f.r2:.3f} adjR2={f.r2_adj:.3f} n={f.n}")

    print(
        "\n== (b) two-way FE panels, country-clustered SE "
        "(B1 1980-T: socx,taxrev; B2 2000-T: +pit) =="
    )
    fe_fits: list[Fit] = []
    for label, lo, xs in (("B1", 1980, INST_NO_PIT), ("B2", 2000, INST_ALL)):
        sub = panel.filter((pl.col("year") >= lo) & (pl.col("year") <= end))
        for lag in (0, 5):
            lp = lagged(sub, xs, lag)
            for y in OUTCOMES:
                f = fit_twoway_fe(lp, y, tuple(f"{x}_lag{lag}" for x in xs), f"{label} L{lag}")
                fe_fits.append(f)
                print_fit(f)

    fig_scatter(
        d00, a2["top1_income_share"], 2000, end, fig_dir / "h2_scatter_dpit_dtop1_income.png"
    )
    fig_coefs(fe_fits, fig_dir / "h2_fe_coefficients.png")

    print("\n== robustness (all pre-listed) ==")
    d90 = long_difference(panel, 1990, end, (*OUTCOMES, *OUTCOMES_TOP10, *INST_NO_PIT))
    print(f"-- R1: A1 with base=1990 (n={d90.height})")
    for y in OUTCOMES:
        print_fit(fit_ols_hc3(d90, f"d_{y}", tuple(f"d_{x}" for x in INST_NO_PIT), "R1 base1990"))
    print("-- R2: top10 instead of top1")
    for y in OUTCOMES_TOP10:
        print_fit(fit_ols_hc3(d80, f"d_{y}", tuple(f"d_{x}" for x in INST_NO_PIT), "R2 A1 top10"))
        print_fit(fit_ols_hc3(d00, f"d_{y}", tuple(f"d_{x}" for x in INST_ALL), "R2 A2 top10"))
    print("-- R3: excluding USA")
    for y in OUTCOMES:
        print_fit(
            fit_ols_hc3(
                d80.filter(pl.col("iso3") != "USA"),
                f"d_{y}",
                tuple(f"d_{x}" for x in INST_NO_PIT),
                "R3 A1 -USA",
            )
        )
        print_fit(
            fit_ols_hc3(
                d00.filter(pl.col("iso3") != "USA"),
                f"d_{y}",
                tuple(f"d_{x}" for x in INST_ALL),
                "R3 A2 -USA",
            )
        )
    print(
        "-- R4: excluding countries whose WID data_quality at the base year is low (q<=1; "
        "higher = closer to primary data; direction corrected, see docstring)"
    )
    for y in OUTCOMES:
        q80, q00 = drop_low_quality(d80, y), drop_low_quality(d00, y)
        dropped80 = sorted(set(d80["iso3"]) - set(q80["iso3"]))
        dropped00 = sorted(set(d00["iso3"]) - set(q00["iso3"]))
        print(f"  {y}: dropped at 1980 {dropped80 or '-'}; dropped at 2000 {dropped00 or '-'}")
        print_fit(fit_ols_hc3(q80, f"d_{y}", tuple(f"d_{x}" for x in INST_NO_PIT), "R4 A1 q>1"))
        print_fit(fit_ols_hc3(q00, f"d_{y}", tuple(f"d_{x}" for x in INST_ALL), "R4 A2 q>1"))
    print(
        "-- R5 (added at this revision, not in the original pre-list): excluding countries whose "
        "base-year WID value is imputed per metadata (observed == False; null kept)"
    )
    for y in OUTCOMES:
        o80, o00 = drop_unobserved(d80, y), drop_unobserved(d00, y)
        dropped80 = sorted(set(d80["iso3"]) - set(o80["iso3"]))
        dropped00 = sorted(set(d00["iso3"]) - set(o00["iso3"]))
        print(f"  {y}: dropped at 1980 {dropped80 or '-'}; dropped at 2000 {dropped00 or '-'}")
        print_fit(fit_ols_hc3(o80, f"d_{y}", tuple(f"d_{x}" for x in INST_NO_PIT), "R5 A1 obs"))
        print_fit(fit_ols_hc3(o00, f"d_{y}", tuple(f"d_{x}" for x in INST_ALL), "R5 A2 obs"))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", type=Path, default=REPO_ROOT / "data")
    ap.add_argument("--fig-dir", type=Path, default=THEME_DIR / "reports" / "figures")
    args = ap.parse_args()
    run(args.data_dir, args.fig_dir)


if __name__ == "__main__":
    main()
