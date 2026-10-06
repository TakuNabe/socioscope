import io
import zipfile
from pathlib import Path

import pytest

from theme_wealth_population_distribution import wid

FIXTURE = (Path(__file__).parent / "fixtures" / "wid_data_sample.csv").read_bytes()


def make_zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, payload in members.items():
            zf.writestr(name, payload)
    return buf.getvalue()


def test_country_zip_url() -> None:
    assert wid.country_zip_url("JP") == "https://wid.world/bulk_download/WID_fulldataset_JP.zip"


def test_country_list_is_iso2_sorted_and_mappable() -> None:
    assert list(wid.COUNTRIES) == sorted(wid.COUNTRIES)
    assert len(set(wid.COUNTRIES)) == len(wid.COUNTRIES) == 46
    assert all(wid.iso2_to_iso3(c) is not None for c in wid.COUNTRIES)


def test_iso2_to_iso3_mapping_is_committed_and_drops_non_countries() -> None:
    assert wid.iso2_to_iso3("JP") == "JPN"
    assert wid.iso2_to_iso3("KS") == "XKX"  # WID's Kosovo code -> World Bank style
    assert wid.iso2_to_iso3("SU") == "SUN"  # former USSR keeps ISO 3166-3 code
    for code in ("WO", "QE", "XF", "US-CA", "QE-MER", "ZZ", ""):
        assert wid.iso2_to_iso3(code) is None


def test_is_zip_payload_checks_magic_bytes() -> None:
    assert wid.is_zip_payload(make_zip({"WID_data_JP.csv": FIXTURE}))
    html = (
        b'<!DOCTYPE html><html><head><script>window.location.href="/lander"</script></head></html>'
    )
    assert not wid.is_zip_payload(html)
    assert not wid.is_zip_payload(b"") and not wid.is_zip_payload(b"PK\x05\x06")


def test_extract_data_csv_from_country_zip() -> None:
    payload = make_zip({"WID_data_JP.csv": FIXTURE, "README.md": b"x", "WID_metadata_JP.csv": b"y"})
    assert wid.extract_data_csv(payload, "JP") == FIXTURE


def test_extract_data_csv_fails_closed_when_member_missing_or_not_zip() -> None:
    with pytest.raises(ValueError, match="WID_data_JP.csv"):
        wid.extract_data_csv(make_zip({"README.md": b"x"}), "JP")
    with pytest.raises(ValueError, match="not a zip"):
        wid.extract_data_csv(b"country;variable\n", "JP")


def test_rows_keep_only_selected_series_and_canonical_codes() -> None:
    shares, population = wid.rows_from_csv(FIXTURE)
    assert [(r["variable"], r["percentile"], r["year"], r["value"]) for r in shares] == [
        ("shweal992j", "p90p100", 2000, 0.58),
        ("shweal992j", "p99p100", 2000, 0.2462),
        ("sptinc992j", "p0p50", 2000, 0.19),
        ("sptinc992j", "p50p90", 2000, 0.41),
        ("sptinc992j", "p90p100", 2000, 0.4),
        ("sptinc992j", "p99p100", 2000, 0.0999),
        ("sptinc992j", "p99p100", 2001, 0.1012),
    ]
    assert shares[0] == {
        "iso3": "JPN",
        "year": 2000,
        "variable": "shweal992j",
        "percentile": "p90p100",
        "value": 0.58,
        "data_quality": 0,
        "source": "wid_world",
    }
    assert population == [
        {
            "iso3": "JPN",
            "year": 2000,
            "value": 126843000.0,
            "data_quality": 5,
            "source": "wid_world",
        },
        {
            "iso3": "JPN",
            "year": 2001,
            "value": 127000000.0,
            "data_quality": None,
            "source": "wid_world",
        },
    ]


def test_rows_drop_regions_and_subnational_codes() -> None:
    csv = (
        b"country;variable;percentile;year;value;age;pop;data_quality\n"
        b"WO;sptincj992;p99p100;2000;0.2;992;j;1\n"
        b"US-CA;sptincj992;p99p100;2000;0.2;992;j;1\n"
        b"QE-MER;sptincj992;p99p100;2000;0.2;992;j;1\n"
        b"FR;sptincj992;p99p100;2000;0.1;992;j;1\n"
    )
    shares, _ = wid.rows_from_csv(csv)
    assert [r["iso3"] for r in shares] == ["FRA"]


def test_non_digit_data_quality_becomes_none_but_value_stays_strict() -> None:
    csv = (
        b"country;variable;percentile;year;value;age;pop;data_quality\n"
        b"CL;sptincj992;p99p100;1980;0.1198;992;j;0.1198\n"
    )
    shares, _ = wid.rows_from_csv(csv)
    assert shares[0]["data_quality"] is None and shares[0]["value"] == 0.1198


def test_conversion_is_deterministic() -> None:
    assert wid.rows_from_csv(FIXTURE) == wid.rows_from_csv(FIXTURE)


@pytest.mark.parametrize(
    "payload",
    [
        b"country,variable,percentile,year,value\nJP,sptincj992,p99p100,2000,0.1\n",  # comma
        b"country;variable;percentile;year;value;age;pop;data_quality\nJP;sptincj992;p99p100;20x0;0.1;992;j;1\n",
        b"country;variable;percentile;year;value;age;pop;data_quality\nJP;sptincj992;p99p100;2000;abc;992;j;1\n",
        b"country;variable;percentile;year;value;age;pop;data_quality\nJP;sptincj992;p99p100;2000\n",
    ],
)
def test_malformed_csv_fails_closed(payload: bytes) -> None:
    with pytest.raises(ValueError):
        wid.rows_from_csv(payload)


# ---------------------------------------------------------------- metadata (WID_metadata_XX.csv)
META_FIXTURE = (Path(__file__).parent / "fixtures" / "wid_metadata_sample.csv").read_bytes()


def test_extract_metadata_csv_from_country_zip_fails_closed() -> None:
    payload = make_zip({"WID_data_JP.csv": FIXTURE, "WID_metadata_JP.csv": META_FIXTURE})
    assert wid.extract_metadata_csv(payload, "JP") == META_FIXTURE
    with pytest.raises(ValueError, match="WID_metadata_JP.csv"):
        wid.extract_metadata_csv(make_zip({"WID_data_JP.csv": FIXTURE}), "JP")
    with pytest.raises(ValueError, match="not a zip"):
        wid.extract_metadata_csv(b"country;variable\n", "JP")


def test_metadata_rows_keep_selected_series_with_canonical_codes() -> None:
    rows = wid.metadata_rows_from_csv(META_FIXTURE)
    assert [(r["iso3"], r["variable"]) for r in rows] == [
        ("JPN", "npopul999i"),
        ("JPN", "shweal992j"),
        ("JPN", "sptinc992j"),
    ]
    wealth = rows[1]
    assert wealth["shortname"] == "Net personal wealth"
    assert wealth["unit"] == "share"
    assert str(wealth["source_text"]).startswith("Bajard, F.")
    assert str(wealth["method"]).startswith("Before 1980, series is constructed")
    assert wealth["avg_quality"] == 0.0
    assert wealth["source"] == "wid_world"
    assert rows[0]["avg_quality"] is None  # blank in the file
    assert rows[2]["avg_quality"] == 1.3
    assert '"Technical Note"' in str(rows[2]["source_text"])  # quoted field, doubled quotes


def test_metadata_rows_are_deterministic() -> None:
    assert wid.metadata_rows_from_csv(META_FIXTURE) == wid.metadata_rows_from_csv(META_FIXTURE)


@pytest.mark.parametrize(
    "payload",
    [
        b"country,variable,age\nJP,sptincj992,992\n",  # comma separated
        # a column added or renamed by WID must stop the stage, not silently pass
        META_FIXTURE.replace(b";avg_quality", b";avg_quality;data_points", 1),
        META_FIXTURE.replace(b";avg_quality", b";quality", 1),
        META_FIXTURE.replace(b";1.3\n", b";high\n", 1),  # avg_quality not a number
    ],
)
def test_metadata_malformed_fails_closed(payload: bytes) -> None:
    with pytest.raises(ValueError):
        wid.metadata_rows_from_csv(payload)


def test_parse_method_by_year_and_before_clauses() -> None:
    rows = wid.metadata_rows_from_csv(META_FIXTURE)
    info = wid.parse_method(str(rows[2]["method"]))
    assert info.by_year[1980] == "extrapolated distribution"
    assert info.by_year[1981] == info.by_year[1983] == "survey + concept correction + tax data"
    assert info.by_year[2023] == "extrapolated distribution using survey data"
    assert 1979 not in info.by_year and 2024 not in info.by_year
    assert info.trend_before == 1980 and info.long_run_before == 1886
    wealth = wid.parse_method(str(rows[1]["method"]))
    assert wealth.by_year == {} and wealth.trend_before == 1980 and wealth.long_run_before is None
    empty = wid.parse_method("")
    assert empty.by_year == {} and empty.trend_before is None and empty.long_run_before is None


def test_parse_method_rejects_unparseable_summary_segment() -> None:
    with pytest.raises(ValueError, match="segment"):
        wid.parse_method(
            "Summary of data construction by year (see source for details): 1980 survey."
        )


@pytest.mark.parametrize(
    ("segment", "construction"),
    [
        ("survey + concept correction + tax data", "observed"),
        ("survey + tax data", "observed"),
        ("survey + imputed nonresponse", "observed"),
        ("survey + concept correction + extrapolated nonresponse", "observed"),
        ("survey + concept correction + interpolated tax data", "partial"),
        ("interpolated survey + concept correction + tax data", "partial"),
        ("extrapolated distribution + tax data", "partial"),
        ("extrapolated distribution survey + tax data", "partial"),  # WID typo, seen in the raw
        ("interpolated survey + concept correction + interpolated tax data", "imputed"),
        ("extrapolated distribution", "imputed"),
        ("extrapolated distribution using survey data", "imputed"),
        ("extrapolated distribtion using survey data", "imputed"),  # WID typo, seen in the raw
        ("interpolated", "imputed"),
    ],
)
def test_classify_segment(segment: str, construction: str) -> None:
    assert wid.classify_segment(segment) == construction


def test_classify_segment_fails_closed_on_unknown_input() -> None:
    with pytest.raises(ValueError, match="unknown"):
        wid.classify_segment("administrative registers")


def test_classify_year_precedence_and_unknown() -> None:
    rows = wid.metadata_rows_from_csv(META_FIXTURE)
    income = wid.parse_method(str(rows[2]["method"]))
    assert wid.classify_year(income, 1982) == ("observed", "method_by_year")
    assert wid.classify_year(income, 1984) == ("imputed", "method_by_year")
    assert wid.classify_year(income, 1985) == ("partial", "method_by_year")
    assert wid.classify_year(income, 1979) == ("imputed", "trend_before_1980")
    assert wid.classify_year(income, 1850) == ("imputed", "long_run_before_1886")
    assert wid.classify_year(income, 2024) == (None, None)  # after the documented range
    wealth = wid.parse_method(str(rows[1]["method"]))
    assert wid.classify_year(wealth, 1970) == ("imputed", "trend_before_1980")
    assert wid.classify_year(wealth, 1980) == (None, None)
    assert wid.classify_year(wid.parse_method(""), 2000) == (None, None)


def test_data_point_rows_follow_years_present_in_shares() -> None:
    shares, _ = wid.rows_from_csv(FIXTURE)  # JPN sptinc992j 2000, 2001; shweal992j 2000
    shares.append({**shares[0], "year": 1979})  # shweal992j p90p100 1979
    shares.append({**shares[0], "year": 1979, "percentile": "p99p100"})  # same year, 2nd pct
    meta = wid.metadata_rows_from_csv(META_FIXTURE)
    meta[2] = {
        **meta[2],
        "method": "Summary of data construction by year (see source for details): "
        "2000: survey + tax data, 2001-2023: extrapolated distribution.",
    }
    points = wid.data_point_rows(shares, meta)
    assert points == [
        {
            "iso3": "JPN",
            "year": 1979,
            "variable": "shweal992j",
            "is_observed": False,
            "construction": "imputed",
            "basis": "trend_before_1980",
            "method_segment": None,
            "source": "wid_world",
        },
        {
            "iso3": "JPN",
            "year": 2000,
            "variable": "shweal992j",
            "is_observed": None,
            "construction": None,
            "basis": None,
            "method_segment": None,
            "source": "wid_world",
        },
        {
            "iso3": "JPN",
            "year": 2000,
            "variable": "sptinc992j",
            "is_observed": True,
            "construction": "observed",
            "basis": "method_by_year",
            "method_segment": "survey + tax data",
            "source": "wid_world",
        },
        {
            "iso3": "JPN",
            "year": 2001,
            "variable": "sptinc992j",
            "is_observed": False,
            "construction": "imputed",
            "basis": "method_by_year",
            "method_segment": "extrapolated distribution",
            "source": "wid_world",
        },
    ]


def test_data_point_rows_without_metadata_row_are_unknown() -> None:
    shares, _ = wid.rows_from_csv(FIXTURE)
    points = wid.data_point_rows(shares, [])
    assert {p["is_observed"] for p in points} == {None}
    assert len(points) == 3  # (JPN, shweal992j, 2000), (JPN, sptinc992j, 2000), (…, 2001)


# ---------------------------------------------------------------- distribution / thresholds (H4)
def test_distribution_rows_keep_g_percentiles_and_top_tails_with_bounds() -> None:
    dist, thresholds = wid.distribution_rows_from_csv(FIXTURE)
    assert [
        (r["variable"], r["percentile"], r["p_lower"], r["p_upper"], r["share"]) for r in dist
    ] == [
        ("sptinc992j", "p0p1", 0.0, 1.0, -0.001),
        ("sptinc992j", "p99.9p100", 99.9, 100.0, 0.03),
        ("sptinc992j", "p99.99p100", 99.99, 100.0, 0.008),
        ("sptinc992j", "p99.999p100", 99.999, 100.0, 0.004),
    ]
    assert dist[0] == {
        "iso3": "JPN",
        "year": 2000,
        "variable": "sptinc992j",
        "percentile": "p0p1",
        "p_lower": 0.0,
        "p_upper": 1.0,
        "share": -0.001,
        "data_quality": 1,
        "source": "wid_world",
    }
    # p0p50 / p90p100 / p0p90 (neither g-percentiles nor the two top tails) stay out of this table
    assert [(r["variable"], r["percentile"], r["value"]) for r in thresholds] == [
        ("thweal992j", 50, 12000000.0),
        ("tptinc992j", 10, 900000.0),
        ("tptinc992j", 50, 3000000.0),
        ("tptinc992j", 90, 7500000.0),
        ("tptinc992j", 99, 21000000.0),
    ]
    assert thresholds[1] == {
        "iso3": "JPN",
        "year": 2000,
        "variable": "tptinc992j",
        "percentile": 10,
        "percentile_code": "p10p11",
        "value": 900000.0,
        "unit": "local currency, constant prices",
        "data_quality": 1,
        "source": "wid_world",
    }


def test_distribution_rows_fail_closed_on_bad_header_and_are_deterministic() -> None:
    with pytest.raises(ValueError, match="header"):
        wid.distribution_rows_from_csv(b"a,b\n1,2\n")
    assert wid.distribution_rows_from_csv(FIXTURE) == wid.distribution_rows_from_csv(FIXTURE)


def test_existing_rows_from_csv_is_unchanged_by_new_fixture_rows() -> None:
    shares, population = wid.rows_from_csv(FIXTURE)
    assert len(shares) == 7 and len(population) == 2
    assert not any(r["percentile"] in {"p99.9p100", "p99.99p100", "p0p1"} for r in shares)
