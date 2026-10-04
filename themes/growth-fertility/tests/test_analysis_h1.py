import math

import polars as pl
import pytest

from theme_growth_fertility.analysis import a20261004_h1_income_tfr as h1


def panel() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "iso3": ["JPN", "JPN", "JPN", "USA", "USA", "QAT", "TUV"],
            "country": ["Japan"] * 3 + ["United States"] * 2 + ["Qatar", "Tuvalu"],
            "year": [1989, 2000, 2010, 2000, 2010, 2010, 2010],
            "region": ["EAS"] * 3 + ["NAC"] * 2 + ["MEA", "EAS"],
            "income_group": ["High income"] * 6 + ["Upper middle income"],
            "tfr": [1.57, 1.36, 1.39, 2.06, None, 2.0, 3.2],
            "gdp_pcap_ppp": [30000.0, 35000.0, None, 50000.0, 55000.0, 100000.0, 4000.0],
            "gdp_growth": [None] * 7,
            "population": [1.2e8, 1.27e8, 1.28e8, 2.8e8, 3.1e8, 1.7e6, 1.0e4],
        }
    )


def test_decade_of() -> None:
    assert [h1.decade_of(y) for y in (1990, 1999, 2000, 2024)] == [1990, 1990, 2000, 2020]


def test_build_regression_frame_drops_missing_without_imputing_and_adds_ln_gdp() -> None:
    frame = h1.build_regression_frame(panel())
    # 1989 (before START_YEAR), JPN 2010 (gdp null), USA 2010 (tfr null) are dropped
    assert frame.select("iso3", "year").rows() == [
        ("JPN", 2000),
        ("QAT", 2010),
        ("TUV", 2010),
        ("USA", 2000),
    ]
    assert frame["ln_gdp"][0] == pytest.approx(math.log(35000.0))
    assert frame["decade"].to_list() == [2000, 2010, 2010, 2000]
    assert frame["tfr"].null_count() == 0 and frame["ln_gdp"].null_count() == 0


def test_build_regression_frame_sample_filters() -> None:
    by_period = h1.build_regression_frame(panel(), start_year=2005)
    assert by_period["iso3"].to_list() == ["QAT", "TUV"]
    no_small = h1.build_regression_frame(panel(), min_population=1_000_000)
    assert "TUV" not in no_small["iso3"].to_list()
    no_oil = h1.build_regression_frame(panel(), exclude_iso3=h1.OIL_STATES)
    assert "QAT" not in no_oil["iso3"].to_list()


def test_decade_summary_matches_sql_definition() -> None:
    frame = h1.build_regression_frame(panel())
    s = h1.decade_summary(frame)
    assert s["decade"].to_list() == [2000, 2010]
    row2000 = s.filter(pl.col("decade") == 2000).row(0, named=True)
    assert row2000["n"] == 2 and row2000["countries"] == 2
    assert row2000["median_tfr"] == pytest.approx((1.36 + 2.06) / 2)
    assert row2000["median_gdp_pcap_ppp"] == pytest.approx(42500.0)
    assert row2000["corr_log_gdp_tfr"] == pytest.approx(1.0)  # two points, upward


def test_demean_two_way_is_exact_on_balanced_panel() -> None:
    frame = pl.DataFrame(
        {
            "iso3": ["A", "A", "B", "B"],
            "year": [1, 2, 1, 2],
            "x": [1.0, 2.0, 3.0, 4.0],  # x = a_i + g_t exactly -> within deviation is 0
        }
    )
    dm = h1.demean_two_way(frame, ["x"])
    assert dm["x_dm"].to_list() == pytest.approx([0.0, 0.0, 0.0, 0.0])


def test_piecewise_terms_hinge() -> None:
    frame = pl.DataFrame({"ln_gdp": [9.0, 10.0, 11.0]})
    out = h1.piecewise_terms(frame, knot=10.0)
    assert out["ln_gdp_hinge"].to_list() == [0.0, 0.0, 1.0]


def test_turning_point() -> None:
    assert h1.turning_point(-2.0, 0.1) == pytest.approx(10.0)
    assert h1.turning_point(-2.0, 0.0) is None


def test_high_income_rules() -> None:
    frame = h1.build_regression_frame(panel())
    assert set(h1.high_income(frame, "gdp20k")["iso3"]) == {"JPN", "USA", "QAT"}
    assert set(h1.high_income(frame, "wb_group")["iso3"]) == {"JPN", "USA", "QAT"}
    assert set(h1.high_income(frame, "gdp30k")["iso3"]) == {"JPN", "USA", "QAT"}


def test_in_sample_split_separates_present_and_absent_codes() -> None:
    frame = h1.build_regression_frame(panel())  # QAT present; VEN absent
    present, absent = h1.in_sample_split(frame, {"VEN", "QAT"})
    assert present == ["QAT"] and absent == ["VEN"]


def test_small_country_breakdown_counts_fully_and_partially_dropped() -> None:
    frame = pl.DataFrame(
        {
            "iso3": ["A", "A", "B", "B", "C", "C", "D"],
            "population": [5e5, 6e5, 9e5, 1.2e6, 2e6, 3e6, None],
        }
    )
    out = h1.small_country_breakdown(frame, 1_000_000)
    assert out == {"fully_dropped": 1, "partially_dropped": 1}
