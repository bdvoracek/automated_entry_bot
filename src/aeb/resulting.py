"""Resulting worker — Metaculus as a free resolution layer.

For every question we surfaced a prediction on, poll Metaculus for its
resolution and our bot's score, and store a Resolution mapped back to the
question. No home-grown resolution engine — the competition resolves for us.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .data import Question, Repository, Resolution, SurfacedPrediction
from .metaculus import MetaculusClient


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ResultingWorker:
    def __init__(self, mc: MetaculusClient, repo: Repository):
        self.mc = mc
        self.repo = repo

    def poll(self) -> list[Resolution]:
        """Check each predicted-on question for resolution; store results."""
        out: list[Resolution] = []
        for qdoc in self.repo.all(Question.COLLECTION):
            qent = Question.from_doc(qdoc)
            # only result questions we actually surfaced a prediction on
            if not self.repo.query(SurfacedPrediction.COLLECTION, question_id=qent.question_id):
                continue
            existing = self.repo.load(Resolution, f"res:{qent.question_id}")
            if existing and existing.resolved:
                continue  # already have a final resolution

            post = self.mc.get_question(qent.post_id)
            if post is None:
                continue
            qraw = post.raw.get("question") or {}
            resolution = qraw.get("resolution")
            resolved = qraw.get("status") == "resolved" or resolution is not None
            score = ((qraw.get("my_forecasts") or {}).get("latest") or {}).get("score_data")

            res = Resolution(
                question_id=qent.question_id, post_id=qent.post_id,
                resolved=bool(resolved), resolution_value=resolution,
                resolved_at=qraw.get("actual_resolve_time"),
                metaculus_score_data=score, checked_at=_now())
            self.repo.save(res)
            out.append(res)
        return out
