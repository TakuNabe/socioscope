"""e-Stat (政府統計の総合窓口) file downloads: URL builders and deterministic CSV -> rows (no I/O).

Source: 国民生活基礎調査（厚生労働省）所得票 statistical tables, fetched through the public
``stat-search/file-download`` endpoint (no application ID needed). Each table is one CSV
(CP932, a few preamble lines, multi-row headers, full-width digits). Parsing is fail-closed:
an unexpected layout raises ``ValueError`` instead of producing a partial table.
"""

import csv
import io
import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

BASE = "https://www.e-stat.go.jp/stat-search/file-download"
LICENSE = (
    "政府標準利用規約（第2.0版）/ CC BY 4.0 compatible "
    "(https://www.e-stat.go.jp/terms-of-use, checked 2026-10-04; 出典：政府統計の総合窓口(e-Stat))"
)
SOURCE = "estat_kiso"  # 国民生活基礎調査 (Comprehensive Survey of Living Conditions)
SURVEY = "国民生活基礎調査"
ENCODING = "cp932"
MAN_YEN = 10_000


class TableKind(StrEnum):
    INCOME_DIST_TS = "income_dist_ts"  # 世帯数の相対度数分布，年次・所得金額階級別 (%)
    WORKERS_MARITAL = (
        "workers_marital_income"  # 有業人員，配偶者の有無・性・所得金額階級別 (per 100k)
    )
    HH_TYPE = "hh_type_income"  # 世帯数，世帯類型・所得金額階級別 (per 10k)


@dataclass(frozen=True)
class Table:
    key: str
    stat_inf_id: str
    kind: TableKind
    survey_year: int
    population: str | None = None  # INCOME_DIST_TS only: "all" | "with_children"

    @property
    def raw_name(self) -> str:
        return f"{self.key}.csv"


# 大規模調査年 (every 3 years) carry the 所得票 cross tables. 年次推移 tables are taken from the
# latest wave only (they restate 1985- in one file). statInfIds are stable per published table.
TABLES: tuple[Table, ...] = (
    Table("hh_income_dist_ts", "000040473361", TableKind.INCOME_DIST_TS, 2025, "all"),
    Table(
        "children_hh_income_dist_ts",
        "000040473376",
        TableKind.INCOME_DIST_TS,
        2025,
        "with_children",
    ),
    Table("workers_marital_income_2013", "000026222087", TableKind.WORKERS_MARITAL, 2013),
    Table("workers_marital_income_2016", "000031734158", TableKind.WORKERS_MARITAL, 2016),
    Table("workers_marital_income_2019", "000031957928", TableKind.WORKERS_MARITAL, 2019),
    Table("workers_marital_income_2022", "000040076501", TableKind.WORKERS_MARITAL, 2022),
    Table("workers_marital_income_2025", "000040473461", TableKind.WORKERS_MARITAL, 2025),
    Table("hh_type_income_2013", "000026222010", TableKind.HH_TYPE, 2013),
    Table("hh_type_income_2016", "000031734081", TableKind.HH_TYPE, 2016),
    Table("hh_type_income_2019", "000031957851", TableKind.HH_TYPE, 2019),
    Table("hh_type_income_2022", "000040076424", TableKind.HH_TYPE, 2022),
    Table("hh_type_income_2025", "000040473384", TableKind.HH_TYPE, 2025),
)


def file_download_url(stat_inf_id: str, *, file_kind: int = 1) -> str:
    """fileKind=1 is CSV (fileKind=0 Excel is not published for these tables)."""
    if not re.fullmatch(r"\d{12}", stat_inf_id):
        msg = f"statInfId must be 12 digits: {stat_inf_id!r}"
        raise ValueError(msg)
    return f"{BASE}?statInfId={stat_inf_id}&fileKind={file_kind}"


# ---------------------------------------------------------------- shared parsing helpers


def _norm(cell: str) -> str:
    """NFKC (full-width digits/tilde -> ASCII), drop all whitespace incl. U+3000."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", cell))


def _rows(payload: bytes) -> list[list[str]]:
    try:
        text = payload.decode(ENCODING)
    except UnicodeDecodeError as e:
        msg = f"e-Stat CSV is not {ENCODING}"
        raise ValueError(msg) from e
    return [list(r) for r in csv.reader(io.StringIO(text))]


def _cell(row: list[str], i: int) -> str:
    return row[i] if i < len(row) else ""


def _number(cell: str) -> float | None:
    """e-Stat markers: '-' = none (0); '…' not surveyed, '・' not applicable, '' -> None."""
    c = _norm(cell)
    if c == "-":
        return 0.0
    if c in {"", "…", "・", "...", "x", "X"}:
        return None
    try:
        return float(c.replace(",", ""))
    except ValueError as e:
        msg = f"unexpected numeric cell {cell!r}"
        raise ValueError(msg) from e


class IncomeClass(BaseModel):
    """One 所得金額階級 row label. Bounds in yen; both None for 'total' and 'none'."""

    model_config = ConfigDict(frozen=True)
    code: str  # "total" | "none" | "<lower>-<upper>" | "<lower>-" (open top), in 万円
    lower_yen: int | None
    upper_yen: int | None


_RE_UNDER = re.compile(r"^(\d+)万円未満$")
_RE_RANGE = re.compile(r"^(\d+)[~〜-](\d+)(万円)?$")
_RE_OVER = re.compile(r"^(\d+)万円以上$")


def parse_income_class(label: str) -> IncomeClass | None:
    """Return None when *label* is not an income-class label (e.g. a block title)."""
    c = _norm(label)
    if c in {"総数", "合計"}:
        return IncomeClass(code="total", lower_yen=None, upper_yen=None)
    if c == "所得なし":
        return IncomeClass(code="none", lower_yen=None, upper_yen=None)
    if m := _RE_UNDER.match(c):
        hi = int(m.group(1))
        return IncomeClass(code=f"0-{hi}", lower_yen=0, upper_yen=hi * MAN_YEN)
    if m := _RE_RANGE.match(c):
        lo, hi = int(m.group(1)), int(m.group(2))
        if hi <= lo:
            msg = f"income class upper <= lower: {label!r}"
            raise ValueError(msg)
        return IncomeClass(code=f"{lo}-{hi}", lower_yen=lo * MAN_YEN, upper_yen=hi * MAN_YEN)
    if m := _RE_OVER.match(c):
        lo = int(m.group(1))
        return IncomeClass(code=f"{lo}-", lower_yen=lo * MAN_YEN, upper_yen=None)
    return None


def _find_header(rows: list[list[str]], startswith: str) -> int:
    for i, r in enumerate(rows):
        if _norm(_cell(r, 0)).startswith(startswith):
            return i
    msg = f"header row starting with {startswith!r} not found"
    raise ValueError(msg)


def _check_title(rows: list[list[str]], *must_contain: str) -> None:
    head = _norm("".join("".join(r) for r in rows[:3]))
    for s in must_contain:
        if _norm(s) not in head:
            msg = f"table title does not mention {s!r}; wrong table?"
            raise ValueError(msg)


# ---------------------------------------------------------------- 年次・所得金額階級別 (時系列)


class IncomeDistRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    population: str
    year: int  # income reference year (the survey is conducted the following year)
    income_class: IncomeClass
    share_pct: float | None


_RE_YEAR = re.compile(r"^(\d{4})")


def parse_income_dist_ts(payload: bytes, *, population: str) -> list[IncomeDistRow]:
    rows = _rows(payload)
    _check_title(rows, "相対度数分布", "年次・所得金額階級別")
    h = _find_header(rows, "所得金額階級")
    years: list[tuple[int, int]] = []
    for j, cell in enumerate(rows[h][1:], start=1):
        if m := _RE_YEAR.match(_norm(cell)):
            years.append((j, int(m.group(1))))
    if len(years) < 2 or len({y for _, y in years}) != len(years):
        msg = "year header missing or duplicated"
        raise ValueError(msg)
    out: list[IncomeDistRow] = []
    in_block = False
    for r in rows[h + 1 :]:
        label = _norm(_cell(r, 0))
        if label == "相対度数分布":
            in_block = True
            continue
        if label == "累積度数分布":
            break
        if not in_block or not label:
            continue
        ic = parse_income_class(label)
        if ic is None:
            msg = f"unexpected row label in 相対度数分布 block: {label!r}"
            raise ValueError(msg)
        if ic.code == "total":
            continue
        for j, y in years:
            out.append(
                IncomeDistRow(
                    population=population, year=y, income_class=ic, share_pct=_number(_cell(r, j))
                )
            )
    if not out:
        msg = "no 相対度数分布 rows parsed"
        raise ValueError(msg)
    return out


# ------------------------------------------------ 有業人員，配偶者の有無・性・所得金額階級別


class WorkersMaritalRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    marital: str  # "total" | "married" | "unmarried"
    sex: str  # "total" | "male" | "female"
    income_class: IncomeClass
    workers_per_100k: float | None  # 総数 column (all 勤めか自営かの別)


_MARITAL = {"総数": "total", "配偶者あり": "married", "配偶者なし": "unmarried"}
_SEX = {"男": "male", "女": "female"}


def parse_workers_marital(payload: bytes) -> list[WorkersMaritalRow]:
    rows = _rows(payload)
    _check_title(rows, "有業人員", "配偶者の有無・性・所得金額階級別")
    h = _find_header(rows, "配偶者の有無")
    if _norm(_cell(rows[h], 3)) != "総数":
        msg = "expected 総数 as the 4th column"
        raise ValueError(msg)
    out: list[WorkersMaritalRow] = []
    marital: str | None = None
    sex = "total"
    for r in rows[h + 1 :]:
        c0, c1, c2 = (_norm(_cell(r, i)) for i in range(3))
        if c0:
            if c0 not in _MARITAL:
                msg = f"unexpected 配偶者の有無 label {c0!r}"
                raise ValueError(msg)
            marital, sex = _MARITAL[c0], "total"
            label = "総数"
        elif c1:
            if c1 not in _SEX:
                msg = f"unexpected 性 label {c1!r}"
                raise ValueError(msg)
            sex = _SEX[c1]
            label = "総数"
        elif c2:
            label = c2
        else:
            continue
        if marital is None:
            msg = "income rows before any 配偶者の有無 block"
            raise ValueError(msg)
        ic = parse_income_class(label)
        if ic is None:
            msg = f"unexpected income label {label!r}"
            raise ValueError(msg)
        out.append(
            WorkersMaritalRow(
                marital=marital, sex=sex, income_class=ic, workers_per_100k=_number(_cell(r, 3))
            )
        )
    keys = {(o.marital, o.sex) for o in out}
    if keys != {(m, s) for m in _MARITAL.values() for s in ("total", "male", "female")}:
        msg = f"incomplete 配偶者の有無×性 blocks: {sorted(keys)}"
        raise ValueError(msg)
    return out


# ---------------------------------------------------------------- 世帯数，世帯類型・所得金額階級別


class HouseholdTypeRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    income_class: IncomeClass
    households_per_10k: float | None  # 総数
    with_children_per_10k: float | None  # （再掲）児童のいる世帯
    single_mother_per_10k: float | None  # 母子世帯


def _joined_headers(rows: list[list[str]], h: int) -> list[str]:
    """Join the multi-row header (from row *h* up to the first data row) column-wise."""
    end = h + 1
    while end < len(rows) and parse_income_class(_cell(rows[end], 0)) is None:
        end += 1
    width = max(len(r) for r in rows[h:end])
    return ["".join(_norm(_cell(r, j)) for r in rows[h:end]) for j in range(width)]


def _col(headers: list[str], contains: str, *, exclude: str = "") -> int:
    hits = [j for j, t in enumerate(headers) if contains in t and (not exclude or exclude not in t)]
    if len(hits) != 1:
        msg = f"column {contains!r} not uniquely found: {hits}"
        raise ValueError(msg)
    return hits[0]


def parse_hh_type(payload: bytes) -> list[HouseholdTypeRow]:
    rows = _rows(payload)
    _check_title(rows, "世帯類型", "所得金額階級別")
    h = _find_header(rows, "所得金額階級")
    headers = _joined_headers(rows, h)
    j_total = _col(headers, "総数")
    j_children = _col(headers, "児童のいる世帯", exclude="65歳")
    j_single_mother = _col(headers, "母子世帯")
    out: list[HouseholdTypeRow] = []
    for r in rows[h + 1 :]:
        label = _norm(_cell(r, 0))
        if not label:
            continue
        ic = parse_income_class(label)
        if ic is None:
            msg = f"unexpected income label {label!r}"
            raise ValueError(msg)
        out.append(
            HouseholdTypeRow(
                income_class=ic,
                households_per_10k=_number(_cell(r, j_total)),
                with_children_per_10k=_number(_cell(r, j_children)),
                single_mother_per_10k=_number(_cell(r, j_single_mother)),
            )
        )
    if not any(o.income_class.code == "total" for o in out) or len(out) < 3:
        msg = "household-type table has no 総数 row or too few classes"
        raise ValueError(msg)
    return out


# ---------------------------------------------------------------- staged row builders (dicts)


def _class_cols(ic: IncomeClass) -> dict[str, object]:
    return {
        "income_class": ic.code,
        "income_class_lower_yen": ic.lower_yen,
        "income_class_upper_yen": ic.upper_yen,
    }


def _common(table: Table, year: int) -> dict[str, object]:
    return {
        "survey_year": table.survey_year,
        "year": year,
        "source": SOURCE,
        "stat_inf_id": table.stat_inf_id,
    }


def income_dist_rows(payload: bytes, table: Table) -> list[dict[str, object]]:
    if table.kind is not TableKind.INCOME_DIST_TS or table.population is None:
        msg = f"{table.key} is not an income-distribution time series"
        raise ValueError(msg)
    return [
        {
            "population": r.population,
            **_common(table, r.year),
            **_class_cols(r.income_class),
            "share_pct": r.share_pct,
        }
        for r in parse_income_dist_ts(payload, population=table.population)
    ]


def workers_marital_rows(payload: bytes, table: Table) -> list[dict[str, object]]:
    if table.kind is not TableKind.WORKERS_MARITAL:
        msg = f"{table.key} is not a workers×marital table"
        raise ValueError(msg)
    return [
        {
            **_common(table, table.survey_year - 1),
            "marital": r.marital,
            "sex": r.sex,
            **_class_cols(r.income_class),
            "workers_per_100k": r.workers_per_100k,
        }
        for r in parse_workers_marital(payload)
    ]


def hh_type_rows(payload: bytes, table: Table) -> list[dict[str, object]]:
    if table.kind is not TableKind.HH_TYPE:
        msg = f"{table.key} is not a household-type table"
        raise ValueError(msg)
    return [
        {
            **_common(table, table.survey_year - 1),
            **_class_cols(r.income_class),
            "households_per_10k": r.households_per_10k,
            "with_children_per_10k": r.with_children_per_10k,
            "single_mother_per_10k": r.single_mother_per_10k,
        }
        for r in parse_hh_type(payload)
    ]


def tables_of(kind: TableKind) -> Iterator[Table]:
    return (t for t in TABLES if t.kind is kind)
