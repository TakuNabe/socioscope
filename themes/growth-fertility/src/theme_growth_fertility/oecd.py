"""OECD SOCX family expenditure (SDMX REST): URL builder and deterministic CSV -> rows (no I/O).

Dataflow ``OECD.ELS.SPD,DSD_SOCX_AGG@DF_SOCX_AGG,1.0`` (verified 2026-10-06). Key in dimension
order REF_AREA.FREQ.MEASURE.UNIT_MEASURE.EXPEND_SOURCE.SPENDING_TYPE.PROGRAMME_TYPE.PRICE_BASE,
REF_AREA left empty (= all reference areas). We take public (ES10) family programmes (TP51) as
% of GDP, split by spending type: ``_T`` total, ``C`` cash, ``K`` in kind.
"""

import csv
import io

from pydantic import BaseModel, ConfigDict, field_validator

BASE = "https://sdmx.oecd.org/public/rest/data"
SOURCE = "oecd_socx"
LICENSE = (
    "OECD Terms & Conditions (last updated 2024-07-01, checked 2026-10-04): data may be used, "
    "adapted and redistributed for any purpose with attribution (CC BY 4.0 for OECD content "
    "published since 2024-07-01); https://www.oecd.org/en/about/terms-conditions.html"
)
FLOW_REF = "OECD.ELS.SPD,DSD_SOCX_AGG@DF_SOCX_AGG,1.0"
STRUCTURE_ID = "OECD.ELS.SPD:DSD_SOCX_AGG@DF_SOCX_AGG(1.0)"
UNIT = "PT_B1GQ"
SPENDING_TYPES: tuple[str, ...] = ("_T", "C", "K")
# dimension -> expected code for every row (SPENDING_TYPE varies and is checked separately)
FIXED_DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("FREQ", "A"),
    ("MEASURE", "SOCX"),
    ("UNIT_MEASURE", UNIT),
    ("EXPEND_SOURCE", "ES10"),
    ("PROGRAMME_TYPE", "TP51"),
    ("PRICE_BASE", "_Z"),
)
REQUIRED_COLUMNS = ("STRUCTURE_ID", "REF_AREA", "SPENDING_TYPE", "TIME_PERIOD", "OBS_VALUE")

# The 38 OECD members (ISO 3166-1 alpha-3). Aggregates (OECD) and non-members present in the
# dataflow (BGR, HRV, PER, ROU) are dropped at stage.
OECD_MEMBERS: tuple[str, ...] = (
    "AUS", "AUT", "BEL", "CAN", "CHE", "CHL", "COL", "CRI", "CZE", "DEU", "DNK", "ESP", "EST",
    "FIN", "FRA", "GBR", "GRC", "HUN", "IRL", "ISL", "ISR", "ITA", "JPN", "KOR", "LTU", "LUX",
    "LVA", "MEX", "NLD", "NOR", "NZL", "POL", "PRT", "SVK", "SVN", "SWE", "TUR", "USA",
)  # fmt: skip


def family_spending_url(*, start_period: int = 1980) -> str:
    key = f".A.SOCX.{UNIT}.ES10.{'+'.join(SPENDING_TYPES)}.TP51._Z"
    return f"{BASE}/{FLOW_REF}/{key}?startPeriod={start_period}&format=csvfilewithlabels"


class _Line(BaseModel):
    model_config = ConfigDict(extra="ignore")
    STRUCTURE_ID: str
    REF_AREA: str
    SPENDING_TYPE: str
    TIME_PERIOD: int
    OBS_VALUE: float | None

    @field_validator("OBS_VALUE", mode="before")
    @classmethod
    def _blank_is_missing(cls, v: object) -> object:
        return None if v == "" else v


def family_spending_rows(payload: bytes) -> list[dict[str, object]]:
    """iso3 × year × spending_type rows. Fail closed on another dataflow / dimension / header.

    Blank OBS_VALUE rows are dropped (never imputed); only OECD members are kept.
    Sorted by (iso3, year, spending_type).
    """
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
    fields = set(reader.fieldnames or ())
    missing = [c for c in (*REQUIRED_COLUMNS, *(d for d, _ in FIXED_DIMENSIONS)) if c not in fields]
    if missing:
        msg = f"unexpected OECD SOCX header: missing {missing}"
        raise ValueError(msg)
    out: list[dict[str, object]] = []
    for raw in reader:
        if None in raw or any(v is None for v in raw.values()):
            msg = f"ragged OECD row: {raw}"
            raise ValueError(msg)
        line = _Line.model_validate(raw)
        if line.STRUCTURE_ID != STRUCTURE_ID:
            msg = f"OECD STRUCTURE_ID {line.STRUCTURE_ID!r}, expected {STRUCTURE_ID!r}"
            raise ValueError(msg)
        for dim, code in FIXED_DIMENSIONS:
            if raw[dim] != code:
                msg = f"OECD SOCX dimension {dim}={raw[dim]!r}, expected {code!r}"
                raise ValueError(msg)
        if line.SPENDING_TYPE not in SPENDING_TYPES:
            msg = (
                f"OECD SOCX dimension SPENDING_TYPE={line.SPENDING_TYPE!r} not in {SPENDING_TYPES}"
            )
            raise ValueError(msg)
        if line.OBS_VALUE is None or line.REF_AREA not in OECD_MEMBERS:
            continue
        out.append(
            {
                "iso3": line.REF_AREA,
                "year": line.TIME_PERIOD,
                "spending_type": line.SPENDING_TYPE,
                "value": line.OBS_VALUE,
                "unit": UNIT,
                "source": SOURCE,
            }
        )
    out.sort(key=lambda r: (str(r["iso3"]), int(str(r["year"])), str(r["spending_type"])))
    return out
