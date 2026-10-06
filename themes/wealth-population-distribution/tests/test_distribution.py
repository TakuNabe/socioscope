import pytest

from theme_wealth_population_distribution import distribution as d


def uniform(n: int = 100) -> list[d.Bracket]:
    w = 100 / n
    return [(i * w, (i + 1) * w, 1 / n) for i in range(n)]


def test_parse_percentile_handles_decimals_and_rejects_non_brackets() -> None:
    assert d.parse_percentile("p99.9p100") == (99.9, 100.0)
    assert d.parse_percentile("p0p1") == (0.0, 1.0)
    assert d.parse_percentile("p99.99p99.991") == (99.99, 99.991)
    assert d.parse_percentile("p100p100") is None
    assert d.parse_percentile("p50p10") is None
    assert d.parse_percentile("x") is None


def test_g_percentiles_are_127_consecutive_codes() -> None:
    codes = d.g_percentiles()
    assert len(codes) == 127 and len(set(codes)) == 127
    assert codes[:2] == ("p0p1", "p1p2") and codes[98] == "p98p99"
    assert codes[99] == "p99p99.1" and codes[107] == "p99.8p99.9"
    assert codes[108] == "p99.9p99.91" and codes[117] == "p99.99p99.991"
    assert codes[-1] == "p99.999p100"
    bounds = [d.parse_percentile(c) for c in codes]
    assert all(b is not None for b in bounds)
    assert d.is_partition([(lo, hi, 0.0) for lo, hi in bounds])  # type: ignore[misc]


def test_is_partition_rejects_gaps_overlaps_and_incomplete_coverage() -> None:
    assert d.is_partition(uniform(4))
    assert not d.is_partition([(0, 50, 0.5), (60, 100, 0.5)])
    assert not d.is_partition([(0, 60, 0.5), (50, 100, 0.5)])
    assert not d.is_partition([(0, 50, 0.5)])
    assert not d.is_partition([])


def test_lorenz_points_cumulate_in_order_regardless_of_input_order() -> None:
    pts = d.lorenz_points([(50, 100, 0.8), (0, 50, 0.2)])
    assert pts == [(0.0, 0.0), (0.5, 0.2), (1.0, 1.0)]


def test_lorenz_points_fail_closed_on_bad_partition_or_total() -> None:
    with pytest.raises(ValueError, match="partition"):
        d.lorenz_points([(0, 50, 0.5)])
    with pytest.raises(ValueError, match="sum to"):
        d.lorenz_points([(0, 50, 0.5), (50, 100, 0.8)])


def test_gini_uniform_is_zero_and_one_person_is_about_one() -> None:
    assert d.gini_from_brackets(uniform()) == pytest.approx(0.0, abs=1e-12)
    one = [(0, 99, 0.0), (99, 100, 1.0)]
    assert d.gini_from_brackets(one) == pytest.approx(0.99)
    fine = [(i, i + 1, 0.0) for i in range(99)] + [(99, 99.999, 0.0), (99.999, 100, 1.0)]
    assert d.gini_from_brackets(fine) == pytest.approx(0.99999)


def test_gini_matches_textbook_two_group_value() -> None:
    # bottom half holds 20%: Lorenz (0,0)-(0.5,0.2)-(1,1): area = 0.05 + 0.3 = 0.35 -> G = 0.3
    assert d.gini_from_brackets([(0, 50, 0.2), (50, 100, 0.8)]) == pytest.approx(0.3)


def test_gini_allows_negative_bottom_shares_as_in_net_wealth() -> None:
    g = d.gini_from_brackets([(0, 50, -0.02), (50, 90, 0.32), (90, 100, 0.70)])
    assert 0.6 < g < 0.8


def test_middle40_share_and_none_propagation() -> None:
    assert d.middle40_share(0.19, 0.40) == pytest.approx(0.41)
    assert d.middle40_share(None, 0.4) is None and d.middle40_share(0.2, None) is None


def test_ratio_and_top_within_share() -> None:
    th = {10: 100.0, 50: 300.0, 90: 900.0}
    assert d.ratio(th, 90, 50) == pytest.approx(3.0)
    assert d.ratio(th, 50, 10) == pytest.approx(3.0)
    assert d.ratio(th, 99, 50) is None
    assert d.ratio({10: 0.0, 50: 1.0}, 50, 10) is None  # zero/negative denominator
    assert d.top_within_share(0.05, 0.10) == pytest.approx(0.5)
    assert d.top_within_share(None, 0.1) is None and d.top_within_share(0.05, 0.0) is None
