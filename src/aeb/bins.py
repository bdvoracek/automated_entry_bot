"""Continuous Distribution Agent: design 5 bins (+ tails) for a numeric question.

The agent's behaviour is specified in ContinuousDistributionAgent.txt (repo root).
Our orchestrator runs it (option 1) and CONSTRAINS the bins to the Metaculus axis
by feeding the question's range_min/range_max + open/closed bounds as hard limits.

This module provides:
  - PROMPT: the agent system prompt (loaded from the txt file).
  - parse_distribution_block(): parse the `=== DISTRIBUTION READY ===` output.
  - design_bins(): call an injected LLM to produce a BinSpec (or raise if none).
The actual LLM+web-search call is dependency-injected so this stays testable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import config
from .cdf import Scaling

PROMPT_PATH = config.REPO_ROOT / "ContinuousDistributionAgent.txt"


def load_prompt() -> str:
    return PROMPT_PATH.read_text() if PROMPT_PATH.exists() else ""


PROMPT = load_prompt()


@dataclass
class BinSpec:
    unit: str
    low_tail: float
    high_tail: float
    edges: list[float]          # length 6: [low_tail, b1u, b2u, b3u, b4u, high_tail]
    status: str = "FOUND"
    time_to_expiry: str | None = None
    source_context: str | None = None

    @property
    def labels(self) -> list[str]:
        """Human-readable bin labels for the 5 51Folds outcomes."""
        def fmt(v: float) -> str:
            return f"{v:g}"
        return [f"{fmt(self.edges[i])}-{fmt(self.edges[i + 1])}" for i in range(5)]


_NUM = r"[-+]?\d*\.?\d+"


def parse_distribution_block(text: str) -> BinSpec:
    """Parse the structured block the Continuous Distribution Agent emits."""
    if "NOT_FOUND" in text and "STATUS: NOT_FOUND" in text:
        raise ValueError("Continuous Distribution Agent returned NOT_FOUND (non-quantitative)")

    def field(name: str) -> str | None:
        m = re.search(rf"^{name}:\s*(.+)$", text, re.MULTILINE)
        return m.group(1).strip() if m else None

    def num(name: str) -> float:
        v = field(name)
        if v is None:
            raise ValueError(f"missing field {name}")
        m = re.search(_NUM, v)
        if not m:
            raise ValueError(f"no numeric value for {name}: {v!r}")
        return float(m.group(0))

    def bin_bounds(name: str) -> tuple[float, float]:
        v = field(name)
        if v is None or "|" not in v:
            raise ValueError(f"missing/invalid {name}: {v!r}")
        lo, hi = v.split("|", 1)
        return float(re.search(_NUM, lo).group(0)), float(re.search(_NUM, hi).group(0))

    low_tail = num("LOW_TAIL")
    high_tail = num("HIGH_TAIL")
    b = [bin_bounds(f"BIN_{i}") for i in range(1, 6)]
    # Build contiguous edges from bin bounds; snap outer edges to the tails.
    edges = [low_tail, b[0][1], b[1][1], b[2][1], b[3][1], high_tail]
    for i in range(len(edges) - 1):
        if edges[i] >= edges[i + 1]:
            raise ValueError(f"non-ascending bin edges: {edges}")
    return BinSpec(
        unit=field("UNIT") or "",
        low_tail=low_tail,
        high_tail=high_tail,
        edges=edges,
        status=field("STATUS") or "FOUND",
        time_to_expiry=field("TIME_TO_EXPIRY"),
        source_context=field("SOURCE_CONTEXT"),
    )


# An LLM runner takes (system_prompt, user_message) and returns the model's text.
LLMRunner = Callable[[str, str], str]


def design_bins(
    question_title: str,
    scaling: Scaling,
    *,
    llm: LLMRunner | None = None,
    community_anchor: float | None = None,
) -> BinSpec:
    """Run the Continuous Distribution Agent, constrained to the Metaculus axis.

    `llm` is injected (an LLM with web search). If absent, this raises — the
    numeric path cannot proceed without the bin designer.
    """
    if llm is None:
        raise NotImplementedError(
            "design_bins requires an LLM runner (LLM + web search). "
            "Inject one via orchestrator(bin_designer=...)."
        )
    constraints = (
        f"HARD CONSTRAINTS (Metaculus axis): the 5 bins MUST span exactly "
        f"[{scaling.range_min}, {scaling.range_max}]. "
        f"open_lower_bound={scaling.open_lower_bound}, "
        f"open_upper_bound={scaling.open_upper_bound}. "
        f"Set LOW_TAIL={scaling.range_min} and HIGH_TAIL={scaling.range_max}."
    )
    if community_anchor is not None:
        constraints += f" Proposed central anchor (community midpoint): {community_anchor}."
    user_msg = f"DV_TEXT: {question_title}\n\n{constraints}"
    return parse_distribution_block(llm(PROMPT, user_msg))
