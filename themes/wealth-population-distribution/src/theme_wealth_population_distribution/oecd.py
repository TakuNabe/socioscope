"""OECD Data Explorer (SDMX REST): URL builders and deterministic CSV -> rows conversion (no I/O).

Endpoint: https://sdmx.oecd.org/public/rest/data/<agency>,<dataflow>,<version>/<key>
?format=csvfilewithlabels (no API key). The CSV carries one column per dimension (code) followed
by its label column, then TIME_PERIOD / OBS_VALUE / OBS_STATUS. The key is "." separated in
dataflow dimension order, with an empty slot for REF_AREA (= all countries).

Dataflows verified on 2026-10-04 by fetching a slice (see design/data-sources.md):
  OECD.CTP.TPS,DSD_TAX_PIT@DF_PIT_TOP_EARN_THRESH,1.0  top statutory PIT rate (2000-)
  OECD.ELS.SPD,DSD_SOCX_AGG@DF_SOCX_AGG,1.0            public social expenditure % GDP (1980-)
  OECD.CTP.TPS,DSD_REV_COMP_OECD@DF_RSOECD,2.0         tax revenue % GDP by category (1965-)
"""

import csv
import io
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, field_validator

BASE = "https://sdmx.oecd.org/public/rest/data"
SOURCE = "oecd"
LICENSE = (
    "OECD Terms & Conditions (last updated 2024-07-01, checked 2026-10-04): data may be used, "
    "adapted and redistributed for any purpose with attribution (CC BY 4.0 for OECD content "
    "published since 2024-07-01); https://www.oecd.org/en/about/terms-conditions.html"
)

# The 38 OECD members (ISO 3166-1 alpha-3). Aggregates (OECD, EU27...) and non-member
# countries that appear in some dataflows (BGR, HRV, PER, ROU...) are dropped at stage.
OECD_MEMBERS: tuple[str, ...] = (
    "AUS", "AUT", "BEL", "CAN", "CHE", "CHL", "COL", "CRI", "CZE", "DEU", "DNK", "ESP", "EST",
    "FIN", "FRA", "GBR", "GRC", "HUN", "IRL", "ISL", "ISR", "ITA", "JPN", "KOR", "LTU", "LUX",
    "LVA", "MEX", "NLD", "NOR", "NZL", "POL", "PRT", "SVK", "SVN", "SWE", "TUR", "USA",
)  # fmt: skip


@dataclass(frozen=True)
class Indicator:
    """One staged series = one dataflow + one fully specified key (REF_AREA left open)."""

    name: str
    agency: str
    dataflow: str
    version: str
    # dimension id -> code, in dataflow dimension order, REF_AREA excluded
    key: tuple[tuple[str, str], ...]
    unit: str
    description: str

    @property
    def flow_ref(self) -> str:
        return f"{self.agency},{self.dataflow},{self.version}"

    @property
    def structure_id(self) -> str:
        """STRUCTURE_ID column value in csvfilewithlabels output."""
        return f"{self.agency}:{self.dataflow}({self.version})"

    def key_string(self) -> str:
        return "." + ".".join(code for _, code in self.key)


_PIT_KEY = (
    ("FREQ", "A"),
    ("TRANSACTION", "_Z"),
    ("MEASURE", "TS_PIT"),
    ("UNIT_MEASURE", "PT_WG_EARN_G"),
    ("SECTOR", "S13"),
    ("CIVIL_STATUS", "_Z"),
    ("HOUSEHOLD_TYPE", "_Z"),
    ("INCOME_PRINCIPAL", "_Z"),
    ("INCOME_SPOUSE", "_Z"),
    ("LEVEL", "_Z"),
    ("TAX_BASE", "_Z"),
)
_SOCX_KEY = (
    ("FREQ", "A"),
    ("MEASURE", "SOCX"),
    ("UNIT_MEASURE", "PT_B1GQ"),
    ("EXPEND_SOURCE", "ES10"),  # public
    ("SPENDING_TYPE", "_T"),
    ("PROGRAMME_TYPE", "_T"),
    ("PRICE_BASE", "_Z"),
)


def _rev_key(standard_revenue: str) -> tuple[tuple[str, str], ...]:
    return (
        ("MEASURE", "TAX_REV"),
        ("SECTOR", "S13"),  # general government
        ("STANDARD_REVENUE", standard_revenue),
        ("CTRY_SPECIFIC_REVENUE", "_T"),
        ("UNIT_MEASURE", "PT_B1GQ"),
        ("FREQ", "A"),
    )


INDICATORS: dict[str, Indicator] = {
    "top_pit_rate": Indicator(
        name="top_pit_rate",
        agency="OECD.CTP.TPS",
        dataflow="DSD_TAX_PIT@DF_PIT_TOP_EARN_THRESH",
        version="1.0",
        key=_PIT_KEY,
        unit="PT_WG_EARN_G",
        description="Top statutory personal income tax rate, combined central + sub-central, "
        "% of gross wage earnings (OECD Tax Database Table I.7)",
    ),
    "social_expenditure_gdp": Indicator(
        name="social_expenditure_gdp",
        agency="OECD.ELS.SPD",
        dataflow="DSD_SOCX_AGG@DF_SOCX_AGG",
        version="1.0",
        key=_SOCX_KEY,
        unit="PT_B1GQ",
        description="Public social expenditure, total (cash + in kind), % of GDP (SOCX)",
    ),
    "tax_revenue_gdp": Indicator(
        name="tax_revenue_gdp",
        agency="OECD.CTP.TPS",
        dataflow="DSD_REV_COMP_OECD@DF_RSOECD",
        version="2.0",
        key=_rev_key("_T"),
        unit="PT_B1GQ",
        description="Total tax revenue, general government, % of GDP (Revenue Statistics)",
    ),
    "inheritance_tax_rev_gdp": Indicator(
        name="inheritance_tax_rev_gdp",
        agency="OECD.CTP.TPS",
        dataflow="DSD_REV_COMP_OECD@DF_RSOECD",
        version="2.0",
        key=_rev_key("T_4300"),
        unit="PT_B1GQ",
        description="Estate, inheritance and gift taxes (4300), general government, % of GDP "
        "(Revenue Statistics) - revenue-based proxy for inheritance taxation",
    ),
}

REQUIRED_COLUMNS = ("STRUCTURE_ID", "REF_AREA", "TIME_PERIOD", "OBS_VALUE", "OBS_STATUS")


def data_url(ind: Indicator) -> str:
    return f"{BASE}/{ind.flow_ref}/{ind.key_string()}?format=csvfilewithlabels"


def raw_name(ind: Indicator) -> str:
    return f"{ind.name}.csv"


class _Line(BaseModel):
    model_config = ConfigDict(extra="ignore")
    STRUCTURE_ID: str
    REF_AREA: str
    TIME_PERIOD: int
    OBS_VALUE: float | None
    OBS_STATUS: str

    @field_validator("OBS_VALUE", mode="before")
    @classmethod
    def _blank_is_missing(cls, v: object) -> object:
        return None if v == "" else v


def rows_from_csv(payload: bytes, ind: Indicator) -> list[dict[str, object]]:
    """iso3 × year rows for one indicator. Fail closed on another dataflow / key / header.

    Rows with empty OBS_VALUE (OBS_STATUS M/L...) are dropped, never imputed. Only the 38 OECD
    members are kept. Sorted by (iso3, year).
    """
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
    fields = set(reader.fieldnames or ())
    missing = [c for c in (*REQUIRED_COLUMNS, *(d for d, _ in ind.key)) if c not in fields]
    if missing:
        msg = f"unexpected OECD header for {ind.name}: missing {missing}"
        raise ValueError(msg)
    out: list[dict[str, object]] = []
    for raw in reader:
        if None in raw or any(v is None for v in raw.values()):
            msg = f"ragged OECD row: {raw}"
            raise ValueError(msg)
        line = _Line.model_validate(raw)
        if ind.structure_id != line.STRUCTURE_ID:
            msg = f"{ind.name}: STRUCTURE_ID {line.STRUCTURE_ID!r}, expected {ind.structure_id!r}"
            raise ValueError(msg)
        for dim, code in ind.key:
            if raw[dim] != code:
                msg = f"{ind.name}: dimension {dim}={raw[dim]!r}, expected {code!r}"
                raise ValueError(msg)
        if line.OBS_VALUE is None or line.REF_AREA not in OECD_MEMBERS:
            continue
        out.append(
            {
                "iso3": line.REF_AREA,
                "year": line.TIME_PERIOD,
                "value": line.OBS_VALUE,
                "unit": ind.unit,
                "obs_status": line.OBS_STATUS,
                "source": SOURCE,
            }
        )
    out.sort(key=lambda r: (str(r["iso3"]), int(str(r["year"]))))
    return out
