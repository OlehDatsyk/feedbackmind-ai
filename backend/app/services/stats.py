"""Statistical helpers. Kept small, explicit and unit-tested independently of AI."""

from __future__ import annotations

import math
from dataclasses import dataclass


def pct(part: int, whole: int) -> float | None:
    """Percentage with one decimal; None when the denominator is zero (never a misleading 0%)."""
    if whole <= 0:
        return None
    return round(100.0 * part / whole, 1)


@dataclass
class ZTest:
    p1: float
    p2: float
    diff: float
    z: float
    p_value: float
    significant: bool
    method: str = "two-proportion z-test (pooled), two-sided, alpha=0.05"


def two_proportion_ztest(x1: int, n1: int, x2: int, n2: int, alpha: float = 0.05) -> ZTest | None:
    """Compare proportions x1/n1 vs x2/n2. Returns None when either sample is empty or the test is degenerate.

    The normal approximation is only reasonable with enough observations; callers apply minimum sample sizes.
    """
    if n1 <= 0 or n2 <= 0:
        return None
    p1, p2 = x1 / n1, x2 / n2
    pooled = (x1 + x2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    if se == 0:
        return ZTest(p1, p2, p2 - p1, 0.0, 1.0, False)
    z = (p2 - p1) / se
    p_value = math.erfc(abs(z) / math.sqrt(2))
    return ZTest(p1, p2, p2 - p1, z, p_value, p_value < alpha)


def normal_approx_ok(x: int, n: int) -> bool:
    """Rule of thumb for the z-test: at least 5 successes and 5 failures."""
    return x >= 5 and (n - x) >= 5


@dataclass
class LinearTrend:
    slope: float
    p_value: float
    r_squared: float
    n_points: int
    significant: bool
    method: str = "ordinary least-squares regression of the bucket value on bucket index; two-sided p-value, alpha=0.05"


def linear_trend(values: list[float]) -> LinearTrend | None:
    """OLS slope per bucket. Needs at least 4 points with variation; returns None otherwise."""
    n = len(values)
    if n < 4:
        return None
    from scipy import stats as sstats

    xs = list(range(n))
    if max(values) == min(values):
        return LinearTrend(0.0, 1.0, 0.0, n, False)
    res = sstats.linregress(xs, values)
    p = float(res.pvalue) if res.pvalue == res.pvalue else 1.0  # NaN guard
    return LinearTrend(float(res.slope), p, float(res.rvalue**2), n, p < 0.05)


def evidence_strength(n: int) -> str:
    if n >= 30:
        return "strong"
    if n >= 10:
        return "moderate"
    return "limited"
