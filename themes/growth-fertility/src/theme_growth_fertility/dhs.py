"""DHS Program Indicator Data API: URL builders and deterministic JSON -> rows (no I/O).

Indicator ``FE_FRTR_W_TFR`` (total fertility rate 15-49, three years before the survey) broken
down by *Wealth quintile* (asset-based within-country rank, not income), every survey type.
ISO3 comes from ``/rest/dhs/countries`` (``ISO3_CountryCode``); records whose DHS country code
has no ISO3 are dropped and reported via ``unmapped_codes``.
"""

import json

from pydantic import BaseModel, ConfigDict

BASE = "https://api.dhsprogram.com/rest/dhs"
SOURCE = "dhs_api"
# No API key. Terms (api.dhsprogram.com/#/terms.cfm, checked 2026-10-05) require this citation
# wherever the data are used or redistributed:
LICENSE = (
    "DHS Program API terms: citation required - 'The DHS Program Indicator Data API, "
    "The Demographic and Health Surveys (DHS) Program. ICF. Originally funded by the United "
    "States Agency for International Development (USAID). Available from api.dhsprogram.com. "
    "[Accessed 10-05-2026]' (https://api.dhsprogram.com/#/terms.cfm)"
)
INDICATOR = "FE_FRTR_W_TFR"  # Total fertility rate 15-49
CHARACTERISTIC = "Wealth quintile"
QUINTILES: dict[str, int] = {"Lowest": 1, "Second": 2, "Middle": 3, "Fourth": 4, "Highest": 5}


def data_url(*, per_page: int = 5000) -> str:
    return (
        f"{BASE}/data?indicatorIds={INDICATOR}&breakdown=all"
        f"&characteristicCategory={CHARACTERISTIC.replace(' ', '%20')}"
        f"&perpage={per_page}&f=json"
    )


def countries_url(*, per_page: int = 300) -> str:
    return f"{BASE}/countries?f=json&perpage={per_page}"


class _Page(BaseModel):
    model_config = ConfigDict(extra="ignore")
    TotalPages: int
    RecordCount: int
    Data: list[object]


class _Record(BaseModel):
    model_config = ConfigDict(extra="ignore")
    Value: float | None
    DHS_CountryCode: str
    CountryName: str
    SurveyYear: int
    SurveyId: str
    IndicatorId: str
    CharacteristicCategory: str
    CharacteristicLabel: str
    SurveyType: str
    # The API serialises these as strings ("" when absent).
    DenominatorWeighted: float | str | None = None
    CILow: float | str | None = None
    CIHigh: float | str | None = None


class _Country(BaseModel):
    model_config = ConfigDict(extra="ignore")
    DHS_CountryCode: str
    ISO3_CountryCode: str = ""


def _split(payload: bytes) -> list[object]:
    """Validate the envelope; fail closed on pagination/truncation (same policy as worldbank)."""
    try:
        doc = json.loads(payload)
    except ValueError as e:
        msg = f"DHS response is not JSON: {e}"
        raise ValueError(msg) from None
    if not isinstance(doc, dict):
        msg = "unexpected DHS response shape (expected a JSON object)"
        raise ValueError(msg)
    page = _Page.model_validate(doc)
    if page.TotalPages != 1 or page.RecordCount != len(page.Data):
        msg = (
            f"paginated/truncated DHS response: TotalPages={page.TotalPages} "
            f"RecordCount={page.RecordCount} rows={len(page.Data)}; raise per_page"
        )
        raise ValueError(msg)
    return page.Data


def _num(v: float | str | None) -> float | None:
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return None
    return float(v)


def iso3_map(countries_payload: bytes) -> dict[str, str]:
    """DHS_CountryCode -> ISO3 (entries without an ISO3, e.g. sub-national 'OS', are excluded)."""
    out: dict[str, str] = {}
    for c in (_Country.model_validate(x) for x in _split(countries_payload)):
        iso3 = c.ISO3_CountryCode.strip()
        if iso3:
            out[c.DHS_CountryCode] = iso3
    return out


def _wealth_records(payload: bytes) -> list[_Record]:
    recs = (_Record.model_validate(x) for x in _split(payload))
    return [
        r
        for r in recs
        if r.IndicatorId == INDICATOR
        and r.CharacteristicCategory == CHARACTERISTIC
        and r.CharacteristicLabel in QUINTILES
    ]


def rows_from_response(
    payload: bytes, *, iso3_by_dhs_code: dict[str, str]
) -> list[dict[str, object]]:
    """Long rows (one per survey × quintile). Pure; rows without an ISO3 are dropped."""
    rows: list[dict[str, object]] = []
    for r in _wealth_records(payload):
        iso3 = iso3_by_dhs_code.get(r.DHS_CountryCode)
        if iso3 is None:
            continue
        rows.append(
            {
                "iso3": iso3,
                "country": r.CountryName,
                "dhs_country_code": r.DHS_CountryCode,
                "survey_id": r.SurveyId,
                "survey_year": r.SurveyYear,
                "survey_type": r.SurveyType,
                "quintile": QUINTILES[r.CharacteristicLabel],
                "quintile_label": r.CharacteristicLabel,
                "value": _num(r.Value),
                "ci_low": _num(r.CILow),
                "ci_high": _num(r.CIHigh),
                "denominator_weighted": _num(r.DenominatorWeighted),
                "source": SOURCE,
            }
        )
    rows.sort(
        key=lambda r: (
            int(str(r["survey_year"])),
            str(r["iso3"]),
            str(r["survey_id"]),
            int(str(r["quintile"])),
        )
    )
    return rows


def unmapped_codes(payload: bytes, *, iso3_by_dhs_code: dict[str, str]) -> list[str]:
    """DHS country codes of wealth-quintile rows that got no ISO3 (sorted, distinct)."""
    return sorted(
        {
            r.DHS_CountryCode
            for r in _wealth_records(payload)
            if r.DHS_CountryCode not in iso3_by_dhs_code
        }
    )
