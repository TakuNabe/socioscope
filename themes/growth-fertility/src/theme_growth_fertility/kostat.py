"""국가데이터처 (Statistics Korea) 신혼부부통계 press-release PDFs -> rows. Pure; no I/O.

Source table: 「초혼 신혼부부의 소득구간별 자녀 현황」 (first-marriage newlywed couples, married
within 5 years and still married, by the couple's combined annual earned + business income
bracket × number of children). Each yearly release (``Release.ref_year`` = reference year of the
statistics) is a PDF on the press-release board ``mods.go.kr/board.es?mid=a10301010000&bid=11815``.
Releases found on the board (2026-10-06): 2015 … 2024 reference years, all ten. The 2015-basis
release only tabulates couples with *wage* income (health-insurance workplace subscribers) ->
``income_concept = "wage_only"``; 2016+ use earned + business income (``"earned_business"``). The
2016-basis release re-tabulates 2015 on the earned + business basis, so ref_year 2015 exists under
both concepts.

Three table layouts are recognised (anything else raises ``ValueError`` = fail closed):
- ``COLUMNS``   (2020–2024 releases): income brackets are columns; rows 전체 / 자녀없음 / 자녀있음 /
  1명 / 2명 / 3명 이상 per year block; mean children either as a 「평균 자녀수(명)」 row (2024)
  or in a separate 「소득구간별 평균 자녀 수」 sub-table (2020–2023). The 2020 release prints
  couples in thousands (단위: 천 쌍) — converted to couples.
- ``ROWS_SHARE`` (2016–2019 releases): income brackets are rows with shares (%); couples in
  thousands in parentheses; mean children on the following page (「전체」 row of the
  맞벌이여부별 sub-table, or a year row).
- ``ROWS_COUNT`` (2015 release): income brackets are rows with counts (쌍) + a 구성비 row.

Shares are stored as fractions (0.512 = 51.2 %). Income bounds are in 만원 (10k KRW):
1천만원 = 1000, 1억원 = 10000; the open top bracket has ``upper = None``.
"""

import io
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from pypdf import PdfReader
from pypdf.errors import PdfReadError

SOURCE = "kostat_newlywed"
BOARD_URL = "https://mods.go.kr/board.es?mid=a10301010000&bid=11815"
# 국가데이터처 저작권정책 (https://mods.go.kr/menu.es?mid=a10706000000, checked 2026-10-06):
# press releases are 공공누리 (KOGL) 제1유형 — attribution only, commercial use and
# modification allowed.
LICENSE = (
    "KOGL Type 1 (공공누리 제1유형: 출처표시; https://www.kogl.or.kr/info/license.do). "
    "Attribution: 국가데이터처, 신혼부부통계 (<year>년 기준), 보도자료, mods.go.kr "
    "(https://mods.go.kr/menu.es?mid=a10706000000)"
)
POPULATION = "first_marriage_within_5y"
WAGE_ONLY_RELEASE_YEARS = frozenset({2015})


@dataclass(frozen=True)
class Release:
    """One press release (= one PDF). ``ref_year`` is the statistics' reference year."""

    ref_year: int
    list_no: int
    seq: int

    @property
    def url(self) -> str:
        return (
            f"https://mods.go.kr/boardDownload.es?bid=11815&list_no={self.list_no}&seq={self.seq}"
        )

    @property
    def raw_name(self) -> str:
        return f"newlywed_{self.ref_year}.pdf"

    @property
    def income_concept(self) -> str:
        return "wage_only" if self.ref_year in WAGE_ONLY_RELEASE_YEARS else "earned_business"


# list_no / seq taken from the board (search 「신혼부부」, 2026-10-06). Titles: 「<year>년 (기준)
# 신혼부부통계 결과」. Every reference year 2015–2024 has a PDF attachment.
RELEASES: tuple[Release, ...] = (
    Release(2015, 358364, 5),
    Release(2016, 365445, 15),
    Release(2017, 371980, 2),
    Release(2018, 379256, 10),
    Release(2019, 386554, 2),
    Release(2020, 415466, 2),
    Release(2021, 422173, 1),
    Release(2022, 428407, 3),
    Release(2023, 434122, 3),
    Release(2024, 442387, 3),
)


@dataclass(frozen=True)
class IncomeClass:
    key: str
    label: str  # canonical Korean label (whitespace-insensitive match)
    lower_10k_krw: int | None
    upper_10k_krw: int | None


INCOME_CLASSES: tuple[IncomeClass, ...] = (
    IncomeClass("total", "전체", None, None),
    IncomeClass("lt_1000", "1천만원 미만", 0, 1000),
    IncomeClass("1000_3000", "1천만원~3천만원 미만", 1000, 3000),
    IncomeClass("3000_5000", "3천만원~5천만원 미만", 3000, 5000),
    IncomeClass("5000_7000", "5천만원~7천만원 미만", 5000, 7000),
    IncomeClass("7000_10000", "7천만원~1억원 미만", 7000, 10000),
    IncomeClass("ge_10000", "1억원 이상", 10000, None),
)
N_CLASSES = len(INCOME_CLASSES)


class Layout(StrEnum):
    COLUMNS = "columns"
    ROWS_SHARE = "rows_share"
    ROWS_COUNT = "rows_count"


@dataclass(frozen=True)
class TableLocation:
    layout: Layout
    page_index: int


@dataclass(frozen=True)
class _YearBlock:
    """Parsed values for one reference year; every tuple has N_CLASSES entries (total first)."""

    ref_year: int
    couples: tuple[int, ...]
    no_children_pct: tuple[float, ...]
    with_children_pct: tuple[float, ...]
    children_1_pct: tuple[float, ...]
    children_2_pct: tuple[float, ...]
    children_3plus_pct: tuple[float, ...]
    mean_children: tuple[float, ...]


# ---- text extraction -----------------------------------------------------------------------


def pdf_text(payload: bytes) -> list[str]:
    """One text string per page (pypdf). Non-PDF payloads raise ``ValueError``."""
    if not payload.lstrip().startswith(b"%PDF"):
        msg = "payload is not a PDF (missing %PDF header)"
        raise ValueError(msg)
    try:
        reader = PdfReader(io.BytesIO(payload))
        return [page.extract_text() or "" for page in reader.pages]
    except PdfReadError as e:
        msg = f"unreadable PDF: {e}"
        raise ValueError(msg) from None


def _normalise(page: str) -> list[str]:
    """NFKC (～ -> ~, full-width digits/spaces), collapse inner whitespace, drop blank lines."""
    out: list[str] = []
    for raw in unicodedata.normalize("NFKC", page).splitlines():
        line = " ".join(raw.split())
        if line:
            out.append(line)
    return out


def _label_re(label: str) -> str:
    """Regex for a Korean label tolerant of arbitrary whitespace between characters."""
    return r"\s*".join(re.escape(ch) for ch in label.replace(" ", ""))


_TITLE_COLUMNS = re.compile(r"^\d+\.\s*초혼\s*신혼부부의\s*소득\s*구간별\s*자녀\s*현황$")
_TITLE_ROWS_SHARE = re.compile(
    r"^<\s*초혼\s*신혼부부의\s*소득\s*구간별\s*출산\s*현황(\s*분포)?\s*>$"
)
_TITLE_ROWS_COUNT = re.compile(
    r"^<\s*초혼\s*신혼부부\s*\(임금근로자\s*대상\)\s*의\s*소득수준별\s*출산\s*현황\s*>$"
)


def find_income_children_table(pages: Sequence[str]) -> TableLocation:
    """Locate the page carrying the income × children table and classify its layout.

    Table-of-contents lines (title followed by leaders and a page number) do not match because
    the title patterns are anchored at both ends.
    """
    for i, page in enumerate(pages):
        for line in _normalise(page):
            if _TITLE_COLUMNS.match(line):
                return TableLocation(Layout.COLUMNS, i)
            if _TITLE_ROWS_SHARE.match(line):
                return TableLocation(Layout.ROWS_SHARE, i)
            if _TITLE_ROWS_COUNT.match(line):
                return TableLocation(Layout.ROWS_COUNT, i)
    msg = "income x children table not found in any page"
    raise ValueError(msg)


# ---- shared number helpers ----------------------------------------------------------------

_INT = r"\d{1,3}(?:,\d{3})*|\d+"
_PCT = r"\(?-?\d+\.\d\)?"  # 47.5 or (47.5)
_MEAN = r"\d\.\d{2}"


def _ints(tokens: Iterable[str]) -> tuple[int, ...]:
    return tuple(int(t.replace(",", "")) for t in tokens)


def _pcts(tokens: Iterable[str]) -> tuple[float, ...]:
    return tuple(float(t.strip("()")) for t in tokens)


def _thousands(token: str) -> int:
    """'1,179.0' / '998' (thousand couples) -> couples."""
    return round(float(token.replace(",", "")) * 1000)


def _row_values(line: str, label_re: str, value_re: str, n: int) -> tuple[str, ...] | None:
    m = re.match(rf"^{label_re}\s+((?:{value_re})(?:\s+(?:{value_re})){{{n - 1}}})\s*$", line)
    return tuple(m.group(1).split()) if m else None


# ---- mean children (shared by COLUMNS and ROWS_SHARE) --------------------------------------

_YEAR_ONLY = re.compile(r"^(\d{4})년?$")
_YEAR_MEANS = re.compile(rf"^(\d{{4}})년\s+((?:{_MEAN})(?:\s+{_MEAN}){{{N_CLASSES - 1}}})$")
_TOTAL_MEANS = re.compile(rf"^전체\s+((?:{_MEAN})(?:\s+{_MEAN}){{{N_CLASSES - 1}}})$")
_INLINE_MEANS = re.compile(
    rf"^평균\s*자녀\s*수\s*\(명\)\s+((?:{_MEAN})(?:\s+{_MEAN}){{{N_CLASSES - 1}}})$"
)


def _join_split_mean_label(lines: list[str]) -> list[str]:
    """2024 release prints 「평균」 and 「자녀수(명) 0.61 …」 on two lines."""
    out: list[str] = []
    i = 0
    while i < len(lines):
        if lines[i] == "평균" and i + 1 < len(lines) and lines[i + 1].startswith("자녀"):
            out.append(f"평균 {lines[i + 1]}")
            i += 2
            continue
        out.append(lines[i])
        i += 1
    return out


def _mean_rows(lines: list[str]) -> dict[int, tuple[float, ...]]:
    """ref_year -> mean children per class, from the three published forms."""
    means: dict[int, tuple[float, ...]] = {}
    year: int | None = None
    for i, line in enumerate(lines):
        if m := _YEAR_ONLY.match(line):
            year = int(m.group(1))
            if i + 1 < len(lines) and (t := _TOTAL_MEANS.match(lines[i + 1])):
                means.setdefault(year, _pcts(t.group(1).split()))
            continue
        if m := _YEAR_MEANS.match(line):
            means.setdefault(int(m.group(1)), _pcts(m.group(2).split()))
            continue
        if (m := _INLINE_MEANS.match(line)) and year is not None:
            means.setdefault(year, _pcts(m.group(1).split()))
            continue
        if line.startswith("증감"):
            year = None
    return means


# ---- layout parsers ------------------------------------------------------------------------

_SHARE_ROWS: dict[str, str] = {
    "no": "자녀없음",
    "with": "자녀있음",
    "c1": "1명",
    "c2": "2명",
    "c3": "3명이상",
}


def _check_header(lines: list[str], *, start: int) -> int:
    """COLUMNS layout: the header between the title/unit lines and the first year line must
    list exactly the seven income classes in order. Returns the index of the first year line."""
    i = start
    while i < len(lines) and not _YEAR_ONLY.match(lines[i]):
        i += 1
    header = re.sub(r"\s+", "", "".join(lines[start:i]))
    header = header.split(")", 1)[-1] if header.startswith("(단위") else header
    expected = "".join(c.label.replace(" ", "") for c in INCOME_CLASSES)
    if not header.endswith(expected):
        msg = f"unexpected income-class header: {header!r}"
        raise ValueError(msg)
    return i


def _parse_columns(lines: list[str]) -> list[_YearBlock]:
    lines = _join_split_mean_label(lines)
    title = next(i for i, ln in enumerate(lines) if _TITLE_COLUMNS.match(ln))
    unit_thousands = any("천 쌍" in ln or "천쌍" in ln for ln in lines[title : title + 4])
    first_year = _check_header(lines, start=title + 1)
    means = _mean_rows(lines)
    blocks: list[_YearBlock] = []
    year: int | None = None
    couples: tuple[int, ...] | None = None
    shares: dict[str, tuple[float, ...]] = {}

    def flush() -> None:
        if year is None:
            return
        if couples is None or set(shares) != set(_SHARE_ROWS):
            msg = f"{year}: incomplete column table (rows found: {sorted(shares)})"
            raise ValueError(msg)
        if year not in means:
            msg = f"{year}: mean children row not found"
            raise ValueError(msg)
        blocks.append(
            _YearBlock(
                year,
                couples,
                shares["no"],
                shares["with"],
                shares["c1"],
                shares["c2"],
                shares["c3"],
                means[year],
            )
        )

    for line in lines[first_year:]:
        if m := _YEAR_ONLY.match(line):
            flush()
            year, couples, shares = int(m.group(1)), None, {}
            continue
        if year is None:
            continue
        if vals := _row_values(line, "전체", _INT, N_CLASSES):
            raw = _ints(vals)
            couples = tuple(v * 1000 for v in raw) if unit_thousands else raw
            continue
        for key, label in _SHARE_ROWS.items():
            if vals := _row_values(line, _label_re(label), _PCT, N_CLASSES):
                shares[key] = _pcts(vals)
                break
        else:
            if line.startswith("<") and shares:  # next sub-table / section
                flush()
                year = None
    flush()
    if not blocks:
        msg = "no year block parsed from the column layout"
        raise ValueError(msg)
    return blocks


_ROWS_SHARE_VALUES = re.compile(
    rf"^(?:100\.0\s+)?\((?P<couples>(?:{_INT})(?:\.\d)?)\)\s+(?:100\.0\s+)?"
    rf"(?P<rest>-?\d+\.\d(?:\s+-?\d+\.\d){{4}})$"
)


def _parse_rows_share(lines: list[str], next_page: list[str]) -> list[_YearBlock]:
    means = _mean_rows(lines + next_page)
    blocks: list[_YearBlock] = []
    year: int | None = None
    rows: dict[str, tuple[int, tuple[float, ...]]] = {}

    def flush() -> None:
        if year is None:
            return
        if set(rows) != {c.key for c in INCOME_CLASSES}:
            msg = f"{year}: incomplete row table (classes found: {sorted(rows)})"
            raise ValueError(msg)
        if year not in means:
            msg = f"{year}: mean children row not found"
            raise ValueError(msg)
        ordered = [rows[c.key] for c in INCOME_CLASSES]
        blocks.append(
            _YearBlock(
                year,
                tuple(r[0] for r in ordered),
                tuple(r[1][0] for r in ordered),
                tuple(r[1][1] for r in ordered),
                tuple(r[1][2] for r in ordered),
                tuple(r[1][3] for r in ordered),
                tuple(r[1][4] for r in ordered),
                means[year],
            )
        )

    for line in lines:
        if m := re.match(r"^(\d{4})년$", line):
            flush()
            year, rows = int(m.group(1)), {}
            continue
        if line.startswith("증감"):
            flush()
            year = None
            continue
        if year is None:
            continue
        for cls in INCOME_CLASSES:
            m = re.match(rf"^{_label_re(cls.label)}\s+(.*)$", line)
            if m and (v := _ROWS_SHARE_VALUES.match(m.group(1))):
                rows[cls.key] = (_thousands(v.group("couples")), _pcts(v.group("rest").split()))
                break
    flush()
    if not blocks:
        msg = "no year block parsed from the row layout"
        raise ValueError(msg)
    return blocks


def _parse_rows_count(lines: list[str], ref_year: int) -> list[_YearBlock]:
    """2015 release: '<label> 합계 자녀없음 소계 1명 2명 3명이상 평균(전체 맞벌이 외벌이)' then
    '(구성비)? (100.0) (no) (with) (1) (2) (3+)'. Labels may wrap onto two lines, so match on
    the space-joined page text."""
    text = " ".join(lines)
    rows: dict[str, tuple[int, tuple[float, ...], float]] = {}
    for cls in INCOME_CLASSES:
        label = "전국" if cls.key == "total" else cls.label
        pat = (
            rf"{_label_re(label)}\s+(?P<n>(?:{_INT})(?:\s+(?:{_INT})){{5}})\s+"
            rf"(?P<mean>{_MEAN})\s+{_MEAN}\s+{_MEAN}\s*(?:\(구성비\)\s*)?"
            rf"\(100\.0\)\s*(?P<p>(?:\(\d+\.\d\))(?:\s*\(\d+\.\d\)){{4}})"
        )
        m = re.search(pat, text)
        if m is None:
            continue
        n = _ints(m.group("n").split())
        pcts = _pcts(re.findall(r"\(([\d.]+)\)", m.group("p")))
        if n[1] + n[2] != n[0] or n[3] + n[4] + n[5] != n[2]:
            msg = f"{ref_year} {cls.key}: child counts do not add up to the total"
            raise ValueError(msg)
        rows[cls.key] = (n[0], pcts, float(m.group("mean")))
    if set(rows) != {c.key for c in INCOME_CLASSES}:
        msg = f"{ref_year}: incomplete count table (classes found: {sorted(rows)})"
        raise ValueError(msg)
    ordered = [rows[c.key] for c in INCOME_CLASSES]
    return [
        _YearBlock(
            ref_year,
            tuple(r[0] for r in ordered),
            tuple(r[1][0] for r in ordered),
            tuple(r[1][1] for r in ordered),
            tuple(r[1][2] for r in ordered),
            tuple(r[1][3] for r in ordered),
            tuple(r[1][4] for r in ordered),
            tuple(r[2] for r in ordered),
        )
    ]


# ---- validation + rows ---------------------------------------------------------------------


def _validate(block: _YearBlock) -> None:
    total, classes = block.couples[0], block.couples[1:]
    if abs(sum(classes) - total) > max(5, 0.002 * total):
        msg = f"{block.ref_year}: class couples {sum(classes)} do not sum to total {total}"
        raise ValueError(msg)
    for i, cls in enumerate(INCOME_CLASSES):
        no, with_ = block.no_children_pct[i], block.with_children_pct[i]
        parts = block.children_1_pct[i] + block.children_2_pct[i] + block.children_3plus_pct[i]
        if abs(no + with_ - 100.0) > 0.15 or abs(parts - with_) > 0.25:
            msg = (
                f"{block.ref_year} {cls.key}: shares do not add up "
                f"(none {no} + with {with_}; 1/2/3+ sum {parts:.1f})"
            )
            raise ValueError(msg)
        if not 0.0 <= block.mean_children[i] <= 3.0:
            msg = f"{block.ref_year} {cls.key}: implausible mean children {block.mean_children[i]}"
            raise ValueError(msg)


def _rows(blocks: Sequence[_YearBlock], release: Release) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for b in sorted(blocks, key=lambda b: b.ref_year):
        _validate(b)
        for i, cls in enumerate(INCOME_CLASSES):
            out.append(
                {
                    "release_year": release.ref_year,
                    "ref_year": b.ref_year,
                    "population": POPULATION,
                    "income_class": cls.key,
                    "income_lower_10k_krw": cls.lower_10k_krw,
                    "income_upper_10k_krw": cls.upper_10k_krw,
                    "couples": b.couples[i],
                    "with_children_share": b.with_children_pct[i] / 100,
                    "children_1_share": b.children_1_pct[i] / 100,
                    "children_2_share": b.children_2_pct[i] / 100,
                    "children_3plus_share": b.children_3plus_pct[i] / 100,
                    "mean_children": b.mean_children[i],
                    "income_concept": release.income_concept,
                    "source": SOURCE,
                }
            )
    return out


def income_children_rows_from_pages(
    pages: Sequence[str], release: Release
) -> list[dict[str, object]]:
    """Staged rows (one per ref_year × income class) from page texts. ``ValueError`` on any
    unrecognised layout, missing row, or inconsistent totals (fail closed; nothing imputed)."""
    loc = find_income_children_table(pages)
    lines = _normalise(pages[loc.page_index])
    next_page = _normalise(pages[loc.page_index + 1]) if loc.page_index + 1 < len(pages) else []
    if loc.layout is Layout.COLUMNS:
        blocks = _parse_columns(lines)
    elif loc.layout is Layout.ROWS_SHARE:
        blocks = _parse_rows_share(lines, next_page)
    else:
        blocks = _parse_rows_count(lines, release.ref_year)
    return _rows(blocks, release)


def income_children_rows(payload: bytes, release: Release) -> list[dict[str, object]]:
    return income_children_rows_from_pages(pdf_text(payload), release)
