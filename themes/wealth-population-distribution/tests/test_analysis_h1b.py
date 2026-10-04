import polars as pl
import pytest

from theme_wealth_population_distribution.analysis import a20261004_h1_ushape as h1
from theme_wealth_population_distribution.analysis import a20261004_h1b_observed_only as h1b


def panel() -> pl.DataFrame:
    rows = [
        ("AAA", 1950, 0.30),
        ("AAA", 1960, 0.25),
        ("AAA", 1980, 0.20),
        ("AAA", 2000, 0.25),
        ("AAA", 2010, 0.28),
        ("BBB", 1980, 0.20),
        ("BBB", 2000, 0.25),
    ]
    return pl.DataFrame(rows, schema=["iso3", "year", "top1_income_share"], orient="row")


def data_points() -> pl.DataFrame:
    rows = [
        ("AAA", 1950, "sptinc992j", "imputed"),
        ("AAA", 1960, "sptinc992j", "imputed"),
        ("AAA", 1980, "sptinc992j", "observed"),
        ("AAA", 2000, "sptinc992j", "partial"),
        # 2010 has no row -> unknown
        ("BBB", 1980, "sptinc992j", "observed"),
        ("BBB", 2000, "sptinc992j", None),
        ("AAA", 1980, "shweal992j", "imputed"),  # other variable, must be ignored
    ]
    return pl.DataFrame(
        rows, schema=["iso3", "year", "variable", "construction"], orient="row"
    ).with_columns(pl.col("construction").cast(pl.String))


def test_construction_flags_select_variable() -> None:
    f = h1b.construction_flags(data_points(), "top1_income_share")
    assert f.columns == ["iso3", "year", "construction"]
    assert f.height == 6 and "shweal992j" not in f.to_dicts()[0].values()


def test_mask_construction_keep_drops_unknown_and_other_kinds() -> None:
    f = h1b.construction_flags(data_points(), "top1_income_share")
    out = h1b.mask_construction(panel(), f, "top1_income_share", keep={"observed"})
    assert out.height == panel().height and "construction" not in out.columns
    kept = out.filter(pl.col("top1_income_share").is_not_null())
    assert [(r["iso3"], r["year"]) for r in kept.iter_rows(named=True)] == [
        ("AAA", 1980),
        ("BBB", 1980),
    ]


def test_mask_construction_drop_keeps_unknown_and_partial() -> None:
    f = h1b.construction_flags(data_points(), "top1_income_share")
    out = h1b.mask_construction(panel(), f, "top1_income_share", drop={"imputed"})
    kept = out.filter(pl.col("top1_income_share").is_not_null())
    assert [(r["iso3"], r["year"]) for r in kept.iter_rows(named=True)] == [
        ("AAA", 1980),
        ("AAA", 2000),
        ("AAA", 2010),
        ("BBB", 1980),
        ("BBB", 2000),
    ]


def test_mask_construction_requires_exactly_one_mode() -> None:
    f = h1b.construction_flags(data_points(), "top1_income_share")
    with pytest.raises(ValueError, match="exactly one"):
        h1b.mask_construction(panel(), f, "top1_income_share")
    with pytest.raises(ValueError, match="exactly one"):
        h1b.mask_construction(panel(), f, "top1_income_share", keep={"a"}, drop={"b"})


def test_coverage_by_construction_counts_window_only() -> None:
    f = h1b.construction_flags(data_points(), "top1_income_share")
    cov = h1b.coverage_by_construction(panel(), f, "top1_income_share", (1960, 2024))
    a = cov.filter(pl.col("iso3") == "AAA").row(0, named=True)
    assert a["n"] == 4  # 1950 outside the window
    assert (a["observed"], a["partial"], a["imputed"], a["unknown"]) == (1, 1, 1, 1)
    assert a["first_observed"] == 1980 and a["last_observed"] == 1980
    b = cov.filter(pl.col("iso3") == "BBB").row(0, named=True)
    assert (b["observed"], b["unknown"]) == (1, 1)


def test_quality_by_construction_crosstab() -> None:
    f = h1b.construction_flags(data_points(), "top1_income_share")
    quality = pl.DataFrame(
        {
            "iso3": ["AAA", "AAA", "AAA", "BBB"],
            "year": [1950, 1980, 2010, 2000],
            "data_quality": [0, 4, None, 2],
        }
    )
    ct = h1b.quality_by_construction(quality, f, (1950, 2024))
    assert ct.rows() == [
        ("imputed", 0, 1),
        ("observed", 4, 1),
        ("unknown", None, 1),
        ("unknown", 2, 1),
    ]


def test_changed_countries() -> None:
    base = pl.DataFrame(
        {
            "iso3": ["AAA", "BBB", "CCC"],
            "eligible": [True, True, False],
            "u_shape": [True, False, None],
        }
    )
    new = pl.DataFrame(
        {
            "iso3": ["AAA", "BBB", "CCC"],
            "eligible": [True, False, False],
            "u_shape": [False, None, None],
        }
    )
    assert h1b.changed_countries(new, base) == ["AAA", "BBB"]
    assert h1b.changed_countries(base, base) == []
    # all-null u_shape column (nobody eligible) must not break the comparison
    none = pl.DataFrame(
        {"iso3": ["AAA", "BBB", "CCC"], "eligible": [False] * 3, "u_shape": [None] * 3}
    )
    assert h1b.changed_countries(none, base) == ["AAA", "BBB"]


def test_strict_variant_makes_short_series_ineligible() -> None:
    f = h1b.construction_flags(data_points(), "top1_income_share")
    strict = h1b.mask_construction(panel(), f, "top1_income_share", keep={"observed"})
    traj = h1.classify_all(strict, "top1_income_share")
    assert traj["eligible"].to_list() == [False, False]
    assert traj.filter(pl.col("iso3") == "AAA")["n"][0] == 1
