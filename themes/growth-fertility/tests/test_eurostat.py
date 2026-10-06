import json
from pathlib import Path

import pytest

from theme_growth_fertility import eurostat as es

FIXTURES = Path(__file__).parent / "fixtures"
CENS = (FIXTURES / "eurostat_cens_fi.json").read_bytes()
FORDAGEC = (FIXTURES / "eurostat_fordagec_fi.json").read_bytes()
PJAN = (FIXTURES / "eurostat_pjan_fi.json").read_bytes()
FAEDUC = (FIXTURES / "eurostat_faeduc_fi.json").read_bytes()
LFSA = (FIXTURES / "eurostat_lfsa_fi.json").read_bytes()


# ---------------------------------------------------------------- JSON-stat decoding


def test_jsonstat_rows_expands_sparse_values_in_dimension_order() -> None:
    payload = json.dumps(
        {
            "class": "dataset",
            "id": ["a", "b"],
            "size": [2, 3],
            "dimension": {
                "a": {"category": {"index": {"a0": 0, "a1": 1}}},
                "b": {"category": {"index": {"x": 0, "y": 1, "z": 2}}},
            },
            "value": {"0": 1.5, "5": 2, "4": None},
            "status": {"4": ":"},
        }
    ).encode()
    assert es.jsonstat_rows(payload) == [
        {"a": "a0", "b": "x", "value": 1.5},
        {"a": "a1", "b": "z", "value": 2.0},
    ]


def test_jsonstat_rows_accepts_category_index_as_list() -> None:
    payload = json.dumps(
        {
            "class": "dataset",
            "id": ["a"],
            "size": [2],
            "dimension": {"a": {"category": {"index": ["p", "q"]}}},
            "value": {"1": 3},
        }
    ).encode()
    assert es.jsonstat_rows(payload) == [{"a": "q", "value": 3.0}]


@pytest.mark.parametrize(
    "doc",
    [
        {"error": {"status": 400, "label": "Bad Request"}},
        {"class": "collection", "id": [], "size": [], "dimension": {}, "value": {}},
        {"class": "dataset", "id": ["a"], "dimension": {}, "value": {}},  # no size
        {"class": "dataset", "id": ["a"], "size": [1], "dimension": {}},  # no value
        {
            "class": "dataset",
            "id": ["a"],
            "size": [2],
            "dimension": {"a": {"category": {"index": {"p": 0}}}},
            "value": {},
        },
        [],
    ],
)
def test_jsonstat_rows_fail_closed(doc: object) -> None:
    with pytest.raises(ValueError):
        es.jsonstat_rows(json.dumps(doc).encode())
    with pytest.raises(ValueError):
        es.jsonstat_rows(b"<html>")


def test_age_bounds() -> None:
    assert es.age_bounds("Y25-29") == (25, 30)
    assert es.age_bounds("Y15") == (15, 16)
    assert es.age_bounds("TOTAL") == (None, None)
    assert es.age_bounds("UNK") == (None, None)
    assert es.age_bounds("Y_GE50") == (50, None)


# ---------------------------------------------------------------- requests / URLs


def test_geo_map_covers_eu27_efta_uk_with_special_codes() -> None:
    assert len(es.GEO_TO_ISO3) == 32
    assert es.GEO_TO_ISO3["EL"] == "GRC" and es.GEO_TO_ISO3["UK"] == "GBR"
    assert es.GEO_TO_ISO3["FI"] == "FIN" and es.GEO_TO_ISO3["LI"] == "LIE"
    assert len(es.CENSUS_GEOS) == 31 and "UK" not in es.CENSUS_GEOS
    assert es.ORDER_GEOS == (
        "FI",
        "SE",
        "NO",
        "DK",
        "IS",
        "DE",
        "FR",
        "IT",
        "ES",
        "NL",
        "HU",
        "CZ",
        "PL",
    )
    assert es.EDUCATION_GEOS == ("FI", "SE", "NO", "DK", "IS", "NL", "BE", "AT")


def test_requests_are_per_country_and_small() -> None:
    reqs = es.requests()
    assert len(reqs) == 31 + 13 * 2 + 8 * 2
    assert len({r.raw_name for r in reqs}) == len(reqs)
    cens = next(r for r in reqs if r.dataset == "cens_21me_r2" and r.geo == "EL")
    assert cens.raw_name == "eurostat_cens_21me_r2_EL.json"
    assert cens.url.startswith(
        "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/cens_21me_r2?format=JSON&lang=EN&geo=EL"
    )
    assert (
        cens.url.count("&age=") == 7
        and "&marsta=MAR_REP" in cens.url
        and "&sex=M&sex=F" in cens.url
    )
    births = next(r for r in reqs if r.dataset == "demo_fordagec" and r.geo == "FI")
    assert births.url.count("&age=") == 36 and "&sinceTimePeriod=2005" in births.url
    pjan = next(r for r in reqs if r.dataset == "demo_pjan" and r.geo == "FI")
    assert "&sex=F" in pjan.url and pjan.url.count("&age=") == 35
    faeduc = next(r for r in reqs if r.dataset == "demo_faeduc" and r.geo == "FI")
    assert faeduc.url.count("&age=") == 36 + 7 and "&sinceTimePeriod=2007" in faeduc.url
    lfs = next(r for r in reqs if r.dataset == "lfsa_pgaed" and r.geo == "FI")
    assert lfs.url.count("&age=") == 7 and lfs.url.count("&isced11=") == 4 and "&sex=F" in lfs.url


# ---------------------------------------------------------------- staged rows


def test_census_rows_tag_iso3_and_age_bounds() -> None:
    rows = es.census_rows(CENS)
    assert len(rows) == 60
    assert rows[0] == {
        "iso3": "FIN",
        "year": 2021,
        "sex": "F",
        "age_class": "Y25-29",
        "age_lower": 25,
        "age_upper": 30,
        "isced11": "ED2",
        "marsta": "MAR_REP",
        "value": 6410.0,
        "source": "eurostat",
    }


def test_census_rows_drop_nuts_regions() -> None:
    doc = json.loads(CENS)
    doc["dimension"]["geo"]["category"]["index"] = {"FI1B": 0}
    doc["size"][doc["id"].index("geo")] = 1
    assert es.census_rows(json.dumps(doc).encode()) == []


def test_births_and_population_rows() -> None:
    births = es.births_order_rows(FORDAGEC)
    assert len(births) == 216
    by = {(r["age_class"], r["ord_brth"]): r for r in births}
    assert by[("Y30", "1")] == {
        "iso3": "FIN",
        "year": 2023,
        "age_class": "Y30",
        "ord_brth": "1",
        "births": 1487.0,
        "source": "eurostat",
    }
    women = es.population_female_rows(PJAN)
    assert len(women) == 70
    assert women[0] == {
        "iso3": "FIN",
        "year": 2022,
        "age_class": "Y15",
        "women": 30417.0,
        "source": "eurostat",
    }


def test_births_education_and_lfs_rows() -> None:
    births = es.births_education_rows(FAEDUC)
    assert len(births) == 444
    assert {r["isced11"] for r in births} == {"TOTAL", "ED0-2", "ED3_4", "ED5-8", "NAP", "UNK"}
    lfs = es.lfs_population_rows(LFSA)
    assert len(lfs) == 27  # Y15-19 × ED5-8 has no value in the LFS -> no row
    assert lfs[0] == {
        "iso3": "FIN",
        "year": 2023,
        "age_class": "Y15-19",
        "isced11": "ED0-2",
        "women_thousand": 136.0,
        "source": "eurostat",
    }


# ---------------------------------------------------------------- marts (pure)


def test_build_census_mart_groups_isced_and_excludes_unknown_marital() -> None:
    rows = es.build_census_mart(es.census_rows(CENS))
    # fixture has ED2 / ED3 / ED6 (+ TOTAL, UNK) -> one group each, 2 ages x 2 sexes
    assert len(rows) == 3 * 2 * 2
    assert [r["isced_group"] for r in rows[:3]] == ["ED0-2", "ED3-4", "ED5-8"]
    assert rows[0] == {
        "iso3": "FIN",
        "year": 2021,
        "sex": "F",
        "age_class": "Y25-29",
        "age_lower": 25,
        "age_upper": 30,
        "isced_group": "ED0-2",
        "married": 6410.0,
        "total": 20568.0,
        "married_share": pytest.approx(6410 / 20568),
        "source": "eurostat",
    }


def test_build_census_mart_subtracts_unknown_marital_from_total() -> None:
    base = {
        "iso3": "FIN",
        "year": 2021,
        "sex": "M",
        "age_class": "Y30-34",
        "age_lower": 30,
        "age_upper": 35,
        "source": "eurostat",
    }
    rows = es.build_census_mart(
        [
            {**base, "isced11": "ED5", "marsta": "TOTAL", "value": 100.0},
            {**base, "isced11": "ED5", "marsta": "UNK", "value": 10.0},
            {**base, "isced11": "ED5", "marsta": "MAR_REP", "value": 45.0},
            {**base, "isced11": "ED8", "marsta": "TOTAL", "value": 10.0},
            {**base, "isced11": "ED8", "marsta": "MAR_REP", "value": 5.0},
            {**base, "isced11": "UNK", "marsta": "TOTAL", "value": 999.0},  # not grouped
            {**base, "isced11": "NAP", "marsta": "TOTAL", "value": 999.0},
            {**base, "isced11": "TOTAL", "marsta": "TOTAL", "value": 999.0},
        ]
    )
    assert len(rows) == 1
    assert rows[0]["married"] == 50.0 and rows[0]["total"] == 100.0
    assert rows[0]["married_share"] == pytest.approx(0.5)


def test_build_tfr_by_order_sums_single_year_asfr_15_49() -> None:
    rows = es.build_tfr_by_order(es.births_order_rows(FORDAGEC), es.population_female_rows(PJAN))
    # women exist for 2022 and 2023 but births only for 2023 -> one year
    assert [(r["iso3"], r["year"], r["order"]) for r in rows] == [
        ("FIN", 2023, "1"),
        ("FIN", 2023, "2"),
        ("FIN", 2023, "3"),
        ("FIN", 2023, "GE4"),
        ("FIN", 2023, "TOTAL"),
        ("FIN", 2023, "UNK"),
    ]
    total = rows[4]
    assert total["tfr"] == pytest.approx(1.265439, abs=1e-6)
    assert total["births_age_unknown"] == 0.0 and total["source"] == "eurostat"
    assert rows[0]["tfr"] == pytest.approx(0.557358, abs=1e-6)
    assert rows[5]["tfr"] == 0.0


def test_build_tfr_by_order_drops_incomplete_ages_and_counts_unknown_age() -> None:
    def b(age: str, births: float, year: int = 2020) -> dict[str, object]:
        return {
            "iso3": "SWE",
            "year": year,
            "age_class": age,
            "ord_brth": "1",
            "births": births,
            "source": "eurostat",
        }

    def w(age: str, women: float, year: int = 2020) -> dict[str, object]:
        return {"iso3": "SWE", "year": year, "age_class": age, "women": women, "source": "eurostat"}

    births = [b(f"Y{a}", 10.0) for a in range(15, 50)] + [b("UNK", 7.0)]
    women = [w(f"Y{a}", 1000.0) for a in range(15, 50)]
    rows = es.build_tfr_by_order(births, women)
    assert rows == [
        {
            "iso3": "SWE",
            "year": 2020,
            "order": "1",
            "tfr": pytest.approx(0.35),
            "births_age_unknown": 7.0,
            "source": "eurostat",
        }
    ]
    # one single-year denominator missing -> the year is dropped, not imputed
    assert es.build_tfr_by_order(births, women[1:]) == []
    # 5-year births only: fall back to 5 x births / women-in-class
    five = [
        {
            "iso3": "SWE",
            "year": 2020,
            "age_class": f"Y{a}-{a + 4}",
            "ord_brth": "1",
            "births": 50.0,
            "source": "eurostat",
        }
        for a in range(15, 50, 5)
    ]
    assert es.build_tfr_by_order(five, women)[0]["tfr"] == pytest.approx(0.35)


def test_build_tfr_by_education_uses_5year_classes_and_lfs_denominator() -> None:
    rows = es.build_tfr_by_education(es.births_education_rows(FAEDUC), es.lfs_population_rows(LFSA))
    # births 2022 + 2023, LFS 2023 only -> 2023; FI single ages are summed into 5-year classes
    assert [(r["year"], r["isced_group"]) for r in rows] == [
        (2023, "ED0-2"),
        (2023, "ED3_4"),
        (2023, "ED5-8"),
        (2023, "TOTAL"),
    ]
    by = {r["isced_group"]: r for r in rows}
    assert by["TOTAL"]["tfr"] == pytest.approx(1.261096, abs=1e-6)
    assert by["TOTAL"]["women_total_thousand"] == pytest.approx(1164.5)
    assert by["ED0-2"]["tfr"] == pytest.approx(0.629096, abs=1e-6)
    # Y15-19 x ED5-8: 0 births and no LFS denominator -> contributes 0, class not in women total
    assert by["ED5-8"]["tfr"] == pytest.approx(1.365727, abs=1e-6)
    assert by["ED5-8"]["women_total_thousand"] == pytest.approx(465.6)
    assert by["ED5-8"]["iso3"] == "FIN" and by["ED5-8"]["source"] == "eurostat"


def test_build_tfr_by_education_drops_group_when_births_have_no_denominator() -> None:
    def b(age: str, births: float, g: str = "ED3_4") -> dict[str, object]:
        return {
            "iso3": "SWE",
            "year": 2020,
            "age_class": age,
            "isced11": g,
            "births": births,
            "source": "eurostat",
        }

    def w(age: str, women: float, g: str = "ED3_4") -> dict[str, object]:
        return {
            "iso3": "SWE",
            "year": 2020,
            "age_class": age,
            "isced11": g,
            "women_thousand": women,
            "source": "eurostat",
        }

    ages = [f"Y{a}-{a + 4}" for a in range(15, 50, 5)]
    births = [b(a, 100.0) for a in ages]
    women = [w(a, 10.0) for a in ages]
    rows = es.build_tfr_by_education(births, women)
    assert rows == [
        {
            "iso3": "SWE",
            "year": 2020,
            "isced_group": "ED3_4",
            "tfr": pytest.approx(0.35),
            "women_total_thousand": 70.0,
            "source": "eurostat",
        }
    ]
    assert es.build_tfr_by_education(births, women[1:]) == []  # births > 0 without denominator
    assert es.build_tfr_by_education(births[:6], women) == []  # a class without births data
    assert (
        es.build_tfr_by_education(births, [*women[1:], w(ages[0], 0.0)]) == []
    )  # zero denominator
