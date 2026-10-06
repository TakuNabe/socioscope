"""Eurostat dissemination API (JSON-stat 2.0): request builders and deterministic JSON -> rows.

No I/O here. ``jsonstat_rows`` expands the *sparse* ``value`` dict (string cell index -> number)
into one dict per observed cell with the dimension codes; cells absent from ``value`` are not
emitted (never imputed). ``geo`` is mapped to ISO3 with a fixed dictionary (EU27 + EFTA + UK;
Eurostat uses ``EL`` for Greece and ``UK`` for the United Kingdom). Fail closed on error
documents and on anything that is not a JSON-stat dataset.

Datasets (dimension codes verified against live responses on 2026-10-06):
  cens_21me_r2   2021 census: freq.isced11.marsta.age.sex.unit.geo.time (NR)
  demo_fordagec  live births by mother's age (single years + 5-year classes) x birth order
  demo_pjan      population on 1 January by single age x sex
  demo_faeduc    live births by mother's age x ISCED 2011 (ED0-2 / ED3_4 / ED5-8 / NAP / UNK)
  lfsa_pgaed     LFS population (thousand persons) by sex x 5-year age class x ISCED
"""

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import product

from pydantic import BaseModel, ConfigDict

BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
SOURCE = "eurostat"
LICENSE = (
    "Eurostat copyright notice (checked 2026-10-06): reuse, including commercial, allowed with "
    "source acknowledgement ('Source: Eurostat'); third-country data excluded (not used here); "
    "https://ec.europa.eu/eurostat/web/main/help/copyright-notice"
)

# Eurostat geo code -> ISO 3166-1 alpha-3. EU27 + EFTA (IS, NO, CH, LI) + UK.
GEO_TO_ISO3: dict[str, str] = {
    "AT": "AUT", "BE": "BEL", "BG": "BGR", "HR": "HRV", "CY": "CYP", "CZ": "CZE", "DK": "DNK",
    "EE": "EST", "FI": "FIN", "FR": "FRA", "DE": "DEU", "EL": "GRC", "HU": "HUN", "IE": "IRL",
    "IT": "ITA", "LV": "LVA", "LT": "LTU", "LU": "LUX", "MT": "MLT", "NL": "NLD", "PL": "POL",
    "PT": "PRT", "RO": "ROU", "SK": "SVK", "SI": "SVN", "ES": "ESP", "SE": "SWE",
    "IS": "ISL", "NO": "NOR", "CH": "CHE", "LI": "LIE", "UK": "GBR",
}  # fmt: skip
EU27_EFTA: tuple[str, ...] = tuple(g for g in GEO_TO_ISO3 if g != "UK")
# Pre-registered country sets (design/themes/growth-fertility.md, H5).
CENSUS_GEOS: tuple[str, ...] = EU27_EFTA
ORDER_GEOS: tuple[str, ...] = (
    "FI", "SE", "NO", "DK", "IS", "DE", "FR", "IT", "ES", "NL", "HU", "CZ", "PL",
)  # fmt: skip
EDUCATION_GEOS: tuple[str, ...] = ("FI", "SE", "NO", "DK", "IS", "NL", "BE", "AT")

CENSUS_AGES: tuple[str, ...] = tuple(f"Y{a}-{a + 4}" for a in range(25, 60, 5))
SINGLE_AGES: tuple[str, ...] = tuple(f"Y{a}" for a in range(15, 50))
FIVE_YEAR_AGES: tuple[str, ...] = tuple(f"Y{a}-{a + 4}" for a in range(15, 50, 5))
EDUCATION_GROUPS: tuple[str, ...] = ("ED0-2", "ED3_4", "ED5-8", "TOTAL")
CENSUS_ISCED_GROUPS: dict[str, str] = {
    **{f"ED{i}": "ED0-2" for i in range(3)},
    **{f"ED{i}": "ED3-4" for i in (3, 4)},
    **{f"ED{i}": "ED5-8" for i in range(5, 9)},
}
ORDERS: tuple[str, ...] = ("1", "2", "3", "GE4", "TOTAL", "UNK")
ORDER_START, EDUCATION_START = 2005, 2007


@dataclass(frozen=True)
class Request:
    """One API call = one dataset for one country (keeps responses small)."""

    dataset: str
    geo: str
    params: tuple[tuple[str, str], ...]

    @property
    def url(self) -> str:
        query = "".join(f"&{k}={v}" for k, v in (("geo", self.geo), *self.params))
        return f"{BASE}/{self.dataset}?format=JSON&lang=EN{query}"

    @property
    def raw_name(self) -> str:
        return f"eurostat_{self.dataset}_{self.geo}.json"


def _many(key: str, values: Iterable[str]) -> tuple[tuple[str, str], ...]:
    return tuple((key, v) for v in values)


def census_requests() -> tuple[Request, ...]:
    params = (
        *_many("sex", ("M", "F")),
        *_many("age", CENSUS_AGES),
        *_many("marsta", ("TOTAL", "MAR_REP", "UNK")),
    )
    return tuple(Request("cens_21me_r2", g, params) for g in CENSUS_GEOS)


def births_order_requests() -> tuple[Request, ...]:
    params = (("sinceTimePeriod", str(ORDER_START)), *_many("age", (*SINGLE_AGES, "UNK")))
    return tuple(Request("demo_fordagec", g, params) for g in ORDER_GEOS)


def population_requests() -> tuple[Request, ...]:
    params = (("sinceTimePeriod", str(ORDER_START)), ("sex", "F"), *_many("age", SINGLE_AGES))
    return tuple(Request("demo_pjan", g, params) for g in ORDER_GEOS)


def births_education_requests() -> tuple[Request, ...]:
    params = (
        ("sinceTimePeriod", str(EDUCATION_START)),
        *_many("age", (*SINGLE_AGES, *FIVE_YEAR_AGES, "UNK")),
    )
    return tuple(Request("demo_faeduc", g, params) for g in EDUCATION_GEOS)


def lfs_requests() -> tuple[Request, ...]:
    params = (
        ("sinceTimePeriod", str(EDUCATION_START)),
        ("sex", "F"),
        *_many("age", FIVE_YEAR_AGES),
        *_many("isced11", EDUCATION_GROUPS),
    )
    return tuple(Request("lfsa_pgaed", g, params) for g in EDUCATION_GEOS)


def requests() -> tuple[Request, ...]:
    return (
        *census_requests(),
        *births_order_requests(),
        *population_requests(),
        *births_education_requests(),
        *lfs_requests(),
    )


# ---------------------------------------------------------------- JSON-stat 2.0


class _Category(BaseModel):
    model_config = ConfigDict(extra="ignore")
    index: dict[str, int] | list[str]


class _Dimension(BaseModel):
    model_config = ConfigDict(extra="ignore")
    category: _Category


class _Dataset(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: list[str]
    size: list[int]
    dimension: dict[str, _Dimension]
    value: dict[str, float | None] | list[float | None]


def _codes(cat: _Category, size: int, dim: str) -> list[str]:
    index = cat.index
    codes = list(index) if isinstance(index, list) else sorted(index, key=index.__getitem__)
    if len(codes) != size:
        msg = f"JSON-stat dimension {dim!r}: {len(codes)} categories but size {size}"
        raise ValueError(msg)
    return codes


def jsonstat_rows(payload: bytes) -> list[dict[str, object]]:
    """One dict per observed cell: {<dim>: <code>, ..., 'value': float}. Pure, fail closed."""
    try:
        doc = json.loads(payload)
    except ValueError as e:
        msg = f"Eurostat response is not JSON: {e}"
        raise ValueError(msg) from None
    if not isinstance(doc, dict):
        msg = "unexpected Eurostat response shape (expected a JSON object)"
        raise ValueError(msg)
    if "error" in doc:
        msg = f"Eurostat API error: {doc['error']}"
        raise ValueError(msg)
    if doc.get("class") != "dataset":
        msg = f"JSON-stat class {doc.get('class')!r}, expected 'dataset'"
        raise ValueError(msg)
    ds = _Dataset.model_validate(doc)
    if len(ds.id) != len(ds.size) or any(d not in ds.dimension for d in ds.id):
        msg = f"JSON-stat id/size/dimension mismatch: id={ds.id} size={ds.size}"
        raise ValueError(msg)
    axes = [_codes(ds.dimension[d].category, n, d) for d, n in zip(ds.id, ds.size, strict=True)]
    values = {str(i): v for i, v in enumerate(ds.value)} if isinstance(ds.value, list) else ds.value
    out: list[dict[str, object]] = []
    for i, combo in enumerate(product(*axes)):
        v = values.get(str(i))
        if v is None:
            continue
        row: dict[str, object] = dict(zip(ds.id, combo, strict=True))
        row["value"] = float(v)
        out.append(row)
    return out


_AGE_RANGE = re.compile(r"^Y(\d+)-(\d+)$")
_AGE_SINGLE = re.compile(r"^Y(\d+)$")
_AGE_GE = re.compile(r"^Y_GE(\d+)$")


def age_bounds(code: str) -> tuple[int | None, int | None]:
    """'Y25-29' -> (25, 30); 'Y15' -> (15, 16); 'Y_GE50' -> (50, None); else (None, None).

    Upper bound is exclusive (same convention as ``marts/jp_income_age_marital``).
    """
    if m := _AGE_RANGE.match(code):
        return int(m.group(1)), int(m.group(2)) + 1
    if m := _AGE_SINGLE.match(code):
        return int(m.group(1)), int(m.group(1)) + 1
    if m := _AGE_GE.match(code):
        return int(m.group(1)), None
    return None, None


# ---------------------------------------------------------------- staged rows


def _country_cells(payload: bytes) -> list[tuple[str, int, dict[str, object]]]:
    """(iso3, year, cell) for country-level geo codes only (NUTS regions dropped)."""
    out: list[tuple[str, int, dict[str, object]]] = []
    for c in jsonstat_rows(payload):
        iso3 = GEO_TO_ISO3.get(str(c["geo"]))
        if iso3 is None:
            continue
        out.append((iso3, int(str(c["time"])), c))
    return out


def census_rows(payload: bytes) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for iso3, year, c in _country_cells(payload):
        age = str(c["age"])
        lo, hi = age_bounds(age)
        rows.append(
            {
                "iso3": iso3,
                "year": year,
                "sex": c["sex"],
                "age_class": age,
                "age_lower": lo,
                "age_upper": hi,
                "isced11": c["isced11"],
                "marsta": c["marsta"],
                "value": c["value"],
                "source": SOURCE,
            }
        )
    rows.sort(
        key=lambda r: tuple(
            str(r[k]) for k in ("iso3", "year", "sex", "age_class", "isced11", "marsta")
        )
    )
    return rows


def _simple_rows(
    payload: bytes, *, dims: tuple[str, ...], value_name: str
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for iso3, year, c in _country_cells(payload):
        row: dict[str, object] = {"iso3": iso3, "year": year}
        for d in dims:
            row["age_class" if d == "age" else d] = c[d]
        row[value_name] = c["value"]
        row["source"] = SOURCE
        rows.append(row)
    keys = ("iso3", "year", *("age_class" if d == "age" else d for d in dims))
    rows.sort(key=lambda r: tuple(str(r[k]) if k != "year" else f"{r[k]:04d}" for k in keys))
    return rows


def births_order_rows(payload: bytes) -> list[dict[str, object]]:
    return _simple_rows(payload, dims=("age", "ord_brth"), value_name="births")


def population_female_rows(payload: bytes) -> list[dict[str, object]]:
    return _simple_rows(payload, dims=("age",), value_name="women")


def births_education_rows(payload: bytes) -> list[dict[str, object]]:
    return _simple_rows(payload, dims=("age", "isced11"), value_name="births")


def lfs_population_rows(payload: bytes) -> list[dict[str, object]]:
    return _simple_rows(payload, dims=("age", "isced11"), value_name="women_thousand")


# ---------------------------------------------------------------- marts (pure)


def _f(v: object) -> float:
    return float(str(v))


def build_census_mart(rows: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    """Married share by iso3 × sex × age class × ISCED group (ED0-2 / ED3-4 / ED5-8).

    married = Σ MAR_REP; total = Σ TOTAL − Σ UNK (marital status unknown). ISCED UNK / NAP /
    TOTAL are not grouped. Cells with total <= 0 get married_share None.
    """
    acc: dict[tuple[str, int, str, str, str], dict[str, float]] = {}
    rep: dict[tuple[str, int, str, str, str], dict[str, object]] = {}
    for r in rows:
        group = CENSUS_ISCED_GROUPS.get(str(r["isced11"]))
        if group is None:
            continue
        k = (str(r["iso3"]), int(str(r["year"])), str(r["sex"]), str(r["age_class"]), group)
        parts = acc.setdefault(k, {"TOTAL": 0.0, "MAR_REP": 0.0, "UNK": 0.0})
        marsta = str(r["marsta"])
        if marsta in parts:
            parts[marsta] += _f(r["value"])
        rep[k] = r
    out: list[dict[str, object]] = []
    for k in sorted(acc):
        parts, r = acc[k], rep[k]
        married, total = parts["MAR_REP"], parts["TOTAL"] - parts["UNK"]
        out.append(
            {
                "iso3": k[0],
                "year": k[1],
                "sex": k[2],
                "age_class": k[3],
                "age_lower": r["age_lower"],
                "age_upper": r["age_upper"],
                "isced_group": k[4],
                "married": married,
                "total": total,
                "married_share": married / total if total > 0 else None,
                "source": SOURCE,
            }
        )
    return out


def _class_sum(by_age: dict[str, float], cls: str) -> float | None:
    """Births in a 5-year class: the class cell if present, else the sum of its 5 single years."""
    if cls in by_age:
        return by_age[cls]
    lo, hi = age_bounds(cls)
    assert lo is not None and hi is not None  # FIVE_YEAR_AGES are ranges
    singles = [by_age.get(f"Y{a}") for a in range(lo, hi)]
    if any(s is None for s in singles):
        return None
    return sum(s for s in singles if s is not None)


def build_tfr_by_order(
    births: Sequence[dict[str, object]], women: Sequence[dict[str, object]]
) -> list[dict[str, object]]:
    """TFR by birth order = Σ_{age 15..49} births/women (single years; women from demo_pjan).

    A (iso3, year) needs women for all 35 single ages. Orders use single-year births when all
    35 are present, else fall back to 5 × Σ_class births_class / women_class (5-year cells).
    Otherwise the (iso3, year, order) is dropped. Births of unknown age are excluded from the
    TFR and reported in ``births_age_unknown``.
    """
    w: dict[tuple[str, int], dict[str, float]] = {}
    for r in women:
        w.setdefault((str(r["iso3"]), int(str(r["year"]))), {})[str(r["age_class"])] = _f(
            r["women"]
        )
    b: dict[tuple[str, int, str], dict[str, float]] = {}
    for r in births:
        k = (str(r["iso3"]), int(str(r["year"])), str(r["ord_brth"]))
        b.setdefault(k, {})[str(r["age_class"])] = _f(r["births"])
    out: list[dict[str, object]] = []
    for k in sorted(b, key=lambda k: (k[0], k[1], ORDERS.index(k[2]) if k[2] in ORDERS else 99)):
        wk = w.get((k[0], k[1]))
        if wk is None or any(a not in wk or wk[a] <= 0 for a in SINGLE_AGES):
            continue
        by_age = b[k]
        if all(a in by_age for a in SINGLE_AGES):
            tfr = sum(by_age[a] / wk[a] for a in SINGLE_AGES)
        else:
            terms: list[float] = []
            for cls in FIVE_YEAR_AGES:
                bc = _class_sum(by_age, cls)
                if bc is None:
                    break
                lo, hi = age_bounds(cls)
                assert lo is not None and hi is not None
                terms.append(5 * bc / sum(wk[f"Y{a}"] for a in range(lo, hi)))
            if len(terms) != len(FIVE_YEAR_AGES):
                continue
            tfr = sum(terms)
        out.append(
            {
                "iso3": k[0],
                "year": k[1],
                "order": k[2],
                "tfr": tfr,
                "births_age_unknown": by_age.get("UNK", 0.0),
                "source": SOURCE,
            }
        )
    return out


def build_tfr_by_education(
    births: Sequence[dict[str, object]], women: Sequence[dict[str, object]]
) -> list[dict[str, object]]:
    """TFR by ISCED group = 5 × Σ_{7 five-year classes 15-49} births / (women_thousand × 1000).

    Births per class come from the 5-year cell or the sum of its single years. A class whose LFS
    denominator is missing/zero drops the whole (iso3, year, group) unless its births are 0
    (then it contributes exactly 0 and is left out of ``women_total_thousand``). Nothing is
    imputed.
    """
    w: dict[tuple[str, int, str], dict[str, float]] = {}
    for r in women:
        k = (str(r["iso3"]), int(str(r["year"])), str(r["isced11"]))
        w.setdefault(k, {})[str(r["age_class"])] = _f(r["women_thousand"])
    b: dict[tuple[str, int, str], dict[str, float]] = {}
    for r in births:
        k = (str(r["iso3"]), int(str(r["year"])), str(r["isced11"]))
        b.setdefault(k, {})[str(r["age_class"])] = _f(r["births"])
    out: list[dict[str, object]] = []
    for k in sorted(
        b,
        key=lambda k: (
            k[0],
            k[1],
            EDUCATION_GROUPS.index(k[2]) if k[2] in EDUCATION_GROUPS else 99,
        ),
    ):
        if k[2] not in EDUCATION_GROUPS or k not in w:
            continue
        asfr_sum, women_total, complete = 0.0, 0.0, True
        for cls in FIVE_YEAR_AGES:
            bc = _class_sum(b[k], cls)
            wc = w[k].get(cls)
            if bc is None or (bc > 0 and (wc is None or wc <= 0)):
                complete = False
                break
            if wc is None or wc <= 0:
                continue  # zero births: exact 0 contribution, no denominator needed
            asfr_sum += bc / (wc * 1000)
            women_total += wc
        if not complete:
            continue
        out.append(
            {
                "iso3": k[0],
                "year": k[1],
                "isced_group": k[2],
                "tfr": 5 * asfr_sum,
                "women_total_thousand": women_total,
                "source": SOURCE,
            }
        )
    return out
