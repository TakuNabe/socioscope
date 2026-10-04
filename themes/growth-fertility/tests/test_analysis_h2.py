import math

import numpy as np
import polars as pl
import pytest

from theme_growth_fertility.analysis import a20261004_h2_growth_shocks as h2


def panel() -> pl.DataFrame:
    """JPN 2000-2006 with 2003 missing growth; USA 2000-2004 complete; TUV small; QAT oil."""
    years = [2000, 2001, 2002, 2003, 2004, 2005, 2006]
    jpn_g = [1.0, -3.0, 0.5, None, 2.0, 1.5, -2.5]
    jpn_tfr = [1.36, 1.33, 1.32, 1.29, 1.29, 1.26, 1.32]
    usa_years = [2000, 2001, 2002, 2003, 2004]
    usa_g = [4.0, 1.0, 1.8, 2.8, 3.8]
    usa_tfr = [2.06, 2.03, 2.01, 2.04, 2.05]
    rows = {
        "iso3": ["JPN"] * 7 + ["USA"] * 5 + ["QAT"] * 5 + ["TUV"] * 5,
        "country": ["Japan"] * 7 + ["United States"] * 5 + ["Qatar"] * 5 + ["Tuvalu"] * 5,
        "year": years + usa_years + usa_years + usa_years,
        "region": ["EAS"] * 7 + ["NAC"] * 5 + ["MEA"] * 5 + ["EAS"] * 5,
        "income_group": ["High income"] * 17 + ["Upper middle income"] * 5,
        "tfr": jpn_tfr + usa_tfr + [3.0, 2.9, 2.8, 2.7, 2.6] + [3.2, 3.1, 3.3, 3.2, 3.1],
        "gdp_pcap_ppp": [30000.0] * 7 + [50000.0] * 5 + [None] * 5 + [4000.0] * 5,
        "gdp_growth": jpn_g + usa_g + [10.0, -6.0, 8.0, 5.0, -8.0] + [1.0] * 5,
        "population": [1.27e8] * 7 + [2.9e8] * 5 + [1.7e6] * 5 + [1.0e4] * 5,
    }
    return pl.DataFrame(rows)


def test_build_growth_frame_requires_consecutive_lags_without_imputing() -> None:
    frame = h2.build_growth_frame(panel())
    jpn = frame.filter(pl.col("iso3") == "JPN")
    # 2003 growth missing: rows 2003..2006 lack some lag; 2000-2002 lack lag 3 or tfr_prev
    assert jpn["year"].to_list() == []
    usa = frame.filter(pl.col("iso3") == "USA")
    assert usa["year"].to_list() == [2003, 2004]
    r = usa.filter(pl.col("year") == 2004).row(0, named=True)
    assert (r["g_l0"], r["g_l1"], r["g_l2"], r["g_l3"]) == (3.8, 2.8, 1.8, 1.0)
    assert r["d_tfr"] == pytest.approx(2.05 - 2.04)
    assert r["d_ln_tfr"] == pytest.approx(math.log(2.05) - math.log(2.04))
    assert r["ln_gdp"] == pytest.approx(math.log(50000.0))
    # QAT has no gdp_pcap_ppp -> ln_gdp null but the row is kept (growth models do not need it)
    qat = frame.filter(pl.col("iso3") == "QAT")
    assert qat.height == 2 and qat["ln_gdp"].null_count() == 2


def test_build_growth_frame_with_shorter_lag_keeps_more_rows() -> None:
    frame = h2.build_growth_frame(panel(), max_lag=1)
    jpn = frame.filter(pl.col("iso3") == "JPN")
    # needs g_t, g_t-1, tfr_t-1: 2001, 2002 ok; 2003/2004 broken by the 2003 gap; 2005, 2006 ok
    assert jpn["year"].to_list() == [2001, 2002, 2005, 2006]


def test_build_growth_frame_sample_filters() -> None:
    p = panel()
    assert "QAT" not in h2.build_growth_frame(p, exclude_iso3=h2.OIL_STATES)["iso3"].to_list()
    assert "TUV" not in h2.build_growth_frame(p, min_population=1_000_000)["iso3"].to_list()
    assert 2003 not in h2.build_growth_frame(p, drop_years=(2003,))["year"].to_list()
    assert h2.build_growth_frame(p, start_year=2004)["year"].min() == 2004


def test_detect_events_threshold_and_min_gap() -> None:
    ev = h2.detect_events(panel(), threshold=-2.0)
    # JPN: 2001 (-3), 2006 (-2.5) is 5 years later -> counted
    # QAT: 2001 (-6), 2004 (-8) < 5 years -> skipped
    assert ev.rows() == [("JPN", 2001), ("JPN", 2006), ("QAT", 2001)]
    ev5 = h2.detect_events(panel(), threshold=-5.0)
    assert ev5.rows() == [("QAT", 2001)]
    ev0 = h2.detect_events(panel(), threshold=0.0, min_gap=1)
    assert ev0.rows() == [("JPN", 2001), ("JPN", 2006), ("QAT", 2001), ("QAT", 2004)]
    assert ev.schema == {"iso3": pl.String, "event_year": pl.Int64}


def test_detect_events_ignores_null_growth_and_handles_no_events() -> None:
    ev = h2.detect_events(panel().filter(pl.col("iso3") == "USA"), threshold=-2.0)
    assert ev.height == 0 and ev.columns == ["iso3", "event_year"]


def test_nearest_event_time_ties_go_post() -> None:
    assert h2.nearest_event_time(2003, [2000, 2006]) == 3
    assert h2.nearest_event_time(2002, [2000, 2006]) == 2
    assert h2.nearest_event_time(2005, [2000, 2006]) == -1
    assert h2.nearest_event_time(2005, []) is None


def test_event_dummies_binning_and_reference() -> None:
    frame = pl.DataFrame(
        {"iso3": ["A"] * 12 + ["B"] * 2, "year": list(range(1995, 2007)) + [2000, 2001]}
    )
    events = pl.DataFrame({"iso3": ["A"], "event_year": [2000]})
    out = h2.event_dummies(frame, events)
    a = out.filter(pl.col("iso3") == "A")
    assert a["k_bin"].to_list() == [-3, -3, -3, -2, -1, 0, 1, 2, 3, 4, 5, 5]
    assert "ev_m1" not in out.columns  # reference omitted
    assert a["ev_m3"].to_list() == [1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    assert a["ev_p5"].to_list() == [0] * 10 + [1, 1]
    assert a["ev_p0"].to_list()[5] == 1
    b = out.filter(pl.col("iso3") == "B")
    assert b["k_bin"].null_count() == 2
    assert all(b[h2.dummy_name(k)].sum() == 0 for k in h2.event_ks())
    # each row has at most one dummy on
    dsum = sum(a[h2.dummy_name(k)] for k in h2.event_ks())
    assert dsum.max() == 1


def test_event_dummies_unbinned_window_zeroes_outside() -> None:
    frame = pl.DataFrame({"iso3": ["A"] * 12, "year": list(range(1995, 2007))})
    events = pl.DataFrame({"iso3": ["A"], "event_year": [2000]})
    out = h2.event_dummies(frame, events, bin_endpoints=False)
    assert out["k_bin"].to_list() == [None, None, -3, -2, -1, 0, 1, 2, 3, 4, 5, None]
    assert out["ev_m3"].to_list() == [0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    assert out["ev_p5"].to_list() == [0] * 10 + [1, 0]


def test_event_ks_and_dummy_names() -> None:
    assert h2.event_ks() == [-3, -2, 0, 1, 2, 3, 4, 5]
    assert [h2.dummy_name(k) for k in (-3, 0, 5)] == ["ev_m3", "ev_p0", "ev_p5"]


def test_cumulative_sums_and_variance() -> None:
    b = [1.0, 2.0, -0.5]
    cov = np.array([[1.0, 0.5, 0.0], [0.5, 4.0, 0.0], [0.0, 0.0, 0.25]])
    cum = h2.cumulative(b, cov)
    assert [c[0] for c in cum] == pytest.approx([1.0, 3.0, 2.5])
    assert cum[1][1] == pytest.approx(math.sqrt(1.0 + 4.0 + 2 * 0.5))
    assert cum[0][2] == pytest.approx(1.0 - 1.96)
    assert cum[2][1] == pytest.approx(math.sqrt(6.0 + 0.25))


def test_shock_profile_means_and_quartiles() -> None:
    frame = pl.DataFrame(
        {
            "year": [2008, 2008, 2008, 2009],
            "d_tfr": [-0.1, 0.0, 0.1, -0.2],
            "g_l0": [-3.0, 1.0, 2.0, -4.0],
        }
    )
    prof = h2.shock_profile(frame, [2008, 2009])
    assert prof["year"].to_list() == [2008, 2009]
    assert prof["n"].to_list() == [3, 1]
    assert prof["mean_d_tfr"].to_list() == pytest.approx([0.0, -0.2])
    assert prof["share_recession"].to_list() == pytest.approx([1 / 3, 1.0])


def test_standardized() -> None:
    assert h2.standardized(2.0, 0.5, 4.0) == pytest.approx(0.25)
    assert math.isnan(h2.standardized(2.0, 0.5, 0.0))


def test_fit_recovers_within_slope_and_within_r2() -> None:
    # y = 0.5 x + country effect + year effect, exact -> within_r2 = 1, std coef = 1
    iso = ["A"] * 6 + ["B"] * 6 + ["C"] * 6
    years = [2000, 2001, 2002, 2003, 2004, 2005] * 3
    x = [float(v) for v in [1, 3, 2, 5, 4, 6, 2, 1, 4, 3, 6, 5, 3, 2, 1, 6, 5, 4]]
    ce = {"A": 0.0, "B": 1.0, "C": -1.0}
    ye = {y: 0.1 * (y - 2000) for y in set(years)}
    yv = [0.5 * xi + ce[i] + ye[t] for xi, i, t in zip(x, iso, years, strict=True)]
    frame = pl.DataFrame({"iso3": iso, "year": years, "x": x, "y": yv})
    fr = h2.fit(frame, "y", ["x"], label="t", within_stats=True)
    assert fr.est.coefs["x"][0] == pytest.approx(0.5, abs=1e-8)
    assert fr.est.extra["within_r2"] == pytest.approx(1.0, abs=1e-8)
    assert fr.est.extra["std_x"] == pytest.approx(1.0, abs=1e-8)
    assert fr.names == ["x"] and fr.cov.shape == (1, 1)


def test_event_time_means_demeans_within_country() -> None:
    frame = pl.DataFrame(
        {
            "iso3": ["A", "A", "B", "B"],
            "d_tfr": [0.1, -0.1, 0.3, 0.1],
            "g_l0": [1.0, -3.0, 2.0, -4.0],
            "k_bin": [None, 0, None, 0],
        }
    )
    out = h2.event_time_means(frame)
    assert out["k_bin"].to_list() == [0, 99]
    assert out["mean_d_tfr_within"].to_list() == pytest.approx([-0.1, 0.1])
    assert out["mean_growth"].to_list() == pytest.approx([-3.5, 1.5])
