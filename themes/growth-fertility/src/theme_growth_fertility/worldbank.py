"""World Bank WDI v2 API: URL builders and deterministic JSON -> rows conversion (no I/O)."""

import json
from collections.abc import Collection

from pydantic import BaseModel, ConfigDict

BASE = "https://api.worldbank.org/v2"
LICENSE = "CC BY 4.0 (https://datacatalog.worldbank.org/public-licenses)"
SOURCE = "worldbank_wdi"
COUNTRIES_KEY = "countries"
AGGREGATE_REGION_ID = "NA"  # region.id of World Bank aggregates (World, income groups, regions)

INDICATORS: dict[str, str] = {
    "tfr": "SP.DYN.TFRT.IN",  # Fertility rate, total (births per woman)
    "gdp_pcap_ppp": "NY.GDP.PCAP.PP.KD",  # GDP per capita, PPP (constant intl $)
    "gdp_growth": "NY.GDP.MKTP.KD.ZG",  # GDP growth (annual %)
    "population": "SP.POP.TOTL",  # Population, total (sample filters only)
}


def indicator_url(indicator_code: str, *, per_page: int = 20000) -> str:
    return f"{BASE}/country/all/indicator/{indicator_code}?format=json&per_page={per_page}"


def countries_url(*, per_page: int = 400) -> str:
    return f"{BASE}/country?format=json&per_page={per_page}"


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


class _Country(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    name: str
    region: _Ref
    incomeLevel: _Ref  # noqa: N815  (World Bank field name)


class WorldBankPage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    page: int
    pages: int
    total: int


def is_json_list_payload(payload: bytes) -> bool:
    """True when the body parses as a JSON array (the WB API's [meta, data] shape).

    HTML error pages and JSON error objects ({"message": ...}) are rejected so the fetch
    never stores them as raw (fail closed)."""
    try:
        return isinstance(json.loads(payload), list)
    except ValueError:
        return False


def _split(payload: bytes) -> tuple[WorldBankPage, list[object]]:
    """World Bank returns a 2-element array: [meta, data]. Validate; fail closed on pagination."""
    doc = json.loads(payload)
    if not (isinstance(doc, list) and len(doc) == 2):
        msg = "unexpected World Bank response shape"
        raise ValueError(msg)
    meta = WorldBankPage.model_validate(doc[0])
    data: list[object] = list(doc[1] or [])
    if meta.pages != 1 or meta.total != len(data):
        msg = (
            f"paginated/truncated World Bank response: pages={meta.pages} "
            f"total={meta.total} rows={len(data)}; raise per_page"
        )
        raise ValueError(msg)
    return meta, data


def parse_response(payload: bytes) -> tuple[WorldBankPage, list[_Point]]:
    meta, data = _split(payload)
    return meta, [_Point.model_validate(p) for p in data]


def country_rows(payload: bytes) -> list[dict[str, object]]:
    """Economy-level metadata rows (aggregates excluded), sorted by iso3."""
    _, data = _split(payload)
    rows: list[dict[str, object]] = []
    for c in (_Country.model_validate(x) for x in data):
        if c.region.id == AGGREGATE_REGION_ID:
            continue
        rows.append(
            {
                "iso3": c.id,
                "country": c.name,
                "region": c.region.value.strip(),
                "income_group": c.incomeLevel.value.strip(),
                "source": SOURCE,
            }
        )
    rows.sort(key=lambda r: str(r["iso3"]))
    return rows


def country_set(payload: bytes) -> frozenset[str]:
    return frozenset(str(r["iso3"]) for r in country_rows(payload))


def rows_from_response(
    payload: bytes, *, key: str, countries: Collection[str] | None = None
) -> list[dict[str, object]]:
    """Long rows for one indicator.

    Aggregates such as 'World' have an empty iso3 and are always dropped. Aggregates with a
    3-letter code (e.g. 'NAC' North America, 'WLD') are dropped only when *countries* (from
    ``country_set``) is given, which is what the pipeline does.
    """
    _, points = parse_response(payload)
    rows: list[dict[str, object]] = []
    for p in points:
        iso3 = p.countryiso3code.strip()
        if len(iso3) != 3 or not p.date.isdigit():
            continue
        if countries is not None and iso3 not in countries:
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
