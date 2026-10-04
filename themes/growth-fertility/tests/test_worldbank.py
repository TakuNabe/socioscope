from pathlib import Path

import pytest

from theme_growth_fertility import worldbank as wb

FIXTURE = (Path(__file__).parent / "fixtures" / "tfr_page.json").read_bytes()


def test_rows_keep_countries_drop_aggregates_and_sort() -> None:
    rows = wb.rows_from_response(FIXTURE, key="tfr")
    assert [(r["iso3"], r["year"], r["value"]) for r in rows] == [
        ("JPN", 2000, 1.36),
        ("JPN", 2001, 1.33),
        ("USA", 2000, None),
    ]
    assert rows[0]["source"] == "worldbank_wdi" and rows[0]["indicator"] == "SP.DYN.TFRT.IN"


def test_conversion_is_deterministic() -> None:
    assert wb.rows_from_response(FIXTURE, key="tfr") == wb.rows_from_response(FIXTURE, key="tfr")


def test_malformed_payload_fails_closed() -> None:
    with pytest.raises(ValueError, match="unexpected"):
        wb.rows_from_response(b'{"not": "a list"}', key="tfr")


def test_indicator_url() -> None:
    assert wb.indicator_url("SP.DYN.TFRT.IN") == (
        "https://api.worldbank.org/v2/country/all/indicator/SP.DYN.TFRT.IN?format=json&per_page=20000"
    )
