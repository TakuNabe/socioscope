from pathlib import Path

import pytest

from theme_wealth_population_distribution import oecd

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(indicator: str) -> bytes:
    return (FIXTURES / f"oecd_{indicator}_sample.csv").read_bytes()


def test_data_url_follows_sdmx_rest_layout() -> None:
    ind = oecd.INDICATORS["top_pit_rate"]
    assert oecd.data_url(ind) == (
        "https://sdmx.oecd.org/public/rest/data/"
        "OECD.CTP.TPS,DSD_TAX_PIT@DF_PIT_TOP_EARN_THRESH,1.0/"
        ".A._Z.TS_PIT.PT_WG_EARN_G.S13._Z._Z._Z._Z._Z._Z?format=csvfilewithlabels"
    )
    assert oecd.data_url(oecd.INDICATORS["tax_revenue_gdp"]).endswith(
        "DSD_REV_COMP_OECD@DF_RSOECD,2.0/.TAX_REV.S13._T._T.PT_B1GQ.A?format=csvfilewithlabels"
    )


def test_oecd_members_are_38_iso3_codes() -> None:
    assert len(oecd.OECD_MEMBERS) == 38
    assert all(len(c) == 3 and c.isupper() for c in oecd.OECD_MEMBERS)
    assert {"JPN", "USA", "CRI", "COL"} <= set(oecd.OECD_MEMBERS)
    assert not {"CHN", "RUS", "BRA"} & set(oecd.OECD_MEMBERS)


def test_rows_from_csv_keeps_iso3_year_value_unit_source() -> None:
    ind = oecd.INDICATORS["social_expenditure_gdp"]
    rows = oecd.rows_from_csv(fixture("social_expenditure_gdp"), ind)
    assert rows == [
        {
            "iso3": "JPN",
            "year": 1980,
            "value": 9.82,
            "unit": "PT_B1GQ",
            "obs_status": "A",
            "source": "oecd",
        },
        {
            "iso3": "JPN",
            "year": 2000,
            "value": 14.916,
            "unit": "PT_B1GQ",
            "obs_status": "A",
            "source": "oecd",
        },
        {
            "iso3": "JPN",
            "year": 2022,
            "value": 24.736,
            "unit": "PT_B1GQ",
            "obs_status": "A",
            "source": "oecd",
        },
    ]


def test_rows_from_csv_drops_empty_obs_value_rows() -> None:
    ind = oecd.INDICATORS["tax_revenue_gdp"]
    rows = oecd.rows_from_csv(fixture("tax_revenue_gdp"), ind)
    assert [r["year"] for r in rows] == [1980, 2000, 2022]  # 2024 has no OBS_VALUE
    assert rows[0]["value"] == pytest.approx(24.031693)


@pytest.mark.parametrize("indicator", sorted(oecd.INDICATORS))
def test_every_indicator_fixture_parses(indicator: str) -> None:
    rows = oecd.rows_from_csv(fixture(indicator), oecd.INDICATORS[indicator])
    assert rows and all(r["iso3"] == "JPN" for r in rows)


def test_rows_from_csv_fails_closed_on_other_dataflow() -> None:
    # SOCX lacks the PIT dimensions -> header check; same header, other flow -> STRUCTURE_ID
    with pytest.raises(ValueError, match="header"):
        oecd.rows_from_csv(fixture("social_expenditure_gdp"), oecd.INDICATORS["top_pit_rate"])
    other = fixture("tax_revenue_gdp").replace(b"DF_RSOECD(2.0)", b"DF_RSOECD(9.9)")
    with pytest.raises(ValueError, match="STRUCTURE_ID"):
        oecd.rows_from_csv(other, oecd.INDICATORS["tax_revenue_gdp"])


def test_rows_from_csv_fails_closed_when_a_dimension_does_not_match_the_key() -> None:
    # same dataflow (Revenue Statistics), different STANDARD_REVENUE code
    with pytest.raises(ValueError, match="STANDARD_REVENUE"):
        oecd.rows_from_csv(fixture("tax_revenue_gdp"), oecd.INDICATORS["inheritance_tax_rev_gdp"])


def test_rows_from_csv_fails_closed_on_missing_columns() -> None:
    with pytest.raises(ValueError, match="header"):
        oecd.rows_from_csv(b"REF_AREA,TIME_PERIOD\nJPN,2000\n", oecd.INDICATORS["top_pit_rate"])


def test_rows_from_csv_drops_non_member_and_aggregate_areas() -> None:
    payload = fixture("top_pit_rate").decode("utf-8")
    payload = payload.replace("JPN,Japan", "OECD,OECD", 1).replace("JPN,Japan", "BGR,Bulgaria", 1)
    rows = oecd.rows_from_csv(payload.encode("utf-8"), oecd.INDICATORS["top_pit_rate"])
    assert [(r["iso3"], r["year"]) for r in rows] == [("JPN", 2022)]
