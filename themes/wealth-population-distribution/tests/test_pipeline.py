import io
import zipfile
from pathlib import Path

import pytest

from socioscope_core.core.pipeline import Context, Stage
from socioscope_core.testing.fakes import FakeFetcher, InMemoryRawStore, InMemoryTableStore
from theme_wealth_population_distribution import oecd, wid
from theme_wealth_population_distribution.pipeline import build_institutions_panel, build_panel
from theme_wealth_population_distribution.wiring import PIPELINE

FIXTURE = (Path(__file__).parent / "fixtures" / "wid_data_sample.csv").read_bytes()
FIXTURES = Path(__file__).parent / "fixtures"


def oecd_responses(iso3: str = "JPN") -> dict[str, bytes]:
    """Every OECD indicator URL -> the real-response fixture, with the country relabelled."""
    out: dict[str, bytes] = {}
    for name, ind in oecd.INDICATORS.items():
        payload = (FIXTURES / f"oecd_{name}_sample.csv").read_bytes()
        out[oecd.data_url(ind)] = payload.replace(b"JPN,Japan", f"{iso3},X".encode())
    return out


META_FIXTURE = (Path(__file__).parent / "fixtures" / "wid_metadata_sample.csv").read_bytes()


def country_zip(iso2: str, csv: bytes, meta: bytes = META_FIXTURE) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"WID_data_{iso2}.csv", csv)
        zf.writestr(f"WID_metadata_{iso2}.csv", meta)
    return buf.getvalue()


def make_ctx(responses: dict[str, bytes]) -> Context:
    return Context(
        fetcher=FakeFetcher(responses), raw=InMemoryRawStore(), tables=InMemoryTableStore()
    )


def test_fetch_stores_one_zip_per_country_with_license_and_reports_failures() -> None:
    ctx = make_ctx({wid.country_zip_url("JP"): country_zip("JP", FIXTURE)})
    result = PIPELINE.run(Stage.FETCH, ctx)

    assert result.written == ("wealth-population-distribution/wid_world/WID_fulldataset_JP.zip",)
    assert len(result.skipped) == len(wid.COUNTRIES) - 1 + len(oecd.INDICATORS)
    recs = ctx.raw.records()
    assert len(recs) == 1 and "CC BY-NC-SA 4.0" in recs[0].license
    assert recs[0].url == wid.country_zip_url("JP")


HTML_STUB = (
    b'<!DOCTYPE html><html><head><script>window.location.href="/lander"</script></head></html>'
)


def test_fetch_rejects_non_zip_payload_without_touching_raw_or_manifest() -> None:
    ctx = make_ctx(
        {
            wid.country_zip_url("JP"): HTML_STUB,
            wid.country_zip_url("FR"): country_zip("FR", FIXTURE.replace(b"JP;", b"FR;")),
        }
    )
    result = PIPELINE.run(Stage.FETCH, ctx)
    assert result.written == ("wealth-population-distribution/wid_world/WID_fulldataset_FR.zip",)
    assert "JP: non-zip payload (site down?)" in result.skipped
    assert (
        ctx.raw.get(
            theme="wealth-population-distribution",
            source="wid_world",
            name="WID_fulldataset_JP.zip",
        )
        is None
    )
    assert [r.name for r in ctx.raw.records()] == ["WID_fulldataset_FR.zip"]


def test_fetch_raises_when_every_wid_payload_is_non_zip() -> None:
    ctx = make_ctx({wid.country_zip_url(c): HTML_STUB for c in wid.COUNTRIES})
    with pytest.raises(RuntimeError, match="wid_world: all 46"):
        PIPELINE.run(Stage.FETCH, ctx)
    assert ctx.raw.records() == []


def test_oecd_is_csv_payload_and_fetch_rejects_html() -> None:
    good = oecd_responses()
    assert all(oecd.is_csv_payload(p) for p in good.values())
    assert not oecd.is_csv_payload(HTML_STUB) and not oecd.is_csv_payload(b"<?xml ?><Error/>")
    bad_url = oecd.data_url(oecd.INDICATORS["top_pit_rate"])
    ctx = Context(
        fetcher=FakeFetcher({**good, bad_url: HTML_STUB}),
        raw=InMemoryRawStore(),
        tables=InMemoryTableStore(),
        sources=frozenset({oecd.SOURCE}),
    )
    result = PIPELINE.run(Stage.FETCH, ctx)
    assert result.skipped == ("oecd/top_pit_rate: non-CSV payload (site down?)",)
    assert len(result.written) == len(oecd.INDICATORS) - 1
    assert "top_pit_rate.csv" not in [r.name for r in ctx.raw.records()]
    all_bad = Context(
        fetcher=FakeFetcher(dict.fromkeys(good, HTML_STUB)),
        raw=InMemoryRawStore(),
        tables=InMemoryTableStore(),
        sources=frozenset({oecd.SOURCE}),
    )
    with pytest.raises(RuntimeError, match="oecd: all 4"):
        PIPELINE.run(Stage.FETCH, all_bad)


def test_fetch_only_oecd_skips_wid_and_stores_one_csv_per_indicator() -> None:
    ctx = Context(
        fetcher=FakeFetcher(oecd_responses()),
        raw=InMemoryRawStore(),
        tables=InMemoryTableStore(),
        sources=frozenset({oecd.SOURCE}),
    )
    result = PIPELINE.run(Stage.FETCH, ctx)
    assert result.written == tuple(
        f"wealth-population-distribution/oecd/{name}.csv" for name in sorted(oecd.INDICATORS)
    )
    assert result.skipped == ()
    assert not any(u.startswith(wid.BASE) for u in ctx.fetcher.requested)  # type: ignore[attr-defined]
    recs = ctx.raw.records()
    assert len(recs) == len(oecd.INDICATORS)
    assert all("oecd.org/en/about/terms-conditions" in r.license for r in recs)


def test_stage_oecd_writes_one_table_per_indicator_and_mart_joins_institutions() -> None:
    responses = {wid.country_zip_url("JP"): country_zip("JP", FIXTURE), **oecd_responses()}
    ctx = make_ctx(responses)
    PIPELINE.run(Stage.FETCH, ctx)
    staged = PIPELINE.run(Stage.STAGE, ctx)
    assert staged.written == (
        "staged/oecd/inheritance_tax_rev_gdp",
        "staged/oecd/social_expenditure_gdp",
        "staged/oecd/tax_revenue_gdp",
        "staged/oecd/top_pit_rate",
        "staged/wid/population",
        "staged/wid/top_shares",
        "staged/wid/metadata",
        "staged/wid/data_points",
        "staged/wid/distribution",
        "staged/wid/thresholds",
    )
    socx = ctx.tables.read_table("staged/oecd/social_expenditure_gdp")
    assert [(r["iso3"], r["year"], r["value"]) for r in socx] == [
        ("JPN", 1980, 9.82),
        ("JPN", 2000, 14.916),
        ("JPN", 2022, 24.736),
    ]

    mart = PIPELINE.run(Stage.MART, ctx)
    assert mart.written == ("marts/wealth_population_panel", "marts/wealth_institutions_panel")
    inst = ctx.tables.read_table("marts/wealth_institutions_panel")
    # WID fixture has 2000/2001; OECD fixture 1980/2000/2001(pit)/2022 -> union of years >= 1980
    assert [(r["iso3"], r["year"]) for r in inst] == [
        ("JPN", 1980),
        ("JPN", 2000),
        ("JPN", 2001),
        ("JPN", 2022),
    ]
    assert inst[1] == {
        "iso3": "JPN",
        "year": 2000,
        "top1_income_share": 0.0999,
        "top10_income_share": 0.4,
        "top1_wealth_share": 0.2462,
        "top10_wealth_share": 0.58,
        "top1_income_quality": 1,
        "top1_wealth_quality": 0,
        "top1_income_observed": False,  # fixture metadata: 1986-2023 extrapolated distribution
        "top1_wealth_observed": None,  # fixture metadata says nothing about wealth 1980+
        "top_pit_rate": 50.0,
        "social_expenditure_gdp": 14.916,
        "tax_revenue_gdp": 25.330599,
        "inheritance_tax_rev_gdp": 0.331502,
        "source": "wid_world+oecd",
    }
    assert inst[0]["top1_income_share"] is None and inst[0]["top_pit_rate"] is None


def test_stage_only_oecd_leaves_wid_tables_alone() -> None:
    ctx = Context(
        fetcher=FakeFetcher(oecd_responses()),
        raw=InMemoryRawStore(),
        tables=InMemoryTableStore(),
        sources=frozenset({oecd.SOURCE}),
    )
    PIPELINE.run(Stage.FETCH, ctx)
    result = PIPELINE.run(Stage.STAGE, ctx)
    assert result.skipped == () and len(result.written) == len(oecd.INDICATORS)
    assert "staged/wid/top_shares" not in ctx.tables.list_tables()


def test_build_institutions_panel_restricts_to_oecd_members_from_1980() -> None:
    panel = [
        {"iso3": "CHN", "year": 2000, "top1_income_share": 0.1, "top1_wealth_share": 0.3},
        {"iso3": "JPN", "year": 1979, "top1_income_share": 0.1, "top1_wealth_share": 0.3},
        {
            "iso3": "JPN",
            "year": 2000,
            "top1_income_share": 0.1,
            "top1_wealth_share": 0.3,
            "top1_income_observed": False,
        },
    ]
    shares = [
        {
            "iso3": "JPN",
            "year": 2000,
            "variable": "sptinc992j",
            "percentile": "p99p100",
            "value": 0.1,
            "data_quality": 4,
        }
    ]
    staged = {"top_pit_rate": [{"iso3": "JPN", "year": 2000, "value": 50.0}]}
    out = build_institutions_panel(panel, shares, staged)
    assert [(r["iso3"], r["year"]) for r in out] == [("JPN", 2000)]
    assert out[0]["top1_income_quality"] == 4 and out[0]["top1_wealth_quality"] is None
    assert out[0]["top1_income_observed"] is False and out[0]["top1_wealth_observed"] is None
    assert out[0]["top_pit_rate"] == 50.0 and out[0]["social_expenditure_gdp"] is None


def test_stage_then_mart_build_panel_from_raw() -> None:
    fr = FIXTURE.replace(b"JP;", b"FR;")
    ctx = make_ctx(
        {
            wid.country_zip_url("JP"): country_zip("JP", FIXTURE),
            wid.country_zip_url("FR"): country_zip("FR", fr, META_FIXTURE.replace(b"JP;", b"FR;")),
        }
    )
    PIPELINE.run(Stage.FETCH, ctx)
    staged = PIPELINE.run(Stage.STAGE, ctx)
    assert staged.written[:2] == ("staged/wid/population", "staged/wid/top_shares")
    assert len(staged.skipped) == len(wid.COUNTRIES) - 2 + len(oecd.INDICATORS)  # no OECD raw
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
    assert without_h4(panel[2]) == {
        "iso3": "JPN",
        "year": 2000,
        "top1_income_share": 0.0999,
        "top10_income_share": 0.4,
        "bottom50_income_share": 0.19,
        "top1_wealth_share": 0.2462,
        "top10_wealth_share": 0.58,
        "population": 126843000.0,
        "source": "wid_world",
        "top1_income_observed": False,  # fixture method: 1986-2023 extrapolated distribution
        "top1_wealth_observed": None,  # fixture method says nothing about 1980+
    }
    assert panel[3]["top1_income_share"] == 0.1012 and panel[3]["top10_wealth_share"] is None


def test_stage_without_raw_skips_explicitly_and_writes_nothing() -> None:
    ctx = make_ctx({})
    result = PIPELINE.run(Stage.STAGE, ctx)
    assert result.written == ()
    assert len(result.skipped) == len(wid.COUNTRIES) + len(oecd.INDICATORS)
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
    assert [without_h4(r) for r in build_panel(shares, population)] == [
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
            "top1_income_observed": None,
            "top1_wealth_observed": None,
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
            "top1_income_observed": None,
            "top1_wealth_observed": None,
        },
    ]


# ---------------------------------------------------------------- metadata / data_points / observed
def test_stage_writes_metadata_and_data_points_and_mart_gets_observed_flags() -> None:
    data = (
        FIXTURE
        + b"JP;sptincj992;p99p100;1979;0.09;992;j;4\n"
        + b"JP;shwealj992;p99p100;1979;0.2;992;j;0\n"
    )
    meta = META_FIXTURE.replace(
        b"1986-2023: extrapolated distribution using survey data",
        b"1986-2000: survey + tax data, 2001-2023: extrapolated distribution using survey data",
    )
    ctx = make_ctx({wid.country_zip_url("JP"): country_zip("JP", data, meta)})
    PIPELINE.run(Stage.FETCH, ctx)
    staged = PIPELINE.run(Stage.STAGE, ctx)
    assert staged.written == (
        "staged/wid/population",
        "staged/wid/top_shares",
        "staged/wid/metadata",
        "staged/wid/data_points",
        "staged/wid/distribution",
        "staged/wid/thresholds",
    )
    meta_rows = ctx.tables.read_table("staged/wid/metadata")
    assert [(m["iso3"], m["variable"]) for m in meta_rows] == [
        ("JPN", "npopul999i"),
        ("JPN", "shweal992j"),
        ("JPN", "sptinc992j"),
    ]
    points = ctx.tables.read_table("staged/wid/data_points")
    assert [(p["variable"], p["year"], p["is_observed"]) for p in points] == [
        ("shweal992j", 1979, False),
        ("shweal992j", 2000, None),
        ("sptinc992j", 1979, False),
        ("sptinc992j", 2000, True),
        ("sptinc992j", 2001, False),
    ]

    PIPELINE.run(Stage.MART, ctx)
    panel = ctx.tables.read_table("marts/wealth_population_panel")
    assert [(p["year"], p["top1_income_observed"], p["top1_wealth_observed"]) for p in panel] == [
        (1979, False, False),
        (2000, True, None),
        (2001, False, None),
    ]
    # existing columns unchanged
    assert panel[1]["top1_income_share"] == 0.0999 and panel[1]["population"] == 126843000.0


def test_mart_without_data_points_table_keeps_observed_flags_null() -> None:
    ctx = make_ctx({})
    shares, population = wid.rows_from_csv(FIXTURE)
    ctx.tables.write_table("staged/wid/top_shares", shares)
    ctx.tables.write_table("staged/wid/population", population)
    result = PIPELINE.run(Stage.MART, ctx)
    assert result.written == ("marts/wealth_population_panel",)
    assert "staged/wid/data_points" in " ".join(result.notes)
    panel = ctx.tables.read_table("marts/wealth_population_panel")
    assert all(
        p["top1_income_observed"] is None and p["top1_wealth_observed"] is None for p in panel
    )


def test_build_panel_observed_columns_default_to_none_and_keep_column_order() -> None:
    share = {
        "iso3": "JPN",
        "year": 2000,
        "variable": "sptinc992j",
        "percentile": "p99p100",
        "value": 0.1,
    }
    panel = build_panel([share], [])
    assert panel[0]["top1_income_observed"] is None and panel[0]["top1_wealth_observed"] is None
    panel = build_panel(
        [share], [], [{"iso3": "JPN", "year": 2000, "variable": "sptinc992j", "is_observed": True}]
    )
    assert panel[0]["top1_income_observed"] is True and panel[0]["top1_wealth_observed"] is None
    assert list(panel[0])[:11] == [
        "iso3",
        "year",
        "top1_income_share",
        "top10_income_share",
        "bottom50_income_share",
        "top1_wealth_share",
        "top10_wealth_share",
        "population",
        "source",
        "top1_income_observed",
        "top1_wealth_observed",
    ]


# ---------------------------------------------------------------- distribution / thresholds (H4)
def g_partition(
    iso3: str, year: int, variable: str, shares: dict[str, float]
) -> list[dict[str, object]]:
    """127 g-percentile rows; `shares` fixes specific codes, the rest spread the remainder
    proportionally to bracket width (uniform density -> Gini 0 when nothing is fixed)."""
    from theme_wealth_population_distribution import distribution as d

    codes = d.g_percentiles()
    bounds = {c: d.parse_percentile(c) for c in codes}
    rest_width = sum(b[1] - b[0] for c, b in bounds.items() if b is not None and c not in shares)
    remainder = 1.0 - sum(shares.values())
    out: list[dict[str, object]] = []
    for c in codes:
        lo, hi = bounds[c]  # type: ignore[misc]
        out.append(
            {
                "iso3": iso3,
                "year": year,
                "variable": variable,
                "percentile": c,
                "p_lower": lo,
                "p_upper": hi,
                "share": shares.get(c, remainder * (hi - lo) / rest_width),
                "data_quality": 1,
                "source": "wid_world",
            }
        )
    return out


def without_h4(row: dict[str, object]) -> dict[str, object]:
    """The pre-H4 view of a mart row (first 11 columns), for the older exact-equality tests."""
    return {k: v for k, v in row.items() if k not in H4_COLUMNS}


def share(variable: str, percentile: str, value: float) -> dict[str, object]:
    return {
        "iso3": "JPN",
        "year": 2000,
        "variable": variable,
        "percentile": percentile,
        "value": value,
    }


def tail(variable: str, percentile: str, lo: float, value: float) -> dict[str, object]:
    return {
        "iso3": "JPN",
        "year": 2000,
        "variable": variable,
        "percentile": percentile,
        "p_lower": lo,
        "p_upper": 100.0,
        "share": value,
    }


def threshold(variable: str, percentile: int, value: float) -> dict[str, object]:
    return {
        "iso3": "JPN",
        "year": 2000,
        "variable": variable,
        "percentile": percentile,
        "value": value,
    }


H4_COLUMNS = [
    "top01_income_share", "top001_income_share", "top01_wealth_share", "top001_wealth_share",
    "gini_income", "gini_wealth", "middle40_income_share", "middle40_wealth_share",
    "p90_p50_income", "p50_p10_income", "p90_p50_wealth", "p50_p10_wealth",
]  # fmt: skip


def test_build_panel_appends_h4_columns_after_existing_ones_and_keeps_none() -> None:
    shares = [
        share("sptinc992j", "p99p100", 0.10),
        share("sptinc992j", "p90p100", 0.40),
        share("sptinc992j", "p0p50", 0.19),
        share("shweal992j", "p90p100", 0.58),
        share("shweal992j", "p0p50", 0.05),
    ]
    dist = [
        tail("sptinc992j", "p99.9p100", 99.9, 0.03),
        tail("sptinc992j", "p99.99p100", 99.99, 0.008),
        tail("shweal992j", "p99.9p100", 99.9, 0.09),
        # uniform partition -> Gini 0 for income; wealth partition incomplete (126 rows) -> None
        *g_partition("JPN", 2000, "sptinc992j", {}),
        *g_partition("JPN", 2000, "shweal992j", {})[:-1],
    ]
    thresholds = [
        threshold("tptinc992j", 10, 100.0),
        threshold("tptinc992j", 50, 300.0),
        threshold("tptinc992j", 90, 900.0),
        threshold("thweal992j", 50, 10.0),
        threshold("thweal992j", 10, -5.0),
    ]
    panel = build_panel(shares, [], None, dist, thresholds)
    assert list(panel[0])[11:] == H4_COLUMNS
    r = panel[0]
    assert r["top01_income_share"] == 0.03 and r["top001_income_share"] == 0.008
    assert r["top01_wealth_share"] == 0.09 and r["top001_wealth_share"] is None
    assert r["gini_income"] == pytest.approx(0.0, abs=1e-9) and r["gini_wealth"] is None
    assert r["middle40_income_share"] == pytest.approx(0.41)
    assert r["middle40_wealth_share"] == pytest.approx(0.37)
    assert r["p90_p50_income"] == pytest.approx(3.0) and r["p50_p10_income"] == pytest.approx(3.0)
    assert r["p90_p50_wealth"] is None and r["p50_p10_wealth"] is None  # p90 missing / p10 <= 0
    # without the new tables every tail/gini/ratio column is None and old columns are untouched
    old = build_panel(shares, [])
    assert all(old[0][c] is None for c in H4_COLUMNS if "middle40" not in c)
    assert old[0]["top1_income_share"] == 0.10


def test_build_panel_gini_is_none_when_partition_shares_do_not_sum_to_one() -> None:
    dist = g_partition("JPN", 2000, "sptinc992j", {})
    for r in dist[:10]:
        r["share"] = 0.5  # total far above 1 -> inconsistent -> None, not an exception
    panel = build_panel([], [], None, dist, [])
    assert panel[0]["gini_income"] is None


def test_stage_writes_distribution_and_thresholds_and_mart_fills_h4_columns() -> None:
    ctx = make_ctx({wid.country_zip_url("JP"): country_zip("JP", FIXTURE)})
    PIPELINE.run(Stage.FETCH, ctx)
    staged = PIPELINE.run(Stage.STAGE, ctx)
    assert staged.written == (
        "staged/wid/population",
        "staged/wid/top_shares",
        "staged/wid/metadata",
        "staged/wid/data_points",
        "staged/wid/distribution",
        "staged/wid/thresholds",
    )
    dist = ctx.tables.read_table("staged/wid/distribution")
    assert [r["percentile"] for r in dist] == ["p0p1", "p99.9p100", "p99.99p100", "p99.999p100"]
    th = ctx.tables.read_table("staged/wid/thresholds")
    assert [(r["variable"], r["percentile"]) for r in th] == [
        ("thweal992j", 50),
        ("tptinc992j", 10),
        ("tptinc992j", 50),
        ("tptinc992j", 90),
        ("tptinc992j", 99),
    ]
    mart = PIPELINE.run(Stage.MART, ctx)
    assert mart.written == ("marts/wealth_population_panel",) and mart.notes == ()
    panel = ctx.tables.read_table("marts/wealth_population_panel")
    r = panel[0]
    assert r["year"] == 2000 and r["top1_income_share"] == 0.0999  # existing column intact
    assert r["top01_income_share"] == 0.03 and r["top001_income_share"] == 0.008
    assert r["gini_income"] is None  # fixture has no full partition
    assert r["middle40_income_share"] == pytest.approx(0.41)
    assert r["p90_p50_income"] == pytest.approx(2.5)
    assert r["p50_p10_income"] == pytest.approx(3000000 / 900000)
    assert r["p90_p50_wealth"] is None
    assert panel[1]["top01_income_share"] is None  # 2001 has no tail row


def test_mart_without_distribution_tables_leaves_h4_columns_null_with_note() -> None:
    ctx = make_ctx({})
    shares, population = wid.rows_from_csv(FIXTURE)
    ctx.tables.write_table("staged/wid/top_shares", shares)
    ctx.tables.write_table("staged/wid/population", population)
    result = PIPELINE.run(Stage.MART, ctx)
    assert any("staged/wid/distribution" in n for n in result.notes)
    panel = ctx.tables.read_table("marts/wealth_population_panel")
    assert all(p["top01_income_share"] is None and p["gini_income"] is None for p in panel)
    assert panel[0]["middle40_income_share"] == pytest.approx(0.41)  # needs only top_shares
