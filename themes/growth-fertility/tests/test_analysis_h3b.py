import math

import numpy as np
import polars as pl
import pytest

from theme_growth_fertility.analysis import a20261004_h3_jp_income_class as h3
from theme_growth_fertility.analysis import a20261004_h3b_age_adjusted as h3b

BANDS = (("0-50", 0, 500_000), ("50-100", 500_000, 1_000_000), ("1500-", 15_000_000, None))
AGES = (
    ("total", None, None),
    ("15-19", 15, 20),
    ("25-29", 25, 30),
    ("55-59", 55, 60),
    ("85-", 85, None),
)


def _row(sex: str, age: tuple, band: tuple, value: float | None, den: float) -> dict[str, object]:
    return {
        "survey": "就業構造基本調査",
        "survey_year": 2022,
        "year": 2022,
        "sex": sex,
        "age_class": age[0],
        "age_lower": age[1],
        "age_upper": age[2],
        "income_class": band[0],
        "income_class_lower_yen": band[1],
        "income_class_upper_yen": band[2],
        "metric": "ever_married_share",
        "value": value,
        "denominator": den,
        "source": "estat_shugyo",
    }


def _df() -> pl.DataFrame:
    """share = 0.1 + 0.2 * ln(mid) offset per age so within-age slope is exactly 0.2."""
    rows = []
    offsets = {"15-19": -0.9, "25-29": -0.5, "55-59": 0.0, "85-": 0.1, "total": 0.0}
    den_by_age = {"15-19": 100.0, "25-29": 300.0, "55-59": 100.0, "85-": 10.0, "total": 510.0}
    for age in AGES:
        rows.append(_row("male", age, ("total", None, None), 0.5, den_by_age[age[0]]))
        for band in BANDS:
            mid = h3.band_midpoint(band[1], band[2])
            assert mid is not None
            value = 0.5 + offsets[age[0]] + 0.2 * (math.log(mid) - math.log(75.0))
            rows.append(_row("male", age, band, value, den_by_age[age[0]] / 3))
    # a zero-denominator cell and a null value must be dropped by age_frame
    rows.append(_row("male", ("25-29", 25, 30), ("100-150", 1_000_000, 1_500_000), None, 0.0))
    rows.append(_row("female", ("25-29", 25, 30), BANDS[0], 0.3, 50.0))
    return pl.DataFrame(rows)


def test_age_frame_filters_ages_and_bounded_bands() -> None:
    f = h3b.age_frame(_df(), sex="male")  # ages 20-59
    assert sorted(f["age_class"].unique().to_list()) == ["25-29", "55-59"]
    assert f.height == 6  # 2 ages x 3 bands; the null/zero-denominator cell is gone
    assert "weight" in f.columns and f["ln_mid"][0] == pytest.approx(math.log(25.0))
    assert f["age_class"].to_list()[:3] == ["25-29"] * 3  # sorted by age then midpoint
    allf = h3b.age_frame(_df(), sex="male", ages=h3b.ALL_AGES)
    assert sorted(allf["age_class"].unique().to_list()) == ["15-19", "25-29", "55-59", "85-"]
    assert h3b.age_frame(_df(), sex="male", exclude_lowest=True)["income_class"].n_unique() == 2
    assert h3b.age_frame(_df(), sex="female").height == 1


def test_age_weights_use_income_total_rows_and_sum_to_one() -> None:
    w = h3b.age_weights(_df(), sex="male")
    assert set(w) == {"25-29", "55-59"}
    assert w["25-29"] == pytest.approx(0.75) and sum(w.values()) == pytest.approx(1.0)
    with pytest.raises(ValueError, match="standard population"):
        h3b.age_weights(_df(), sex="female", ages=(60, 64))


def test_standardise_is_weighted_mean_over_ages_and_fails_on_missing_cells() -> None:
    f = h3b.age_frame(_df(), sex="male")
    std = h3b.standardise(f, {"25-29": 0.75, "55-59": 0.25})
    assert std["income_class"].to_list() == ["0-50", "50-100", "1500-"]
    # shares: 25-29 -> 0.0 + slope term, 55-59 -> 0.5 + slope term at mid=75 -> 0.0 / 0.5
    assert std.filter(pl.col("income_class") == "50-100")["value"][0] == pytest.approx(0.125)
    assert std["weight"][0] == pytest.approx(100.0 + 100.0 / 3)
    with pytest.raises(ValueError, match="sum to 1"):
        h3b.standardise(f, {"25-29": 0.5})
    with pytest.raises(ValueError, match="lacks age classes"):
        h3b.standardise(f.filter(pl.col("age_class") == "25-29"), {"25-29": 0.75, "55-59": 0.25})


def test_slopes_by_age_recover_the_constructed_slope() -> None:
    res = h3b.slopes_by_age(h3b.age_frame(_df(), sex="male"))
    assert list(res) == ["25-29", "55-59"]
    for c, rho, n in res.values():
        assert c.b == pytest.approx(0.2) and n == 3 and rho == pytest.approx(1.0)


def test_fe_fit_recovers_common_slope_and_age_offsets() -> None:
    fit = h3b.fe_fit(h3b.age_frame(_df(), sex="male"))
    assert fit.n == 6
    assert fit.coefs["ln_mid"].b == pytest.approx(0.2)
    assert fit.coefs["age[55-59]"].b == pytest.approx(0.5)  # offset relative to 25-29
    assert "age[25-29]" not in fit.coefs  # reference class
    unweighted = h3b.fe_fit(h3b.age_frame(_df(), sex="male"), weighted=False)
    assert unweighted.coefs["ln_mid"].b == pytest.approx(0.2)


def test_attenuation() -> None:
    assert h3b.attenuation(h3.Coef(0.1, 0, 0, 0), h3.Coef(0.2, 0, 0, 0)) == pytest.approx(0.5)
    assert math.isnan(h3b.attenuation(h3.Coef(0.1, 0, 0, 0), h3.Coef(0.0, 0, 0, 0)))


def test_complete_ages_and_restrict_weights() -> None:
    f = h3b.age_frame(_df(), sex="male", ages=h3b.ALL_AGES)
    assert h3b.complete_ages(f) == ["15-19", "25-29", "55-59", "85-"]
    partial = f.filter(~((pl.col("age_class") == "15-19") & (pl.col("income_class") == "1500-")))
    assert h3b.complete_ages(partial) == ["25-29", "55-59", "85-"]
    w = h3b.restrict_weights({"15-19": 0.2, "25-29": 0.6, "55-59": 0.2}, ["25-29", "55-59"])
    assert w == {"25-29": pytest.approx(0.75), "55-59": pytest.approx(0.25)}
    with pytest.raises(ValueError, match="no age classes"):
        h3b.restrict_weights({"15-19": 0.2}, ["25-29"])


def test_crude_slope_uses_age_total_rows() -> None:
    df = _df()
    c, rho, n = h3b.crude_slope(df, sex="male")
    assert n == 3 and c.b == pytest.approx(0.2) and rho == pytest.approx(1.0)
    assert np.isfinite(c.se)
