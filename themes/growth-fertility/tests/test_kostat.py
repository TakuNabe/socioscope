"""kostat.py: 국가데이터처 신혼부부통계 press-release PDF -> rows (pure, fail-closed).

Fixtures are the pypdf text of the table page (+ the next page; 2024 also carries the table of
contents page) of each release, pages separated by form feed. PDFs themselves are not committed.
"""

from pathlib import Path

import pytest

from theme_growth_fertility import kostat

FIXTURES = Path(__file__).parent / "fixtures"
CLASSES = ["total", "lt_1000", "1000_3000", "3000_5000", "5000_7000", "7000_10000", "ge_10000"]


def pages_of(release_year: int) -> list[str]:
    return (
        (FIXTURES / f"kostat_newlywed_{release_year}.txt").read_text(encoding="utf-8").split("\f")
    )


def release(year: int) -> kostat.Release:
    return next(r for r in kostat.RELEASES if r.ref_year == year)


def rows_for(release_year: int) -> list[dict[str, object]]:
    return kostat.income_children_rows_from_pages(pages_of(release_year), release(release_year))


def by_year(rows: list[dict[str, object]], ref_year: int) -> dict[str, dict[str, object]]:
    return {str(r["income_class"]): r for r in rows if r["ref_year"] == ref_year}


def test_releases_cover_2015_to_2024_with_static_board_urls() -> None:
    years = [r.ref_year for r in kostat.RELEASES]
    assert years == list(range(2015, 2025))
    r2024 = release(2024)
    assert r2024.url == "https://mods.go.kr/boardDownload.es?bid=11815&list_no=442387&seq=3"
    assert release(2021).url == "https://mods.go.kr/boardDownload.es?bid=11815&list_no=422173&seq=1"
    assert release(2015).url == "https://mods.go.kr/boardDownload.es?bid=11815&list_no=358364&seq=5"
    assert r2024.raw_name == "newlywed_2024.pdf"
    assert release(2015).income_concept == "wage_only"
    assert all(r.income_concept == "earned_business" for r in kostat.RELEASES if r.ref_year >= 2016)
    assert kostat.SOURCE == "kostat_newlywed"
    assert "KOGL" in kostat.LICENSE and "kogl.or.kr" in kostat.LICENSE


def test_income_classes_in_10k_krw_with_open_top() -> None:
    bounds = [(c.key, c.lower_10k_krw, c.upper_10k_krw) for c in kostat.INCOME_CLASSES]
    assert bounds == [
        ("total", None, None),
        ("lt_1000", 0, 1000),
        ("1000_3000", 1000, 3000),
        ("3000_5000", 3000, 5000),
        ("5000_7000", 5000, 7000),
        ("7000_10000", 7000, 10000),
        ("ge_10000", 10000, None),
    ]


def test_finder_locates_column_layout_and_ignores_table_of_contents() -> None:
    pages = pages_of(2024)
    found = kostat.find_income_children_table(pages)
    assert found.page_index == 1  # page 0 is the TOC line "8. ... 소득구간별 자녀 현황 ····· 29"
    assert found.layout == kostat.Layout.COLUMNS
    assert kostat.find_income_children_table(pages_of(2019)).layout == kostat.Layout.ROWS_SHARE
    assert kostat.find_income_children_table(pages_of(2015)).layout == kostat.Layout.ROWS_COUNT


def test_finder_fails_closed_when_table_absent() -> None:
    with pytest.raises(ValueError, match="not found"):
        kostat.find_income_children_table(["- 1 -\n신혼부부 수\n전체 1,000"])


def test_2024_release_matches_published_values() -> None:
    rows = rows_for(2024)
    assert sorted({int(str(r["ref_year"])) for r in rows}) == [2023, 2024]
    assert len(rows) == 14
    y = by_year(rows, 2024)
    assert [r["income_class"] for r in rows if r["ref_year"] == 2024] == CLASSES
    assert [round(float(str(y[c]["with_children_share"])) * 100, 1) for c in CLASSES] == [
        51.2,
        54.3,
        59.3,
        57.5,
        53.8,
        45.8,
        45.9,
    ]
    assert [float(str(y[c]["mean_children"])) for c in CLASSES] == [
        0.61,
        0.67,
        0.73,
        0.69,
        0.63,
        0.53,
        0.53,
    ]
    assert [y[c]["couples"] for c in CLASSES] == [
        756_358,
        49_890,
        73_418,
        121_861,
        150_966,
        179_810,
        180_413,
    ]
    t = y["total"]
    assert t["children_1_share"] == pytest.approx(0.421)
    assert t["children_2_share"] == pytest.approx(0.088)
    assert t["children_3plus_share"] == pytest.approx(0.003)
    assert t["release_year"] == 2024
    assert t["population"] == "first_marriage_within_5y"
    assert t["income_concept"] == "earned_business"
    assert t["source"] == "kostat_newlywed"
    assert t["income_lower_10k_krw"] is None and t["income_upper_10k_krw"] is None
    assert y["7000_10000"]["income_lower_10k_krw"] == 7000
    assert y["7000_10000"]["income_upper_10k_krw"] == 10000
    assert y["ge_10000"]["income_upper_10k_krw"] is None
    # the 2023 block in the same PDF (shares printed in parentheses)
    y23 = by_year(rows, 2023)
    assert y23["total"]["with_children_share"] == pytest.approx(0.525)
    assert y23["total"]["mean_children"] == 0.63
    assert y23["total"]["couples"] == 769_067


def test_2021_release_matches_published_values_with_separate_mean_table() -> None:
    rows = rows_for(2021)
    assert sorted({int(str(r["ref_year"])) for r in rows}) == [2020, 2021]
    y = by_year(rows, 2021)
    assert [round(float(str(y[c]["with_children_share"])) * 100, 1) for c in CLASSES] == [
        54.2,
        61.8,
        60.8,
        59.4,
        54.2,
        47.1,
        46.7,
    ]
    assert [float(str(y[c]["mean_children"])) for c in CLASSES] == [
        0.66,
        0.77,
        0.74,
        0.73,
        0.66,
        0.55,
        0.55,
    ]
    assert y["total"]["couples"] == 871_428
    assert by_year(rows, 2020)["lt_1000"]["mean_children"] == 0.76


@pytest.mark.parametrize("release_year", [2022, 2023])
def test_2022_2023_releases_parse_with_the_column_layout(release_year: int) -> None:
    rows = rows_for(release_year)
    assert sorted({int(str(r["ref_year"])) for r in rows}) == [release_year - 1, release_year]
    y = by_year(rows, 2022)
    assert y["total"]["with_children_share"] == pytest.approx(0.536)
    assert y["total"]["mean_children"] == 0.65
    assert y["ge_10000"]["couples"] == 146_203


def test_2020_release_publishes_couples_in_thousands() -> None:
    rows = rows_for(2020)
    y = by_year(rows, 2019)
    assert y["total"]["couples"] == 998_000
    assert y["total"]["with_children_share"] == pytest.approx(0.575)
    assert y["total"]["mean_children"] == 0.71
    assert by_year(rows, 2020)["ge_10000"]["mean_children"] == 0.58


@pytest.mark.parametrize(
    ("release_year", "ref_year", "total_couples", "total_share", "total_mean"),
    [
        (2019, 2019, 998_000, 0.575, 0.71),
        (2019, 2018, 1_052_000, 0.598, 0.74),
        (2018, 2018, 1_052_400, 0.598, 0.74),
        (2017, 2017, 1_103_300, 0.625, 0.78),
        (2016, 2016, 1_151_100, 0.637, 0.80),
        (2016, 2015, 1_179_000, 0.645, 0.82),
    ],
)
def test_2016_2019_releases_row_layout(
    release_year: int, ref_year: int, total_couples: int, total_share: float, total_mean: float
) -> None:
    rows = rows_for(release_year)
    y = by_year(rows, ref_year)
    assert len(y) == 7
    assert y["total"]["couples"] == total_couples
    assert y["total"]["with_children_share"] == pytest.approx(total_share)
    assert y["total"]["mean_children"] == total_mean
    assert y["total"]["income_concept"] == "earned_business"


def test_2019_release_class_values() -> None:
    y = by_year(rows_for(2019), 2019)
    assert y["lt_1000"]["couples"] == 88_000
    assert y["lt_1000"]["with_children_share"] == pytest.approx(0.639)
    assert y["lt_1000"]["children_3plus_share"] == pytest.approx(0.010)
    assert y["ge_10000"]["mean_children"] == 0.58


def test_2015_release_is_wage_only_with_counts() -> None:
    rows = rows_for(2015)
    assert {int(str(r["ref_year"])) for r in rows} == {2015}
    y = by_year(rows, 2015)
    assert all(r["income_concept"] == "wage_only" for r in rows)
    assert y["total"]["couples"] == 852_618
    assert y["total"]["with_children_share"] == pytest.approx(0.636)
    assert y["total"]["children_1_share"] == pytest.approx(0.479)
    assert y["total"]["mean_children"] == 0.80
    assert y["1000_3000"]["couples"] == 156_590
    assert y["1000_3000"]["with_children_share"] == pytest.approx(0.665)
    assert y["ge_10000"]["mean_children"] == 0.66


def test_rows_are_sorted_by_ref_year_then_income_lower() -> None:
    rows = rows_for(2024)
    assert [(r["ref_year"], r["income_class"]) for r in rows] == [
        (y, c) for y in (2023, 2024) for c in CLASSES
    ]


def test_fails_closed_when_shares_do_not_add_up() -> None:
    pages = pages_of(2021)
    broken = [p.replace("자녀있음 54.2 61.8", "자녀있음 44.2 61.8") for p in pages]
    with pytest.raises(ValueError, match="add up"):
        kostat.income_children_rows_from_pages(broken, release(2021))


def test_fails_closed_when_class_couples_do_not_sum_to_total() -> None:
    pages = pages_of(2024)
    broken = [p.replace("전체 756,358 49,890", "전체 756,358 149,890") for p in pages]
    with pytest.raises(ValueError, match="sum"):
        kostat.income_children_rows_from_pages(broken, release(2024))


def test_fails_closed_when_mean_children_row_missing() -> None:
    pages = pages_of(2021)
    broken = [p.replace("2021년 0.66 0.77", "xxxx 0.66 0.77") for p in pages]
    with pytest.raises(ValueError, match="mean"):
        kostat.income_children_rows_from_pages(broken, release(2021))


def test_fails_closed_when_header_classes_differ() -> None:
    pages = pages_of(2024)
    broken = [p.replace("7천만원～\n1억원 \n미만", "7천만원～\n9천만원 \n미만") for p in pages]
    with pytest.raises(ValueError, match="header"):
        kostat.income_children_rows_from_pages(broken, release(2024))


def test_pdf_text_extracts_one_string_per_page(pdf_from_pages) -> None:  # type: ignore[no-untyped-def]
    payload = pdf_from_pages(["first page\nline two", "second 1천만원 미만"])
    pages = kostat.pdf_text(payload)
    assert len(pages) == 2
    assert "line two" in pages[0]
    assert "1천만원 미만" in pages[1]


def test_pdf_text_rejects_non_pdf_payload() -> None:
    with pytest.raises(ValueError, match="PDF"):
        kostat.pdf_text(b"<html>not a pdf</html>")


def test_income_children_rows_end_to_end_from_pdf_bytes(pdf_from_pages) -> None:  # type: ignore[no-untyped-def]
    payload = pdf_from_pages(pages_of(2021))
    rows = kostat.income_children_rows(payload, release(2021))
    assert by_year(rows, 2021)["total"]["with_children_share"] == pytest.approx(0.542)
