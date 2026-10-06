"""Standard Eurobarometer, "expectations for the next twelve months" by country. Pure; no I/O.

Source: the Volume A ("VOL A", weighted country tables) workbook of each Standard Eurobarometer
wave, distributed through data.europa.eu. Two-step resolution: the dataset's JSON-LD record
(``Wave.jsonld_url``, hub repo API) lists the distributions; ``vol_a`` picks the Volume A file
and its static download URL (``webgate.ec.europa.eu/.../odp/download?key=...``; no key or
login needed). Waves are pinned in ``WAVES`` (dataset ids found with the hub search API on
2026-10-06: ``.../api/hub/search/search?q=Standard%20Eurobarometer``); fetch never searches.

Workbook layout (checked on STD91–STD105): one sheet per item; the question text is in the
first rows ("What are your expectations for the next twelve/12 months: will the next twelve
months be better, worse or the same, when it comes to...?"), the English item label below it,
then a header row of country codes (EU27 aggregate first; ``D-W``/``D-E`` beside ``DE``), a
``Total`` row of weighted counts, and for each answer a French row (counts) followed by an
English row (shares as fractions): ``Better`` / ``Worse`` / ``The same`` or ``Same`` /
``Don't know`` or ``DK``. STD91–92 ship a legacy ``.xls`` (inside a zip), STD93 a zip with an
``.xlsx``, STD94+ a bare ``.xlsx``. Shares are stored as percentages; ``-`` (no respondents)
is 0. Sheets whose question is not the expectations item are ignored; a wave with no matching
sheet yields no rows (the pipeline reports it as skipped).

Licence: Commission reuse policy (Decision 2011/833/EU, equivalent to CC BY 4.0; the JSON-LD
records ``licence/CC_BY_4_0``).
"""

import io
import json
import re
import zipfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

import openpyxl
import xlrd
from xlrd.biffh import XLRDError

SOURCE = "eurobarometer_std"
LICENSE = (
    "European Commission reuse policy, Decision 2011/833/EU (CC BY 4.0 equivalent; "
    "https://commission.europa.eu/legal-notice_en). Attribution: European Commission, "
    "Standard Eurobarometer <wave>, Volume A, via data.europa.eu."
)
HUB_REPO = "https://data.europa.eu/api/hub/repo/datasets"


@dataclass(frozen=True)
class Wave:
    """One Standard Eurobarometer wave. ``fieldwork_year``/``fieldwork_half`` is the survey's
    season (Spring/Summer = 1, Autumn/Winter = 2, winter waves keyed to the first year), which
    is unique per wave; ``fieldwork_start`` is the actual first month of fieldwork."""

    code: str
    dataset_id: str
    fieldwork_year: int
    fieldwork_half: int
    fieldwork_start: str

    @property
    def jsonld_url(self) -> str:
        return f"{HUB_REPO}/{self.dataset_id}.jsonld"

    @property
    def meta_raw_name(self) -> str:
        return f"eb_{self.code}_meta.json"


# All Standard Eurobarometer waves published on data.europa.eu from Spring 2019 on (none
# missing as of 2026-10-06). Fieldwork months read from the workbooks' "Terrain/Fieldwork" line.
WAVES: tuple[Wave, ...] = (
    Wave("STD91", "s2253_91_5_std91_eng", 2019, 1, "2019-06"),
    Wave("STD92", "s2255_92_3_std92_eng", 2019, 2, "2019-11"),
    Wave("STD93", "s2262_93_1_93_1_eng", 2020, 1, "2020-07"),
    Wave("STD94", "s2355_94_1_std94_eng", 2020, 2, "2021-02"),
    Wave("STD95", "s2532_95_3_95_eng", 2021, 1, "2021-06"),
    Wave("STD96", "s2553_96_3_std96_eng", 2021, 2, "2022-01"),
    Wave("STD97", "s2693_97_5_std97_eng", 2022, 1, "2022-06"),
    Wave("STD98", "s2872_98_2_std98_eng", 2022, 2, "2023-01"),
    Wave("STD99", "s3052_99_4_std99_eng", 2023, 1, "2023-05"),
    Wave("STD100", "s3053_100_2_std100_eng", 2023, 2, "2023-10"),
    Wave("STD101", "s3216_101_3_std101_eng", 2024, 1, "2024-04"),
    Wave("STD102", "s3215_102_2_std102_eng", 2024, 2, "2024-10"),
    Wave("STD103", "s3372_103_3_std103_eng", 2025, 1, "2025-03"),
    Wave("STD104", "s3378_104_1_std104_eng", 2025, 2, "2025-10"),
    Wave("STD105", "s3613_105_2_std105_eng", 2026, 1, "2026-03"),
)

ITEMS: dict[str, str] = {
    "your life in general": "life_general",
    "the financial situation of your household": "household_finance",
    "the economic situation in (our country)": "national_economy",
    "the state of (our country)'s economy": "national_economy",  # STD100 wording
    "the employment situation in (our country)": "employment_situation",
}
CODE_TO_ISO3: dict[str, str] = {
    "BE": "BEL", "BG": "BGR", "CZ": "CZE", "DK": "DNK", "DE": "DEU", "EE": "EST", "IE": "IRL",
    "EL": "GRC", "ES": "ESP", "FR": "FRA", "HR": "HRV", "IT": "ITA", "CY": "CYP", "LV": "LVA",
    "LT": "LTU", "LU": "LUX", "HU": "HUN", "MT": "MLT", "NL": "NLD", "AT": "AUT", "PL": "POL",
    "PT": "PRT", "RO": "ROU", "SI": "SVN", "SK": "SVK", "FI": "FIN", "SE": "SWE", "UK": "GBR",
    "TR": "TUR", "MK": "MKD", "ME": "MNE", "RS": "SRB", "AL": "ALB", "MD": "MDA", "BA": "BIH",
    "GE": "GEO", "CH": "CHE", "NO": "NOR", "IS": "ISL", "UA": "UKR", "AM": "ARM",
}  # fmt: skip
# Header cells that are not countries we keep: aggregates, German halves, non-ISO entities.
_QUESTION = re.compile(r"expectations for the next (?:twelve|12) months", re.I)
_CODE = re.compile(r"^[A-Z]{2}$")
_HEADER_MARK = re.compile(r"^(UE\d{2}|CY ?\(TCC\))")
_LABELS: dict[str, str] = {
    "better": "better_share",
    "worse": "worse_share",
    "same": "same_share",
    "the same": "same_share",
    "dk": "dk_share",
    "don't know": "dk_share",
    "don’t know": "dk_share",
}
_APOSTROPHES = str.maketrans({"’": "'", "‘": "'"})
_VOL_A = re.compile(r"vol(?:ume)?[_ ]?A(?:_xls)?\.(zip|xlsx?)$", re.I)


# ---- JSON-LD -> Volume A distribution ----------------------------------------------------


@dataclass(frozen=True)
class Distribution:
    filename: str
    url: str

    def raw_name(self, wave_code: str) -> str:
        ext = self.filename.rsplit(".", 1)[-1].lower()
        return f"eb_{wave_code}_vol_a.{ext}"


def _titles(node: dict[str, object]) -> list[str]:
    title = node.get("dct:title")
    if isinstance(title, str):
        return [title]
    if isinstance(title, dict):
        return [str(title.get("@value", ""))]
    if isinstance(title, list):
        return [
            str(t.get("@value", ""))
            for t in title
            if isinstance(t, dict) and t.get("@language") in ("en", None)
        ]
    return []


def vol_a(jsonld_payload: bytes) -> Distribution:
    """Pick the Volume A distribution (static download URL) out of a dataset's JSON-LD."""
    try:
        doc = json.loads(jsonld_payload)
    except ValueError:
        msg = "dataset record is not JSON-LD"
        raise ValueError(msg) from None
    graph = doc.get("@graph") if isinstance(doc, dict) else None
    if not isinstance(graph, list):
        msg = "dataset record is not JSON-LD (no @graph)"
        raise ValueError(msg)
    found: list[Distribution] = []
    for node in graph:
        if not isinstance(node, dict) or "Distribution" not in str(node.get("@type")):
            continue
        for title in _titles(node):
            if _VOL_A.search(title):
                access = node.get("dcat:accessURL")
                url = access.get("@id") if isinstance(access, dict) else access
                filename = re.sub(r"^Link to ", "", title).strip()
                found.append(Distribution(filename=filename, url=str(url)))
                break
    if not found:
        msg = "no Volume A distribution in the dataset record"
        raise ValueError(msg)
    if len(found) > 1:
        msg = f"{len(found)} Volume A distributions in the dataset record: {found}"
        raise ValueError(msg)
    return found[0]


# ---- workbook -> rows -------------------------------------------------------------------

Grid = list[list[object]]
_MAX_ROWS = 40


def _xlsx_sheets(data: bytes) -> Iterator[tuple[str, Grid]]:
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        for ws in wb.worksheets:
            rows = [list(r) for r in ws.iter_rows(min_row=1, max_row=_MAX_ROWS, values_only=True)]
            yield ws.title, rows
    finally:
        wb.close()


def _xls_sheets(data: bytes) -> Iterator[tuple[str, Grid]]:
    try:
        book = xlrd.open_workbook(file_contents=data)
    except XLRDError:
        msg = "payload is not an Excel workbook"
        raise ValueError(msg) from None
    for sheet in book.sheets():
        rows: Grid = []
        for r in range(min(sheet.nrows, _MAX_ROWS)):
            rows.append(
                [
                    None if sheet.cell_value(r, c) == "" else sheet.cell_value(r, c)
                    for c in range(sheet.ncols)
                ]
            )
        yield sheet.name, rows


def workbook_sheets(payload: bytes) -> list[tuple[str, Grid]]:
    """(sheet name, first rows) for an .xlsx / legacy .xls, possibly wrapped in a zip."""
    if zipfile.is_zipfile(io.BytesIO(payload)):
        with zipfile.ZipFile(io.BytesIO(payload)) as z:
            names = z.namelist()
            if "[Content_Types].xml" in names:
                return list(_xlsx_sheets(payload))
            members = [n for n in names if _VOL_A.search(n)]
            if len(members) != 1:
                msg = f"zip does not contain exactly one Volume A workbook: {names}"
                raise ValueError(msg)
            return workbook_sheets(z.read(members[0]))
    if payload[:2] in (b"\xd0\xcf", b"\x09\x08"):
        return list(_xls_sheets(payload))
    msg = "payload is not an Excel workbook"
    raise ValueError(msg)


def _text(cell: object) -> str:
    return " ".join(str(cell).split()) if cell is not None else ""


def _item_of(rows: Grid) -> str | None:
    """Item key if this sheet is one of the four expectations items we keep, else None."""
    q_row = next(
        (i for i, row in enumerate(rows[:8]) if any(_QUESTION.search(_text(c)) for c in row)),
        None,
    )
    if q_row is None:
        return None
    for row in rows[q_row + 1 : q_row + 4]:
        cells = [_text(c) for c in row if _text(c)]
        if cells:
            return ITEMS.get(cells[-1].lower().translate(_APOSTROPHES))
    return None


def _share(cell: object, *, sheet: str, label: str) -> float | None:
    if cell is None:
        return None
    if isinstance(cell, (int, float)) and not isinstance(cell, bool):
        if not 0 <= float(cell) <= 1:
            msg = f"{sheet}: {label}: expected a share in [0, 1], got {cell!r}"
            raise ValueError(msg)
        return round(float(cell) * 100, 2)
    if _text(cell) == "-":
        return 0.0
    msg = f"{sheet}: {label}: unexpected cell {cell!r}"
    raise ValueError(msg)


def _is_header(row: list[object]) -> bool:
    """Country header: starts with the EU aggregate ("UE27 EU27"), or is a CY(tcc)-only table
    (STD93 repeats the items for the Turkish Cypriot Community), or has several ISO2 codes."""
    texts = [_text(c).upper() for c in row]
    codes = sum(bool(_CODE.match(t)) for t in texts)
    return any(_HEADER_MARK.match(t) for t in texts) or codes >= 5


def _is_share_row(row: list[object], columns: dict[int, str]) -> bool:
    values: list[float] = []
    for c in columns:
        v = row[c] if c < len(row) else None
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            values.append(float(v))
    return bool(values) and all(0 <= v <= 1 for v in values)


def _parse_sheet(sheet: str, rows: Grid, item: str, wave: Wave) -> list[dict[str, object]]:
    header = next((row for row in rows if _is_header(row)), None)
    if header is None:
        msg = f"{sheet}: country header row not found"
        raise ValueError(msg)
    columns = {i: CODE_TO_ISO3[_text(c)] for i, c in enumerate(header) if _text(c) in CODE_TO_ISO3}
    if not columns:
        return []  # e.g. a CY(tcc)-only table: nothing we keep
    shares: dict[str, list[object]] = {}
    for i, grid_row in enumerate(rows):
        first = next((str(c) for c in grid_row if _text(c)), "")
        # STD93 puts both languages in one cell ("Meilleurs\nBetter"); the English label is last
        key = _LABELS.get(_text(first.splitlines()[-1]).lower()) if first else None
        if key is None or key in shares:
            continue
        # shares are fractions; if this row holds counts, the shares are on the next row
        candidates = [grid_row] + ([rows[i + 1]] if i + 1 < len(rows) else [])
        shares[key] = next((c for c in candidates if _is_share_row(c, columns)), grid_row)
    for key in ("better_share", "worse_share", "same_share", "dk_share"):
        if key not in shares:
            label = key.removesuffix("_share").capitalize()
            msg = f"{sheet}: answer row {label!r} not found"
            raise ValueError(msg)
    out: list[dict[str, object]] = []
    for col, iso3 in columns.items():
        row: dict[str, object] = {
            "iso3": iso3,
            "wave": wave.code,
            "fieldwork_year": wave.fieldwork_year,
            "fieldwork_half": wave.fieldwork_half,
            "fieldwork_start": wave.fieldwork_start,
            "item": item,
        }
        for key, cells in shares.items():
            cell = cells[col] if col < len(cells) else None
            row[key] = _share(cell, sheet=sheet, label=key)
        row["source"] = SOURCE
        out.append(row)
    return out


def expectation_rows(payload: bytes, wave: Wave) -> list[dict[str, object]]:
    """Volume A workbook -> one row per country × item. Empty if the question is absent."""
    out: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for sheet, rows in workbook_sheets(payload):
        item = _item_of(rows)
        if item is None:
            continue
        for r in _parse_sheet(sheet, rows, item, wave):
            k = (str(r["iso3"]), item)
            if k in seen:
                msg = f"{sheet}: duplicate country {k[0]} for item {item}"
                raise ValueError(msg)
            seen.add(k)
            out.append(r)
    return out


# ---- mart -------------------------------------------------------------------------------


def build_expectations_mart(rows: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    """Staged rows + ``net_optimism`` = better − worse; sorted by iso3, season, item. Pure."""
    out: list[dict[str, object]] = []
    for r in rows:
        better, worse = r["better_share"], r["worse_share"]
        net = (
            None
            if better is None or worse is None
            else round(float(str(better)) - float(str(worse)), 2)
        )
        out.append({**r, "net_optimism": net})
    out.sort(
        key=lambda r: (
            str(r["iso3"]),
            int(str(r["fieldwork_year"])),
            int(str(r["fieldwork_half"])),
            str(r["item"]),
        )
    )
    return out
