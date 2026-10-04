import polars as pl
import pytest

from theme_wealth_population_distribution.analysis import a20261004_h1_ushape as h1
from theme_wealth_population_distribution.analysis import a20261005_h1c_quality_corrected as h1c


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


def flags() -> pl.DataFrame:
    rows = [
        ("AAA", 1950, 0),
        ("AAA", 1960, 1),
        ("AAA", 1980, 2),
        ("AAA", 2000, 4),
        # AAA 2010 has no quality row -> unknown
        ("BBB", 1980, 5),
        ("BBB", 2000, None),
    ]
    return pl.DataFrame(rows, schema=["iso3", "year", "data_quality"], orient="row").with_columns(
        pl.col("data_quality").cast(pl.Int64)
    )


def kept(df: pl.DataFrame) -> list[tuple[str, int]]:
    k = df.filter(pl.col("top1_income_share").is_not_null())
    return [(r["iso3"], r["year"]) for r in k.iter_rows(named=True)]


def test_mask_quality_drop_le_keeps_unknown() -> None:
    out = h1c.mask_quality(panel(), flags(), "top1_income_share", drop_le=1)
    assert out.height == panel().height and "data_quality" not in out.columns
    assert kept(out) == [("AAA", 1980), ("AAA", 2000), ("AAA", 2010), ("BBB", 1980), ("BBB", 2000)]
    out2 = h1c.mask_quality(panel(), flags(), "top1_income_share", drop_le=2)
    assert kept(out2) == [("AAA", 2000), ("AAA", 2010), ("BBB", 1980), ("BBB", 2000)]


def test_mask_quality_keep_ge_drops_unknown() -> None:
    out = h1c.mask_quality(panel(), flags(), "top1_income_share", keep_ge=4)
    assert kept(out) == [("AAA", 2000), ("BBB", 1980)]


def test_mask_quality_requires_exactly_one_mode() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        h1c.mask_quality(panel(), flags(), "top1_income_share")
    with pytest.raises(ValueError, match="exactly one"):
        h1c.mask_quality(panel(), flags(), "top1_income_share", drop_le=1, keep_ge=4)


def test_mask_quality_matches_h1_drop_quality_for_explicit_set() -> None:
    # V-A (<=1) must equal H1's drop_quality with bad={0,1} on the same data.
    a = h1c.mask_quality(panel(), flags(), "top1_income_share", drop_le=1)
    b = h1.drop_quality(panel(), flags(), "top1_income_share", {0, 1})
    assert a.equals(b)


def test_quality_matrix_rows_follow_codes_and_years() -> None:
    m = h1c.quality_matrix(flags(), ["AAA", "BBB", "CCC"], (1950, 2000))
    assert len(m) == 3 and all(len(r) == 51 for r in m)
    assert m[0][0] == 0 and m[0][10] == 1 and m[0][30] == 2 and m[0][50] == 4
    assert m[0][1] is None  # no row for 1951
    assert m[1][30] == 5 and m[1][50] is None  # null quality -> None
    assert all(v is None for v in m[2])


def test_quality_counts_by_country() -> None:
    t = h1c.quality_counts_by_country(flags(), (1950, 2024))
    a = t.filter(pl.col("iso3") == "AAA").row(0, named=True)
    assert a["n"] == 4 and (a["q0"], a["q1"], a["q2"], a["q4"]) == (1, 1, 1, 1)
    assert a["q3"] == 0 and a["q5"] == 0 and a["qnull"] == 0
    assert a["first_ge4"] == 2000
    b = t.filter(pl.col("iso3") == "BBB").row(0, named=True)
    assert b["n"] == 2 and b["q5"] == 1 and b["qnull"] == 1 and b["first_ge4"] == 1980
