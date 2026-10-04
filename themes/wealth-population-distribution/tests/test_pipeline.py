import io
import zipfile
from pathlib import Path

from socioscope_core.core.pipeline import Context, Stage
from socioscope_core.testing.fakes import FakeFetcher, InMemoryRawStore, InMemoryTableStore
from theme_wealth_population_distribution import wid
from theme_wealth_population_distribution.pipeline import build_panel
from theme_wealth_population_distribution.wiring import PIPELINE

FIXTURE = (Path(__file__).parent / "fixtures" / "wid_data_sample.csv").read_bytes()


def country_zip(iso2: str, csv: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"WID_data_{iso2}.csv", csv)
        zf.writestr(f"WID_metadata_{iso2}.csv", b"meta")
    return buf.getvalue()


def make_ctx(responses: dict[str, bytes]) -> Context:
    return Context(
        fetcher=FakeFetcher(responses), raw=InMemoryRawStore(), tables=InMemoryTableStore()
    )


def test_fetch_stores_one_zip_per_country_with_license_and_reports_failures() -> None:
    ctx = make_ctx({wid.country_zip_url("JP"): country_zip("JP", FIXTURE)})
    result = PIPELINE.run(Stage.FETCH, ctx)

    assert result.written == ("wealth-population-distribution/wid_world/WID_fulldataset_JP.zip",)
    assert len(result.skipped) == len(wid.COUNTRIES) - 1
    recs = ctx.raw.records()
    assert len(recs) == 1 and "CC BY-NC-SA 4.0" in recs[0].license
    assert recs[0].url == wid.country_zip_url("JP")


def test_stage_then_mart_build_panel_from_raw() -> None:
    fr = FIXTURE.replace(b"JP;", b"FR;")
    ctx = make_ctx(
        {
            wid.country_zip_url("JP"): country_zip("JP", FIXTURE),
            wid.country_zip_url("FR"): country_zip("FR", fr),
        }
    )
    PIPELINE.run(Stage.FETCH, ctx)
    staged = PIPELINE.run(Stage.STAGE, ctx)
    assert staged.written == ("staged/wid/population", "staged/wid/top_shares")
    assert len(staged.skipped) == len(wid.COUNTRIES) - 2
    shares = ctx.tables.read_table("staged/wid/top_shares")
    assert [r["iso3"] for r in shares] == ["FRA"] * 7 + ["JPN"] * 7

    mart = PIPELINE.run(Stage.MART, ctx)
    assert mart.written == ("marts/wealth_population_panel",)
    panel = ctx.tables.read_table("marts/wealth_population_panel")
    assert [(p["iso3"], p["year"]) for p in panel] == [
        ("FRA", 2000),
        ("FRA", 2001),
        ("JPN", 2000),
        ("JPN", 2001),
    ]
    assert panel[2] == {
        "iso3": "JPN",
        "year": 2000,
        "top1_income_share": 0.0999,
        "top10_income_share": 0.4,
        "bottom50_income_share": 0.19,
        "top1_wealth_share": 0.2462,
        "top10_wealth_share": 0.58,
        "population": 126843000.0,
        "source": "wid_world",
    }
    assert panel[3]["top1_income_share"] == 0.1012 and panel[3]["top10_wealth_share"] is None


def test_stage_without_raw_skips_explicitly_and_writes_nothing() -> None:
    ctx = make_ctx({})
    result = PIPELINE.run(Stage.STAGE, ctx)
    assert result.written == () and len(result.skipped) == len(wid.COUNTRIES)
    assert ctx.tables.list_tables() == []
    mart = PIPELINE.run(Stage.MART, ctx)
    assert mart.written == () and mart.skipped


def test_build_panel_keeps_missing_as_none() -> None:
    shares = [
        {
            "iso3": "JPN",
            "year": 2000,
            "variable": "sptinc992j",
            "percentile": "p99p100",
            "value": 0.1,
        },
        {
            "iso3": "JPN",
            "year": 2000,
            "variable": "sptinc992j",
            "percentile": "p99.9p100",
            "value": 9.0,
        },
    ]
    population = [{"iso3": "JPN", "year": 2001, "value": 100.0}]
    assert build_panel(shares, population) == [
        {
            "iso3": "JPN",
            "year": 2000,
            "top1_income_share": 0.1,
            "top10_income_share": None,
            "bottom50_income_share": None,
            "top1_wealth_share": None,
            "top10_wealth_share": None,
            "population": None,
            "source": "wid_world",
        },
        {
            "iso3": "JPN",
            "year": 2001,
            "top1_income_share": None,
            "top10_income_share": None,
            "bottom50_income_share": None,
            "top1_wealth_share": None,
            "top10_wealth_share": None,
            "population": 100.0,
            "source": "wid_world",
        },
    ]
