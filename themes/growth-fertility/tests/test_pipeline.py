from pathlib import Path

import pytest

from socioscope_core.core.pipeline import Context, Stage
from socioscope_core.testing.fakes import FakeFetcher, InMemoryRawStore, InMemoryTableStore
from theme_growth_fertility import dhs, estat, pipeline
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
    # every other indicator + countries + all e-Stat tables + 2 DHS files had no fake response
    assert len(result.skipped) == len(wb.INDICATORS) + len(estat.TABLES) + 2
    recs = ctx.raw.records()
    assert len(recs) == 1 and recs[0].license.startswith("CC BY 4.0")
    assert ctx.raw.get(theme="growth-fertility", source="worldbank_wdi", name="tfr.json") == FIXTURE


def test_fetch_also_stores_country_metadata() -> None:
    ctx = make_ctx(all_responses())
    result = PIPELINE.run(Stage.FETCH, ctx)
    assert "growth-fertility/worldbank_wdi/countries.json" in result.written
    assert all(s.startswith(tuple(t.key for t in estat.TABLES)) for s in result.skipped)


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
    assert len(result.skipped) == len(wb.INDICATORS) + 1 + len(estat.TABLES) + 2


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
    assert len(result.skipped) == len(wb.INDICATORS) + 1 + 2  # no World Bank / DHS responses
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
    assert len(result.skipped) == len(wb.INDICATORS) + 1 + len(estat.TABLES)
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
