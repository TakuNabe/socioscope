"""surveys.py: ideal / intended / actual family size tables transcribed from two PDFs (pure).

Fixtures are pypdf page texts (form-feed separated): Testa (2012) Appendix pages (Table A.1.1 and
A.2.1–A.2.8) and BiB (2025) Table 1. The PDFs themselves are not committed.
"""

from pathlib import Path

import pytest

from theme_growth_fertility import surveys

FIXTURES = Path(__file__).parent / "fixtures"
EU27 = {
    "AUT", "BEL", "BGR", "CYP", "CZE", "DEU", "DNK", "ESP", "EST", "FIN", "FRA", "GBR", "GRC",
    "HUN", "IRL", "ITA", "LTU", "LUX", "LVA", "MLT", "NLD", "POL", "PRT", "ROU", "SVK", "SVN",
    "SWE",
}  # fmt: skip
GGS11 = {"DEU", "AUT", "NLD", "CZE", "HRV", "EST", "NOR", "DNK", "FIN", "MDA", "GBR"}


def eb_pages() -> list[str]:
    return (FIXTURES / "testa2012_appendix.txt").read_text(encoding="utf-8").split("\f")


def bib_pages() -> list[str]:
    return (FIXTURES / "bib2025_table1.txt").read_text(encoding="utf-8").split("\f")


def pick(
    rows: list[dict[str, object]], **where: object
) -> dict[tuple[object, ...], dict[str, object]]:
    out = [r for r in rows if all(r[k] == v for k, v in where.items())]
    return {(r["iso3"], r["sex"], r["age_class"]): r for r in out}


# ---------------------------------------------------------------- constants


def test_sources_and_licenses_are_explicit() -> None:
    assert surveys.TESTA_URL.startswith("https://www.oeaw.ac.at/") and surveys.TESTA_URL.endswith(
        "edrp_2012_02.pdf"
    )
    assert surveys.BIB_URL.startswith("https://www.bib.bund.de/Publikation/2025/pdf/")
    assert surveys.TESTA_SOURCE == "testa2012_eb75_4" and surveys.BIB_SOURCE == "bib2025_ggs2"
    assert "not redistributed" in surveys.TESTA_LICENSE and "Testa" in surveys.TESTA_LICENSE
    assert "Eurobarometer 75.4" in surveys.TESTA_LICENSE
    assert "CC BY-SA 4.0" in surveys.BIB_LICENSE
    assert surveys.TESTA_RAW.endswith(".pdf") and surveys.BIB_RAW.endswith(".pdf")


# ---------------------------------------------------------------- Testa 2012 (EB 75.4)


def test_eb_mean_tables_cover_27_countries_by_sex_and_age() -> None:
    rows, issues = surveys.eb2011_rows_from_pages(eb_pages())
    means = [r for r in rows if str(r["metric"]).endswith("_mean")]
    assert {r["metric"] for r in means} == {
        "ideal_general_mean",
        "ideal_personal_mean",
        "actual_mean",
        "intended_additional_mean",
    }
    assert len(means) == 4 * 27 * 2 * 5
    assert {r["iso3"] for r in means} == EU27
    assert {r["sex"] for r in means} == {"F", "M"}
    assert {r["age_class"] for r in means} == {"15-24", "25-39", "40-54", "55+", "total"}
    assert {r["source"] for r in rows} == {"testa2012_eb75_4"}
    assert set(rows[0]) == {"iso3", "sex", "age_class", "metric", "value", "n", "source", "table"}


def test_eb_personal_ideal_women_total_matches_table_a22() -> None:
    rows, _ = surveys.eb2011_rows_from_pages(eb_pages())
    ideal = pick(rows, metric="ideal_personal_mean", sex="F", age_class="total")
    got = {k[0]: r["value"] for k, r in ideal.items()}
    assert got["DNK"] == 2.55 and got["FIN"] == 2.50 and got["SWE"] == 2.41
    assert got["ITA"] == 2.02 and got["ESP"] == 2.27 and got["PRT"] == 2.11 and got["AUT"] == 1.95
    assert got["DEU"] == 2.27  # the all-Germany row, not East/West
    assert ideal[("DEU", "F", "total")]["table"] == "A.2.2"
    # "2. 24" (space inside the number in the extracted text) is normalised
    assert pick(rows, metric="ideal_personal_mean")[("CZE", "F", "55+")]["value"] == 2.24
    assert pick(rows, metric="ideal_general_mean")[("CZE", "F", "55+")]["value"] == 2.07
    assert pick(rows, metric="actual_mean")[("AUT", "M", "25-39")]["value"] == 0.61
    assert pick(rows, metric="intended_additional_mean")[("AUT", "F", "total")]["value"] == 0.35
    assert all(r["n"] is None for r in rows if str(r["metric"]).endswith("_mean"))


def test_eb_low_high_ideal_shares_from_table_a11_both_sexes() -> None:
    rows, _ = surveys.eb2011_rows_from_pages(eb_pages())
    a11 = [r for r in rows if r["table"] == "A.1.1"]
    assert len(a11) == 27 * 2 * 3
    assert {r["sex"] for r in a11} == {"T"}
    assert {r["age_class"] for r in a11} == {"15-39", "55+"}
    at = pick(a11, metric="ideal_zero_share")[("AUT", "T", "15-39")]
    assert at["value"] == 9.0 and at["n"] is None
    assert pick(a11, metric="ideal_low_share")[("AUT", "T", "15-39")]["value"] == 24.0  # 9 + 15
    assert pick(a11, metric="ideal_high_share")[("AUT", "T", "15-39")]["value"] == 13.0
    assert pick(a11, metric="ideal_high_share")[("IRL", "T", "55+")]["value"] == 58.0


def test_eb_distribution_tables_give_zero_shares_with_n_and_report_garbled_rows() -> None:
    rows, issues = surveys.eb2011_rows_from_pages(eb_pages())
    zero = pick(rows, metric="ideal_zero_share", table="A.2.6")
    assert len(zero) == 27 * 10 - 1  # Italy / men / 15-24 is garbled in the extracted text
    dk = zero[("DNK", "F", "25-39")]
    assert dk["value"] == 4.0 and dk["n"] == 78
    assert (
        pick(rows, metric="ideal_low_share", table="A.2.6")[("AUT", "F", "25-39")]["value"] == 26.0
    )
    assert (
        pick(rows, metric="ideal_high_share", table="A.2.6")[("DNK", "F", "25-39")]["value"] == 48.0
    )
    assert pick(rows, metric="ideal_general_zero_share")[("AUT", "F", "15-24")]["n"] == 54
    assert pick(rows, metric="childless_share")[("AUT", "F", "15-24")]["value"] is not None
    intended0 = pick(rows, metric="intended_additional_zero_share")
    assert intended0[("AUT", "M", "total")]["value"] == 63.0
    assert intended0[("AUT", "M", "total")]["n"] == 474
    assert len(intended0) == 27 * 10 - 3  # three garbled Malta rows
    assert len(issues) == 4
    assert any("A.2.6" in i and "Italy" in i for i in issues)
    assert sum("A.2.8" in i and "Malta" in i for i in issues) == 3


def test_eb_fails_closed_on_missing_table_or_header_mismatch() -> None:
    pages = eb_pages()
    with pytest.raises(ValueError, match="A.2.3"):
        surveys.eb2011_rows_from_pages([p for p in pages if "Table A.2.3 Mean" not in p])
    bad = [
        p.replace("15-24 25-39 40-54 55+ Total 15-24", "15-24 25-39 40-54 55+ 15-24") for p in pages
    ]
    with pytest.raises(ValueError, match="columns"):
        surveys.eb2011_rows_from_pages(bad)
    missing_country = [p.replace("\nFinland 2.45 2.47 2.64 2.45 2.50", "\n") for p in pages]
    with pytest.raises(ValueError, match="Finland"):
        surveys.eb2011_rows_from_pages(missing_country)
    with pytest.raises(ValueError, match="A.1.1"):
        surveys.eb2011_rows_from_pages(
            [p.replace("Ages 15-39 Ages 55+", "Ages 15-39") for p in pages]
        )
    with pytest.raises(ValueError, match="not found"):
        surveys.eb2011_rows_from_pages(["nothing here"])


def test_eb_rows_from_pdf_bytes_rejects_non_pdf() -> None:
    with pytest.raises(ValueError, match="PDF"):
        surveys.eb2011_rows(b"<html>not a pdf</html>")


# ---------------------------------------------------------------- BiB 2025 (GGS-II)


def test_ggs_table1_rows_match_published_values() -> None:
    rows = surveys.ggs_rows_from_pages(bib_pages())
    assert {r["iso3"] for r in rows} == GGS11
    assert {r["sex"] for r in rows} == {"F"}
    assert {r["age_class"] for r in rows} == {"18-29", "30-39", "40-49", "total"}
    assert {r["metric"] for r in rows} == {
        "actual_mean",
        "intended_total_mean",
        "ideal_personal_mean",
        "gap_intended_actual",
        "gap_ideal_actual",
        "gap_ideal_intended",
    }
    assert len(rows) == 11 * 4 * 6
    ideal = pick(rows, metric="ideal_personal_mean", age_class="total")
    assert ideal[("NOR", "F", "total")]["value"] == 2.38
    assert ideal[("DNK", "F", "total")]["value"] == 2.34
    assert ideal[("FIN", "F", "total")]["value"] == 2.18
    assert ideal[("DEU", "F", "total")]["value"] == 2.28
    assert pick(rows, metric="intended_total_mean")[("FIN", "F", "18-29")]["value"] == 1.82
    assert pick(rows, metric="gap_ideal_actual")[("GBR", "F", "40-49")]["value"] == 0.62
    # n (Observations) is attached to the total rows only
    assert ideal[("DEU", "F", "total")]["n"] == 9533
    assert pick(rows, metric="ideal_personal_mean")[("DEU", "F", "18-29")]["n"] is None
    # survey year = first fieldwork year from the table note
    years = {r["iso3"]: (r["survey_year"], r["fieldwork"]) for r in rows}
    assert years["DEU"] == (2021, "2021-2022")
    assert years["NOR"] == (2020, "2020")
    assert years["HRV"] == (2023, "2023")
    assert years["GBR"] == (2022, "2022-2023")
    assert {r["source"] for r in rows} == {"bib2025_ggs2"}
    assert set(rows[0]) == {
        "iso3", "survey_year", "fieldwork", "sex", "age_class", "metric", "value", "n", "source"
    }  # fmt: skip


def test_ggs_fails_closed_on_layout_changes() -> None:
    pages = bib_pages()
    with pytest.raises(ValueError, match="Table 1"):
        surveys.ggs_rows_from_pages(["no table here"])
    swapped = [
        p.replace("Germany Austria Netherlands", "Austria Germany Netherlands") for p in pages
    ]
    with pytest.raises(ValueError, match="countries"):
        surveys.ggs_rows_from_pages(swapped)
    short = [
        p.replace("Total 2.28 2.17 2.19 2.17 2.38 2.39 2.38 2.34 2.18 2.68 2.30", "Total 2.28")
        for p in pages
    ]
    with pytest.raises(ValueError, match="Ideal number of children"):
        surveys.ggs_rows_from_pages(short)
    no_source = [p.replace("GGS-II Norway (2020)", "GGS-II Norway") for p in pages]
    with pytest.raises(ValueError, match="fieldwork"):
        surveys.ggs_rows_from_pages(no_source)


# ---------------------------------------------------------------- mart


def test_build_ideals_mart_is_long_sorted_and_tags_sources() -> None:
    eb, _ = surveys.eb2011_rows_from_pages(eb_pages())
    ggs = surveys.ggs_rows_from_pages(bib_pages())
    mart = surveys.build_ideals_mart(eb, ggs)
    assert len(mart) == len(eb) + len(ggs)
    assert set(mart[0]) == {
        "source", "iso3", "survey_year", "sex", "age_class", "metric", "value", "n", "table"
    }  # fmt: skip
    assert {r["source"] for r in mart} == {"eb2011", "ggs2020"}
    assert {r["survey_year"] for r in mart if r["source"] == "eb2011"} == {2011}
    keys = [(r["source"], r["iso3"], r["sex"], r["age_class"], r["metric"]) for r in mart]
    assert keys == sorted(keys)
    assert len(set(keys)) == len(keys)  # (source, iso3, sex, age, metric) is unique
    assert surveys.build_ideals_mart(eb, []) and surveys.build_ideals_mart([], ggs)
