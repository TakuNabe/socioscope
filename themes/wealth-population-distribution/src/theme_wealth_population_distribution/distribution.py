"""Pure distribution helpers (no I/O): Lorenz curve, trapezoid Gini, middle-40 share, ratios.

Inputs are WID-style brackets ``(p_lower, p_upper, share)`` where the bounds are population
percentiles in [0, 100] and ``share`` is the bracket's share of the total (0–1, may be negative
for net wealth). A *partition* is a set of brackets with consecutive bounds covering 0..100
(WID's 127 generalized percentiles p0p1 … p99.999p100). Everything here is deterministic and
unit-tested in tests/test_distribution.py.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from itertools import pairwise

Bracket = tuple[float, float, float]  # (p_lower, p_upper, share)

_PCT = re.compile(r"^p(?P<lo>\d+(?:\.\d+)?)p(?P<hi>\d+(?:\.\d+)?)$")
TOTAL_TOLERANCE = 0.02  # a partition's shares must sum to 1 within this (WID rounding)


def parse_percentile(code: str) -> tuple[float, float] | None:
    """'p99.9p100' -> (99.9, 100.0); None when the code is not of the form pXpY with X < Y."""
    m = _PCT.match(code)
    if m is None:
        return None
    lo, hi = float(m.group("lo")), float(m.group("hi"))
    if not (0 <= lo < hi <= 100):
        return None
    return lo, hi


def g_percentiles() -> tuple[str, ...]:
    """WID's 127 generalized-percentile bracket codes, in ascending order.

    p0p1 … p98p99 (99), p99p99.1 … p99.8p99.9 (9), p99.9p99.91 … p99.98p99.99 (9),
    p99.99p99.991 … p99.998p99.999 (9), p99.999p100 (1).
    """
    out = [f"p{i}p{i + 1}" for i in range(99)]
    for scale in (1, 2, 3):  # tenths, hundredths, thousandths of a percent inside the top 1%
        step = 10**-scale
        base = 100 - 10 * step  # 99, 99.9, 99.99
        for k in range(9):
            lo = round(base + k * step, scale)
            hi = round(base + (k + 1) * step, scale)
            out.append(f"p{_fmt(lo)}p{_fmt(hi)}")
    out.append("p99.999p100")
    return tuple(out)


def _fmt(x: float) -> str:
    return f"{x:.3f}".rstrip("0").rstrip(".")


def is_partition(brackets: Iterable[Bracket]) -> bool:
    """True when the brackets, sorted by lower bound, cover 0..100 with no gaps or overlaps."""
    bs = sorted(brackets)
    if not bs or bs[0][0] != 0 or bs[-1][1] != 100:
        return False
    return all(abs(a[1] - b[0]) < 1e-9 for a, b in pairwise(bs))


def lorenz_points(brackets: Iterable[Bracket]) -> list[tuple[float, float]]:
    """Cumulative (population share, income/wealth share) points, from (0, 0) to (1, ~1).

    Requires a partition; the shares are used as given (not renormalised) so a partition
    whose shares do not sum to 1 ± TOTAL_TOLERANCE raises (fail closed on inconsistent data).
    """
    bs = sorted(brackets)
    if not is_partition(bs):
        msg = "brackets do not form a partition of [0, 100]"
        raise ValueError(msg)
    total = sum(s for _, _, s in bs)
    if abs(total - 1.0) > TOTAL_TOLERANCE:
        msg = f"bracket shares sum to {total:.4f}, not 1"
        raise ValueError(msg)
    pts = [(0.0, 0.0)]
    cum = 0.0
    for _, hi, s in bs:
        cum += s
        pts.append((hi / 100.0, cum))
    return pts


def gini_from_brackets(brackets: Iterable[Bracket]) -> float:
    """Gini = 1 − 2·∫L(p)dp with the Lorenz curve linearly interpolated between bracket ends
    (trapezoid rule). Within-bracket inequality is ignored, so this slightly understates the
    true Gini; the bias shrinks with finer brackets (WID's 127 g-percentiles are fine enough
    for cross-country/time comparison). Uniform distribution -> 0; one person holding all -> ~1.
    """
    pts = lorenz_points(brackets)
    area = 0.0
    for (p0, l0), (p1, l1) in pairwise(pts):
        area += (p1 - p0) * (l0 + l1) / 2.0
    return 1.0 - 2.0 * area


def middle40_share(bottom50: float | None, top10: float | None) -> float | None:
    """Share of the p50–p90 group = 1 − bottom50 − top10. None when either input is missing."""
    if bottom50 is None or top10 is None:
        return None
    return 1.0 - bottom50 - top10


def ratio(thresholds: Mapping[int, float | None], num: int, den: int) -> float | None:
    """thresholds[num] / thresholds[den] (e.g. P90/P50). None when missing or denominator <= 0
    (WID thresholds can be 0 or negative at the bottom of wealth distributions)."""
    a, b = thresholds.get(num), thresholds.get(den)
    if a is None or b is None or b <= 0:
        return None
    return a / b


def top_within_share(top_fine: float | None, top_coarse: float | None) -> float | None:
    """Share of the top-1% total held by the top 0.1% (= top0.1 / top1). None when missing or
    the coarse share is <= 0."""
    if top_fine is None or top_coarse is None or top_coarse <= 0:
        return None
    return top_fine / top_coarse
