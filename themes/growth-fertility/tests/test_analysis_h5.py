import math

import polars as pl
import pytest

from theme_growth_fertility.analysis import a20261006_h5_europe_korea_policy as h5


def spend_long() -> pl.DataFrame:
    rows = []
    for iso3, years in (("FIN", [2007, 2010, 2021]), ("KOR", [2010, 2021])):
        for y in years:
            for st, v in (("_T", 3.0), ("C", 1.5), ("K", 1.5)):
                rows.append(
                    {"iso3": iso3, "year": y, "spending_type": st, "value": v + (y - 2010) / 100}
                )
    rows.append({"iso3": "FIN", "year": 2021, "spending_type": "ES_OTHER", "value": 9.9})
    return pl.DataFrame(rows)


def panel() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "iso3": ["FIN", "FIN", "FIN", "KOR", "KOR", "USA"],
            "country": ["Finland"] * 3 + ["Korea"] * 2 + ["United States"],
            "year": [2007, 2010, 2021, 2010, 2021, 2010],
            "tfr": [1.83, 1.87, 1.46, 1.23, 0.81, 1.93],
            "population": [5.3e6, 5.4e6, 5.5e6, 4.9e7, 5.2e7, 3.1e8],
        }
    )


def test_spending_wide_pivots_and_ignores_other_types() -> None:
    wide = h5.spending_wide(spend_long())
    assert wide.columns == ["iso3", "year", "family_total", "cash", "inkind"]
    row = wide.filter((pl.col("iso3") == "FIN") & (pl.col("year") == 2021)).row(0, named=True)
    assert row["family_total"] == pytest.approx(3.11) and row["cash"] == pytest.approx(1.61)


def test_policy_frame_inner_joins_and_add_lag_requires_the_lagged_row() -> None:
    frame = h5.policy_frame(panel(), spend_long())
    assert frame.select("iso3", "year").rows() == [
        ("FIN", 2007),
        ("FIN", 2010),
        ("FIN", 2021),
        ("KOR", 2010),
        ("KOR", 2021),
    ]
    lagged = h5.add_lag(frame, ["family_total"])
    by = dict(
        zip(
            zip(lagged["iso3"], lagged["year"], strict=True), lagged["family_total_l3"], strict=True
        )
    )
    assert by[("FIN", 2010)] == pytest.approx(2.97)  # 2007 exists
    assert by[("FIN", 2021)] is None and by[("KOR", 2021)] is None  # no 2018 row: not interpolated


def test_delta_frame_and_explained_share() -> None:
    d = h5.delta_frame(h5.policy_frame(panel(), spend_long()), 2010, 2021)
    assert d["iso3"].to_list() == ["FIN", "KOR"]
    fin = d.filter(pl.col("iso3") == "FIN").row(0, named=True)
    assert fin["d_tfr"] == pytest.approx(-0.41) and fin["d_spend"] == pytest.approx(0.11)
    assert h5.explained_share(0.1, 0.11, -0.41) == pytest.approx(-0.0268, abs=1e-3)
    assert h5.explained_share(0.1, 0.11, 0.0) is None


def test_verdict_a3_uses_nordic_four_only() -> None:
    base = {"FIN": 0.1, "SWE": 0.2, "NOR": 0.05, "DNK": 0.0, "KOR": 0.9}
    assert h5.verdict_a3(base).startswith("consistent")
    assert h5.verdict_a3({**base, "SWE": 0.3}) == "partial"
    assert h5.verdict_a3({**base, "SWE": 0.6}).startswith("not supported")
    assert h5.verdict_a3({**base, "SWE": None}).startswith("undetermined")


def census_cells(slope: float) -> pl.DataFrame:
    rows = []
    for a, base in ((25, 0.2), (30, 0.4), (35, 0.6)):
        for grp, r in h5.EDU_RANK.items():
            rows.append(
                {
                    "age_class": f"Y{a}-{a + 4}",
                    "age_lower": a,
                    "isced_group": grp,
                    "married_share": base + slope * r,
                    "total": 1000.0,
                }
            )
    rows.append(
        {
            "age_class": "Y25-29",
            "age_lower": 25,
            "isced_group": "UNK",
            "married_share": 0.9,
            "total": 50.0,
        }
    )
    return pl.DataFrame(rows)


def test_census_gradient_recovers_slope_with_age_effects() -> None:
    c = h5.census_gradient(census_cells(0.05))
    assert c.b == pytest.approx(0.05, abs=1e-9)
    c2 = h5.census_gradient(census_cells(-0.02))
    assert c2.b == pytest.approx(-0.02, abs=1e-9)


def test_krw_midpoint_open_top_rule() -> None:
    assert h5.krw_midpoint(1000, 3000) == 2000
    assert h5.krw_midpoint(10000, None) == 15000
    assert h5.krw_midpoint(None, 1000) is None


def test_order_decomposition_uses_latest_complete_year_and_excludes_unknown() -> None:
    rows = []
    for year, vals in (
        (2010, (0.9, 0.6, 0.2, 0.1)),
        (2020, (0.6, 0.5, 0.2, 0.1)),
        (2023, (0.5, 0.5, 0.15, 0.1)),
    ):
        for o, v in zip(("1", "2", "3", "GE4"), vals, strict=True):
            rows.append({"iso3": "FIN", "year": year, "order": o, "tfr": v})
        rows.append({"iso3": "FIN", "year": year, "order": "UNK", "tfr": 0.3})
    rows.append(
        {"iso3": "FIN", "year": 2024, "order": "1", "tfr": 0.4}
    )  # incomplete year -> ignored
    orders = pl.DataFrame(rows)
    r = h5.order_decomposition(orders, "FIN", 2010)
    assert r is not None and r["end_year"] == 2023
    assert r["d_known"] == pytest.approx(-0.55) and r["first_share"] == pytest.approx(0.4 / 0.55)
    assert h5.order_decomposition(orders, "FIN", 2010, 2020)["d_1"] == pytest.approx(-0.3)
    assert h5.order_decomposition(orders, "SWE", 2010) is None


def test_education_change_drops_small_cells_and_needs_three_groups() -> None:
    rows = []
    for year in (2010, 2023):
        for grp, v in (("ED0-2", 1.5), ("ED3-4", 1.8), ("ED5-8", 1.9)):
            rows.append(
                {
                    "iso3": "FIN",
                    "year": year,
                    "isced_group": grp,
                    "tfr": v - (0.3 if year == 2023 else 0),
                    "women_total_thousand": 100.0,
                }
            )
    rows.append(
        {
            "iso3": "FIN",
            "year": 2024,
            "isced_group": "ED0-2",
            "tfr": 1.0,
            "women_total_thousand": 100.0,
        }
    )
    rows.append(
        {
            "iso3": "FIN",
            "year": 2024,
            "isced_group": "ED3-4",
            "tfr": 1.0,
            "women_total_thousand": 10.0,
        }
    )  # too small
    ch = h5.education_change(pl.DataFrame(rows), "FIN", 2010)
    assert ch["end"].to_list() == [2023] * 3 and ch["change"].to_list() == pytest.approx([-0.3] * 3)
    assert h5.education_change(pl.DataFrame(rows), "SWE", 2010).height == 0


def test_helpers_are_pure_on_nan_free_inputs() -> None:
    assert not math.isnan(h5.explained_share(0.0, 1.0, -1.0) or 0.0)
