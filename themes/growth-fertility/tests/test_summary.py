import math

import polars as pl
import pytest

from theme_growth_fertility.analysis import s20261005_summary as s


def _panel() -> pl.DataFrame:
    rows = []
    for iso3, tfr0, gdp0 in (("JPN", 2.0, 30_000.0), ("NGA", 6.5, 2_000.0), ("USA", 3.6, 40_000.0)):
        for i, year in enumerate(range(1960, 1965)):
            gdp = None if year < 1962 else gdp0 * (1 + 0.01 * i)
            rows.append(
                {
                    "iso3": iso3,
                    "country": iso3,
                    "year": year,
                    "region": "r",
                    "income_group": "g",
                    "tfr": tfr0 - 0.1 * i,
                    "gdp_pcap_ppp": gdp,
                    "gdp_growth": 1.0,
                    "population": 1e8,
                }
            )
    # one TFR gap for NGA
    rows.append(
        {
            "iso3": "NGA",
            "country": "NGA",
            "year": 1965,
            "region": "r",
            "income_group": "g",
            "tfr": None,
            "gdp_pcap_ppp": 2_500.0,
            "gdp_growth": 1.0,
            "population": 1e8,
        }
    )
    return pl.DataFrame(rows)


def test_choose_font_prefers_first_available_in_order() -> None:
    available = {"DejaVu Sans", "Noto Sans CJK JP", "Hiragino Sans"}
    assert s.choose_font(available, ["Hiragino Sans", "Noto Sans CJK JP"]) == "Hiragino Sans"
    assert s.choose_font(available, ["IPAexGothic", "Noto Sans CJK JP"]) == "Noto Sans CJK JP"
    assert s.choose_font(available, ["IPAexGothic"]) is None


def test_year_slice_keeps_complete_rows_and_flags_japan() -> None:
    sl = s.year_slice(_panel(), 1963)
    assert sl["iso3"].to_list() == ["JPN", "NGA", "USA"]
    assert sl.filter(pl.col("iso3") == "JPN")["is_japan"].to_list() == [True]
    assert sl.filter(pl.col("iso3") == "USA")["is_japan"].to_list() == [False]
    assert math.isclose(sl.filter(pl.col("iso3") == "NGA")["ln_gdp"][0], math.log(2_000.0 * 1.03))
    # 1960 has no GDP -> empty
    assert s.year_slice(_panel(), 1960).height == 0


def test_country_trails_drops_incomplete_rows_and_orders_by_year() -> None:
    tr = s.country_trails(_panel(), ["NGA", "JPN"], start=1960, end=1965)
    assert tr["iso3"].unique(maintain_order=True).to_list() == ["JPN", "NGA"]
    nga = tr.filter(pl.col("iso3") == "NGA")
    assert nga["year"].to_list() == [1962, 1963, 1964]  # 1965 has no TFR, 1960-61 no GDP
    assert nga["year"].is_sorted()


def test_tfr_in_year_returns_requested_countries_in_given_order() -> None:
    out = s.tfr_in_year(_panel(), ["USA", "JPN", "XXX"], 1961)
    assert out == [("USA", 3.5), ("JPN", 1.9)]


def test_japan_series_has_full_tfr_but_gdp_only_where_observed() -> None:
    jp = s.japan_series(_panel())
    assert jp["year"].to_list() == [1960, 1961, 1962, 1963, 1964]
    assert jp["gdp_pcap_ppp"].null_count() == 2


def test_dollar_ticks_cover_the_range_with_round_values() -> None:
    assert s.dollar_ticks(math.log(900), math.log(60_000)) == [
        1_000,
        2_000,
        5_000,
        10_000,
        20_000,
        50_000,
    ]
    assert s.dollar_ticks(math.log(10_000), math.log(10_000)) == [10_000]


def test_wave_curves_returns_one_curve_per_year_sorted_by_income() -> None:
    frame = pl.DataFrame(
        {
            "year": [2024, 2012, 2012, 2024],
            "mid_man": [75.0, 25.0, 75.0, 25.0],
            "value": [0.5, 0.3, 0.4, 0.2],
            "weight": [1.0, 1.0, 1.0, 1.0],
        }
    )
    curves = s.wave_curves(frame)
    assert [c.year for c in curves] == [2012, 2024]
    assert curves[0].x == [25.0, 75.0]
    assert curves[1].y == [0.2, 0.5]


def test_sign_word_uses_ci_not_point_estimate() -> None:
    assert s.sign_word(1.0, 0.5, 1.5) == "正（上向き）"
    assert s.sign_word(-1.0, -1.5, -0.5) == "負（下向き）"
    assert s.sign_word(0.1, -0.1, 0.3) == "ゼロと区別できない"


def test_ladder_items_are_fixed_and_three_rungs() -> None:
    items = s.ladder_items()
    rungs = {i.rung for i in items}
    assert rungs == {0, 1}  # nothing sits on the causal rung
    assert all(0 <= i.rung <= 2 for i in items)
    with pytest.raises(ValueError, match="rung"):
        s.LadderItem("x", "y", 3)
