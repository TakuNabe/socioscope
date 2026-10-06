from pathlib import Path

import pytest

from socioscope_core.core.pipeline import Context, Stage
from socioscope_core.testing.fakes import FakeFetcher, InMemoryRawStore, InMemoryTableStore
from theme_growth_fertility import dhs, estat, kostat, pipeline
from theme_growth_fertility import worldbank as wb
from theme_growth_fertility.pipeline import build_panel
from theme_growth_fertility.wiring import PIPELINE

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE = (FIXTURES / "tfr_page.json").read_bytes()
COUNTRIES = (FIXTURES / "countries_page.json").read_bytes()
DHS_DATA = (FIXTURES / "dhs_tfr_wealth_page.json").read_bytes()
DHS_COUNTRIES = (FIXTURES / "dhs_countries_page.json").read_bytes()


def make_ctx(responses: dict[str, bytes]) -> Context:
    return Context(
        fetcher=FakeFetcher(responses), raw=InMemoryRawStore(), tables=InMemoryTableStore()
    )


def all_responses() -> dict[str, bytes]:
    out = {wb.indicator_url(code): FIXTURE for code in wb.INDICATORS.values()}
    out[wb.countries_url()] = COUNTRIES
    out.update(dhs_responses())
    return out


def dhs_responses() -> dict[str, bytes]:
    return {dhs.data_url(): DHS_DATA, dhs.countries_url(): DHS_COUNTRIES}


def test_fetch_stores_raw_with_manifest_and_reports_failures() -> None:
    ctx = make_ctx({wb.indicator_url(wb.INDICATORS["tfr"]): FIXTURE})
    result = PIPELINE.run(Stage.FETCH, ctx)

    assert result.written == ("growth-fertility/worldbank_wdi/tfr.json",)
    # every other indicator + countries + e-Stat tables + 2 DHS files + kostat PDFs: no response
    assert len(result.skipped) == len(wb.INDICATORS) + len(estat.TABLES) + 2 + len(kostat.RELEASES)
    recs = ctx.raw.records()
    assert len(recs) == 1 and recs[0].license.startswith("CC BY 4.0")
    assert ctx.raw.get(theme="growth-fertility", source="worldbank_wdi", name="tfr.json") == FIXTURE


def test_fetch_also_stores_country_metadata() -> None:
    ctx = make_ctx(all_responses())
    result = PIPELINE.run(Stage.FETCH, ctx)
    assert "growth-fertility/worldbank_wdi/countries.json" in result.written
    assert all(
        s.startswith(tuple(t.key for t in estat.TABLES)) or s.startswith("newlywed_")
        for s in result.skipped
    )


def test_stage_then_mart_build_panel_from_raw() -> None:
    ctx = make_ctx(all_responses())
    PIPELINE.run(Stage.FETCH, ctx)
    staged = PIPELINE.run(Stage.STAGE, ctx)
    assert set(staged.written) == {f"staged/worldbank/{k}" for k in wb.INDICATORS} | {
        "staged/worldbank/countries",
        pipeline.DHS_TABLE,
    }
    # the 'NAC' aggregate is dropped at stage using the country metadata
    assert [r["iso3"] for r in ctx.tables.read_table("staged/worldbank/tfr")] == [
        "JPN",
        "JPN",
        "USA",
    ]

    mart = PIPELINE.run(Stage.MART, ctx)
    assert mart.written == ("marts/growth_fertility_panel", pipeline.DHS_MART)
    panel = ctx.tables.read_table("marts/growth_fertility_panel")
    assert panel[0] == {
        "iso3": "JPN",
        "country": "Japan",
        "year": 2000,
        "region": "East Asia & Pacific",
        "income_group": "High income",
        "tfr": 1.36,
        "gdp_pcap_ppp": 1.36,
        "gdp_growth": 1.36,
        "population": 1.36,
        "u5_mortality": 1.36,
        "fem_sec_enrol": 1.36,
        "urban_share": 1.36,
        "fem_lfp": 1.36,
        "life_exp": 1.36,
    }
    assert [p["iso3"] for p in panel] == ["JPN", "JPN", "USA"]


def test_stage_without_raw_skips_explicitly() -> None:
    ctx = make_ctx({})
    result = PIPELINE.run(Stage.STAGE, ctx)
    assert result.written == ()
    assert len(result.skipped) == len(wb.INDICATORS) + 1 + len(estat.TABLES) + 2 + len(
        kostat.RELEASES
    )


# ---------------------------------------------------------------- e-Stat (国民生活基礎調査)

ESTAT_FIXTURE_BY_KIND = {
    estat.TableKind.INCOME_DIST_TS: (
        FIXTURES / "estat_children_hh_income_dist_ts.csv"
    ).read_bytes(),
    estat.TableKind.WORKERS_MARITAL: (FIXTURES / "estat_workers_marital_income.csv").read_bytes(),
    estat.TableKind.HH_TYPE: (FIXTURES / "estat_hh_type_income.csv").read_bytes(),
    estat.TableKind.SHUGYO_MARITAL_AGE_INCOME: (
        FIXTURES / "estat_shugyo_marital_age_income.xlsx"
    ).read_bytes(),
}


def estat_responses(tables: tuple[estat.Table, ...] = estat.TABLES) -> dict[str, bytes]:
    return {t.url: ESTAT_FIXTURE_BY_KIND[t.kind] for t in tables}


def test_fetch_stores_estat_files_with_license() -> None:
    ctx = make_ctx(estat_responses())
    result = PIPELINE.run(Stage.FETCH, ctx)
    assert "growth-fertility/estat_kiso/workers_marital_income_2025.csv" in result.written
    assert "growth-fertility/estat_shugyo/shugyo_marital_age_income_2022.xlsx" in result.written
    assert len([w for w in result.written if "/estat_kiso/" in w]) == len(estat.TABLES) - 1
    # no World Bank / DHS / kostat responses
    assert len(result.skipped) == len(wb.INDICATORS) + 1 + 2 + len(kostat.RELEASES)
    recs = [r for r in ctx.raw.records() if r.source in {"estat_kiso", "estat_shugyo"}]
    assert len(recs) == len(estat.TABLES)
    assert all("政府標準利用規約" in r.license and "CC BY 4.0" in r.license for r in recs)
    assert all("appId" not in r.url for r in recs)


def test_stage_estat_concatenates_waves_and_reports_missing_ones() -> None:
    present = tuple(t for t in estat.TABLES if t.survey_year in (2025, 2013))
    ctx = make_ctx(estat_responses(present))
    PIPELINE.run(Stage.FETCH, ctx)
    result = PIPELINE.run(Stage.STAGE, ctx)
    assert set(result.written) == set(pipeline.ESTAT_TABLES.values()) - {
        "staged/estat/shugyo_marital_age_income"
    }
    # kiso 2016/19/22 × 2 kinds + the shugyo 2022 table (its key also contains "income_")
    assert sum("raw missing" in s for s in result.skipped if "income_" in s) == 7
    assert "staged/estat/shugyo_marital_age_income" not in result.written
    marital = ctx.tables.read_table("staged/estat/kiso_workers_marital_income")
    assert sorted({int(str(r["survey_year"])) for r in marital}) == [2013, 2025]
    assert {r["source"] for r in marital} == {"estat_kiso"}
    ts = ctx.tables.read_table("staged/estat/kiso_income_dist_ts")
    assert {r["population"] for r in ts} == {"all", "with_children"}


def test_stage_estat_independent_of_worldbank_fail_closed() -> None:
    # No World Bank raw at all: WB stages nothing, e-Stat still stages.
    ctx = make_ctx(estat_responses())
    PIPELINE.run(Stage.FETCH, ctx)
    result = PIPELINE.run(Stage.STAGE, ctx)
    assert set(result.written) == set(pipeline.ESTAT_TABLES.values())


def test_mart_jp_income_class_fertility_from_staged() -> None:
    ctx = make_ctx(estat_responses())
    PIPELINE.run(Stage.FETCH, ctx)
    PIPELINE.run(Stage.STAGE, ctx)
    result = PIPELINE.run(Stage.MART, ctx)
    assert result.written == (pipeline.JP_MART, pipeline.JP_AGE_MART)  # no WB -> no WB panel
    rows = ctx.tables.read_table(pipeline.JP_MART)
    assert set(rows[0]) == {
        "survey",
        "survey_year",
        "year",
        "income_class",
        "income_class_lower_yen",
        "income_class_upper_yen",
        "sex",
        "metric",
        "value",
        "denominator",
        "source",
    }
    by = {(r["metric"], r["survey_year"], r["sex"], r["income_class"]): r for r in rows}
    m = by[("married_share", 2025, "male", "50-100")]
    assert m["value"] == pytest.approx(286 / (286 + 582)) and m["denominator"] == 286 + 582
    assert m["income_class_lower_yen"] == 500_000 and m["year"] == 2024
    c = by[("children_household_share", 2013, None, "0-50")]
    assert c["value"] == pytest.approx(2 / 129) and c["denominator"] == 129
    # the stage fixture is the same CSV for both ts tables, so both populations exist
    assert ("children_household_share_pct", 2025, None, "2000-") in by
    assert ("household_share_pct", 2025, None, "2000-") in by


def test_mart_jp_income_age_marital_from_staged_shugyo_only() -> None:
    shugyo = tuple(t for t in estat.TABLES if t.kind is estat.TableKind.SHUGYO_MARITAL_AGE_INCOME)
    ctx = make_ctx(estat_responses(shugyo))
    PIPELINE.run(Stage.FETCH, ctx)
    staged = PIPELINE.run(Stage.STAGE, ctx)
    assert staged.written == ("staged/estat/shugyo_marital_age_income",)
    result = PIPELINE.run(Stage.MART, ctx)
    assert result.written == (pipeline.JP_AGE_MART,)  # kiso not staged -> no kiso mart
    rows = ctx.tables.read_table(pipeline.JP_AGE_MART)
    assert set(rows[0]) == {
        "survey",
        "survey_year",
        "year",
        "sex",
        "age_class",
        "age_lower",
        "age_upper",
        "income_class",
        "income_class_lower_yen",
        "income_class_upper_yen",
        "metric",
        "value",
        "denominator",
        "source",
    }
    assert len(rows) == 2 * 3 * 4  # sex x age x income cells (fixture)
    assert {r["metric"] for r in rows} == {"ever_married_share"}
    assert {r["survey"] for r in rows} == {"就業構造基本調査"}
    by = {(r["sex"], r["age_class"], r["income_class"]): r for r in rows}
    m = by[("male", "25-29", "total")]
    assert m["value"] == pytest.approx((2_928_900 - 2_200_100) / 2_928_900)
    assert m["denominator"] == 2_928_900 and m["year"] == 2022 and m["age_upper"] == 30
    assert by[("male", "85-", "1500-")]["value"] == pytest.approx(1.0)  # never-married '-' = 0
    assert by[("male", "total", "total")]["age_lower"] is None
    # sorted: year, sex, age (total first), income lower (total first)
    assert [r["age_class"] for r in rows[:4]] == ["total"] * 4
    assert rows[0]["income_class"] == "total" and rows[1]["income_class"] == "0-50"


def test_build_income_age_marital_keeps_missing_as_none() -> None:
    base = {
        "survey_year": 2022,
        "year": 2022,
        "source": "estat_shugyo",
        "sex": "male",
        "age_class": "25-29",
        "age_lower": 25,
        "age_upper": 30,
        "income_class": "0-50",
        "income_class_lower_yen": 0,
        "income_class_upper_yen": 500_000,
    }
    mid = {
        "income_class": "50-100",
        "income_class_lower_yen": 500_000,
        "income_class_upper_yen": 1_000_000,
    }
    high = {
        "income_class": "100-150",
        "income_class_lower_yen": 1_000_000,
        "income_class_upper_yen": 1_500_000,
    }
    rows = pipeline.build_income_age_marital(
        [
            {**base, "marital": "total", "persons": 100.0},
            {**base, "marital": "never_married", "persons": None},
            {**base, **mid, "marital": "total", "persons": 0.0},
            {**base, **mid, "marital": "never_married", "persons": 0.0},
            {**base, **high, "marital": "total", "persons": 200.0},
            {**base, **high, "marital": "never_married", "persons": 50.0},
        ]
    )
    assert [(r["income_class"], r["value"], r["denominator"]) for r in rows] == [
        ("0-50", None, 100.0),  # missing numerator
        ("50-100", None, 0.0),  # zero denominator
        ("100-150", 0.75, 200.0),
    ]


def test_build_income_class_fertility_keeps_missing_as_none_and_is_sorted() -> None:
    base = {
        "survey_year": 2025,
        "year": 2024,
        "income_class_lower_yen": 0,
        "income_class_upper_yen": 500_000,
        "income_class": "0-50",
    }
    rows = pipeline.build_income_class_fertility(
        income_dist=[],
        workers_marital=[
            {**base, "sex": "total", "marital": "married", "workers_per_100k": None},
            {**base, "sex": "total", "marital": "unmarried", "workers_per_100k": 5.0},
        ],
        hh_type=[
            {**base, "households_per_10k": 0.0, "with_children_per_10k": 0.0},
            {
                **base,
                "income_class": "2000-",
                "income_class_lower_yen": 20_000_000,
                "income_class_upper_yen": None,
                "households_per_10k": 100.0,
                "with_children_per_10k": 25.0,
            },
        ],
    )
    assert [(r["metric"], r["income_class"], r["value"]) for r in rows] == [
        ("children_household_share", "0-50", None),  # zero denominator -> None
        ("children_household_share", "2000-", 0.25),
        ("married_share", "0-50", None),  # missing numerator -> None
    ]
    assert rows == pipeline.build_income_class_fertility(
        income_dist=[],
        workers_marital=[
            {**base, "sex": "total", "marital": "unmarried", "workers_per_100k": 5.0},
            {**base, "sex": "total", "marital": "married", "workers_per_100k": None},
        ],
        hh_type=[
            {
                **base,
                "income_class": "2000-",
                "income_class_lower_yen": 20_000_000,
                "income_class_upper_yen": None,
                "households_per_10k": 100.0,
                "with_children_per_10k": 25.0,
            },
            {**base, "households_per_10k": 0.0, "with_children_per_10k": 0.0},
        ],
    )


def test_stage_without_country_metadata_fails_closed() -> None:
    # Indicators present, countries.json missing: do not stage aggregates silently.
    ctx = make_ctx({wb.indicator_url(code): FIXTURE for code in wb.INDICATORS.values()})
    PIPELINE.run(Stage.FETCH, ctx)
    result = PIPELINE.run(Stage.STAGE, ctx)
    assert result.written == ()
    assert any("countries" in s for s in result.skipped)


def test_build_panel_keeps_missing_as_none() -> None:
    staged = {
        "tfr": [{"iso3": "JPN", "country": "Japan", "year": 2000, "value": 1.36}],
        "gdp_growth": [{"iso3": "JPN", "country": "Japan", "year": 2001, "value": 0.4}],
    }
    assert build_panel(staged, countries=[]) == [
        {
            "iso3": "JPN",
            "country": "Japan",
            "year": 2000,
            "region": None,
            "income_group": None,
            "tfr": 1.36,
            "gdp_growth": None,
        },
        {
            "iso3": "JPN",
            "country": "Japan",
            "year": 2001,
            "region": None,
            "income_group": None,
            "tfr": None,
            "gdp_growth": 0.4,
        },
    ]


# ---------------------------------------------------------------- DHS (TFR by wealth quintile)


def test_wdi_stage_indicators_are_registered() -> None:
    assert wb.INDICATORS["u5_mortality"] == "SH.DYN.MORT"
    assert wb.INDICATORS["fem_sec_enrol"] == "SE.SEC.ENRR.FE"
    assert wb.INDICATORS["urban_share"] == "SP.URB.TOTL.IN.ZS"
    assert wb.INDICATORS["fem_lfp"] == "SL.TLF.CACT.FE.ZS"
    assert wb.INDICATORS["life_exp"] == "SP.DYN.LE00.IN"


def test_fetch_stores_dhs_files_with_citation_license() -> None:
    ctx = make_ctx(dhs_responses())
    result = PIPELINE.run(Stage.FETCH, ctx)
    assert result.written == (
        "growth-fertility/dhs_api/dhs_tfr_wealth.json",
        "growth-fertility/dhs_api/dhs_countries.json",
    )
    assert len(result.skipped) == len(wb.INDICATORS) + 1 + len(estat.TABLES) + len(kostat.RELEASES)
    recs = ctx.raw.records()
    assert {r.source for r in recs} == {dhs.SOURCE}
    assert all("The DHS Program Indicator Data API" in r.license for r in recs)
    assert {r.url for r in recs} == {dhs.data_url(), dhs.countries_url()}
    assert ctx.raw.get(theme="growth-fertility", source="dhs_api", name="dhs_countries.json") == (
        DHS_COUNTRIES
    )


def test_stage_dhs_writes_long_table_and_reports_unmapped_codes() -> None:
    ctx = make_ctx(dhs_responses())
    PIPELINE.run(Stage.FETCH, ctx)
    result = PIPELINE.run(Stage.STAGE, ctx)
    assert result.written == (pipeline.DHS_TABLE,)  # WB / e-Stat absent -> independent
    assert any("OS" in s and "iso3" in s.lower() for s in result.skipped)
    rows = ctx.tables.read_table(pipeline.DHS_TABLE)
    assert len(rows) == 7
    assert {r["iso3"] for r in rows} == {"AFG", "ALB"}
    assert {r["source"] for r in rows} == {"dhs_api"}


def test_stage_dhs_without_country_metadata_fails_closed() -> None:
    ctx = make_ctx({dhs.data_url(): DHS_DATA})
    PIPELINE.run(Stage.FETCH, ctx)
    result = PIPELINE.run(Stage.STAGE, ctx)
    assert result.written == ()
    assert any("dhs_countries" in s and "raw missing" in s for s in result.skipped)


def test_mart_dhs_from_staged_only() -> None:
    ctx = make_ctx(dhs_responses())
    PIPELINE.run(Stage.FETCH, ctx)
    PIPELINE.run(Stage.STAGE, ctx)
    result = PIPELINE.run(Stage.MART, ctx)
    assert result.written == (pipeline.DHS_MART,)
    rows = ctx.tables.read_table(pipeline.DHS_MART)
    assert set(rows[0]) == {
        "iso3",
        "country",
        "dhs_country_code",
        "survey_id",
        "survey_year",
        "survey_type",
        "quintile",
        "quintile_label",
        "value",
        "ci_low",
        "ci_high",
        "denominator_weighted",
        "source",
    }
    assert [(r["survey_year"], r["iso3"], r["quintile"]) for r in rows] == [
        (2008, "ALB", 1),
        (2008, "ALB", 5),
        (2015, "AFG", 1),
        (2015, "AFG", 2),
        (2015, "AFG", 3),
        (2015, "AFG", 4),
        (2015, "AFG", 5),
    ]


def test_build_dhs_mart_sorts_and_keeps_rows_unchanged() -> None:
    a = {"survey_year": 2015, "iso3": "AFG", "quintile": 2, "value": 5.4}
    b = {"survey_year": 2008, "iso3": "ALB", "quintile": 5, "value": None}
    c = {"survey_year": 2015, "iso3": "AFG", "quintile": 1, "value": 5.3}
    assert pipeline.build_dhs_mart([a, b, c]) == [b, c, a]


# ---- H5: Korea newlywed statistics (PDF) ------------------------------------------------


def kostat_release(year: int) -> kostat.Release:
    return next(r for r in kostat.RELEASES if r.ref_year == year)


def kostat_pages(year: int) -> list[str]:
    return (FIXTURES / f"kostat_newlywed_{year}.txt").read_text(encoding="utf-8").split("\f")


def test_fetch_kostat_stores_each_release_pdf_with_kogl_license(pdf_from_pages) -> None:  # type: ignore[no-untyped-def]
    pdf = pdf_from_pages(kostat_pages(2024))
    ctx = make_ctx({kostat_release(2024).url: pdf, kostat_release(2015).url: b"%PDF-1.4 junk"})
    result = PIPELINE.run(Stage.FETCH, ctx)
    assert "growth-fertility/kostat_newlywed/newlywed_2024.pdf" in result.written
    assert "growth-fertility/kostat_newlywed/newlywed_2015.pdf" in result.written
    assert (
        ctx.raw.get(theme="growth-fertility", source=kostat.SOURCE, name="newlywed_2024.pdf") == pdf
    )
    assert any(s.startswith("newlywed_2016.pdf:") for s in result.skipped)
    recs = [r for r in ctx.raw.records() if r.source == kostat.SOURCE]
    assert len(recs) == 2 and all("KOGL" in r.license for r in recs)
    assert {r.url for r in recs} == {kostat_release(2024).url, kostat_release(2015).url}


def test_stage_kostat_concatenates_releases_and_skips_unrecognised_layout(pdf_from_pages) -> None:  # type: ignore[no-untyped-def]
    ctx = make_ctx(
        {
            kostat_release(2024).url: pdf_from_pages(kostat_pages(2024)),
            kostat_release(2015).url: pdf_from_pages(kostat_pages(2015)),
            kostat_release(2019).url: pdf_from_pages(["- 1 -\n신혼부부 수\n전체 1,000"]),
            kostat_release(2018).url: b"<html>maintenance</html>",
        }
    )
    PIPELINE.run(Stage.FETCH, ctx)
    result = PIPELINE.run(Stage.STAGE, ctx)
    assert pipeline.KOSTAT_TABLE in result.written
    rows = ctx.tables.read_table(pipeline.KOSTAT_TABLE)
    assert set(rows[0]) == {
        "release_year",
        "ref_year",
        "population",
        "income_class",
        "income_lower_10k_krw",
        "income_upper_10k_krw",
        "couples",
        "with_children_share",
        "children_1_share",
        "children_2_share",
        "children_3plus_share",
        "mean_children",
        "income_concept",
        "source",
    }
    assert sorted({(r["release_year"], r["ref_year"]) for r in rows}) == [
        (2015, 2015),
        (2024, 2023),
        (2024, 2024),
    ]
    assert len(rows) == 21
    assert any(
        s.startswith("newlywed_2019.pdf: layout not recognised (") and "not found" in s
        for s in result.skipped
    )
    assert any(s.startswith("newlywed_2018.pdf: layout not recognised (") for s in result.skipped)
    assert any(s.startswith("newlywed_2016.pdf: raw missing") for s in result.skipped)
    # other sources untouched: nothing of WB / e-Stat / DHS was written
    assert all(name == pipeline.KOSTAT_TABLE for name in result.written)


def test_stage_kostat_writes_nothing_without_any_raw() -> None:
    ctx = make_ctx({})
    result = PIPELINE.run(Stage.STAGE, ctx)
    assert pipeline.KOSTAT_TABLE not in result.written
    assert pipeline.KOSTAT_TABLE not in ctx.tables.list_tables()
    assert sum(s.startswith("newlywed_") and "raw missing" in s for s in result.skipped) == len(
        kostat.RELEASES
    )


def test_mart_kostat_long_table_prefers_latest_release_per_ref_year(pdf_from_pages) -> None:  # type: ignore[no-untyped-def]
    ctx = make_ctx(
        {
            kostat_release(2024).url: pdf_from_pages(kostat_pages(2024)),
            kostat_release(2023).url: pdf_from_pages(kostat_pages(2023)),  # 2022 + 2023 (dup 2023)
            kostat_release(2015).url: pdf_from_pages(kostat_pages(2015)),  # wage_only
            kostat_release(2016).url: pdf_from_pages(kostat_pages(2016)),  # 2015 earned + 2016
        }
    )
    PIPELINE.run(Stage.FETCH, ctx)
    PIPELINE.run(Stage.STAGE, ctx)
    result = PIPELINE.run(Stage.MART, ctx)
    assert result.written == (pipeline.KOSTAT_MART,)
    rows = ctx.tables.read_table(pipeline.KOSTAT_MART)
    assert set(rows[0]) == {
        "ref_year",
        "release_year",
        "income_class",
        "income_lower_10k_krw",
        "income_upper_10k_krw",
        "metric",
        "value",
        "income_concept",
        "source",
    }
    metrics = {
        "with_children_share",
        "mean_children",
        "couples",
        "children_1_share",
        "children_2_share",
        "children_3plus_share",
    }
    assert {str(r["metric"]) for r in rows} == metrics
    # ref years: 2015 (wage_only + earned_business), 2016, 2022, 2023, 2024 -> 6 blocks × 7 × 6
    assert len(rows) == 6 * 7 * 6
    keyed = {(r["ref_year"], r["income_concept"], r["income_class"], r["metric"]): r for r in rows}
    r2023 = keyed[(2023, "earned_business", "total", "with_children_share")]
    assert r2023["release_year"] == 2024 and r2023["value"] == pytest.approx(0.525)
    assert keyed[(2015, "wage_only", "total", "couples")]["value"] == 852_618
    assert keyed[(2015, "earned_business", "total", "couples")]["value"] == 1_179_000
    assert keyed[(2024, "earned_business", "ge_10000", "mean_children")]["value"] == 0.53
    assert keyed[(2024, "earned_business", "lt_1000", "couples")]["income_upper_10k_krw"] == 1000
    # sorted by ref_year, income_concept, then income lower bound (total first)
    order = [
        (r["ref_year"], r["income_concept"], r["income_class"])
        for r in rows
        if r["metric"] == "couples"
    ]
    assert order[:8] == [
        (2015, "earned_business", "total"),
        (2015, "earned_business", "lt_1000"),
        (2015, "earned_business", "1000_3000"),
        (2015, "earned_business", "3000_5000"),
        (2015, "earned_business", "5000_7000"),
        (2015, "earned_business", "7000_10000"),
        (2015, "earned_business", "ge_10000"),
        (2015, "wage_only", "total"),
    ]
    assert order[-1] == (2024, "earned_business", "ge_10000")


def test_mart_kostat_skipped_when_staged_missing() -> None:
    ctx = make_ctx({})
    result = PIPELINE.run(Stage.MART, ctx)
    assert pipeline.KOSTAT_MART not in result.written
    assert any(
        s.startswith(f"{pipeline.KOSTAT_TABLE}: staged table missing") for s in result.skipped
    )


def test_build_kostat_mart_is_pure_and_deterministic() -> None:
    staged = [
        {
            "release_year": 2021,
            "ref_year": 2021,
            "population": "first_marriage_within_5y",
            "income_class": "total",
            "income_lower_10k_krw": None,
            "income_upper_10k_krw": None,
            "couples": 10,
            "with_children_share": 0.5,
            "children_1_share": 0.4,
            "children_2_share": 0.1,
            "children_3plus_share": 0.0,
            "mean_children": 0.6,
            "income_concept": "earned_business",
            "source": "kostat_newlywed",
        },
        {
            "release_year": 2022,
            "ref_year": 2021,
            "population": "first_marriage_within_5y",
            "income_class": "total",
            "income_lower_10k_krw": None,
            "income_upper_10k_krw": None,
            "couples": 11,
            "with_children_share": 0.5,
            "children_1_share": 0.4,
            "children_2_share": 0.1,
            "children_3plus_share": 0.0,
            "mean_children": 0.6,
            "income_concept": "earned_business",
            "source": "kostat_newlywed",
        },
    ]
    out = pipeline.build_kostat_mart(staged)
    assert len(out) == 6
    assert {r["release_year"] for r in out} == {2022}
    assert next(r for r in out if r["metric"] == "couples")["value"] == 11
    assert out == pipeline.build_kostat_mart(list(reversed(staged)))
