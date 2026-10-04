"""H1c: H1 の data_quality 感度分析を、向きを正して再実行する追補（記述のみ、事前列挙）。

H1（a20261004_h1_ushape.py）の頑健性変種「data_quality ∈ {4,5} を欠損化」は、4–5 を「推計・外挿」と
誤解していた。H1b（a20261004_h1b_observed_only.py）と design/data-sources.md で、WID の
`data_quality`（0–5）は**高いほど一次データに近い**（observed 年は q3–5 のみ、SAU/JPN 資産は
全年 q0）ことを確認したので、本スクリプトは同じ U 字基準・同じ窓（h1.BASE）で、**正しい向き**の
変種だけを再実行する。H1 の数値は変更しない。

入力: data/marts/wealth_population_panel.parquet（系列）、data/staged/wid/top_shares.parquet
（`data_quality` 列）。乱数なし。純粋関数は tests/test_analysis_h1c.py で検証。
H1 の純粋関数（classify_all, majority_test, rise_since_1980_test, quality_flags, rank_in_year）は
import して使い、コピーしない。

    uv run python themes/wealth-population-distribution/src/theme_wealth_population_distribution/\
analysis/<this file> [--data-dir data] [--fig-dir .../reports/figures]

## 変種（結果を見る前に列挙。U 字基準・窓・適格性は H1 の BASE と同一。欠損は補完しない）
対象系列: top1/top10 × wealth/income（H1 と同じ 4 系列）。
- V0 基準: 全年（= H1 の主結果。照合用）。
- V-A: data_quality <= 1 の国×年を欠損化（弱）。
- V-B: data_quality <= 2 の国×年を欠損化（中。H1b で「q <= 2 ⇒ 非観測」が所得で成立）。
- V-C: data_quality >= 4 の国×年だけ残す（強。<= 3 と quality 不明を欠損化）。
各変種・系列で: 適格 n、U 字の割合（Wilson 95%、片側二項 p は目安）、1980 年以降上昇の割合、
判定が V0 から変わった国、日本の判定・順位（適格なら）。
図: data_quality の国×年ヒートマップ（46 行 × 1950–2024）を top1 wealth / top1 income で 1 枚ずつ。
予想（事前）: 資産は国×年の約 7 割が q0 なので V-A で既に適格国が大きく減る。所得は q3 が多いので
V-A/V-B の影響は小さく、V-C で 1980 年以前の年が落ちて適格国が減る。
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import polars as pl

from theme_wealth_population_distribution.analysis import a20261004_h1_ushape as h1
from theme_wealth_population_distribution.analysis.a20261004_h1b_observed_only import (
    changed_countries,
)

THEME_DIR = Path(__file__).resolve().parents[3]
REPO_ROOT = THEME_DIR.parents[1]

SERIES = tuple(h1.SERIES)  # all four H1 series
HEATMAP_SERIES = ("top1_wealth_share", "top1_income_share")
JAPAN = h1.JAPAN
Q_LEVELS = range(6)

# dataviz: sequential = one hue, light -> dark (0 = lightest, 5 = darkest); missing = surface.
SEQ_BLUE = ["#e8eef9", "#c3d4f0", "#93b2e6", "#5f8cd6", "#2f63b8", "#143d80"]
MISSING = "#ffffff"


# ---------------------------------------------------------------- pure helpers (tested)
def mask_quality(
    panel: pl.DataFrame,
    flags: pl.DataFrame,
    col: str,
    *,
    drop_le: int | None = None,
    keep_ge: int | None = None,
) -> pl.DataFrame:
    """data_quality で col を欠損化する（行は残す、補完しない）。

    drop_le=k: quality <= k の年を欠損化（quality 不明は残す）。
    keep_ge=k: quality >= k の年だけ残す（不明は欠損化。fail-closed）。両方は不可。
    """
    if (drop_le is None) == (keep_ge is None):
        msg = "give exactly one of drop_le / keep_ge"
        raise ValueError(msg)
    joined = panel.join(flags, on=["iso3", "year"], how="left")
    q = pl.col("data_quality")
    bad = (q <= drop_le) if drop_le is not None else (q.is_null() | (q < keep_ge))
    return joined.with_columns(
        pl.when(bad.fill_null(False)).then(None).otherwise(pl.col(col)).alias(col)
    ).drop("data_quality")


def quality_matrix(
    flags: pl.DataFrame, codes: list[str], window: tuple[int, int]
) -> list[list[int | None]]:
    """国（codes 順）× 年（window 連続）の data_quality。無い年・quality 不明は None。"""
    lo, hi = window
    lookup = {
        (r["iso3"], r["year"]): r["data_quality"]
        for r in flags.filter((pl.col("year") >= lo) & (pl.col("year") <= hi)).iter_rows(named=True)
    }
    return [[lookup.get((c, y)) for y in range(lo, hi + 1)] for c in codes]


def quality_counts_by_country(flags: pl.DataFrame, window: tuple[int, int]) -> pl.DataFrame:
    """国別: 窓内の年数と q0..q5 / 不明の件数、最初に q >= 4 となる年。"""
    lo, hi = window
    q = pl.col("data_quality")
    df = flags.filter((pl.col("year") >= lo) & (pl.col("year") <= hi))
    return (
        df.group_by("iso3")
        .agg(
            pl.len().alias("n"),
            *[(q == k).sum().alias(f"q{k}") for k in Q_LEVELS],
            q.is_null().sum().alias("qnull"),
            pl.col("year").filter(q >= 4).min().alias("first_ge4"),
        )
        .sort("iso3")
    )


# ---------------------------------------------------------------- figure
def fig_quality_heatmap(flags: pl.DataFrame, codes: list[str], path: Path, *, title: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import BoundaryNorm, ListedColormap
    from matplotlib.patches import Patch

    lo, hi = h1.BASE.window
    m = quality_matrix(flags, codes, (lo, hi))
    data = [[(-1 if v is None else v) for v in row] for row in m]
    cmap = ListedColormap([MISSING, *SEQ_BLUE])
    norm = BoundaryNorm([-1.5, -0.5, 0.5, 1.5, 2.5, 3.5, 4.5, 5.5], cmap.N)
    fig, ax = plt.subplots(figsize=(9.5, 8.5))
    ax.imshow(
        data,
        aspect="auto",
        cmap=cmap,
        norm=norm,
        interpolation="nearest",
        extent=(lo - 0.5, hi + 0.5, len(codes) - 0.5, -0.5),
    )
    ax.set_yticks(range(len(codes)))
    ax.set_yticklabels(codes, fontsize=7)
    for lab in ax.get_yticklabels():
        if lab.get_text() == JAPAN:
            lab.set_color(h1.ORANGE)
            lab.set_fontweight("bold")
    ax.set_xticks(range(1950, hi + 1, 10))
    ax.tick_params(colors=h1.INK, labelsize=7, length=0)
    for side in ax.spines.values():
        side.set_visible(False)
    ax.set_xlabel("year", fontsize=8, color=h1.INK)
    for y in range(1, len(codes)):
        ax.axhline(y - 0.5, color="#ffffff", linewidth=0.4)
    handles = [Patch(facecolor=SEQ_BLUE[k], edgecolor="none", label=f"q{k}") for k in Q_LEVELS]
    handles.append(Patch(facecolor=MISSING, edgecolor="#cccccc", label="no value"))
    ax.legend(
        handles=handles,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.06),
        ncol=7,
        fontsize=7,
        frameon=False,
        title=(
            "WID data_quality (0 = furthest from primary data, 5 = closest; definition not public)"
        ),
        title_fontsize=7,
    )
    ax.set_title(
        f"{title}: WID data_quality by country x year, {lo}-{hi} (n={len(codes)} countries).\n"
        "Source: World Inequality Database (wid.world), CC BY-NC-SA 4.0",
        fontsize=9,
        color=h1.INK,
    )
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------- reporting
def print_quality_coverage(staged: pl.DataFrame) -> None:
    lo, hi = h1.BASE.window
    for col in SERIES:
        f = h1.quality_flags(staged, col)
        t = quality_counts_by_country(f, (lo, hi))
        tot = {k: int(t[k].sum()) for k in ["n", *(f"q{k}" for k in Q_LEVELS), "qnull"]}
        print(f"== data_quality coverage: {col} (window {lo}-{hi}) ==")
        cells = " ".join(f"q{k}={tot[f'q{k}']} ({tot[f'q{k}'] / tot['n']:.3f})" for k in Q_LEVELS)
        print(f"  country-years n={tot['n']}: {cells} qnull={tot['qnull']}")
        for k in (1, 2):
            n_left = t.filter((pl.col("n") - sum(pl.col(f"q{j}") for j in range(k + 1))) > 0)
            print(f"  countries with >=1 year of q>{k}: {n_left.height}/{t.height}")
        ge4 = t.filter(pl.col("first_ge4").is_not_null())
        pre = ge4.filter(pl.col("first_ge4") < h1.BASE.pre_cut)
        print(
            f"  countries with >=1 year of q>=4: {ge4.height}/{t.height}; "
            f"first q>=4 before {h1.BASE.pre_cut}: {pre.height} "
            f"({' '.join(pre['iso3'].to_list()) or '-'})"
        )
        if col in HEATMAP_SERIES:
            head = "".join(f"{f'q{k}':>5}" for k in Q_LEVELS)
            print(f"  {'iso3':<5}{'n':>4}{head}  first_q>=4")
            for r in t.iter_rows(named=True):
                fg = r["first_ge4"] if r["first_ge4"] is not None else "-"
                print(
                    f"  {r['iso3']:<5}{r['n']:>4}"
                    + "".join(f"{r[f'q{k}']:>5}" for k in Q_LEVELS)
                    + f"  {fg!s:>10}"
                )


def print_japan(panel: pl.DataFrame, traj: pl.DataFrame, col: str) -> None:
    r = traj.filter(pl.col("iso3") == JAPAN).row(0, named=True)
    if r["n"] == 0:
        print(f"    JPN {col}: no years left")
        return
    if not r["eligible"]:
        print(f"    JPN {col}: n={r['n']} not eligible ({r['first_year']}-{r['last_year']})")
        return
    # rank in Japan's own last remaining year (masking can end JPN's series before other countries')
    rank, n = h1.rank_in_year(panel, col, int(r["last_year"]), JAPAN)
    print(
        f"    JPN {col}: n={r['n']} eligible u_shape={r['u_shape']} "
        f"trough {r['trough_year']}={r['trough']:.3f} last {r['last_year']}={r['last']:.3f} "
        f"change_since_1980(nearest {r['year_1980']})={r['change_since_1980']:+.3f} "
        f"| rank in {r['last_year']}: {rank}/{n} (1 = highest share)"
    )


def run(data_dir: Path, fig_dir: Path) -> None:
    panel = pl.read_parquet(data_dir / h1.MART).sort(["iso3", "year"])
    staged = pl.read_parquet(data_dir / h1.STAGED_SHARES)
    fig_dir.mkdir(parents=True, exist_ok=True)
    codes = sorted(panel["iso3"].unique().to_list())

    print("== inputs ==")
    print(f"mart rows={panel.height} countries={len(codes)} staged top_shares rows={staged.height}")
    print_quality_coverage(staged)

    variants: list[tuple[str, str, int | None, int | None]] = [
        ("V0", "base (all years, = H1)", None, None),
        ("V-A", "null-out data_quality <= 1", 1, None),
        ("V-B", "null-out data_quality <= 2", 2, None),
        ("V-C", "keep only data_quality >= 4", None, 4),
    ]
    base_traj: dict[str, pl.DataFrame] = {}
    for code, name, drop_le, keep_ge in variants:
        print(f"\n== {code}: {name} ==")
        for col in SERIES:
            p = panel
            if drop_le is not None or keep_ge is not None:
                p = mask_quality(
                    panel, h1.quality_flags(staged, col), col, drop_le=drop_le, keep_ge=keep_ge
                )
            traj = h1.classify_all(p, col)
            if code == "V0":
                base_traj[col] = traj
            print("  " + h1.majority_test(traj, f"[M] {code} {col}").line())
            print(
                "  "
                + h1.rise_since_1980_test(traj, f"[A] {code} rise since 1980 > 0: {col}").line()
            )
            elig = traj.filter(pl.col("eligible"))
            u = sorted(elig.filter(pl.col("u_shape").cast(pl.Boolean).fill_null(False))["iso3"])
            print(f"    U-shape countries ({len(u)}): {' '.join(u) or '-'}")
            if code != "V0":
                ch = changed_countries(traj, base_traj[col])
                print(f"    eligibility/U changed vs V0 ({len(ch)}): {' '.join(ch) or '-'}")
                inel = sorted(traj.filter(~pl.col("eligible"))["iso3"].to_list())
                print(f"    ineligible ({len(inel)}): {' '.join(inel) or '-'}")
            print_japan(p, traj, col)

    fig_quality_heatmap(
        h1.quality_flags(staged, "top1_wealth_share"),
        codes,
        fig_dir / "h1c_quality_heatmap_top1_wealth.png",
        title="Top 1% net personal wealth share (shweal992j p99p100)",
    )
    fig_quality_heatmap(
        h1.quality_flags(staged, "top1_income_share"),
        codes,
        fig_dir / "h1c_quality_heatmap_top1_income.png",
        title="Top 1% pre-tax national income share (sptinc992j p99p100)",
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", type=Path, default=REPO_ROOT / "data")
    ap.add_argument("--fig-dir", type=Path, default=THEME_DIR / "reports" / "figures")
    args: Any = ap.parse_args()
    run(args.data_dir, args.fig_dir)


if __name__ == "__main__":
    main()
