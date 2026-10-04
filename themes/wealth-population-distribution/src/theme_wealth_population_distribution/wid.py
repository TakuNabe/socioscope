"""WID.world bulk download: URL builder and deterministic zip/CSV -> rows conversion (no I/O).

Source: https://wid.world/bulk_download/WID_fulldataset_<ISO2>.zip (per-country zip containing
WID_data_<ISO2>.csv, WID_metadata_<ISO2>.csv, WID_countries.csv, README.md). The data CSV is
semicolon-separated with columns country;variable;percentile;year;value;age;pop;data_quality.
In the bulk files the variable column is "<type><concept><pop><age>" (e.g. "sptincj992"); we
re-emit the canonical WID code "<type><concept><age><pop>" (e.g. "sptinc992j") used on the site.
"""

import csv
import io
import re
import zipfile
from functools import cache
from importlib import resources

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
    member = f"WID_data_{iso2}.csv"
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            if member not in zf.namelist():
                msg = f"{member} not found in zip"
                raise ValueError(msg)
            return zf.read(member)
    except zipfile.BadZipFile as e:
        msg = "payload is not a zip file"
        raise ValueError(msg) from e


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
