"""Ensemble aggregation across the N concurrent 51Folds runs.

Project rule (locked): the aggregated point is the MIDPOINT BETWEEN the mean
and the median of the N runs:  (mean + median) / 2  — not plain mean/median.
"""
from __future__ import annotations

from typing import Iterable, Mapping


def mean(values: list[float]) -> float:
    if not values:
        raise ValueError("mean() of empty sequence")
    return sum(values) / len(values)


def median(values: list[float]) -> float:
    if not values:
        raise ValueError("median() of empty sequence")
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else 0.5 * (s[mid - 1] + s[mid])


def midpoint(values: list[float]) -> float:
    """(mean + median) / 2 — the project's aggregation definition."""
    return 0.5 * (mean(values) + median(values))


def aggregate_outcomes(
    runs: Iterable[Mapping[str, float]],
    *,
    normalize: bool = True,
) -> dict[str, float]:
    """Aggregate per-outcome probabilities across N runs via midpoint().

    Each run is a {label: probability} mapping over the SAME outcome set
    (Yes/No for binary, the option labels for MC, the bin labels for numeric).
    Returns {label: aggregated_probability}. If normalize, rescales to sum 1.
    """
    runs = [dict(r) for r in runs]
    if not runs:
        raise ValueError("no runs to aggregate")
    labels = list(runs[0].keys())
    for r in runs:
        if set(r.keys()) != set(labels):
            raise ValueError(f"inconsistent outcome labels across runs: {set(r)} vs {set(labels)}")

    agg = {lab: midpoint([r[lab] for r in runs]) for lab in labels}
    if normalize:
        total = sum(agg.values())
        if total <= 0:
            raise ValueError("aggregated probabilities sum to <= 0")
        agg = {lab: v / total for lab, v in agg.items()}
    return agg
