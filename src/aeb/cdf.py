"""Convert a 5-bin PMF (+ tail bounds) into a Metaculus 201-point continuous_cdf.

Rule (locked): every numeric/discrete question is answered by spooling up a
5-category 51Folds model, then converting the resulting bin PMF into a CDF.

Approach:
  1. Bins partition [range_min, range_max] (constrained to the Metaculus axis).
     Cumulative mass at each bin edge gives anchor points (nominal_x, height).
  2. Map nominal x -> cdf-location [0,1] via the question's scaling
     (linear, or log when zero_point is set), matching Metaculus exactly.
  3. Linearly interpolate the CDF height at the cdf_size evenly-spaced locations.
  4. Standardize: enforce Metaculus mass/monotonicity/step constraints.

This is a stdlib port of Metaculus/forecasting-tools' NumericDistribution.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Scaling:
    range_min: float
    range_max: float
    zero_point: float | None = None       # None -> linear; set -> log-scaled
    open_lower_bound: bool = True
    open_upper_bound: bool = True
    cdf_size: int = 201                    # 201 numeric/date; inbound_outcome_count+1 discrete

    @property
    def inbound(self) -> int:
        return self.cdf_size - 1


def nominal_to_location(x: float, s: Scaling) -> float:
    """Map a real-world value to its [0,1] position on the Metaculus axis."""
    rmin, rmax, zp = s.range_min, s.range_max, s.zero_point
    if zp is None:
        return (x - rmin) / (rmax - rmin)
    deriv_ratio = (rmax - zp) / (rmin - zp)
    if x == zp:
        x += 1e-10
    return (
        math.log((x - rmin) * (deriv_ratio - 1) + (rmax - rmin)) - math.log(rmax - rmin)
    ) / math.log(deriv_ratio)


def location_to_nominal(loc: float, s: Scaling) -> float:
    rmin, rmax, zp = s.range_min, s.range_max, s.zero_point
    if zp is None:
        return rmin + (rmax - rmin) * loc
    deriv_ratio = (rmax - zp) / (rmin - zp)
    return rmin + (rmax - rmin) * (deriv_ratio ** loc - 1) / (deriv_ratio - 1)


def _standardize(cdf: list[float], s: Scaling) -> list[float]:
    """Enforce Metaculus submission constraints (port of _standardize_cdf).

    - no mass outside closed bounds; minimum mass outside open bounds
    - strictly increasing by a small minimum each step
    - PMF step capped (default 0.2 for 200 inbound outcomes)
    """
    n = len(cdf)
    lower_open, upper_open = s.open_lower_bound, s.open_upper_bound
    scale_lower = 0.0 if lower_open else cdf[0]
    scale_upper = 1.0 if upper_open else cdf[-1]
    mass = scale_upper - scale_lower or 1e-9

    out: list[float] = []
    for i, F in enumerate(cdf):
        loc = i / (n - 1)
        rF = (F - scale_lower) / mass
        if lower_open and upper_open:
            v = 0.988 * rF + 0.01 * loc + 0.001
        elif lower_open:
            v = 0.989 * rF + 0.01 * loc + 0.001
        elif upper_open:
            v = 0.989 * rF + 0.01 * loc
        else:
            v = 0.99 * rF + 0.01 * loc
        out.append(v)
    cdf = out

    # PMF with implicit 0 below and 1 above the inbound region.
    pmf = [cdf[0]] + [cdf[i] - cdf[i - 1] for i in range(1, n)] + [1.0 - cdf[-1]]
    cap = 0.2 * (200 / s.inbound) * 0.95

    def capped(scale: float) -> list[float]:
        return [pmf[0]] + [min(cap, scale * p) for p in pmf[1:-1]] + [pmf[-1]]

    def capped_sum(scale: float) -> float:
        return sum(capped(scale))

    lo, hi = 1.0, 1.0
    while capped_sum(hi) < 1.0:
        hi *= 1.2
    scale = 1.0
    for _ in range(100):
        scale = 0.5 * (lo + hi)
        stotal = capped_sum(scale)
        if stotal < 1.0:
            lo = scale
        else:
            hi = scale
        if abs(stotal - 1.0) < 1e-12 or (hi - lo) < 2e-5:
            break

    pmf = capped(scale)
    inner = sum(pmf[1:-1])
    target = cdf[-1] - cdf[0]
    if inner > 0:
        factor = target / inner
        pmf = [pmf[0]] + [p * factor for p in pmf[1:-1]] + [pmf[-1]]

    acc = 0.0
    cum: list[float] = []
    for p in pmf:
        acc += p
        cum.append(acc)
    result = [round(min(1.0, max(0.0, x)), 10) for x in cum[:-1]]
    # final monotonic safety pass
    for i in range(1, len(result)):
        if result[i] < result[i - 1]:
            result[i] = result[i - 1]
    return result


def bins_to_cdf(
    edges: list[float],
    masses: list[float],
    scaling: Scaling,
) -> list[float]:
    """Build the 201-point CDF from contiguous bin edges + per-bin masses.

    edges: len k+1 ascending values spanning [range_min, range_max]
           (edges[0] == LOW_TAIL, edges[-1] == HIGH_TAIL).
    masses: len k probabilities per bin (need not be pre-normalized).
    """
    if len(edges) != len(masses) + 1:
        raise ValueError("edges must have exactly one more element than masses")
    if any(edges[i] >= edges[i + 1] for i in range(len(edges) - 1)):
        raise ValueError("edges must be strictly ascending")
    total = sum(masses)
    if total <= 0:
        raise ValueError("bin masses must sum to > 0")
    masses = [m / total for m in masses]

    # Cumulative-mass anchor points at each edge: (nominal_x, cdf_height).
    cum = 0.0
    anchors: list[tuple[float, float]] = [(edges[0], 0.0)]
    for i, m in enumerate(masses):
        cum += m
        anchors.append((edges[i + 1], cum))
    # Convert nominal x -> location, keep heights.
    loc_anchors = [(nominal_to_location(x, scaling), h) for x, h in anchors]

    def cdf_at(loc: float) -> float:
        if loc <= loc_anchors[0][0]:
            return loc_anchors[0][1]
        if loc >= loc_anchors[-1][0]:
            return loc_anchors[-1][1]
        for j in range(1, len(loc_anchors)):
            x0, h0 = loc_anchors[j - 1]
            x1, h1 = loc_anchors[j]
            if x0 <= loc <= x1:
                if x1 == x0:
                    return h1
                return h0 + (h1 - h0) * (loc - x0) / (x1 - x0)
        return loc_anchors[-1][1]  # pragma: no cover

    n = scaling.cdf_size
    raw = [cdf_at(i / (n - 1)) for i in range(n)]
    return _standardize(raw, scaling)


def validate_cdf(cdf: list[float], scaling: Scaling) -> None:
    """Raise if the CDF would be rejected by Metaculus."""
    if len(cdf) != scaling.cdf_size:
        raise ValueError(f"cdf length {len(cdf)} != {scaling.cdf_size}")
    if not all(0.0 <= x <= 1.0 for x in cdf):
        raise ValueError("cdf values must be within [0, 1]")
    if any(cdf[i] < cdf[i - 1] for i in range(1, len(cdf))):
        raise ValueError("cdf must be monotonically non-decreasing")
    min_step = 5e-05
    if any((cdf[i] - cdf[i - 1]) < min_step - 1e-9 for i in range(1, len(cdf))):
        raise ValueError("cdf must increase by at least 5e-05 each step")
