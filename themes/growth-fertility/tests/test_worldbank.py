from pathlib import Path

import pytest

from theme_growth_fertility import worldbank as wb

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE = (FIXTURES / "tfr_page.json").read_bytes()
COUNTRIES = (FIXTURES / "countries_page.json").read_bytes()


def test_rows_keep_countries_drop_aggregates_and_sort() -> None:
    rows = wb.rows_from_response(FIXTURE, key="tfr", countries=wb.country_set(COUNTRIES))
    assert [(r["iso3"], r["year"], r["value"]) for r in rows] == [
        ("JPN", 2000, 1.36),
        ("JPN", 2001, 1.33),
        ("USA", 2000, None),
    ]
    assert rows[0]["source"] == "worldbank_wdi" and rows[0]["indicator"] == "SP.DYN.TFRT.IN"


def test_rows_without_country_set_keep_three_letter_aggregates() -> None:
    # Without metadata only the empty-iso3 aggregates ('World') can be dropped; NAC survives.
    rows = wb.rows_from_response(FIXTURE, key="tfr")
    assert [r["iso3"] for r in rows] == ["JPN", "JPN", "NAC", "USA"]


def test_country_set_excludes_region_na_aggregates() -> None:
    assert wb.country_set(COUNTRIES) == frozenset({"JPN", "USA"})


def test_country_rows_carry_region_and_income_group() -> None:
    rows = wb.country_rows(COUNTRIES)
    assert rows == [
        {
            "iso3": "JPN",
            "country": "Japan",
            "region": "East Asia & Pacific",
            "income_group": "High income",
            "source": "worldbank_wdi",
        },
        {
            "iso3": "USA",
            "country": "United States",
            "region": "North America",
            "income_group": "High income",
            "source": "worldbank_wdi",
        },
    ]


def test_conversion_is_deterministic() -> None:
    assert wb.rows_from_response(FIXTURE, key="tfr") == wb.rows_from_response(FIXTURE, key="tfr")


def test_malformed_payload_fails_closed() -> None:
    with pytest.raises(ValueError, match="unexpected"):
        wb.rows_from_response(b'{"not": "a list"}', key="tfr")
    with pytest.raises(ValueError, match="unexpected"):
        wb.country_set(b"[]")


def test_paginated_response_fails_closed() -> None:
    truncated = FIXTURE.replace(b'"pages":1', b'"pages":2')
    with pytest.raises(ValueError, match="paginated"):
        wb.rows_from_response(truncated, key="tfr")


def test_urls() -> None:
    assert wb.indicator_url("SP.DYN.TFRT.IN") == (
        "https://api.worldbank.org/v2/country/all/indicator/SP.DYN.TFRT.IN?format=json&per_page=20000"
    )
    assert wb.countries_url() == "https://api.worldbank.org/v2/country?format=json&per_page=400"
