import math

import polars as pl
import pytest

from theme_growth_fertility.analysis import a20261005_h4_stage_vs_gdp as h4


def panel() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "iso3": ["JPN", "JPN", "NGA", "NGA", "IND", "TUV"],
            "country": ["Japan", "Japan", "Nigeria", "Nigeria", "India", "Tuvalu"],
            "year": [2000, 2010, 2000, 2010, 2010, 2010],
            "region": ["EAS", "EAS", "SSF", "SSF", "SAS", "EAS"],
            "income_group": ["High income"] * 2
            + ["Lower middle income"] * 3
            + ["Upper middle income"],
            "tfr": [1.36, 1.39, 6.1, 5.8, 2.6, 3.2],
            "gdp_pcap_ppp": [35000.0, 36000.0, 3000.0, 4500.0, 4000.0, 4000.0],
            "gdp_growth": [None] * 6,
            "population": [1.27e8, 1.28e8, 1.2e8, 1.6e8, 1.2e9, 1.0e4],
            "u5_mortality": [4.5, 3.0, 180.0, 130.0, 60.0, None],
            "fem_sec_enrol": [100.0, 101.0, None, 40.0, 60.0, 80.0],
            "urban_share": [78.0, 90.0, 35.0, 44.0, 31.0, 50.0],
            "fem_lfp": [49.0, 48.0, 50.0, 52.0, 27.0, 40.0],
            "life_exp": [81.0, 83.0, 47.0, 51.0, 67.0, 65.0],
        }
    )


def test_stage_frame_is_listwise_without_imputation() -> None:
    frame = h4.stage_frame(panel())
    # NGA 2000 (fem_sec_enrol null) and TUV (u5 null) are dropped; nothing is filled in
    assert frame.select("iso3", "year").rows() == [
        ("IND", 2010),
        ("JPN", 2000),
        ("JPN", 2010),
        ("NGA", 2010),
    ]
    assert all(frame[v].null_count() == 0 for v in h4.STAGE_VARS)
    smaller = h4.stage_frame(panel(), stage_vars=("u5_mortality",))
    assert smaller.height == 5  # only TUV dropped


def test_u5_band_uses_prefixed_exclusive_upper_bounds() -> None:
    frame = h4.u5_band(h4.stage_frame(panel(), stage_vars=("u5_mortality",)))
    bands = dict(zip(frame["iso3"].to_list(), frame["u5_band"].to_list(), strict=True))
    assert bands == {"IND": "U5MR 50-100", "JPN": "U5MR 0-10", "NGA": "U5MR >= 100"}
    edge = h4.u5_band(pl.DataFrame({"u5_mortality": [10.0, 9.999, 100.0, None]}))
    assert edge["u5_band"].to_list() == ["U5MR 10-25", "U5MR 0-10", "U5MR >= 100", None]
    assert edge["u5_band_order"].to_list() == [1, 0, 4, None]


def test_verdicts_follow_pre_registered_thresholds() -> None:
    assert h4.attenuation_ratio(-0.4, -1.0) == pytest.approx(0.4)
    assert h4.attenuation_ratio(-0.4, 0.0) is None
    assert h4.verdict_a(0.5).startswith("consistent")
    assert h4.verdict_a(0.7).startswith("partial")
    assert h4.verdict_a(0.9).startswith("not supported")
    assert h4.verdict_a(None).startswith("undetermined")
    assert h4.verdict_b(0.0, 0.3).startswith("consistent")
    assert h4.verdict_b(-0.1, 0.3).startswith("undetermined")
    assert h4.verdict_b(-0.5, -0.1).startswith("not supported")
    assert h4.verdict_c(-1.0, [-0.5, 0.2, -0.1]).startswith("consistent")
    assert h4.verdict_c(-1.0, [-0.51]).startswith("not supported")
    assert h4.verdict_d(0.1, 0.2).startswith("consistent")
    assert h4.verdict_d(0.1, -0.2).startswith("partial")
    assert h4.verdict_d(-0.1, -0.2).startswith("not supported")


def dhs() -> pl.DataFrame:
    def survey(
        sid: str, iso3: str, year: int, values: list[float | None], stype: str = "DHS"
    ) -> list[dict[str, object]]:
        return [
            {
                "iso3": iso3,
                "country": iso3,
                "survey_id": sid,
                "survey_year": year,
                "survey_type": stype,
                "quintile": q,
                "value": v,
                "source": "dhs_api",
            }
            for q, v in zip(range(1, 6), values, strict=True)
        ]

    rows = (
        survey("NG2000", "NGA", 2000, [7.0, 6.5, 6.0, 5.5, 5.0])
        + survey("NG2010", "NGA", 2010, [6.5, 6.0, 5.5, 5.0, 4.5])
        + survey("IN2010", "IND", 2010, [3.0, 2.8, 2.6, 2.4, 2.4])
        + survey("AL2008", "ALB", 2008, [1.9, 1.7, None, 1.5, 1.2])  # incomplete -> dropped
        + survey("XX2010", "XXX", 2010, [4.0, 4.0, 4.0, 4.0, 5.0], "MIS")  # no WDI row
    )
    return pl.DataFrame(rows)


def test_quintile_gradients_requires_all_five_quintiles() -> None:
    g = h4.quintile_gradients(dhs())
    assert g["survey_id"].to_list() == ["IN2010", "NG2000", "NG2010", "XX2010"]
    ng = g.filter(pl.col("survey_id") == "NG2000").row(0, named=True)
    assert ng["gap"] == pytest.approx(-2.0)
    assert ng["slope"] == pytest.approx(-0.5)  # linear profile: slope per quintile step
    assert ng["ratio"] == pytest.approx(5.0 / 7.0)
    xx = g.filter(pl.col("survey_id") == "XX2010").row(0, named=True)
    assert xx["gap"] == pytest.approx(1.0) and xx["slope"] == pytest.approx(0.2)


def test_merge_stage_joins_survey_year_and_drops_rows_without_gdp() -> None:
    merged = h4.merge_stage(h4.quintile_gradients(dhs()), panel())
    assert merged["survey_id"].to_list() == ["IN2010", "NG2000", "NG2010"]  # XXX has no WDI row
    ng = merged.filter(pl.col("survey_id") == "NG2000").row(0, named=True)
    assert ng["ln_gdp"] == pytest.approx(math.log(3000.0))
    assert ng["u5_mortality"] == 180.0 and ng["fem_sec_enrol"] is None  # None stays None
    assert ng["national_tfr"] == 6.1
    assert ng["population"] == 1.2e8  # weight for the pre-registered WLS robustness


def test_latest_and_repeated_helpers() -> None:
    merged = h4.merge_stage(h4.quintile_gradients(dhs()), panel())
    assert h4.latest_per_country(merged).select("iso3", "survey_year").rows() == [
        ("IND", 2010),
        ("NGA", 2010),
    ]
    assert h4.repeated_countries(merged)["survey_id"].to_list() == ["NG2000", "NG2010"]
