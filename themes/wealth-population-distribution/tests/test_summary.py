import polars as pl
import pytest

from theme_wealth_population_distribution.analysis import a20261004_h1_ushape as h1
from theme_wealth_population_distribution.analysis import a20261004_h2_institutions as h2
from theme_wealth_population_distribution.analysis import s20261005_summary as s


def test_pick_font_prefers_candidate_order_and_falls_back_to_none() -> None:
    assert s.pick_font(["DejaVu Sans", "Yu Gothic", "Hiragino Sans"]) == "Hiragino Sans"
    assert s.pick_font(["DejaVu Sans", "Yu Gothic"]) == "Yu Gothic"
    assert s.pick_font(["DejaVu Sans"]) is None
    assert s.pick_font([]) is None


def test_income_groups_sum_to_one_and_reject_inconsistent() -> None:
    g = s.income_groups(0.127, 0.435, 0.182)
    assert list(g) == ["上位 1%", "次の 9%", "中間 40%", "下位 50%"]
    assert g["次の 9%"] == pytest.approx(0.308)
    assert g["中間 40%"] == pytest.approx(0.383)
    assert sum(g.values()) == pytest.approx(1.0)
    with pytest.raises(ValueError, match="inconsistent"):
        s.income_groups(0.5, 0.4, 0.1)


def test_allocate_cells_sums_to_n_with_largest_remainder() -> None:
    cells = s.allocate_cells({"a": 0.127, "b": 0.308, "c": 0.383, "d": 0.182})
    assert sum(cells.values()) == 100
    assert cells == {"a": 13, "b": 31, "c": 38, "d": 18}
    tie = s.allocate_cells({"a": 0.5, "b": 0.5}, n=3)
    assert tie == {"a": 2, "b": 1}  # equal remainders: ties broken by input order


def traj(rows: list[tuple[str, bool, int | None, float | None]]) -> pl.DataFrame:
    return pl.DataFrame(
        rows,
        schema={
            "iso3": pl.Utf8,
            "eligible": pl.Boolean,
            "trough_year": pl.Int64,
            "change_since_1980": pl.Float64,
        },
        orient="row",
    )


def test_changes_table_joins_and_converts_to_pp() -> None:
    a = traj([("AAA", True, 1980, 0.02), ("BBB", True, 1990, -0.01), ("CCC", True, 1985, None)])
    b = traj([("AAA", True, 1980, 0.05), ("BBB", True, 1990, 0.03), ("DDD", True, 1985, 0.01)])
    out = s.changes_table(a, b, "inc", "wea")
    assert out["iso3"].to_list() == ["AAA", "BBB"]
    assert out["inc"].to_list() == pytest.approx([2.0, -1.0])
    assert out["wea"].to_list() == pytest.approx([5.0, 3.0])


def test_trough_year_bins_counts_eligible_only() -> None:
    t = traj(
        [
            ("AAA", True, 1955, 0.0),
            ("BBB", True, 1984, 0.0),
            ("CCC", True, 1989, 0.0),
            ("DDD", True, 2020, 0.0),
            ("EEE", False, 1984, 0.0),
        ]
    )
    bins = dict(s.trough_year_bins(t))
    assert bins == {
        "1950s": 1,
        "1960s": 0,
        "1970s": 0,
        "1980s": 2,
        "1990s": 0,
        "2000s": 0,
        "2010–2024": 1,
    }


def panel() -> pl.DataFrame:
    rows = [
        ("AAA", 1980, 0.10),
        ("AAA", 1981, 0.12),
        ("BBB", 1980, 0.30),
        ("BBB", 1981, None),
        ("CCC", 1980, 0.20),
        ("CCC", 1981, 0.22),
    ]
    return pl.DataFrame(rows, schema=["iso3", "year", "top1_income_share"], orient="row")


def test_median_by_year_ignores_missing() -> None:
    m = s.median_by_year(panel(), "top1_income_share", (1980, 1981))
    assert m["year"].to_list() == [1980, 1981]
    assert m["median"].to_list() == pytest.approx([0.20, 0.17])
    assert m["n"].to_list() == [3, 2]


def test_ratio_series_drops_missing_and_nonpositive_denominators() -> None:
    p = panel().with_columns(
        pl.Series("top01_income_share", [0.03, None, 0.09, 0.1, 0.05, 0.06]),
        pl.Series("top1_income_share", [0.10, 0.12, 0.30, None, 0.0, 0.22]),
    )
    r = s.ratio_series(p, "top01_income_share", "top1_income_share")
    assert [(x["iso3"], x["year"]) for x in r.iter_rows(named=True)] == [
        ("AAA", 1980),
        ("BBB", 1980),
        ("CCC", 1981),
    ]
    assert r["ratio"].to_list() == pytest.approx([0.3, 0.3, 0.06 / 0.22])


def test_rank_series_only_years_with_full_panel() -> None:
    rs = s.rank_series(panel(), "top1_income_share", "AAA", (1980, 1981), full_n=3)
    assert rs == [(1980, 3)]  # 1981 has only 2 countries
    rs2 = s.rank_series(panel(), "top1_income_share", "CCC", (1980, 1981), full_n=3)
    assert rs2 == [(1980, 2)]


def test_shares_by_decade_fills_unknown_and_sums_to_one() -> None:
    lab = pl.DataFrame(
        [
            ("AAA", 1950, "observed"),
            ("AAA", 1951, None),
            ("AAA", 1952, "imputed"),
            ("AAA", 1953, "imputed"),
            ("BBB", 1985, "observed"),
        ],
        schema={"iso3": pl.Utf8, "year": pl.Int64, "construction": pl.Utf8},
        orient="row",
    )
    out = s.shares_by_decade(
        lab, "construction", s.CONSTRUCTION_ORDER, bins=[(1950, 1959), (1980, 1989), (1990, 1999)]
    )
    assert out["period"].to_list() == ["1950s", "1980s", "1990s"]
    assert out["n"].to_list() == [4, 1, 0]
    r = out.row(0, named=True)
    assert (r["observed"], r["partial"], r["imputed"], r["unknown"]) == pytest.approx(
        (0.25, 0.0, 0.5, 0.25)
    )
    assert out.row(2, named=True)["observed"] == 0.0


def test_quality_labels_formats_q_and_keeps_unknown() -> None:
    staged = pl.DataFrame(
        [
            ("AAA", 1980, "sptinc992j", "p99p100", 0.1, 4),
            ("AAA", 1981, "sptinc992j", "p99p100", 0.1, None),
        ],
        schema={
            "iso3": pl.Utf8,
            "year": pl.Int64,
            "variable": pl.Utf8,
            "percentile": pl.Utf8,
            "value": pl.Float64,
            "data_quality": pl.Int64,
        },
        orient="row",
    )
    out = s.quality_labels(panel(), staged, "top1_income_share", h1.BASE.window).sort(
        ["iso3", "year"]
    )
    aaa = out.filter(pl.col("iso3") == "AAA")["q"].to_list()
    assert aaa == ["q4", None]
    assert out.filter(pl.col("iso3") == "BBB").height == 1  # BBB 1981 is null in panel → excluded


def test_construction_labels_restricts_to_non_null_years() -> None:
    dp = pl.DataFrame(
        [("AAA", 1980, "sptinc992j", "observed"), ("BBB", 1981, "sptinc992j", "imputed")],
        schema={"iso3": pl.Utf8, "year": pl.Int64, "variable": pl.Utf8, "construction": pl.Utf8},
        orient="row",
    )
    out = s.construction_labels(panel(), dp, "top1_income_share", (1980, 1981)).sort(
        ["iso3", "year"]
    )
    assert out.height == 5
    assert (
        out.filter((pl.col("iso3") == "AAA") & (pl.col("year") == 1980))["construction"][0]
        == "observed"
    )
    assert out.filter(pl.col("iso3") == "BBB")["construction"].to_list() == [
        None
    ]  # 1981 null → not present


def test_coef_rows_drops_constant_and_builds_ci() -> None:
    fit = h2.Fit(
        label="A1",
        y="d_top1_income_share",
        n=23,
        coef={"const": 1.0, "d_x": 0.5},
        se={"const": 0.1, "d_x": 0.2},
        pval={"const": 0.0, "d_x": 0.02},
        r2=0.2,
        r2_adj=0.1,
    )
    rows = s.coef_rows(fit, "A1")
    assert len(rows) == 1
    r = rows[0]
    assert r["x"] == "d_x" and r["n"] == 23
    assert (r["lo"], r["hi"]) == pytest.approx((0.5 - 1.96 * 0.2, 0.5 + 1.96 * 0.2))
