import polars as pl
import pytest

from theme_wealth_population_distribution.analysis import a20261004_h2_institutions as h2


def panel() -> pl.DataFrame:
    """4 countries × 1980–2010 (every 5 years), exact (no noise):
    y = 10 + 0.5*socx − 0.2*taxrev + country effect + year effect,
    so the FE and long-difference estimators have known answers."""
    rows: list[dict[str, object]] = []
    years = list(range(1980, 2011, 5))
    for i, iso3 in enumerate(["AAA", "BBB", "JPN", "USA"]):
        for t, year in enumerate(years):
            socx = 10.0 + 2.0 * i + 0.8 * t + (1.0 if iso3 == "USA" and t > 3 else 0.0)
            taxrev = 25.0 + i + 0.5 * t * (i + 1)
            y_pp = 10.0 + 0.5 * socx - 0.2 * taxrev + 3.0 * i + 0.7 * t
            rows.append(
                {
                    "iso3": iso3,
                    "year": year,
                    "top1_income_share": y_pp / 100,
                    "top10_income_share": 3 * y_pp / 100,
                    "top1_wealth_share": None
                    if (iso3 == "AAA" and year == 1980)
                    else 2 * y_pp / 100,
                    "top10_wealth_share": 4 * y_pp / 100,
                    "top1_income_quality": 4 if iso3 == "USA" else 1,
                    "top1_wealth_quality": 0,
                    "top_pit_rate": None if year < 2000 else 50.0 - i,
                    "social_expenditure_gdp": socx,
                    "tax_revenue_gdp": taxrev,
                    "inheritance_tax_rev_gdp": 0.2,
                    "source": "wid_world+oecd",
                }
            )
    return pl.DataFrame(rows)


def test_to_pp_scales_only_wid_shares() -> None:
    p = h2.to_pp(panel())
    r = p.filter((pl.col("iso3") == "AAA") & (pl.col("year") == 1980)).row(0, named=True)
    assert r["top1_income_share"] == pytest.approx(10 + 5 - 5)  # 0.5*10 - 0.2*25 + 10
    assert r["social_expenditure_gdp"] == 10.0


def test_end_year_is_last_year_with_enough_complete_countries() -> None:
    p = h2.to_pp(panel())
    assert h2.end_year(p, (*h2.OUTCOMES, *h2.INST_ALL), 4) == 2010
    assert h2.end_year(p, ("top1_wealth_share",), 4) == 2010
    # pit is missing before 2000 for everyone -> only 2000+ qualify
    assert h2.end_year(p.filter(pl.col("year") <= 2000), ("top_pit_rate",), 4) == 2000
    with pytest.raises(ValueError, match="no year"):
        h2.end_year(p, ("top_pit_rate",), 5)


def test_long_difference_keeps_only_countries_with_both_years_and_base_quality() -> None:
    p = h2.to_pp(panel())
    d = h2.long_difference(p, 1980, 2010, ("top1_wealth_share", *h2.INST_NO_PIT))
    assert d["iso3"].to_list() == ["BBB", "JPN", "USA"]  # AAA lacks wealth in 1980
    d2 = h2.long_difference(p, 1980, 2010, ("top1_income_share", *h2.INST_NO_PIT))
    assert d2["iso3"].to_list() == ["AAA", "BBB", "JPN", "USA"]
    usa = d2.filter(pl.col("iso3") == "USA").row(0, named=True)
    assert usa["d_social_expenditure_gdp"] == pytest.approx(0.8 * 6 + 1.0)
    assert usa["top1_income_quality"] == 4
    d3 = h2.long_difference(p, 1980, 2010, ("top_pit_rate",))
    assert d3.height == 0  # pit missing at base


def test_fit_ols_hc3_recovers_exact_linear_relation() -> None:
    p = h2.to_pp(panel())
    d = h2.long_difference(p, 1980, 2010, ("top1_income_share", *h2.INST_NO_PIT))
    f = h2.fit_ols_hc3(
        d, "d_top1_income_share", ("d_social_expenditure_gdp", "d_tax_revenue_gdp"), "t"
    )
    assert f.n == 4 and f.r2 == pytest.approx(1.0)
    assert f.coef["d_social_expenditure_gdp"] == pytest.approx(0.5)
    assert f.coef["d_tax_revenue_gdp"] == pytest.approx(-0.2)
    assert set(f.se) == {"const", "d_social_expenditure_gdp", "d_tax_revenue_gdp"}


def test_lagged_shifts_within_country_and_keeps_missing() -> None:
    p = h2.to_pp(panel())
    lp = h2.lagged(p, ("social_expenditure_gdp",), 5)
    r = lp.filter((pl.col("iso3") == "AAA") & (pl.col("year") == 1985)).row(0, named=True)
    assert r["social_expenditure_gdp_lag5"] == 10.0
    first = lp.filter((pl.col("iso3") == "AAA") & (pl.col("year") == 1980)).row(0, named=True)
    assert first["social_expenditure_gdp_lag5"] is None
    l0 = h2.lagged(p, ("tax_revenue_gdp",), 0)
    assert l0["tax_revenue_gdp_lag0"].to_list() == p["tax_revenue_gdp"].to_list()


def test_fit_twoway_fe_recovers_slopes_net_of_country_and_year_effects() -> None:
    p = h2.to_pp(panel())
    lp = h2.lagged(p, h2.INST_NO_PIT, 0)
    f = h2.fit_twoway_fe(
        lp, "top1_income_share", ("social_expenditure_gdp_lag0", "tax_revenue_gdp_lag0"), "fe"
    )
    assert f.n == 28 and f.n_groups == 4
    assert f.coef["social_expenditure_gdp_lag0"] == pytest.approx(0.5, abs=1e-6)
    assert f.coef["tax_revenue_gdp_lag0"] == pytest.approx(-0.2, abs=1e-6)
    assert f.r2 == pytest.approx(1.0, abs=1e-6)


def test_drop_bad_quality_uses_base_year_flag_of_matching_series() -> None:
    p = h2.to_pp(panel())
    d = h2.long_difference(
        p, 1980, 2010, ("top1_income_share", "top10_income_share", *h2.INST_NO_PIT)
    )
    assert h2.drop_bad_quality(d, "top1_income_share")["iso3"].to_list() == ["AAA", "BBB", "JPN"]
    assert h2.drop_bad_quality(d, "top10_income_share")["iso3"].to_list() == ["AAA", "BBB", "JPN"]
    assert h2.drop_bad_quality(d, "top1_wealth_share").height == 4
