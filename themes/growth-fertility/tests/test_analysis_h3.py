import math

import numpy as np
import polars as pl
import pytest

from theme_growth_fertility.analysis import a20261004_h3_jp_income_class as h3


def test_band_midpoint_rules() -> None:
    assert h3.band_midpoint(0, 500_000) == pytest.approx(25.0)  # 0-50 万円 -> 25 万円
    assert h3.band_midpoint(5_000_000, 6_000_000) == pytest.approx(550.0)
    assert h3.band_midpoint(10_000_000, None) == pytest.approx(1250.0)  # open top: lower x 1.25
    assert h3.band_midpoint(10_000_000, None, top_factor=1.5) == pytest.approx(1500.0)
    assert h3.band_midpoint(None, None) is None  # 'none' / 'total'
    with pytest.raises(ValueError, match="non-positive"):
        h3.band_midpoint(0, 0)


def test_weighted_slope_recovers_exact_line_and_weights_matter() -> None:
    x = np.array([1.0, 2.0, 3.0, 4.0])
    y = 0.5 + 2.0 * x
    c = h3.weighted_slope(x, y)
    assert c.b == pytest.approx(2.0)
    assert c.se == pytest.approx(0.0, abs=1e-9)
    # one outlier point; giving it ~zero weight restores the line
    y2 = y.copy()
    y2[3] = 100.0
    unweighted = h3.weighted_slope(x, y2)
    weighted = h3.weighted_slope(x, y2, np.array([1.0, 1.0, 1.0, 1e-9]))
    assert unweighted.b > 2.0
    assert weighted.b == pytest.approx(2.0, abs=1e-5)
    assert weighted.lo <= weighted.b <= weighted.hi


def test_wls_matches_closed_form_simple_regression() -> None:
    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    y = np.array([1.1, 1.9, 3.2, 3.9, 5.3])
    fit = h3.wls(x[:, None], y, None, ["x"])
    bx = float(np.cov(x, y, bias=True)[0, 1] / np.var(x))
    assert fit.coefs["x"].b == pytest.approx(bx)
    assert fit.coefs["intercept"].b == pytest.approx(float(y.mean() - bx * x.mean()))
    assert 0.95 < fit.r2 <= 1.0
    with pytest.raises(ValueError, match="at least"):
        h3.wls(x[:2, None], y[:2], None, ["x"])


def test_spearman_handles_monotone_and_ties() -> None:
    x = np.array([1.0, 2.0, 3.0, 4.0])
    assert h3.spearman(x, np.exp(x)) == pytest.approx(1.0)
    assert h3.spearman(x, -x) == pytest.approx(-1.0)
    assert math.isnan(h3.spearman(x, np.array([1.0, 1.0, 1.0, 1.0])))


def test_sign_of_and_compare_signs() -> None:
    pos = h3.Coef(0.5, 0.1, 0.3, 0.7)
    neg = h3.Coef(-1.0, 0.1, -1.2, -0.8)
    zero = h3.Coef(0.1, 0.2, -0.3, 0.5)
    assert h3.sign_of(pos) == "positive"
    assert h3.sign_of(neg) == "negative"
    assert h3.sign_of(zero) == "indistinguishable from 0"
    assert h3.compare_signs(neg, pos) == "opposite"
    assert h3.compare_signs(neg, neg) == "same"
    assert h3.compare_signs(neg, zero) == "undetermined"


def _jp() -> pl.DataFrame:
    rows = []
    for year in (2012, 2015):
        for cls, lo, hi, v, w in (
            ("0-50", 0, 500_000, 0.3, 100.0),
            ("50-100", 500_000, 1_000_000, 0.4, 200.0),
            ("1000-", 10_000_000, None, 0.9, 50.0),
            ("none", None, None, 0.35, 300.0),
            ("total", None, None, 0.6, 650.0),
        ):
            rows.append(
                {
                    "survey": "s",
                    "survey_year": year + 1,
                    "year": year,
                    "income_class": cls,
                    "income_class_lower_yen": lo,
                    "income_class_upper_yen": hi,
                    "sex": "male",
                    "metric": "married_share",
                    "value": v,
                    "denominator": w,
                    "source": "estat_kiso",
                }
            )
    return pl.DataFrame(rows)


def test_band_frame_drops_unbounded_classes_and_adds_ln_mid() -> None:
    f = h3.band_frame(_jp(), metric="married_share", sex="male")
    assert f["income_class"].to_list() == ["0-50", "50-100", "1000-"] * 2
    assert f["mid_man"].to_list()[:3] == pytest.approx([25.0, 75.0, 1250.0])
    assert f["ln_mid"][0] == pytest.approx(math.log(25.0))
    assert "weight" in f.columns
    low = h3.band_frame(_jp(), metric="married_share", sex="male", exclude_lowest=True)
    assert "0-50" not in low["income_class"].to_list()
    assert h3.band_frame(_jp(), metric="married_share", sex="female").height == 0


def test_wave_centered() -> None:
    assert [h3.wave_centered(y) for y in (2012, 2018, 2024)] == [-2.0, 0.0, 2.0]
