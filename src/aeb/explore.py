"""Systematic 51Folds behaviour exploration.

Every question is spooled up against ALL tiers x N runs (default 3 x 10 = 30
models), every model's prediction is stored, and the surface tier's midpoint
(Advanced by default) is entered into Metaculus. Per-tier credit cost is
captured from the balance delta so cost-vs-quality analytics is possible.

State goes through the generic Repository, so the backend (SQLite now, Cosmos
later) is swappable without touching this engine.
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import aggregate, sanity
from .cdf import Scaling, bins_to_cdf
from .data import BinDesign, ModelRun, Question, Repository, SurfacedPrediction
from .folds import FoldsClient
from .metaculus import MetaculusClient
from .metaculus import Question as MetaQuestion

TIERS = ("Overview", "Insight", "Advanced")
SURFACE_TIER = "Advanced"          # the "large" tier whose midpoint we enter for now
RUNS_PER_TIER = 10


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ExploreEngine:
    def __init__(
        self,
        mc: MetaculusClient,
        folds: FoldsClient,
        repo: Repository,
        *,
        tiers: tuple[str, ...] = TIERS,
        runs_per_tier: int = RUNS_PER_TIER,
        surface_tier: str = SURFACE_TIER,
        dry_run: bool = True,
        stale_after_min: float = 45.0,
        min_quorum: int = 6,
    ):
        self.mc = mc
        self.folds = folds
        self.repo = repo
        self.tiers = tiers
        self.runs_per_tier = runs_per_tier
        self.surface_tier = surface_tier
        self.dry_run = dry_run
        # a model still "running" past this age is treated as hung (excluded);
        # a tier surfaces once no run is pending and >= min_quorum succeeded.
        self.stale_after_min = stale_after_min
        self.min_quorum = min_quorum

    def _log(self, msg: str) -> None:
        print(f"[explore] {msg}", flush=True)

    # -- persistence helpers ------------------------------------------------
    def _persist_question(self, q: MetaQuestion) -> Question:
        qraw = q.raw.get("question") or {}
        ent = Question(
            question_id=q.question_id, post_id=q.post_id, type=q.type, title=q.title,
            unit=qraw.get("unit") or "", scaling=q.scaling, options=q.options,
            open_lower_bound=q.open_lower_bound, open_upper_bound=q.open_upper_bound,
            close_time=qraw.get("scheduled_close_time"),
            resolve_time=qraw.get("scheduled_resolve_time"),
            resolution_criteria=(qraw.get("resolution_criteria") or "")[:500],
            first_seen=_now(),
        )
        if self.repo.get(Question.COLLECTION, ent.id) is None:
            self.repo.save(ent)
        return ent

    def _outcomes_for(self, q: MetaQuestion, bin_design: BinDesign | None) -> list[str]:
        if q.type == "binary":
            return ["Yes", "No"]
        if q.type == "multiple_choice":
            return list(q.options or [])
        if q.type in ("numeric", "discrete"):
            if bin_design is None:
                raise ValueError(f"numeric q{q.question_id} needs a bin_design (Continuous Distribution Agent)")
            return list(bin_design.labels)
        raise ValueError(f"unsupported type {q.type}")

    # -- phase 1: fan out 30 models ----------------------------------------
    def explore(self, q: MetaQuestion, *, bin_design: BinDesign | None = None,
                context: str = "") -> list[ModelRun]:
        """Dispatch all tiers x runs_per_tier for one question. Non-blocking."""
        self._persist_question(q)
        labels = self._outcomes_for(q, bin_design)
        if bin_design is not None:
            bin_design.created_at = bin_design.created_at or _now()
            self.repo.save(bin_design)
            context = context or bin_design.source_context

        created: list[ModelRun] = []
        for tier in self.tiers:
            before = self.folds.credits()
            mids = self.folds.dispatch_ensemble(
                q.title, labels, n=self.runs_per_tier, model_type=tier,
                additional_context=context or None)
            after = self.folds.credits()
            cost_per = round((before - after) / max(1, len(mids)), 4)
            for idx, mid in enumerate(mids):
                run = ModelRun(question_id=q.question_id, tier=tier, run_index=idx,
                               folds_model_id=mid, labels=labels, status="pending",
                               cost_credits=cost_per, created_at=_now())
                self.repo.save(run)
                created.append(run)
            self._log(f"q{q.question_id} tier={tier}: {len(mids)} models, ~{cost_per} credits each")
        return created

    # -- phase 2: poll + surface -------------------------------------------
    def _is_stale(self, run: ModelRun) -> bool:
        if not run.created_at:
            return False
        try:
            created = datetime.fromisoformat(run.created_at)
        except ValueError:
            return False
        age_min = (datetime.now(timezone.utc) - created).total_seconds() / 60
        return age_min > self.stale_after_min

    def collect(self) -> list[SurfacedPrediction]:
        """Poll pending runs, store outcomes, and surface the tier midpoint.

        A run still 'running' past stale_after_min is marked 'stale' so a hung
        51Folds model can't block surfacing indefinitely.
        """
        for run in self.repo.load_all(ModelRun, status="pending"):
            m = self.folds.get_model(run.folds_model_id)
            if m.status in ("succeeded", "failed"):
                run.status = m.status
                run.outcomes = m.outcomes
                run.completed_at = _now()
                self.repo.save(run)
            elif self._is_stale(run):
                run.status = "stale"
                run.completed_at = _now()
                self.repo.save(run)
                self._log(f"model {run.folds_model_id} q{run.question_id} {run.tier} "
                          f"marked STALE (>{self.stale_after_min:.0f}min running)")

        surfaced: list[SurfacedPrediction] = []
        qids = {r.question_id for r in self.repo.load_all(ModelRun)}
        for qid in qids:
            if self.repo.get(SurfacedPrediction.COLLECTION, f"pred:{qid}:{self.surface_tier}"):
                continue  # already surfaced
            tier_runs = [r for r in self.repo.load_all(ModelRun, question_id=qid)
                         if r.tier == self.surface_tier]
            if not tier_runs or any(r.status == "pending" for r in tier_runs):
                continue  # surface tier still has live (non-stale) models building
            good = [r for r in tier_runs if r.status == "succeeded" and r.outcomes]
            if len(good) < self.min_quorum:
                self._log(f"q{qid}: only {len(good)} succeeded (< quorum {self.min_quorum}); not surfaced")
                continue
            sp = self._surface(qid, good)
            if sp:
                surfaced.append(sp)
        return surfaced

    def _surface(self, qid: int, runs: list[ModelRun]) -> SurfacedPrediction | None:
        qent = Question.from_doc(self.repo.get(Question.COLLECTION, f"q:{qid}"))
        agg = aggregate.aggregate_outcomes([r.outcomes for r in runs])
        payload: dict = {}
        if qent.type == "binary":
            p = agg["Yes"]
            payload = {"probability_yes": round(p, 5)}
            resp = self.mc.submit_binary(qent.question_id, p, dry_run=self.dry_run)
        elif qent.type == "multiple_choice":
            payload = {"per_category": agg}
            resp = self.mc.submit_multiple_choice(qent.question_id, agg, dry_run=self.dry_run)
        else:  # numeric / discrete
            bd = BinDesign.from_doc(self.repo.get(BinDesign.COLLECTION, f"bins:{qid}"))
            scaling = Scaling(**bd.scaling)
            masses = [agg[lab] for lab in bd.labels]
            cdf = bins_to_cdf(bd.edges, masses, scaling)
            viols = sanity.preflight_cdf(cdf, scaling, qid, qent.type)
            if not sanity.commit_gate(viols):
                self._log(f"q{qid}: FATAL preflight, not surfaced")
                return None
            payload = {"continuous_cdf": cdf}
            resp = self.mc.submit_numeric(qent.question_id, cdf, dry_run=self.dry_run)
        sp = SurfacedPrediction(
            question_id=qid, post_id=qent.post_id, qtype=qent.type,
            tier_used=self.surface_tier, method="(mean+median)/2",
            aggregate={k: round(v, 5) for k, v in agg.items()}, payload=payload,
            dry_run=self.dry_run, metaculus_response=resp, submitted_at=_now())
        self.repo.save(sp)
        mode = "STAGED" if self.dry_run else "SURFACED"
        self._log(f"q{qid} [{qent.type}] {mode} {self.surface_tier} midpoint from {len(runs)} runs")
        return sp
