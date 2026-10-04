"""World Bank WDI v2 API: URL builder and deterministic JSON -> rows conversion (no I/O)."""

import json

from pydantic import BaseModel, ConfigDict

BASE = "https://api.worldbank.org/v2"
LICENSE = "CC BY 4.0 (https://datacatalog.worldbank.org/public-licenses)"
SOURCE = "worldbank_wdi"

INDICATORS: dict[str, str] = {
    "tfr": "SP.DYN.TFRT.IN",  # Fertility rate, total (births per woman)
    "gdp_pcap_ppp": "NY.GDP.PCAP.PP.KD",  # GDP per capita, PPP (constant intl $)
    "gdp_growth": "NY.GDP.MKTP.KD.ZG",  # GDP growth (annual %)
}


def indicator_url(indicator_code: str, *, per_page: int = 20000) -> str:
    return f"{BASE}/country/all/indicator/{indicator_code}?format=json&per_page={per_page}"


class _Ref(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    value: str


class _Point(BaseModel):
    model_config = ConfigDict(extra="ignore")
    indicator: _Ref
    country: _Ref
    countryiso3code: str
    date: str
    value: float | None


class WorldBankPage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    page: int
    pages: int
    total: int


def parse_response(payload: bytes) -> tuple[WorldBankPage, list[_Point]]:
    """World Bank returns a 2-element array: [meta, data]. Validate both; fail closed."""
    doc = json.loads(payload)
    if not (isinstance(doc, list) and len(doc) == 2):
        msg = "unexpected World Bank response shape"
        raise ValueError(msg)
    meta = WorldBankPage.model_validate(doc[0])
    points = [_Point.model_validate(p) for p in (doc[1] or [])]
    return meta, points


def rows_from_response(payload: bytes, *, key: str) -> list[dict[str, object]]:
    """Country-level rows only (aggregates like 'World' have an empty iso3 in this endpoint)."""
    _, points = parse_response(payload)
    rows: list[dict[str, object]] = []
    for p in points:
        iso3 = p.countryiso3code.strip()
        if len(iso3) != 3 or not p.date.isdigit():
            continue
        rows.append(
            {
                "iso3": iso3,
                "country": p.country.value,
                "year": int(p.date),
                "value": p.value,
                "indicator": p.indicator.id,
                "source": SOURCE,
            }
        )
    rows.sort(key=lambda r: (str(r["iso3"]), int(str(r["year"]))))
    _ = key
    return rows
