"""Readiness / elicitation gate — runs BEFORE CDF conversion.

Determines whether a question has everything needed to convert a 5-bin PMF
into a Metaculus CDF. If not, the question is skipped with a reason rather
than producing a malformed submission.
"""
from __future__ import annotations

from dataclasses import dataclass

from .cdf import Scaling
from .metaculus import Question

MAX_MC_OPTIONS = 5  # 51Folds caps outcomes at 5


@dataclass
class Readiness:
    ok: bool
    reason: str


def check(q: Question) -> Readiness:
    if not q.can_forecast:
        return Readiness(False, f"not forecastable (perm={q.user_permission}, status={q.status})")

    if q.type == "binary":
        return Readiness(True, "binary")

    if q.type == "multiple_choice":
        if not q.options:
            return Readiness(False, "multiple_choice question has no options")
        if len(q.options) > MAX_MC_OPTIONS:
            return Readiness(False, f"{len(q.options)} options > {MAX_MC_OPTIONS} (needs grouping)")
        return Readiness(True, "multiple_choice")

    if q.type in ("numeric", "discrete"):
        s = q.scaling or {}
        if s.get("range_min") is None or s.get("range_max") is None:
            return Readiness(False, "numeric question missing scaling range_min/range_max")
        if s["range_min"] >= s["range_max"]:
            return Readiness(False, "numeric range_min >= range_max")
        return Readiness(True, q.type)

    return Readiness(False, f"unsupported type: {q.type}")


def scaling_for(q: Question) -> Scaling:
    """Build a cdf.Scaling from the question's Metaculus scaling metadata."""
    s = q.scaling or {}
    cdf_size = 201
    if q.type == "discrete" and s.get("inbound_outcome_count"):
        cdf_size = int(s["inbound_outcome_count"]) + 1
    return Scaling(
        range_min=float(s["range_min"]),
        range_max=float(s["range_max"]),
        zero_point=(float(s["zero_point"]) if s.get("zero_point") is not None else None),
        open_lower_bound=bool(q.open_lower_bound),
        open_upper_bound=bool(q.open_upper_bound),
        cdf_size=cdf_size,
    )
