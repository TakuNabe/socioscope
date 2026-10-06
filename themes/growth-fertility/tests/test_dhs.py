import json
from pathlib import Path

import pytest

from theme_growth_fertility import dhs

FIXTURES = Path(__file__).parent / "fixtures"
DATA = (FIXTURES / "dhs_tfr_wealth_page.json").read_bytes()
COUNTRIES = (FIXTURES / "dhs_countries_page.json").read_bytes()


def test_urls_request_single_page_json_for_tfr_by_wealth_quintile() -> None:
    url = dhs.data_url()
    assert url.startswith("https://api.dhsprogram.com/rest/dhs/data?")
    assert "indicatorIds=FE_FRTR_W_TFR" in url
    assert "characteristicCategory=Wealth%20quintile" in url
    assert "breakdown=all" in url and "perpage=5000" in url and "f=json" in url
    assert "perpage=10" in dhs.data_url(per_page=10)
    assert dhs.countries_url() == "https://api.dhsprogram.com/rest/dhs/countries?f=json&perpage=300"
    assert "perpage=5" in dhs.countries_url(per_page=5)


def test_license_states_citation_requirement_and_source_name() -> None:
    assert dhs.SOURCE == "dhs_api"
    assert "The DHS Program Indicator Data API" in dhs.LICENSE
    assert "api.dhsprogram.com" in dhs.LICENSE


def test_iso3_map_drops_codes_without_iso3() -> None:
    assert dhs.iso3_map(COUNTRIES) == {"AF": "AFG", "AL": "ALB", "KE": "KEN"}


def test_rows_from_response_maps_quintiles_and_drops_other_breakdowns() -> None:
    rows = dhs.rows_from_response(DATA, iso3_by_dhs_code=dhs.iso3_map(COUNTRIES))
    # AF2015DHS x 5 quintiles + AL2008DHS x 2; the "Residence" row and the unmapped "OS" row drop
    assert len(rows) == 7
    assert rows[0] == {
        "iso3": "ALB",
        "country": "Albania",
        "dhs_country_code": "AL",
        "survey_id": "AL2008DHS",
        "survey_year": 2008,
        "survey_type": "DHS",
        "quintile": 1,
        "quintile_label": "Lowest",
        "value": 1.9,
        "ci_low": None,
        "ci_high": None,
        "denominator_weighted": None,
        "source": "dhs_api",
    }
    af = [r for r in rows if r["survey_id"] == "AF2015DHS"]
    assert [(r["quintile"], r["quintile_label"], r["value"]) for r in af] == [
        (1, "Lowest", 5.3),
        (2, "Second", 5.4),
        (3, "Middle", 5.8),
        (4, "Fourth", 5.3),
        (5, "Highest", 4.6),
    ]
    assert all(isinstance(r["value"], float) for r in rows)
    # sorted by survey_year, iso3, survey_id, quintile
    assert [(r["survey_year"], r["iso3"], r["quintile"]) for r in rows] == sorted(
        (r["survey_year"], r["iso3"], r["quintile"]) for r in rows
    )


def test_rows_from_response_drops_unknown_quintile_label_and_other_indicator() -> None:
    doc = json.loads(DATA)
    base = doc["Data"][0]
    doc["Data"] = [
        base,
        {**base, "DataId": 1, "CharacteristicLabel": "Richest"},
        {**base, "DataId": 2, "IndicatorId": "FE_FRTR_W_GFR"},
    ]
    doc["RecordCount"] = doc["RecordsReturned"] = 3
    rows = dhs.rows_from_response(json.dumps(doc).encode(), iso3_by_dhs_code={"AF": "AFG"})
    assert [(r["survey_id"], r["quintile"]) for r in rows] == [("AF2015DHS", 1)]


def test_numeric_strings_in_ci_and_denominator_are_parsed() -> None:
    doc = json.loads(DATA)
    base = doc["Data"][0]
    doc["Data"] = [
        {**base, "CILow": "5.1", "CIHigh": "5.5", "DenominatorWeighted": "1234", "Value": 5}
    ]
    doc["RecordCount"] = doc["RecordsReturned"] = 1
    (row,) = dhs.rows_from_response(json.dumps(doc).encode(), iso3_by_dhs_code={"AF": "AFG"})
    assert (row["value"], row["ci_low"], row["ci_high"], row["denominator_weighted"]) == (
        5.0,
        5.1,
        5.5,
        1234.0,
    )


def test_unmapped_codes_lists_wealth_quintile_rows_without_iso3() -> None:
    assert dhs.unmapped_codes(DATA, iso3_by_dhs_code=dhs.iso3_map(COUNTRIES)) == ["OS"]
    assert dhs.unmapped_codes(DATA, iso3_by_dhs_code={}) == ["AF", "AL", "OS"]


@pytest.mark.parametrize(
    "patch",
    [{"TotalPages": 2}, {"RecordCount": 99}],
    ids=["paginated", "truncated"],
)
def test_pagination_or_truncation_fails_closed(patch: dict[str, int]) -> None:
    doc = {**json.loads(DATA), **patch}
    with pytest.raises(ValueError, match="DHS"):
        dhs.rows_from_response(json.dumps(doc).encode(), iso3_by_dhs_code={})
    with pytest.raises(ValueError, match="DHS"):
        dhs.iso3_map(json.dumps({**json.loads(COUNTRIES), **patch}).encode())


def test_non_object_payload_is_rejected() -> None:
    with pytest.raises(ValueError, match="DHS"):
        dhs.rows_from_response(b"[]", iso3_by_dhs_code={})
    with pytest.raises(ValueError, match="DHS"):
        dhs.iso3_map(b"<html>maintenance</html>")
