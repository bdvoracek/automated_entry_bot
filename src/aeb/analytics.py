"""Cost-vs-quality analytics over the exploration data.

Backend-agnostic: computes entirely in Python over records pulled through the
Repository, so it works identically over SQLite now and Cosmos later.

Quality = Brier score of a tier's midpoint against the Metaculus resolution
(lower is better). Cost = credits spent on that tier's models. Together they
answer "how cost-effective is each tier?".
"""
from __future__ import annotations

from statistics import mean

from . import aggregate
from .data import ModelRun, Question, Repository, Resolution

TIERS = ("Overview", "Insight", "Advanced")


def _tier_runs(repo: Repository, qid: int, tier: str) -> list[ModelRun]:
    return [r for r in repo.load_all(ModelRun, question_id=qid)
            if r.tier == tier and r.status == "succeeded" and r.outcomes]


def tier_midpoint(runs: list[ModelRun]) -> dict[str, float]:
    return aggregate.aggregate_outcomes([r.outcomes for r in runs]) if runs else {}


def tier_cost(repo: Repository, qid: int, tier: str) -> float:
    return round(sum((r.cost_credits or 0) for r in repo.load_all(ModelRun, question_id=qid)
                     if r.tier == tier), 4)


def brier(qtype: str, agg: dict[str, float], resolution_value, options=None) -> float | None:
    """Brier score of a categorical prediction vs the resolved outcome."""
    if resolution_value is None or not agg:
        return None
    rv = str(resolution_value).strip().lower()
    if qtype == "binary":
        if rv in ("yes", "1", "true"):
            outcome = 1.0
        elif rv in ("no", "0", "false"):
            outcome = 0.0
        else:
            return None
        return round((agg.get("Yes", 0.0) - outcome) ** 2, 5)
    if qtype == "multiple_choice":
        labels = options or list(agg.keys())
        return round(sum((agg.get(l, 0.0) - (1.0 if str(l).lower() == rv else 0.0)) ** 2
                         for l in labels), 5)
    return None  # numeric/discrete need CRPS — deferred


def cost_quality(repo: Repository) -> tuple[list[dict], dict[str, dict]]:
    """Return (per (question,tier) rows, per-tier summary)."""
    rows: list[dict] = []
    for qdoc in repo.all(Question.COLLECTION):
        q = Question.from_doc(qdoc)
        rdoc = repo.get(Resolution.COLLECTION, f"res:{q.question_id}")
        res = Resolution.from_doc(rdoc) if rdoc else None
        for tier in TIERS:
            runs = _tier_runs(repo, q.question_id, tier)
            if not runs:
                continue
            agg = tier_midpoint(runs)
            b = (brier(q.type, agg, res.resolution_value, q.options)
                 if res and res.resolved else None)
            rows.append({"question_id": q.question_id, "qtype": q.type, "tier": tier,
                         "cost": tier_cost(repo, q.question_id, tier), "n": len(runs),
                         "brier": b})
    summary: dict[str, dict] = {}
    for tier in TIERS:
        trows = [r for r in rows if r["tier"] == tier]
        briers = [r["brier"] for r in trows if r["brier"] is not None]
        costs = [r["cost"] for r in trows]
        summary[tier] = {
            "questions": len(trows),
            "avg_cost": round(mean(costs), 3) if costs else None,
            "avg_brier": round(mean(briers), 4) if briers else None,
            "scored": len(briers),
        }
    return rows, summary
