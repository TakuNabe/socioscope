"""Ideal / intended / actual family size by country, transcribed from two PDF publications. Pure.

Two sources (H6), both static PDFs parsed with pypdf (page texts -> rows, fail closed):

- **Testa (2012)** *Family sizes in Europe: evidence from the 2011 Eurobarometer survey*, VID
  European Demographic Research Paper 2 (data: Eurobarometer 75.4, EU-27). Appendix tables
  A.2.1–A.2.4 (means by country × sex × age: 15-24 / 25-39 / 40-54 / 55+ / Total), A.2.5–A.2.8
  (distributions 0 / 1 / 2 / 3+ / [no ideal] / DK with N) and A.1.1 (low / high personal ideal,
  both sexes, ages 15-39 and 55+). Germany East / West rows are dropped (the all-Germany row is
  used); EU-27 rows are dropped. Shares are percentages as printed. Garbled rows in the extracted
  text (a handful of cells where pypdf interleaves digits) are *reported*, not guessed.
- **BiB (2025)** *Intended, ideal and actual fertility in 11 European countries* (GGS-II
  2020–23), Table 1: women 18–49 by country × age (18-29 / 30-39 / 40-49 / Total): mean actual,
  intended and (personal) ideal number of children and the three gaps; N per country. Survey
  years come from the table's source note.
"""

import re
from collections.abc import Iterable, Sequence

from theme_growth_fertility.kostat import pdf_text

TESTA_SOURCE = "testa2012_eb75_4"
TESTA_URL = (
    "https://www.oeaw.ac.at/fileadmin/subsites/Institute/VID/PDF/Publications/EDRP/edrp_2012_02.pdf"
)
TESTA_RAW = "testa2012_edrp_2012_02.pdf"
TESTA_LICENSE = (
    "Working paper, licence not stated: facts transcribed with citation; PDF not redistributed. "
    "Cite: Testa, M.R. (2012) Family sizes in Europe: evidence from the 2011 Eurobarometer "
    "survey. VID European Demographic Research Paper 2, Vienna Institute of Demography. "
    "Data: Eurobarometer 75.4 (2011), European Commission (CC BY 4.0)."
)
BIB_SOURCE = "bib2025_ggs2"
BIB_URL = (
    "https://www.bib.bund.de/Publikation/2025/pdf/Intended-ideal-and-actual-fertility-in-11-"
    "European-countries-Evidence-on-fertility-gaps-in-different-age-groups-from-the-Generations-"
    "and-Gender-Survey.pdf?__blob=publicationFile&v=2"
)
BIB_RAW = "bib2025_ggs2_fertility_gaps.pdf"
BIB_LICENSE = (
    "CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/). Cite: Bundesinstitut für "
    "Bevölkerungsforschung (2025) Intended, ideal and actual fertility in 11 European countries: "
    "Evidence on fertility gaps in different age groups from the Generations and Gender Survey. "
    "BiB Working Paper. Data: GGS-II (2020–2023), Generations and Gender Programme."
)
EB_SURVEY_YEAR = 2011

EB_COUNTRIES: dict[str, str] = {
    "Austria": "AUT",
    "Belgium": "BEL",
    "Bulgaria": "BGR",
    "Cyprus": "CYP",
    "Czech Rep.": "CZE",
    "Denmark": "DNK",
    "Estonia": "EST",
    "Finland": "FIN",
    "France": "FRA",
    "Germany": "DEU",
    "Greece": "GRC",
    "Hungary": "HUN",
    "Ireland": "IRL",
    "Italy": "ITA",
    "Latvia": "LVA",
    "Lithuania": "LTU",
    "Luxembourg": "LUX",
    "Malta": "MLT",
    "Netherlands": "NLD",
    "Poland": "POL",
    "Portugal": "PRT",
    "Romania": "ROU",
    "Slovakia": "SVK",
    "Slovenia": "SVN",
    "Spain": "ESP",
    "Sweden": "SWE",
    "United Kingdom": "GBR",
}
# Rows present in the tables but not staged (sub-national or aggregate).
_EB_DROP = ("Germany East", "Germany West", "East Germany", "West Germany", "EU-27")
# pypdf occasionally drops the second word of a two-word country name.
_EB_ALIASES = {"United": "United Kingdom", "Czech": "Czech Rep."}
EB_AGES: tuple[str, ...] = ("15-24", "25-39", "40-54", "55+", "total")
_EB_AGE_HEADER = "15-24 25-39 40-54 55+ Total"
_EB_SEXES: tuple[str, ...] = ("F", "M")
EB_MEAN_TABLES: dict[str, str] = {
    "A.2.1": "ideal_general_mean",
    "A.2.2": "ideal_personal_mean",
    "A.2.3": "actual_mean",
    "A.2.4": "intended_additional_mean",
}
# Distribution tables: (zero-share metric, columns, whether low/high shares are derived too).
# Columns: None / One / Two / Three or more [/ No ideal] / DK / N.cases.
_EB_DIST_TABLES: dict[str, tuple[str, int, bool]] = {
    "A.2.5": ("ideal_general_zero_share", 7, False),
    "A.2.6": ("ideal_zero_share", 7, True),
    "A.2.7": ("childless_share", 6, False),
    "A.2.8": ("intended_additional_zero_share", 6, False),
}
_MEAN_TITLE = re.compile(r"^Table (A\.2\.[1-4]) Mean ")
_DIST_TITLE = re.compile(r"^Table (A\.2\.[5-8]) Distribution ")
_A11_TITLE = re.compile(r"^Table A\.1\.1 Women and men with low and high")
_BLOCK_SEX = {"Women": "F", "Men": "M"}
_BLOCK_AGE = re.compile(r"^(15-24|25-39|40-54|55\+) years$|^(Total)$")


def _lines(page: str) -> list[str]:
    return [" ".join(raw.split()) for raw in page.splitlines() if raw.strip()]


def _fix_split_decimals(text: str) -> str:
    """'2. 07' -> '2.07' (pypdf inserts a space inside some numbers)."""
    return re.sub(r"(\d)\.\s+(\d)", r"\1.\2", text)


def _split_country_row(line: str) -> tuple[str, list[str]] | None:
    """'Czech Rep. 2.02 1.89 ...' -> ('Czech Rep.', ['2.02', ...]); None if not a data row."""
    m = re.match(r"^([A-Za-z][A-Za-z .\-]*?)\s+(\d.*)$", _fix_split_decimals(line))
    if m is None:
        return None
    name = m.group(1).strip()
    return _EB_ALIASES.get(name, name), m.group(2).split()


def _row(
    iso3: str,
    sex: str,
    age: str,
    metric: str,
    value: float | None,
    n: int | None,
    table: str,
) -> dict[str, object]:
    return {
        "iso3": iso3,
        "sex": sex,
        "age_class": age,
        "metric": metric,
        "value": value,
        "n": n,
        "source": TESTA_SOURCE,
        "table": table,
    }


def _country_rows(lines: Iterable[str], *, table: str) -> dict[str, list[str]]:
    """Country name -> value tokens for every EB_COUNTRIES row; fail closed if one is missing."""
    found: dict[str, list[str]] = {}
    for line in lines:
        parsed = _split_country_row(line)
        if parsed is None:
            continue
        name, values = parsed
        if name in EB_COUNTRIES and name not in found:
            found[name] = values
    missing = [c for c in EB_COUNTRIES if c not in found]
    if missing:
        msg = f"{table}: country rows missing: {missing}"
        raise ValueError(msg)
    return found


def _parse_mean_table(page: str, table: str, metric: str) -> list[dict[str, object]]:
    lines = _lines(page)
    if _EB_AGE_HEADER + " " + _EB_AGE_HEADER not in " ".join(lines[:6]):
        msg = f"{table}: expected columns 'Women/Men x {_EB_AGE_HEADER}' not found"
        raise ValueError(msg)
    out: list[dict[str, object]] = []
    for name, values in _country_rows(lines, table=table).items():
        if len(values) != 10 or not all(re.fullmatch(r"\d\.\d{1,2}", v) for v in values):
            msg = f"{table}: {name}: expected 10 means, got {values}"
            raise ValueError(msg)
        iso3 = EB_COUNTRIES[name]
        for i, v in enumerate(values):
            out.append(_row(iso3, _EB_SEXES[i // 5], EB_AGES[i % 5], metric, float(v), None, table))
    return out


def _parse_a11(page: str) -> list[dict[str, object]]:
    lines = _lines(page)
    head = " ".join(lines[:6])
    if "0 1 2 3+ 0 1 2 3+" not in head or "Ages 15-39 Ages 55+" not in head:
        msg = "A.1.1: expected columns '0 1 2 3+' for ages 15-39 and 55+ not found"
        raise ValueError(msg)
    out: list[dict[str, object]] = []
    for name, values in _country_rows(lines, table="A.1.1").items():
        if len(values) != 8 or not all(v.isdigit() for v in values):
            msg = f"A.1.1: {name}: expected 8 percentages, got {values}"
            raise ValueError(msg)
        iso3 = EB_COUNTRIES[name]
        for age, chunk in (("15-39", values[:4]), ("55+", values[4:])):
            zero, one, _two, three = (float(v) for v in chunk)
            out.append(_row(iso3, "T", age, "ideal_zero_share", zero, None, "A.1.1"))
            out.append(_row(iso3, "T", age, "ideal_low_share", zero + one, None, "A.1.1"))
            out.append(_row(iso3, "T", age, "ideal_high_share", three, None, "A.1.1"))
    return out


def _dist_blocks(lines: Sequence[str]) -> list[tuple[str, str, list[str]]]:
    """Split a distribution page into (sex, age, lines) blocks headed by 'Women'/'Men' + age."""
    blocks: list[tuple[str, str, list[str]]] = []
    i = 0
    while i < len(lines):
        if lines[i] in _BLOCK_SEX and i + 1 < len(lines) and _BLOCK_AGE.match(lines[i + 1]):
            sex = _BLOCK_SEX[lines[i]]
            m = _BLOCK_AGE.match(lines[i + 1])
            assert m is not None
            age = "total" if m.group(2) else m.group(1)
            body: list[str] = []
            i += 2
            while i < len(lines) and lines[i] not in _BLOCK_SEX:
                body.append(lines[i])
                i += 1
            blocks.append((sex, age, body))
        else:
            i += 1
    return blocks


def _parse_dist_page(
    page: str, table: str, issues: list[str]
) -> tuple[list[dict[str, object]], int]:
    """Rows + number of blocks on this page. Garbled country rows go to *issues*."""
    metric, ncol, derive = _EB_DIST_TABLES[table]
    lines = _lines(page)
    blocks = _dist_blocks(lines)
    out: list[dict[str, object]] = []
    for sex, age, body in blocks:
        seen: set[str] = set()
        for line in body:
            parsed = _split_country_row(line)
            if parsed is None:
                continue
            name, values = parsed
            if name not in EB_COUNTRIES:
                # Germany East/West, EU-27, or a garbled name ("M a l t a 9 9 0010 7 4")
                compact = name.replace(" ", "")
                if compact in EB_COUNTRIES and name not in _EB_DROP:
                    issues.append(f"{table} {sex} {age}: garbled row for {compact}: {line!r}")
                    seen.add(compact)
                continue
            seen.add(name)
            if len(values) != ncol or not all(v.isdigit() for v in values):
                issues.append(f"{table} {sex} {age}: garbled row for {name}: {line!r}")
                continue
            iso3 = EB_COUNTRIES[name]
            n = int(values[-1])
            out.append(_row(iso3, sex, age, metric, float(values[0]), n, table))
            if derive:
                low = float(values[0]) + float(values[1])
                out.append(_row(iso3, sex, age, "ideal_low_share", low, n, table))
                out.append(_row(iso3, sex, age, "ideal_high_share", float(values[3]), n, table))
        missing = [c for c in EB_COUNTRIES if c not in seen]
        if missing:
            msg = f"{table} {sex} {age}: country rows missing: {missing}"
            raise ValueError(msg)
    return out, len(blocks)


def eb2011_rows_from_pages(pages: Sequence[str]) -> tuple[list[dict[str, object]], list[str]]:
    """Testa (2012) appendix page texts -> (rows, issues). Missing tables raise ValueError."""
    rows: list[dict[str, object]] = []
    issues: list[str] = []
    seen_means: set[str] = set()
    dist_blocks: dict[str, int] = dict.fromkeys(_EB_DIST_TABLES, 0)
    a11 = False
    current_dist: str | None = None
    for page in pages:
        first = next(iter(_lines(page)[:3]), "")
        titles = [ln for ln in _lines(page)[:3] if ln.startswith("Table A.")]
        title = titles[0] if titles else first
        if (m := _MEAN_TITLE.match(title)) and m.group(1) not in seen_means:
            table = m.group(1)
            rows.extend(_parse_mean_table(page, table, EB_MEAN_TABLES[table]))
            seen_means.add(table)
            current_dist = None
        elif m := _DIST_TITLE.match(title):
            current_dist = m.group(1)
        elif _A11_TITLE.match(title):
            rows.extend(_parse_a11(page))
            a11 = True
            current_dist = None
        elif not title.startswith("Table A.2") or "(Continued)" not in title:
            current_dist = None
        if current_dist is not None:
            page_rows, nblocks = _parse_dist_page(page, current_dist, issues)
            rows.extend(page_rows)
            dist_blocks[current_dist] += nblocks
    if not seen_means and not a11 and not any(dist_blocks.values()):
        msg = "Testa 2012 appendix tables not found in any page"
        raise ValueError(msg)
    for table in EB_MEAN_TABLES:
        if table not in seen_means:
            msg = f"Table {table} (mean) not found"
            raise ValueError(msg)
    if not a11:
        msg = "Table A.1.1 not found"
        raise ValueError(msg)
    for table, n in dist_blocks.items():
        if n != 10:
            msg = f"Table {table}: expected 10 sex x age blocks, found {n}"
            raise ValueError(msg)
    return rows, issues


def eb2011_rows(payload: bytes) -> tuple[list[dict[str, object]], list[str]]:
    return eb2011_rows_from_pages(pdf_text(payload))


# ---- BiB 2025 / GGS-II Table 1 -----------------------------------------------------------

GGS_COUNTRIES: tuple[tuple[str, str], ...] = (
    ("Germany", "DEU"),
    ("Austria", "AUT"),
    ("Netherlands", "NLD"),
    ("Czech Republic", "CZE"),
    ("Croatia", "HRV"),
    ("Estonia", "EST"),
    ("Norway", "NOR"),
    ("Denmark", "DNK"),
    ("Finland", "FIN"),
    ("Moldova", "MDA"),
    ("United Kingdom", "GBR"),
)
_GGS_HEADER = (
    "Germany Austria Netherlands Czech Croatia Estonia Norway Denmark Finland Moldova United"
)
GGS_AGES: tuple[str, ...] = ("18-29", "30-39", "40-49", "total")
GGS_BLOCKS: dict[str, str] = {
    "Gap intended-actual fertility": "gap_intended_actual",
    "Gap ideal-actual fertility": "gap_ideal_actual",
    "Gap ideal-intended fertility": "gap_ideal_intended",
    "Actual number of children": "actual_mean",
    "Intended number of children": "intended_total_mean",
    "Ideal number of children": "ideal_personal_mean",
}
_GGS_TITLE = "Table 1: Mean fertility gaps and mean actual, intended, and ideal number of children"
_GGS_SOURCE_RE = re.compile(r"GGS-II ([A-Za-z ]+?) \((\d{4})(?:-(\d{4}))?\)")


def _ggs_fieldwork(text: str) -> dict[str, str]:
    """Country name -> '2021-2022' from the 'Source: GGS-II Germany (2021-2022), ...' note."""
    out: dict[str, str] = {}
    for m in _GGS_SOURCE_RE.finditer(text):
        name = " ".join(m.group(1).split())
        out[name] = m.group(2) if m.group(3) is None else f"{m.group(2)}-{m.group(3)}"
    return out


def ggs_rows_from_pages(pages: Sequence[str]) -> list[dict[str, object]]:
    """BiB (2025) Table 1 page text -> long rows (women 18-49). Layout changes raise ValueError."""
    page = next((p for p in pages if _GGS_TITLE in " ".join(p.split())), None)
    if page is None:
        msg = "BiB 2025 Table 1 not found in any page"
        raise ValueError(msg)
    lines = _lines(page)
    if _GGS_HEADER not in lines:
        msg = f"Table 1: expected the 11 countries header {_GGS_HEADER!r}"
        raise ValueError(msg)
    fieldwork = _ggs_fieldwork(" ".join(lines))
    missing = [name for name, _ in GGS_COUNTRIES if name not in fieldwork]
    if missing:
        msg = f"Table 1: fieldwork years missing in the source note for {missing}"
        raise ValueError(msg)
    n_by_country: dict[str, int] = {}
    obs = next((ln for ln in lines if ln.startswith("Observations ")), None)
    if obs is not None:
        tokens = obs.split()[1:]
        if len(tokens) == len(GGS_COUNTRIES):
            n_by_country = {
                iso3: int(t.replace(",", ""))
                for (_, iso3), t in zip(GGS_COUNTRIES, tokens, strict=True)
            }
    if len(n_by_country) != len(GGS_COUNTRIES):
        msg = "Table 1: 'Observations' row with 11 counts not found"
        raise ValueError(msg)
    out: list[dict[str, object]] = []
    for block, metric in GGS_BLOCKS.items():
        if block not in lines:
            msg = f"Table 1: block {block!r} not found"
            raise ValueError(msg)
        start = lines.index(block) + 1
        for age in GGS_AGES:
            label = "Total" if age == "total" else age
            line = (
                lines[start + GGS_AGES.index(age)]
                if start + GGS_AGES.index(age) < len(lines)
                else ""
            )
            tokens = line.split()
            if (
                not tokens
                or tokens[0] != label
                or len(tokens) != 1 + len(GGS_COUNTRIES)
                or not all(re.fullmatch(r"\d\.\d{2}", t) for t in tokens[1:])
            ):
                msg = f"Table 1: {block!r} row {label!r} malformed: {line!r}"
                raise ValueError(msg)
            for (name, iso3), v in zip(GGS_COUNTRIES, tokens[1:], strict=True):
                fw = fieldwork[name]
                out.append(
                    {
                        "iso3": iso3,
                        "survey_year": int(fw[:4]),
                        "fieldwork": fw,
                        "sex": "F",
                        "age_class": age,
                        "metric": metric,
                        "value": float(v),
                        "n": n_by_country[iso3] if age == "total" else None,
                        "source": BIB_SOURCE,
                    }
                )
    return out


def ggs_rows(payload: bytes) -> list[dict[str, object]]:
    return ggs_rows_from_pages(pdf_text(payload))


# ---- mart -------------------------------------------------------------------------------


def build_ideals_mart(
    eb_rows: Sequence[dict[str, object]], ggs_rows: Sequence[dict[str, object]]
) -> list[dict[str, object]]:
    """Long table across both surveys. Pure; sorted by source, iso3, sex, age_class, metric."""
    out: list[dict[str, object]] = []
    for r in eb_rows:
        out.append(
            {
                "source": "eb2011",
                "iso3": r["iso3"],
                "survey_year": EB_SURVEY_YEAR,
                "sex": r["sex"],
                "age_class": r["age_class"],
                "metric": r["metric"],
                "value": r["value"],
                "n": r["n"],
                "table": r["table"],
            }
        )
    for r in ggs_rows:
        out.append(
            {
                "source": "ggs2020",
                "iso3": r["iso3"],
                "survey_year": r["survey_year"],
                "sex": r["sex"],
                "age_class": r["age_class"],
                "metric": r["metric"],
                "value": r["value"],
                "n": r["n"],
                "table": "Table 1",
            }
        )
    out.sort(
        key=lambda r: (
            str(r["source"]),
            str(r["iso3"]),
            str(r["sex"]),
            str(r["age_class"]),
            str(r["metric"]),
        )
    )
    return out
