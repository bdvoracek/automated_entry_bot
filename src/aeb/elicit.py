"""Elicitation / readiness agent for the CDF (numeric/discrete) path.

Runs BEFORE the Continuous Distribution Agent and the CDF conversion. Its job
is to gather everything required to finalise a CDF computation for a question,
auto-extracting what Metaculus already gives us and flagging what is still
needed or ambiguous — so we never attempt a CDF from incomplete inputs.

What a CDF computation needs (bins_to_cdf(edges, masses, scaling)):
  - scaling: range_min/max, zero_point (scale type), open bounds, cdf_size  -> AUTO
  - unit, horizon, resolution criteria (context for bin design)             -> AUTO
  - edges:  5 bin boundaries within the axis                                -> Continuous Distribution Agent (LLM+web)
  - masses: 5-bin PMF, normalized to sum to 1                              -> 51Folds ensemble
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .cdf import Scaling, location_to_nominal
from .metaculus import Question
from .readiness import scaling_for


@dataclass
class Elicitation:
    question_id: int
    post_id: int
    title: str
    qtype: str
    scaling: Scaling
    unit: str
    scale_type: str                 # "linear" | "log"
    horizon: dict[str, Any]
    resolution_criteria: str
    crowd_nominal: float | None      # crowd central estimate in real units (if revealed)
    ready_for_bin_design: bool
    needs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        s = self.scaling
        lines = [
            f"q{self.question_id} [{self.qtype}] — {self.title}",
            f"  axis     : [{s.range_min}, {s.range_max}] {self.scale_type}, unit={self.unit!r}",
            f"  bounds   : lower={'open' if s.open_lower_bound else 'closed'}, "
            f"upper={'open' if s.open_upper_bound else 'closed'}",
            f"  cdf_size : {s.cdf_size}",
            f"  horizon  : close={self.horizon.get('close')} resolve={self.horizon.get('resolve')}",
            f"  crowd    : {self.crowd_nominal!r} (real units, sandbox-revealed only)",
            f"  READY for bin design: {self.ready_for_bin_design}",
        ]
        if self.needs:
            lines.append("  NEEDS  : " + "; ".join(self.needs))
        if self.warnings:
            lines.append("  WARN   : " + "; ".join(self.warnings))
        return "\n".join(lines)


def folds_context(el: "Elicitation", extra: str = "") -> str:
    """Assemble the 51Folds additionalContext, leading with the midpoint anchor.

    When the question midpoint (community CP) is available it is passed as the
    central anchor so 51Folds bins/reasons around the right center. On live AIB
    questions the CP is hidden, so this is included only when available.
    """
    parts: list[str] = []
    if el.crowd_nominal is not None:
        parts.append(
            f"Central anchor (question/community midpoint): ~{el.crowd_nominal}{el.unit}. "
            f"Treat this as the middle of the distribution when assigning probabilities "
            f"across the bins."
        )
    if extra:
        parts.append(extra)
    return " ".join(parts)


def elicit(q: Question) -> Elicitation:
    scaling = scaling_for(q)
    scale_type = "log" if scaling.zero_point is not None else "linear"
    unit = (q.raw.get("question") or {}).get("unit") or ""
    qraw = q.raw.get("question") or {}

    crowd_nominal = None
    if q.community_centers:
        # numeric/discrete centers are in cdf-location [0,1]; map back to real units.
        crowd_nominal = round(location_to_nominal(q.community_centers[0], scaling), 3)

    needs = [
        "5-bin design within the axis (Continuous Distribution Agent: LLM + web search)",
        "5-bin PMF from the 51Folds 5-category ensemble (aggregated, normalized to sum to 1)",
    ]
    warnings: list[str] = []

    # Discrete with >5 native outcomes: we still design 5 bins (project rule), then the
    # piecewise-uniform CDF approximates the integer PMF — flag the approximation.
    if q.type == "discrete":
        n_out = scaling.cdf_size - 1
        if n_out > 5:
            warnings.append(
                f"discrete has {n_out} integer outcomes; 5-bin design -> {scaling.cdf_size}-pt "
                f"CDF is a piecewise-uniform approximation of the integer PMF")

    if scaling.open_lower_bound or scaling.open_upper_bound:
        warnings.append("open bound(s): CDF keeps tail mass beyond the range (standardize handles it)")

    # Sanity: a fully specified axis is required before bin design.
    ready = all(v is not None for v in (scaling.range_min, scaling.range_max)) and \
        scaling.range_min < scaling.range_max

    return Elicitation(
        question_id=q.question_id, post_id=q.post_id, title=q.title, qtype=q.type,
        scaling=scaling, unit=unit, scale_type=scale_type,
        horizon={"close": qraw.get("scheduled_close_time"),
                 "resolve": qraw.get("scheduled_resolve_time")},
        resolution_criteria=(qraw.get("resolution_criteria") or "")[:300],
        crowd_nominal=crowd_nominal, ready_for_bin_design=ready,
        needs=needs, warnings=warnings,
    )
