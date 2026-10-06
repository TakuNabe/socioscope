import numpy as np
import polars as pl
import pytest

from theme_growth_fertility.analysis import a20261006_h6_fertility_ideals as h6


def ideals() -> pl.DataFrame:
    rows = []
    for iso3, v in (("FIN", 2.5), ("DNK", 2.55), ("ITA", 2.0), ("ESP", 2.3), ("DEU", 2.1)):
        rows.append(
            {
                "source": "eb2011",
                "iso3": iso3,
                "survey_year": 2011,
                "sex": "F",
                "age_class": "25-39",
                "metric": "ideal_personal_mean",
                "value": v,
            }
        )
        rows.append(
            {
                "source": "eb2011",
                "iso3": iso3,
                "survey_year": 2011,
                "sex": "F",
                "age_class": "total",
                "metric": "ideal_personal_mean",
                "value": v - 0.1,
            }
        )
    for iso3, v in (("FIN", 2.1), ("DNK", 2.3), ("DEU", 2.2), ("NOR", 2.4)):
        rows.append(
            {
                "source": "ggs2020",
                "iso3": iso3,
                "survey_year": 2021,
                "sex": "F",
                "age_class": "30-39",
                "metric": "ideal_personal_mean",
                "value": v,
            }
        )
    rows.append(
        {
            "source": "eb2011",
            "iso3": "FRA",
            "survey_year": 2011,
            "sex": "F",
            "age_class": "25-39",
            "metric": "ideal_personal_mean",
            "value": None,
        }
    )
    return pl.DataFrame(rows)


def panel() -> pl.DataFrame:
    rows = []
    for iso3, t11, t22, t23 in (
        ("FIN", 1.83, 1.32, 1.26),
        ("DNK", 1.75, 1.55, 1.50),
        ("ITA", 1.44, 1.24, 1.20),
        ("ESP", 1.34, 1.16, 1.12),
        ("DEU", 1.39, 1.46, 1.38),
        ("NOR", 1.88, 1.41, 1.40),
    ):
        rows += [
            {"iso3": iso3, "year": 2011, "tfr": t11},
            {"iso3": iso3, "year": 2022, "tfr": t22},
            {"iso3": iso3, "year": 2023, "tfr": t23},
        ]
    rows.append({"iso3": "SWE", "year": 2011, "tfr": 1.9})  # no end year -> dropped
    return pl.DataFrame(rows)


def test_ideal_frame_filters_and_drops_nulls() -> None:
    fr = h6.ideal_frame(ideals(), source="eb2011", metric="ideal_personal_mean", age_class="25-39")
    assert fr["iso3"].to_list() == ["DEU", "DNK", "ESP", "FIN", "ITA"]  # FRA null dropped
    assert fr.filter(pl.col("iso3") == "FIN")["value"][0] == 2.5


def test_delta_tfr_requires_both_years() -> None:
    d = h6.delta_tfr(panel(), 2011, 2023)
    assert "SWE" not in d["iso3"].to_list()
    assert d.filter(pl.col("iso3") == "FIN")["d_tfr"][0] == pytest.approx(-0.57)


def test_corr_stats_and_verdict_a() -> None:
    x = np.array([1.0, 2.0, 3.0, 4.0])
    r, rho, slope = h6.corr_stats(x, 2 * x + 1)
    assert r == pytest.approx(1.0) and rho == pytest.approx(1.0) and slope.b == pytest.approx(2.0)
    v = h6.verdict_a(0.5, {"FIN": 2.5, "DNK": 2.55}, 2.3)
    assert v.startswith("level: consistent") and "cannot predict" in v
    assert "not supported" in h6.verdict_a(0.1, {"FIN": 2.2}, 2.3)
    assert "not all above" in h6.verdict_a(0.5, {"FIN": 2.2, "DNK": 2.5}, 2.3)
    assert "undetermined" in h6.verdict_a(0.5, {}, 2.3)


def test_ideal_change_ranks_largest_fall_first_and_verdict_b() -> None:
    eb = h6.ideal_frame(ideals(), source="eb2011", metric="ideal_personal_mean", age_class="25-39")
    ggs = h6.ideal_frame(
        ideals(), source="ggs2020", metric="ideal_personal_mean", age_class="30-39"
    )
    ch = h6.ideal_change(eb, ggs)
    assert ch["iso3"].to_list() == ["FIN", "DNK", "DEU"]  # -0.4, -0.25, +0.1
    assert ch["rank"].to_list() == [1, 2, 3]
    assert h6.verdict_b(ch, nordic=("FIN",)).startswith("consistent")
    assert h6.verdict_b(ch, nordic=("FIN", "DNK")).startswith("partial")  # DNK rank 2 > 1.5
    assert h6.verdict_b(ch, nordic=("FIN", "NOR")).startswith("undetermined")
    assert h6.verdict_b(ch.with_columns(pl.lit(0.1).alias("d_ideal")), nordic=("FIN",)).startswith(
        "not supported"
    )


def test_mean_optimism_window_and_exclusion_and_verdict_c() -> None:
    exp = pl.DataFrame(
        {
            "iso3": ["FIN"] * 4 + ["ITA"] * 2,
            "item": ["life_general"] * 3 + ["national_economy"] + ["life_general"] * 2,
            "fieldwork_year": [2019, 2020, 2023, 2019, 2019, 2024],
            "net_optimism": [10.0, -20.0, 4.0, 50.0, 0.0, 3.0],
        }
    )
    m = h6.mean_optimism(exp, item="life_general")
    assert dict(zip(m["iso3"], m["optimism"], strict=True)) == {
        "FIN": pytest.approx(-2.0),
        "ITA": 0.0,
    }
    assert dict(zip(m["iso3"], m["waves"], strict=True)) == {
        "FIN": 3,
        "ITA": 1,
    }  # 2024 outside window
    m2 = h6.mean_optimism(exp, item="life_general", exclude_years=(2020, 2021))
    assert m2.filter(pl.col("iso3") == "FIN")["optimism"][0] == pytest.approx(7.0)
    assert h6.verdict_c(0.5).startswith("consistent") and h6.verdict_c(-0.2).startswith(
        "not supported"
    )
    assert h6.verdict_c(float("nan")) == "undetermined"
