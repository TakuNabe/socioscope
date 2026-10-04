"""e-Stat (政府統計の総合窓口) file downloads: URL builders and deterministic file -> rows (no I/O).

Sources, both fetched through the public ``stat-search/file-download`` endpoint (no
application ID needed):

- 国民生活基礎調査（厚生労働省）所得票 statistical tables: one CSV each (``fileKind=1``;
  CP932, a few preamble lines, multi-row headers, full-width digits).
- 就業構造基本調査（総務省）令和4年 全国編 第40表 (男女×配偶関係×年齢×所得, 有業者): published as
  an Excel workbook only (``fileKind=0``; CSV returns 404). It is read with the standard
  library (zipfile + ElementTree), so no spreadsheet dependency is added.

Parsing is fail-closed: an unexpected layout raises ``ValueError`` instead of producing a
partial table.
"""

import csv
import io
import re
import unicodedata
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from xml.etree import ElementTree as ET

from pydantic import BaseModel, ConfigDict

BASE = "https://www.e-stat.go.jp/stat-search/file-download"
LICENSE = (
    "政府標準利用規約（第2.0版）/ CC BY 4.0 compatible "
    "(https://www.e-stat.go.jp/terms-of-use, checked 2026-10-04; 出典：政府統計の総合窓口(e-Stat))"
)
SOURCE = "estat_kiso"  # 国民生活基礎調査 (Comprehensive Survey of Living Conditions)
SURVEY = "国民生活基礎調査"
SOURCE_SHUGYO = "estat_shugyo"  # 就業構造基本調査 (Employment Status Survey)
SURVEY_SHUGYO = "就業構造基本調査"
ENCODING = "cp932"
MAN_YEN = 10_000
FILE_KIND_CSV = 1
FILE_KIND_EXCEL = 0


class TableKind(StrEnum):
    INCOME_DIST_TS = "income_dist_ts"  # 世帯数の相対度数分布，年次・所得金額階級別 (%)
    WORKERS_MARITAL = (
        "workers_marital_income"  # 有業人員，配偶者の有無・性・所得金額階級別 (per 100k)
    )
    HH_TYPE = "hh_type_income"  # 世帯数，世帯類型・所得金額階級別 (per 10k)
    SHUGYO_MARITAL_AGE_INCOME = (
        "shugyo_marital_age_income"  # 有業者数，男女・配偶関係・年齢・所得別 (persons, xlsx)
    )


@dataclass(frozen=True)
class Table:
    key: str
    stat_inf_id: str
    kind: TableKind
    survey_year: int
    population: str | None = None  # INCOME_DIST_TS only: "all" | "with_children"
    file_kind: int = FILE_KIND_CSV

    @property
    def raw_name(self) -> str:
        ext = "csv" if self.file_kind == FILE_KIND_CSV else "xlsx"
        return f"{self.key}.{ext}"

    @property
    def source(self) -> str:
        return SOURCE_SHUGYO if self.kind is TableKind.SHUGYO_MARITAL_AGE_INCOME else SOURCE

    @property
    def url(self) -> str:
        return file_download_url(self.stat_inf_id, file_kind=self.file_kind)


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
    # 就業構造基本調査 令和4年 全国編 第40表 (Excel only). No equivalent 配偶関係×年齢×所得 table
    # for 有業者 exists in the 2017 / 2012 全国編 (checked 2026-10-04), so this is a single wave.
    Table(
        "shugyo_marital_age_income_2022",
        "000040077301",
        TableKind.SHUGYO_MARITAL_AGE_INCOME,
        2022,
        file_kind=FILE_KIND_EXCEL,
    ),
)


def file_download_url(stat_inf_id: str, *, file_kind: int = FILE_KIND_CSV) -> str:
    """fileKind=1 is CSV, fileKind=0 Excel. The 国民生活基礎調査 tables publish CSV only, the
    就業構造基本調査 table Excel only (the other kind returns 404)."""
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


# ---------------------------- 就業構造基本調査 第40表 (xlsx): 男女×配偶関係×年齢×所得, 有業者

_XML_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_SHEET = "xl/worksheets/sheet1.xml"
_SHARED = "xl/sharedStrings.xml"


def _col_index(ref: str) -> int:
    """'A1' -> 1, 'AA3' -> 27 (1-based)."""
    m = re.match(r"[A-Z]+", ref)
    if m is None:
        msg = f"bad cell reference {ref!r}"
        raise ValueError(msg)
    n = 0
    for ch in m.group(0):
        n = n * 26 + ord(ch) - 64
    return n


def xlsx_rows(payload: bytes) -> list[dict[int, str]]:
    """First worksheet of an xlsx as a list of {1-based column: text}. Standard library only.

    Handles shared strings (``t="s"``), inline strings (``t="inlineStr"``) and plain values.
    Empty cells are absent from the dict. Raises ``ValueError`` when *payload* is not an xlsx.
    """
    try:
        z = zipfile.ZipFile(io.BytesIO(payload))
        names = set(z.namelist())
        if _SHEET not in names:
            msg = "xlsx has no first worksheet"
            raise ValueError(msg)
        shared: list[str] = []
        if _SHARED in names:
            shared = [
                "".join(t.text or "" for t in si.iter(f"{_XML_MAIN}t"))
                for si in ET.fromstring(z.read(_SHARED))  # noqa: S314 - trusted public file, stdlib
            ]
        sheet = ET.fromstring(z.read(_SHEET))  # noqa: S314
    except (zipfile.BadZipFile, ET.ParseError, KeyError) as e:
        msg = "payload is not an xlsx workbook"
        raise ValueError(msg) from e
    data = sheet.find(f"{_XML_MAIN}sheetData")
    if data is None:
        msg = "xlsx worksheet has no sheetData"
        raise ValueError(msg)
    out: list[dict[int, str]] = []
    for row in data:
        cells: dict[int, str] = {}
        for c in row:
            ref = c.get("r")
            if ref is None:
                continue
            kind = c.get("t")
            if kind == "inlineStr":
                text = "".join(t.text or "" for t in c.iter(f"{_XML_MAIN}t"))
            else:
                v = c.find(f"{_XML_MAIN}v")
                if v is None or v.text is None:
                    continue
                text = shared[int(v.text)] if kind == "s" else v.text
            cells[_col_index(ref)] = text
        out.append(cells)
    return out


class AgeClass(BaseModel):
    """One 年齢 row label. ``upper`` is exclusive (15～19歳 -> 15, 20); both None for 'total'."""

    model_config = ConfigDict(frozen=True)
    code: str  # "total" | "<lower>-<upper>" | "<lower>-" (open top)
    lower: int | None
    upper: int | None


_RE_CODE_PREFIX = re.compile(r"^\d+_")
_RE_AGE_RANGE = re.compile(r"^(\d+)[~〜-](\d+)歳$")
_RE_AGE_OVER = re.compile(r"^(\d+)歳以上$")
_RE_SHUGYO_RANGE = re.compile(r"^(\d+)[~〜-](\d+)万円$")


def _strip_code(label: str) -> str:
    """'03_25～29歳' -> '25～29歳' (e-Stat DB-style labels carry a numeric code prefix)."""
    return _RE_CODE_PREFIX.sub("", _norm(label))


def parse_age_class(label: str) -> AgeClass | None:
    c = _strip_code(label)
    if c in {"総数", "合計"}:
        return AgeClass(code="total", lower=None, upper=None)
    if m := _RE_AGE_RANGE.match(c):
        lo, hi = int(m.group(1)), int(m.group(2))
        if hi < lo:
            msg = f"age class upper < lower: {label!r}"
            raise ValueError(msg)
        return AgeClass(code=f"{lo}-{hi}", lower=lo, upper=hi + 1)
    if m := _RE_AGE_OVER.match(c):
        lo = int(m.group(1))
        return AgeClass(code=f"{lo}-", lower=lo, upper=None)
    return None


def parse_income_class_shugyo(label: str) -> IncomeClass | None:
    """就業構造基本調査 labels: '02_50～99万円' means 50 <= income < 100 万円, so the upper bound
    is *hi + 1* (the 国民生活基礎調査 labels '50～100' already carry the exclusive bound)."""
    c = _strip_code(label)
    if m := _RE_SHUGYO_RANGE.match(c):
        lo, hi = int(m.group(1)), int(m.group(2)) + 1
        if hi <= lo:
            msg = f"income class upper <= lower: {label!r}"
            raise ValueError(msg)
        return IncomeClass(code=f"{lo}-{hi}", lower_yen=lo * MAN_YEN, upper_yen=hi * MAN_YEN)
    return parse_income_class(c)


class ShugyoRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    sex: str  # "total" | "male" | "female"
    marital: str  # "total" | "never_married" (the table publishes 総数 and うち未婚 only)
    age_class: AgeClass
    income_class: IncomeClass
    persons: float | None  # 教育 総数 column, persons (sample-weighted estimate)


_SHUGYO_SEX = {"総数": "total", "男": "male", "女": "female"}
_SHUGYO_MARITAL = {"総数": "total", "うち未婚": "never_married"}
_SHUGYO_HEADER = {
    1: "階層レベル",
    2: "地域区分",
    4: "男女",
    6: "配偶関係",
    8: "年齢",
    10: "従業上の地位・雇用形態・起業の有無",
    12: "所得（主な仕事からの年間収入・収益）",
}
_C_REGION, _C_SEX, _C_MARITAL, _C_AGE, _C_STATUS, _C_INCOME, _C_VALUE = 2, 4, 6, 8, 10, 12, 13


def parse_shugyo_marital_age_income(payload: bytes) -> list[ShugyoRow]:
    """第40表 (全国): keep 従業上の地位 = 総数 and the 教育 = 総数 column; every
    男女×配偶関係×年齢×所得 cell becomes one row. Fails closed on title / header / label
    surprises."""
    rows = xlsx_rows(payload)
    title = _norm("".join(c for r in rows[:3] for c in r.values()))
    for must in ("就業構造基本調査", "配偶関係、年齢", "所得", "有業者"):
        if _norm(must) not in title:
            msg = f"table title does not mention {must!r}; wrong table?"
            raise ValueError(msg)
    header = next(
        (
            i
            for i, r in enumerate(rows)
            if all(_norm(r.get(j, "")) == _norm(v) for j, v in _SHUGYO_HEADER.items())
        ),
        None,
    )
    if header is None:
        msg = "dimension header row (階層レベル/地域区分/男女/配偶関係/年齢/.../所得) not found"
        raise ValueError(msg)
    item_rows = [r for r in rows[:header] if _norm(r.get(_C_INCOME, "")) in {"事項名", "項目名"}]
    if [_norm(r.get(_C_VALUE, "")) for r in item_rows] != ["教育", "0_総数"]:
        msg = "expected the first value column to be 教育 = 0_総数"
        raise ValueError(msg)
    out: list[ShugyoRow] = []
    for r in rows[header + 1 :]:
        if _norm(r.get(_C_REGION, "")) != "00_全国":
            continue
        if _strip_code(r.get(_C_STATUS, "")) != "総数":
            continue
        sex, marital = _strip_code(r.get(_C_SEX, "")), _strip_code(r.get(_C_MARITAL, ""))
        if sex not in _SHUGYO_SEX or marital not in _SHUGYO_MARITAL:
            msg = f"unexpected 男女/配偶関係 labels {sex!r}/{marital!r}"
            raise ValueError(msg)
        age = parse_age_class(r.get(_C_AGE, ""))
        ic = parse_income_class_shugyo(r.get(_C_INCOME, ""))
        if age is None or ic is None:
            msg = f"unexpected 年齢/所得 labels {r.get(_C_AGE)!r}/{r.get(_C_INCOME)!r}"
            raise ValueError(msg)
        out.append(
            ShugyoRow(
                sex=_SHUGYO_SEX[sex],
                marital=_SHUGYO_MARITAL[marital],
                age_class=age,
                income_class=ic,
                persons=_number(r.get(_C_VALUE, "")),
            )
        )
    if {o.marital for o in out} != set(_SHUGYO_MARITAL.values()):
        msg = "incomplete 配偶関係 blocks (need 総数 and うち未婚)"
        raise ValueError(msg)
    if not any(o.age_class.code == "total" for o in out) or not any(
        o.income_class.code == "total" for o in out
    ):
        msg = "no 総数 age or income rows parsed"
        raise ValueError(msg)
    return out


def shugyo_marital_age_income_rows(payload: bytes, table: Table) -> list[dict[str, object]]:
    """Staged rows. ``year`` is the survey year: the 所得 item covers the 12 months before the
    survey date (2021-10 to 2022-09 for the 2022 survey), not a calendar year."""
    if table.kind is not TableKind.SHUGYO_MARITAL_AGE_INCOME:
        msg = f"{table.key} is not a 就業構造基本調査 marital×age×income table"
        raise ValueError(msg)
    return [
        {
            "survey_year": table.survey_year,
            "year": table.survey_year,
            "source": table.source,
            "stat_inf_id": table.stat_inf_id,
            "sex": r.sex,
            "marital": r.marital,
            "age_class": r.age_class.code,
            "age_lower": r.age_class.lower,
            "age_upper": r.age_class.upper,
            **_class_cols(r.income_class),
            "persons": r.persons,
        }
        for r in parse_shugyo_marital_age_income(payload)
    ]
