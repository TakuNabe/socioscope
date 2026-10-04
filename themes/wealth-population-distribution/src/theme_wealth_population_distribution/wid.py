"""WID.world bulk download: URL builder and deterministic zip/CSV -> rows conversion (no I/O).

Source: https://wid.world/bulk_download/WID_fulldataset_<ISO2>.zip (per-country zip containing
WID_data_<ISO2>.csv, WID_metadata_<ISO2>.csv, WID_countries.csv, README.md). The data CSV is
semicolon-separated with columns country;variable;percentile;year;value;age;pop;data_quality.
In the bulk files the variable column is "<type><concept><pop><age>" (e.g. "sptincj992"); we
re-emit the canonical WID code "<type><concept><age><pop>" (e.g. "sptinc992j") used on the site.

The metadata CSV (one row per country x variable x age x pop; observed 2026-10-04 in all 46
zips) is also ';'-separated with the 18 columns in METADATA_HEADER. It carries NO per-year flag
for interpolation/extrapolation: the only per-year information is the free-text `method`
column, which for the European DINA income series reads
"Summary of data construction by year (see source for details): 1980: extrapolated distribution,
1981-2005: survey + concept correction + tax data, ..." and for many series adds
"Before 1980, series is constructed based on the trend observed in the fiscal income data
available (see sources)." / "Before 1913, pretax income shares estimated based on methodology in
long-run paper (see sources).". parse_method / classify_year turn those sentences into a
per-year construction label; years not covered by any sentence stay None (unknown).
"""

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

BASE = "https://wid.world/bulk_download"
LICENSE = (
    "CC BY-NC-SA 4.0 (rel=license link on wid.world, checked 2026-10-04; "
    "https://creativecommons.org/licenses/by-nc-sa/4.0/)"
)
SOURCE = "wid_world"

# OECD members (38) + non-OECD G20 countries (8). Chosen so the raw per-country zips stay
# under ~200MB in total; see themes/wealth-population-distribution/CLAUDE.md.
COUNTRIES: tuple[str, ...] = (
    "AR", "AT", "AU", "BE", "BR", "CA", "CH", "CL", "CN", "CO", "CR", "CZ", "DE", "DK", "EE", "ES",
    "FI", "FR", "GB", "GR", "HU", "ID", "IE", "IL", "IN", "IS", "IT", "JP", "KR", "LT", "LU", "LV",
    "MX", "NL", "NO", "NZ", "PL", "PT", "RU", "SA", "SE", "SI", "SK", "TR", "US", "ZA",
)  # fmt: skip

SHARE_PERCENTILES: frozenset[str] = frozenset({"p0p50", "p50p90", "p90p100", "p99p100"})
# canonical code -> allowed percentiles
SHARE_VARIABLES: dict[str, frozenset[str]] = {
    "sptinc992j": SHARE_PERCENTILES,  # pre-tax national income share, adults, equal-split
    "shweal992j": SHARE_PERCENTILES,  # net personal (household) wealth share, adults, equal-split
}
POPULATION_VARIABLE = "npopul999i"  # total population, all ages, individuals
POPULATION_PERCENTILE = "p0p100"

EXPECTED_HEADER = ["country", "variable", "percentile", "year", "value", "age", "pop"]
_ISO2 = re.compile(r"^[A-Z]{2}$")


def country_zip_url(iso2: str) -> str:
    return f"{BASE}/WID_fulldataset_{iso2}.zip"


@cache
def _iso_map() -> dict[str, str]:
    text = (
        resources.files("theme_wealth_population_distribution")
        .joinpath("wid_iso2_to_iso3.csv")
        .read_text(encoding="utf-8")
    )
    return {r["alpha2"]: r["iso3"] for r in csv.DictReader(io.StringIO(text))}


def iso2_to_iso3(code: str) -> str | None:
    """Committed WID alpha2 -> ISO 3166-1 alpha-3. Regions/aggregates/subnational -> None."""
    if not _ISO2.match(code):
        return None
    return _iso_map().get(code)


def extract_data_csv(payload: bytes, iso2: str) -> bytes:
    """Pull WID_data_<iso2>.csv out of a per-country zip held in memory. Fail closed."""
    return _extract_member(payload, f"WID_data_{iso2}.csv")


class _Line(BaseModel):
    model_config = ConfigDict(extra="ignore")
    country: str
    variable: str
    percentile: str
    year: int
    value: float
    age: str
    pop: str
    data_quality: int | None = None

    @field_validator("data_quality", mode="before")
    @classmethod
    def _quality_flag_or_none(cls, v: object) -> object:
        # WID documents 0-5; a few rows (e.g. CL wpwodki999) carry a stray copy of `value`.
        # The flag is advisory, so anything that is not a 0-5 digit becomes None.
        return v if isinstance(v, str) and v in {"0", "1", "2", "3", "4", "5"} else None


def canonical_code(variable: str, age: str, pop: str) -> str:
    """Bulk 'sptincj992' + age '992' + pop 'j' -> site code 'sptinc992j'."""
    return f"{variable[:6]}{age}{pop}"


def rows_from_csv(payload: bytes) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """(top-share rows, population rows) for one WID_data_XX.csv. Country-level only; sorted."""
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8")), delimiter=";")
    if reader.fieldnames is None or list(reader.fieldnames)[:7] != EXPECTED_HEADER:
        msg = f"unexpected WID header: {reader.fieldnames}"
        raise ValueError(msg)
    shares: list[dict[str, object]] = []
    population: list[dict[str, object]] = []
    for raw in reader:
        if None in raw or any(v is None for v in raw.values()):
            msg = f"ragged WID row: {raw}"
            raise ValueError(msg)
        line = _Line.model_validate(raw)
        code = canonical_code(line.variable, line.age, line.pop)
        is_share = code in SHARE_VARIABLES and line.percentile in SHARE_VARIABLES[code]
        is_pop = code == POPULATION_VARIABLE and line.percentile == POPULATION_PERCENTILE
        if not (is_share or is_pop):
            continue
        iso3 = iso2_to_iso3(line.country)
        if iso3 is None:
            continue
        if is_share:
            shares.append(
                {
                    "iso3": iso3,
                    "year": line.year,
                    "variable": code,
                    "percentile": line.percentile,
                    "value": line.value,
                    "data_quality": line.data_quality,
                    "source": SOURCE,
                }
            )
        else:
            population.append(
                {
                    "iso3": iso3,
                    "year": line.year,
                    "value": line.value,
                    "data_quality": line.data_quality,
                    "source": SOURCE,
                }
            )
    shares.sort(
        key=lambda r: (
            str(r["iso3"]),
            str(r["variable"]),
            str(r["percentile"]),
            int(str(r["year"])),
        )
    )
    population.sort(key=lambda r: (str(r["iso3"]), int(str(r["year"]))))
    return shares, population


# ---------------------------------------------------------------- metadata (WID_metadata_XX.csv)
METADATA_HEADER = [
    "country", "variable", "age", "pop", "countryname", "shortname", "simpledes", "technicaldes",
    "shorttype", "longtype", "shortpop", "longpop", "shortage", "longage", "unit", "source",
    "method", "avg_quality",
]  # fmt: skip
METADATA_VARIABLES: frozenset[str] = frozenset({*SHARE_VARIABLES, POPULATION_VARIABLE})

Construction = Literal["observed", "partial", "imputed"]


def extract_metadata_csv(payload: bytes, iso2: str) -> bytes:
    """Pull WID_metadata_<iso2>.csv out of a per-country zip held in memory. Fail closed."""
    return _extract_member(payload, f"WID_metadata_{iso2}.csv")


def _extract_member(payload: bytes, member: str) -> bytes:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            if member not in zf.namelist():
                msg = f"{member} not found in zip"
                raise ValueError(msg)
            return zf.read(member)
    except zipfile.BadZipFile as e:
        msg = "payload is not a zip file"
        raise ValueError(msg) from e


class _MetaLine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    country: str
    variable: str
    age: str
    pop: str
    countryname: str
    shortname: str
    simpledes: str
    technicaldes: str
    shorttype: str
    longtype: str
    shortpop: str
    longpop: str
    shortage: str
    longage: str
    unit: str
    source: str
    method: str
    avg_quality: float | None = None

    @field_validator("avg_quality", mode="before")
    @classmethod
    def _blank_is_none(cls, v: object) -> object:
        return None if v == "" else v


def metadata_rows_from_csv(payload: bytes) -> list[dict[str, object]]:
    """One row per country x selected variable from WID_metadata_XX.csv. Fail closed on a
    header that differs from METADATA_HEADER (WID adding/renaming a column must be noticed)."""
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8")), delimiter=";")
    if reader.fieldnames is None or list(reader.fieldnames) != METADATA_HEADER:
        msg = f"unexpected WID metadata header: {reader.fieldnames}"
        raise ValueError(msg)
    out: list[dict[str, object]] = []
    for raw in reader:
        if None in raw or any(v is None for v in raw.values()):
            msg = f"ragged WID metadata row: {raw}"
            raise ValueError(msg)
        try:
            line = _MetaLine.model_validate(raw)
        except ValueError as e:
            msg = f"invalid WID metadata row: {e}"
            raise ValueError(msg) from e
        code = canonical_code(line.variable, line.age, line.pop)
        if code not in METADATA_VARIABLES:
            continue
        iso3 = iso2_to_iso3(line.country)
        if iso3 is None:
            continue
        out.append(
            {
                "iso3": iso3,
                "variable": code,
                "shortname": line.shortname.strip(),
                "unit": line.unit,
                "source_text": line.source,
                "method": line.method,
                "avg_quality": line.avg_quality,
                "source": SOURCE,
            }
        )
    out.sort(key=lambda r: (str(r["iso3"]), str(r["variable"])))
    return out


@dataclass(frozen=True)
class MethodInfo:
    """What the free-text `method` says about how each year was constructed."""

    by_year: dict[int, str] = field(default_factory=dict)  # year -> construction segment
    trend_before: int | None = None  # "Before YYYY, series is constructed based on the trend ..."
    long_run_before: int | None = None  # "Before YYYY, pretax income shares estimated ... long-run"


_SUMMARY = re.compile(
    r"Summary of data construction by year \(see source for details\): (?P<body>.*?)\.(?: |$)"
)
_SEGMENT = re.compile(r"^(?P<y0>\d{4})(?:-(?P<y1>\d{4}))?: (?P<text>.+)$")
_TREND = re.compile(
    r"Before (\d{4}), series is constructed based on the trend observed in the fiscal income"
)
_LONG_RUN = re.compile(r"Before (\d{4}), pretax income shares estimated based on methodology")


def parse_method(method: str) -> MethodInfo:
    """Extract the per-year summary and the 'Before YYYY' clauses. Unparseable segments raise."""
    by_year: dict[int, str] = {}
    m = _SUMMARY.search(method)
    if m:
        for seg in m.group("body").split(", "):
            s = _SEGMENT.match(seg.strip())
            if s is None:
                msg = f"unparseable method segment: {seg!r}"
                raise ValueError(msg)
            y0 = int(s.group("y0"))
            y1 = int(s.group("y1") or y0)
            for y in range(y0, y1 + 1):
                by_year[y] = s.group("text")
    t = _TREND.search(method)
    lr = _LONG_RUN.search(method)
    return MethodInfo(
        by_year=by_year,
        trend_before=int(t.group(1)) if t else None,
        long_run_before=int(lr.group(1)) if lr else None,
    )


_OBSERVED_INPUTS = frozenset({"survey", "tax data"})
_CORRECTIONS = frozenset({"concept correction", "imputed nonresponse", "extrapolated nonresponse"})
_IMPUTED_PREFIXES = ("interpolated", "extrapolated")


def classify_segment(segment: str) -> Construction:
    """'survey + concept correction + interpolated tax data' -> observed/partial/imputed.

    observed = every primary input (survey / tax data) is a direct observation;
    partial  = at least one primary input is direct, another is interpolated/extrapolated;
    imputed  = no direct primary input (pure interpolation/extrapolation).
    Corrections (concept correction, imputed/extrapolated nonresponse) do not count.
    Unknown wording raises so a new WID vocabulary cannot be silently misclassified.
    """
    observed = imputed = 0
    for part in (p.strip() for p in segment.split(" + ")):
        if part in _OBSERVED_INPUTS:
            observed += 1
        elif part in _CORRECTIONS:
            continue
        elif part.startswith(_IMPUTED_PREFIXES):  # also covers WID typos like 'distribtion'
            imputed += 1
        else:
            msg = f"unknown method input: {part!r} in {segment!r}"
            raise ValueError(msg)
    if observed and not imputed:
        return "observed"
    if observed and imputed:
        return "partial"
    return "imputed"


def classify_year(info: MethodInfo, year: int) -> tuple[Construction | None, str | None]:
    """(construction, basis) for one year; (None, None) when the metadata says nothing."""
    seg = info.by_year.get(year)
    if seg is not None:
        return classify_segment(seg), "method_by_year"
    if info.long_run_before is not None and year < info.long_run_before:
        return "imputed", f"long_run_before_{info.long_run_before}"
    if info.trend_before is not None and year < info.trend_before:
        return "imputed", f"trend_before_{info.trend_before}"
    return None, None


def data_point_rows(
    shares: list[dict[str, object]], metadata: list[dict[str, object]]
) -> list[dict[str, object]]:
    """Long iso3 x variable x year table: is the value for that year a direct observation?

    Years are those present in `shares` (any percentile). is_observed: True only for
    construction == 'observed'; False for 'partial'/'imputed'; None when unknown.
    """
    infos = {(str(m["iso3"]), str(m["variable"])): parse_method(str(m["method"])) for m in metadata}
    keys = sorted({(str(r["iso3"]), str(r["variable"]), int(str(r["year"]))) for r in shares})
    out: list[dict[str, object]] = []
    for iso3, variable, year in keys:
        info = infos.get((iso3, variable))
        construction, basis = classify_year(info, year) if info is not None else (None, None)
        out.append(
            {
                "iso3": iso3,
                "year": year,
                "variable": variable,
                "is_observed": None if construction is None else construction == "observed",
                "construction": construction,
                "basis": basis,
                "method_segment": info.by_year.get(year) if info is not None else None,
                "source": SOURCE,
            }
        )
    return out
