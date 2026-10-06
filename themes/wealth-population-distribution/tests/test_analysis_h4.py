import polars as pl
import pytest

from theme_wealth_population_distribution.analysis import a20261005_h4_superrich_dispersion as h4


def panel() -> pl.DataFrame:
    # CON: top1 +3pp, top0.1 +2pp (within-top concentration). DIF: top1 +3pp, top0.1 +0.5pp
    # (diffuse), top10 +2pp. FLAT: top1 falls. JPN: top10 rises more than top1, bottom50 falls.
    rows: list[
        tuple[str, int, float | None, float | None, float | None, float | None, float | None]
    ] = []
    spec = {
        "CON": [(1980, 0.08, 0.030, 0.30, 0.22, 0.40), (2020, 0.11, 0.050, 0.34, 0.20, 0.42)],
        "DIF": [(1981, 0.08, 0.030, 0.30, 0.22, 0.40), (2020, 0.11, 0.035, 0.32, 0.21, 0.41)],
        "FLAT": [(1979, 0.10, 0.040, 0.35, 0.20, 0.45), (2020, 0.09, 0.030, 0.34, 0.21, 0.44)],
        "JPN": [(1980, 0.10, 0.035, 0.35, 0.21, 0.42), (2020, 0.12, 0.040, 0.43, 0.18, 0.40)],
    }
    for iso3, obs in spec.items():
        for y, t1, t01, t10, b50, g in obs:
            rows.append((iso3, y, t1, t01, t10, b50, g))
    rows.append(("LATE", 2000, 0.1, 0.03, 0.3, 0.2, 0.4))  # single obs -> no change
    rows.append(("CON", 1900, 0.2, 0.1, 0.5, 0.1, 0.6))  # outside the window, ignored
    return pl.DataFrame(
        rows,
        schema=[
            "iso3",
            "year",
            "top1_income_share",
            "top01_income_share",
            "top10_income_share",
            "bottom50_income_share",
            "gini_income",
        ],
        orient="row",
    ).sort(["iso3", "year"])


def test_long_change_uses_nearest_to_1980_and_last_obs_in_window() -> None:
    ch = h4.long_change(panel(), "top1_income_share")
    con = ch.filter(pl.col("iso3") == "CON").row(0, named=True)
    assert (con["year0"], con["year1"]) == (1980, 2020)
    assert con["change"] == pytest.approx(0.03)
    dif = ch.filter(pl.col("iso3") == "DIF").row(0, named=True)
    assert dif["year0"] == 1981  # nearest observation to 1980
    assert "LATE" not in ch["iso3"].to_list()  # needs two distinct observations
    assert ch["iso3"].to_list() == ["CON", "DIF", "FLAT", "JPN"]


def test_change_table_joins_several_series_wide() -> None:
    t = h4.change_table(panel(), ["top1_income_share", "top01_income_share"])
    assert t.columns == ["iso3", "d_top1_income_share", "d_top01_income_share"]
    con = t.filter(pl.col("iso3") == "CON").row(0, named=True)
    assert con["d_top01_income_share"] == pytest.approx(0.02)


def test_change_table_full_join_keeps_countries_missing_one_series() -> None:
    p = panel().with_columns(
        pl.when(pl.col("iso3") == "FLAT")
        .then(None)
        .otherwise(pl.col("gini_income"))
        .alias("gini_income")
    )
    inner = h4.change_table(p, ["top1_income_share", "gini_income"])
    full = h4.change_table(p, ["top1_income_share", "gini_income"], how="full")
    assert inner["iso3"].to_list() == ["CON", "DIF", "JPN"]
    assert full["iso3"].to_list() == ["CON", "DIF", "FLAT", "JPN"]
    assert full.filter(pl.col("iso3") == "FLAT")["d_gini_income"][0] is None
    assert h4.rank_desc(full, "d_gini_income", "JPN") == (3, 3)  # nulls excluded from ranking


def test_cap_ratio_nulls_only_values_above_cap() -> None:
    p = pl.DataFrame({"iso3": ["A", "B"], "year": [2000, 2000], "p50_p10_income": [3.0, 500.0]})
    out = h4.cap_ratio(p, "p50_p10_income", cap=20.0)
    assert out["p50_p10_income"].to_list() == [3.0, None]
    assert out.height == 2


def test_within_top_criterion_applies_only_to_rising_top1() -> None:
    t = h4.change_table(panel(), ["top1_income_share", "top01_income_share"])
    res = h4.within_top_test(t, "d_top01_income_share", "d_top1_income_share")
    assert res.rising == ["CON", "DIF", "JPN"] and res.not_rising == ["FLAT"]
    assert res.concentrated == ["CON"]  # 0.02 >= 0.5 * 0.03; DIF 0.005 < 0.015; JPN 0.005 < 0.01
    assert res.k == 1 and res.n == 3
    assert res.ci[0] < 1 / 3 < res.ci[1]


def test_within_top_ratio_change_is_top01_over_top1_at_both_ends() -> None:
    r = h4.ratio_change(panel(), "top01_income_share", "top1_income_share")
    con = r.filter(pl.col("iso3") == "CON").row(0, named=True)
    assert con["ratio0"] == pytest.approx(0.030 / 0.08)
    assert con["ratio1"] == pytest.approx(0.050 / 0.11)
    assert con["d_ratio"] == pytest.approx(0.050 / 0.11 - 0.030 / 0.08)
    assert "LATE" not in r["iso3"].to_list()


def test_japan_pattern_and_count_of_countries_sharing_it() -> None:
    t = h4.change_table(
        panel(), ["top1_income_share", "top10_income_share", "bottom50_income_share"]
    )
    flags = h4.dispersion_pattern(t)
    f = dict(zip(flags["iso3"], flags["pattern"], strict=True))
    assert f["JPN"] is True  # d_top10 0.08 > d_top1 0.02, d_bottom50 -0.03 < 0
    assert f["CON"] is True  # d_top10 0.04 > 0.03, bottom50 -0.02
    assert f["DIF"] is False  # d_top10 0.02 < d_top1 0.03
    assert f["FLAT"] is False  # top1 falls, bottom50 rises
    assert flags.filter(pl.col("pattern"))["iso3"].to_list() == ["CON", "JPN"]


def test_decompose_top10_splits_into_top1_and_p90p99() -> None:
    t = h4.change_table(panel(), ["top1_income_share", "top10_income_share"])
    d = h4.decompose_top10(t)
    jpn = d.filter(pl.col("iso3") == "JPN").row(0, named=True)
    assert jpn["d_top1"] == pytest.approx(0.02) and jpn["d_p90p99"] == pytest.approx(0.06)
    assert jpn["d_top10"] == pytest.approx(0.08)


def test_rank_desc_and_median_of_others() -> None:
    t = h4.change_table(panel(), ["top1_income_share"])
    assert h4.rank_desc(t, "d_top1_income_share", "JPN") == (
        3,
        4,
    )  # CON 0.03, DIF 0.03, JPN 0.02, FLAT -0.01
    assert h4.median_others(t, "d_top1_income_share", "JPN") == pytest.approx(0.03)


def test_lorenz_from_distribution_rows_uses_only_the_g_percentile_partition() -> None:
    from theme_wealth_population_distribution import distribution as d

    rows = []
    for c in d.g_percentiles():
        lo, hi = d.parse_percentile(c)  # type: ignore[misc]
        rows.append(("JPN", 2000, "sptinc992j", c, lo, hi, (hi - lo) / 100))
    rows.append(("JPN", 2000, "sptinc992j", "p99.9p100", 99.9, 100.0, 0.5))  # tail, not a bracket
    dist = pl.DataFrame(
        rows,
        schema=["iso3", "year", "variable", "percentile", "p_lower", "p_upper", "share"],
        orient="row",
    )
    pts = h4.lorenz_curve(dist, "JPN", 2000, "sptinc992j")
    assert pts[0] == (0.0, 0.0) and pts[-1] == pytest.approx((1.0, 1.0))
    assert len(pts) == 128
    assert h4.lorenz_curve(dist, "JPN", 2001, "sptinc992j") is None
