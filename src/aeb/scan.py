"""Scan Metaculus for questions we could answer.

Classifies every open, forecastable question by how our pipeline can handle it:
  - answerable_now     : binary, or multiple_choice with <=5 options (headless)
  - needs_bin_designer : numeric / discrete (need the Continuous Distribution Agent)
  - needs_grouping     : multiple_choice with >5 options (exceeds 51Folds' 5-outcome cap)

Reuses MetaculusClient.iter_open_questions (the same gate the pipeline uses:
status open + user_permission == "forecaster").
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .metaculus import MetaculusClient, Question

MAX_FOLDS_OUTCOMES = 5


def classify(q: Question) -> str:
    if q.type == "binary":
        return "answerable_now"
    if q.type == "multiple_choice":
        n = len(q.options or [])
        return "answerable_now" if 2 <= n <= MAX_FOLDS_OUTCOMES else "needs_grouping"
    if q.type in ("numeric", "discrete"):
        return "needs_bin_designer"
    return "unsupported"


GENERAL_FEED = "(general feed — no tournament)"


@dataclass
class ScanReport:
    total: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    by_bucket: dict[str, int] = field(default_factory=dict)
    by_competition: dict[str, int] = field(default_factory=dict)   # slug -> answerable count
    competition_names: dict[str, str] = field(default_factory=dict)  # slug -> display name
    questions: list[Question] = field(default_factory=list)  # populated only if keep=True

    @property
    def answerable_now(self) -> int:
        return self.by_bucket.get("answerable_now", 0)

    def competitions(self) -> list[tuple[str, str, int]]:
        """(slug, name, answerable_question_count) sorted by count desc."""
        return sorted(
            ((s, self.competition_names.get(s, s), n) for s, n in self.by_competition.items()),
            key=lambda x: -x[2])


def scan(
    mc: MetaculusClient,
    *,
    tournaments: str | int | None = None,
    min_days_to_close: float | None = None,
    skip_already_forecast: bool = False,
    keep: bool = False,
    max_questions: int | None = None,
) -> ScanReport:
    """Enumerate answerable open questions and tally them by type + bucket.

    min_days_to_close: drop questions closing sooner than this many days
    (e.g. 7 to avoid near-expiry questions). keep: also return the Question list.
    """
    now = datetime.now(timezone.utc)
    by_type: Counter[str] = Counter()
    by_bucket: Counter[str] = Counter()
    by_comp: Counter[str] = Counter()
    comp_names: dict[str, str] = {}
    kept: list[Question] = []

    for q in mc.iter_open_questions(
        tournaments=tournaments, forecastable_only=True,
        skip_already_forecast=skip_already_forecast,
        page_size=100, max_questions=max_questions,
    ):
        if min_days_to_close is not None:
            ct = (q.raw.get("question") or {}).get("scheduled_close_time")
            if ct:
                close = datetime.fromisoformat(ct.replace("Z", "+00:00"))
                if (close - now) < timedelta(days=min_days_to_close):
                    continue
        by_type[q.type] += 1
        by_bucket[classify(q)] += 1
        if q.tournaments:
            for t in q.tournaments:
                slug = t.get("slug") or str(t.get("id"))
                by_comp[slug] += 1
                if t.get("name"):
                    comp_names[slug] = t["name"]
        else:
            by_comp[GENERAL_FEED] += 1
        if keep:
            kept.append(q)

    return ScanReport(total=sum(by_type.values()), by_type=dict(by_type),
                      by_bucket=dict(by_bucket), by_competition=dict(by_comp),
                      competition_names=comp_names, questions=kept)
