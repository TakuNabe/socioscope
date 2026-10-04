import math

import polars as pl
import pytest

from theme_wealth_population_distribution.analysis import a20261004_h1_ushape as h1


def panel() -> pl.DataFrame:
    # U-land: falls to a 1980 trough then rises. Flat-land: monotone rise (trough at window start).
    # Late-land: data only from 1995 (ineligible). JPN: gentle U so the Japan helpers have a row.
    rows: list[tuple[str, int, float | None, float | None]] = []
    for y, v in [
        (1950, 0.40),
        (1960, 0.35),
        (1970, 0.30),
        (1980, 0.25),
        (2005, 0.30),
        (2010, 0.33),
        (2020, 0.36),
    ]:
        rows.append(("ULD", y, v, 0.50))
    for y, v in [
        (1950, 0.20),
        (1960, 0.21),
        (1970, 0.22),
        (1980, 0.23),
        (2005, 0.24),
        (2010, 0.25),
        (2020, 0.26),
    ]:
        rows.append(("FLT", y, v, 0.50))
    for y, v in [(1995, 0.30), (2005, 0.31), (2010, 0.32), (2020, 0.33)]:
        rows.append(("LAT", y, v, 0.50))
    for y, v in [
        (1950, 0.22),
        (1960, 0.21),
        (1970, 0.20),
        (1981, 0.19),
        (2005, 0.21),
        (2010, 0.22),
        (2020, 0.22),
    ]:
        rows.append(("JPN", y, v, 0.50))
    rows.append(("ULD", 1900, 0.60, 0.50))  # outside the window, must be ignored
    df = pl.DataFrame(
        rows, schema=["iso3", "year", "top1_wealth_share", "top10_wealth_share"], orient="row"
    )
    return df.with_columns(
        pl.lit(None, dtype=pl.Float64).alias("top1_income_share"),
        pl.lit(None, dtype=pl.Float64).alias("top10_income_share"),
        pl.lit(None, dtype=pl.Float64).alias("bottom50_income_share"),
        pl.lit(1.0e6).alias("population"),
        pl.lit("wid_world").alias("source"),
    ).sort(["iso3", "year"])


def test_coverage_table_counts_pre_and_post_inside_window() -> None:
    cov = h1.coverage_table(panel(), "top1_wealth_share")
    uld = cov.filter(pl.col("iso3") == "ULD").row(0, named=True)
    assert uld["n"] == 8 and uld["first_year"] == 1900 and uld["last_year"] == 2020
    assert uld["pre"] == 4  # 1950..1980 (1900 is outside the window)
    assert uld["post"] == 3
    lat = cov.filter(pl.col("iso3") == "LAT").row(0, named=True)
    assert lat["pre"] == 0 and lat["post"] == 3


def test_series_in_window_excludes_out_of_window_and_nulls() -> None:
    obs = h1.series_in_window(panel(), "ULD", "top1_wealth_share", (1950, 2024))
    assert obs[0] == (1950, 0.40) and obs[-1] == (2020, 0.36) and len(obs) == 7


def test_classify_trajectory_u_shape_and_not() -> None:
    p = panel()
    u = h1.classify_trajectory(
        "ULD", h1.series_in_window(p, "ULD", "top1_wealth_share", (1950, 2024))
    )
    assert u.eligible and u.trough_year == 1980 and u.trough == pytest.approx(0.25)
    assert u.decline == pytest.approx(0.15) and u.rise == pytest.approx(0.11)
    assert u.u_shape is True
    assert u.year_1980 == 1980 and u.change_since_1980 == pytest.approx(0.11)
    f = h1.classify_trajectory(
        "FLT", h1.series_in_window(p, "FLT", "top1_wealth_share", (1950, 2024))
    )
    assert f.eligible and f.trough_year == 1950 and f.u_shape is False  # trough at window edge
    lat = h1.classify_trajectory(
        "LAT", h1.series_in_window(p, "LAT", "top1_wealth_share", (1950, 2024))
    )
    assert lat.eligible is False and lat.u_shape is None and lat.trough_year == 1995
    empty = h1.classify_trajectory("XXX", [])
    assert empty.n == 0 and not empty.eligible and empty.trough_year is None


def test_classify_trajectory_threshold_and_trough_window_matter() -> None:
    obs = h1.series_in_window(panel(), "JPN", "top1_wealth_share", (1950, 2024))
    base = h1.classify_trajectory("JPN", obs)
    assert base.trough_year == 1981 and base.decline == pytest.approx(0.03)
    assert base.rise == pytest.approx(0.03) and base.u_shape is True
    strict = h1.classify_trajectory("JPN", obs, crit=h1.Criterion(min_delta=0.05))
    assert strict.u_shape is False
    narrow = h1.classify_trajectory("JPN", obs, crit=h1.Criterion(trough_window=(1965, 1980)))
    assert narrow.u_shape is False


def test_nearest_obs_prefers_earlier_on_ties() -> None:
    assert h1.nearest_obs([(1978, 1.0), (1982, 2.0)], 1980) == (1978, 1.0)
    assert h1.nearest_obs([], 1980) is None


def test_strip_flat_tail() -> None:
    obs = [
        (2000, 0.1),
        (2001, 0.2),
        (2002, 0.3),
        (2003, 0.3),
        (2004, 0.3),
        (2005, 0.3),
        (2006, 0.3),
    ]
    assert h1.strip_flat_tail(obs) == [(2000, 0.1), (2001, 0.2), (2002, 0.3)]
    assert h1.strip_flat_tail(obs, min_run=6) == obs  # run of 5 is shorter than 6
    assert h1.strip_flat_tail([]) == []
    assert h1.strip_flat_tail([(2000, 0.1)]) == [(2000, 0.1)]


def test_longest_flat_run() -> None:
    obs = [(2000, 0.1), (2001, 0.1), (2002, 0.2), (2003, 0.3), (2004, 0.3), (2005, 0.3)]
    assert h1.longest_flat_run(obs) == (3, 2003)
    assert h1.longest_flat_run([(2000, 0.1), (2001, 0.2)]) == (1, 2000)
    assert h1.longest_flat_run([]) == (0, None)


def test_classify_all_and_majority_test() -> None:
    traj = h1.classify_all(panel(), "top1_wealth_share")
    assert traj["iso3"].to_list() == ["FLT", "JPN", "LAT", "ULD"]
    mt = h1.majority_test(traj, "x")
    assert mt.eligible == 3 and mt.ineligible == 1 and mt.k == 2
    assert mt.share == pytest.approx(2 / 3)
    assert mt.p_one_sided == pytest.approx(4 / 8)  # P(X>=2 | n=3, p=.5)


def test_binom_and_wilson() -> None:
    assert h1.binom_test_majority(10, 10) == pytest.approx(1 / 1024)
    assert h1.binom_test_majority(0, 10) == pytest.approx(1.0)
    assert math.isnan(h1.binom_test_majority(0, 0))
    lo, hi = h1.wilson_ci(5, 10)
    assert lo == pytest.approx(0.2366, abs=1e-3) and hi == pytest.approx(0.7634, abs=1e-3)
    assert h1.wilson_ci(10, 10)[1] == pytest.approx(1.0)


def test_rank_in_year() -> None:
    p = panel()
    assert h1.rank_in_year(p, "top1_wealth_share", 2020, "ULD") == (1, 4)
    assert h1.rank_in_year(p, "top1_wealth_share", 2020, "JPN") == (4, 4)
    assert h1.rank_in_year(p, "top1_wealth_share", 1900, "JPN") == (None, 1)


def test_drop_quality_blanks_without_dropping_rows() -> None:
    p = panel()
    flags = pl.DataFrame(
        {"iso3": ["ULD", "ULD"], "year": [1950, 1960], "data_quality": [4, 2]},
    )
    out = h1.drop_quality(p, flags, "top1_wealth_share", {4, 5})
    assert out.height == p.height and "data_quality" not in out.columns
    assert (
        out.filter((pl.col("iso3") == "ULD") & (pl.col("year") == 1950))["top1_wealth_share"][0]
        is None
    )
    assert (
        out.filter((pl.col("iso3") == "ULD") & (pl.col("year") == 1960))["top1_wealth_share"][0]
        == 0.35
    )


def test_quality_flags_selects_series() -> None:
    staged = pl.DataFrame(
        {
            "iso3": ["JPN", "JPN", "JPN"],
            "year": [2000, 2000, 2000],
            "variable": ["shweal992j", "shweal992j", "sptinc992j"],
            "percentile": ["p99p100", "p90p100", "p99p100"],
            "value": [0.2, 0.5, 0.1],
            "data_quality": [0, 0, 1],
            "source": ["wid_world"] * 3,
        }
    )
    q = h1.quality_flags(staged, "top1_income_share")
    assert q.rows() == [("JPN", 2000, 1)]
