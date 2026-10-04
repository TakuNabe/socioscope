from pathlib import Path

from socioscope_core.core.pipeline import Context, Stage
from socioscope_core.testing.fakes import FakeFetcher, InMemoryRawStore, InMemoryTableStore
from theme_growth_fertility import worldbank as wb
from theme_growth_fertility.pipeline import build_panel
from theme_growth_fertility.wiring import PIPELINE

FIXTURE = (Path(__file__).parent / "fixtures" / "tfr_page.json").read_bytes()


def make_ctx(responses: dict[str, bytes]) -> Context:
    return Context(
        fetcher=FakeFetcher(responses), raw=InMemoryRawStore(), tables=InMemoryTableStore()
    )


def test_fetch_stores_raw_with_manifest_and_reports_failures() -> None:
    ctx = make_ctx({wb.indicator_url(wb.INDICATORS["tfr"]): FIXTURE})
    result = PIPELINE.run(Stage.FETCH, ctx)

    assert result.written == ("growth-fertility/worldbank_wdi/tfr.json",)
    assert len(result.skipped) == 2  # two indicators had no fake response
    recs = ctx.raw.records()
    assert len(recs) == 1 and recs[0].license.startswith("CC BY 4.0")
    assert ctx.raw.get(theme="growth-fertility", source="worldbank_wdi", name="tfr.json") == FIXTURE


def test_stage_then_mart_build_panel_from_raw() -> None:
    ctx = make_ctx({wb.indicator_url(code): FIXTURE for code in wb.INDICATORS.values()})
    PIPELINE.run(Stage.FETCH, ctx)
    staged = PIPELINE.run(Stage.STAGE, ctx)
    assert set(staged.written) == {f"staged/worldbank/{k}" for k in wb.INDICATORS}

    mart = PIPELINE.run(Stage.MART, ctx)
    assert mart.written == ("marts/growth_fertility_panel",)
    panel = ctx.tables.read_table("marts/growth_fertility_panel")
    assert panel[0] == {
        "iso3": "JPN",
        "country": "Japan",
        "year": 2000,
        "tfr": 1.36,
        "gdp_pcap_ppp": 1.36,
        "gdp_growth": 1.36,
    }
    assert [p["iso3"] for p in panel] == ["JPN", "JPN", "USA"]


def test_stage_without_raw_skips_explicitly() -> None:
    ctx = make_ctx({})
    result = PIPELINE.run(Stage.STAGE, ctx)
    assert result.written == () and len(result.skipped) == 3


def test_build_panel_keeps_missing_as_none() -> None:
    staged = {
        "tfr": [{"iso3": "JPN", "country": "Japan", "year": 2000, "value": 1.36}],
        "gdp_growth": [{"iso3": "JPN", "country": "Japan", "year": 2001, "value": 0.4}],
    }
    assert build_panel(staged) == [
        {"iso3": "JPN", "country": "Japan", "year": 2000, "tfr": 1.36, "gdp_growth": None},
        {"iso3": "JPN", "country": "Japan", "year": 2001, "tfr": None, "gdp_growth": 0.4},
    ]
