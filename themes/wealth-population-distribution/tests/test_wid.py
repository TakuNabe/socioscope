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
