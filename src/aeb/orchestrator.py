"""Orchestrator: discover -> predict (51Folds) -> aggregate -> submit.

Flow per question:
  binary          -> outcomes [Yes, No]        -> aggregate -> probability_yes
  multiple_choice -> outcomes = options (<=5)   -> aggregate -> per_category
  numeric/discrete-> readiness gate -> design 5 bins (LLM, constrained to axis)
                     -> 5-category ensemble -> aggregate bins -> 201-pt CDF

Submission is FULLY AUTOMATED by design; pass dry_run=True to stage without
posting (recommended until 51Folds + bin designer are wired and validated).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dataclasses import asdict

from . import aggregate, bins, readiness, sanity
from .cdf import Scaling, bins_to_cdf
from .folds import FoldsClient
from .jobstore import Job, JobStore
from .metaculus import MetaculusClient, Question


def _round(d: dict[str, float]) -> dict[str, float]:
    return {k: round(v, 4) for k, v in d.items()}


@dataclass
class Result:
    post_id: int
    question_id: int
    type: str
    action: str                       # "submitted" | "dry_run" | "skipped" | "error"
    detail: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


class Orchestrator:
    def __init__(
        self,
        metaculus: MetaculusClient,
        folds: FoldsClient | None = None,
        *,
        bin_designer: bins.LLMRunner | None = None,
        dry_run: bool = True,
        store: JobStore | None = None,
        enabled_types: tuple[str, ...] = ("binary", "multiple_choice"),
    ):
        self.mc = metaculus
        self.folds = folds
        self.bin_designer = bin_designer
        self.dry_run = dry_run
        self.store = store if store is not None else JobStore()
        # numeric/discrete (the CDF path) is deferred until last — off by default.
        self.enabled_types = enabled_types

    def _log(self, msg: str) -> None:
        print(f"[aeb] {msg}", flush=True)

    # -- per-type handling --------------------------------------------------
    def _binary(self, q: Question) -> Result:
        runs = self.folds.run_ensemble(q.title, ["Yes", "No"])
        agg = aggregate.aggregate_outcomes(runs)          # {Yes, No} normalized
        p_yes = agg["Yes"]
        resp = self.mc.submit_binary(q.question_id, p_yes, dry_run=self.dry_run)
        return self._result(q, resp, {"probability_yes": p_yes})

    def _multiple_choice(self, q: Question) -> Result:
        options = q.options or []
        runs = self.folds.run_ensemble(q.title, options)
        agg = aggregate.aggregate_outcomes(runs)          # per-option normalized
        resp = self.mc.submit_multiple_choice(q.question_id, agg, dry_run=self.dry_run)
        return self._result(q, resp, {"per_category": agg})

    def _numeric(self, q: Question) -> Result:
        scaling = readiness.scaling_for(q)
        anchor = None
        if q.community_centers:  # opportunistic; usually None for bot accounts
            anchor = q.community_centers[0]
        spec = bins.design_bins(q.title, scaling, llm=self.bin_designer, community_anchor=anchor)
        runs = self.folds.run_ensemble(q.title, spec.labels, additional_context=spec.source_context)
        agg = aggregate.aggregate_outcomes(runs)          # {bin_label: prob}
        masses = [agg[lab] for lab in spec.labels]
        cdf = bins_to_cdf(spec.edges, masses, scaling)
        viols = sanity.preflight_cdf(cdf, scaling, q.question_id, q.type)
        if not sanity.commit_gate(viols):
            fatal = "; ".join(v.message for v in viols if v.severity == sanity.FATAL)
            raise ValueError(f"preflight FATAL: {fatal}")
        resp = self.mc.submit_numeric(q.question_id, cdf, dry_run=self.dry_run)
        return self._result(q, resp, {"bins": spec.labels, "masses": masses, "cdf_len": len(cdf)})

    def _result(self, q: Question, resp: dict[str, Any], payload: dict[str, Any]) -> Result:
        action = "dry_run" if resp.get("dry_run") else "submitted"
        return Result(q.post_id, q.question_id, q.type, action, payload=payload)

    def process(self, q: Question) -> Result:
        gate = readiness.check(q)
        if not gate.ok:
            return Result(q.post_id, q.question_id, q.type, "skipped", gate.reason)
        if self.folds is None:
            return Result(q.post_id, q.question_id, q.type, "skipped", "no 51Folds client wired")
        try:
            if q.type == "binary":
                return self._binary(q)
            if q.type == "multiple_choice":
                return self._multiple_choice(q)
            if q.type in ("numeric", "discrete"):
                return self._numeric(q)
            return Result(q.post_id, q.question_id, q.type, "skipped", "unsupported type")
        except NotImplementedError as e:
            return Result(q.post_id, q.question_id, q.type, "skipped", str(e))
        except Exception as e:  # keep the loop resilient
            return Result(q.post_id, q.question_id, q.type, "error", repr(e))

    # -- two-phase async pipeline (handles the ~30-min build latency) -------
    def _labels_for(self, q: Question) -> tuple[list[str], list[float] | None, Scaling | None, str | None]:
        """Return (outcome_labels, edges, scaling, context) for a question."""
        if q.type == "binary":
            return ["Yes", "No"], None, None, None
        if q.type == "multiple_choice":
            return list(q.options or []), None, None, None
        # numeric / discrete: design the 5 bins constrained to the Metaculus axis
        scaling = readiness.scaling_for(q)
        anchor = q.community_centers[0] if q.community_centers else None
        spec = bins.design_bins(q.title, scaling, llm=self.bin_designer, community_anchor=anchor)
        return spec.labels, spec.edges, scaling, spec.source_context

    def dispatch(
        self,
        tournaments: str | int | None = None,
        *,
        limit: int | None = 25,
        skip_already_forecast: bool = True,
    ) -> list[Job]:
        """Phase 1: find questions, fire N models each, persist jobs. Non-blocking."""
        if self.folds is None:
            raise RuntimeError("dispatch requires a 51Folds client")
        created: list[Job] = []
        for q in self.mc.iter_open_questions(
            tournaments=tournaments, max_questions=limit,
            skip_already_forecast=skip_already_forecast,
        ):
            if q.type not in self.enabled_types:
                self._log(f"skip q{q.question_id} [{q.type}] (type deferred)")
                continue
            if self.store.has_open_job_for(q.question_id):
                continue
            gate = readiness.check(q)
            if not gate.ok:
                self._log(f"skip q{q.question_id} [{q.type}] ({gate.reason})")
                continue
            try:
                labels, edges, scaling, ctx = self._labels_for(q)
                model_ids = self.folds.dispatch_ensemble(q.title, labels, additional_context=ctx)
            except NotImplementedError:
                continue  # numeric without a bin designer wired yet
            except Exception as e:
                self._log(f"skip q{q.question_id} [{q.type}] (dispatch error: {e!r})")
                continue
            self._log(f"dispatched q{q.question_id} [{q.type}] "
                      f"{len(model_ids)} models: {q.title[:50]}")
            job = Job(
                question_id=q.question_id, post_id=q.post_id, qtype=q.type,
                labels=labels, model_ids=model_ids, title=q.title,
                edges=edges, scaling=(asdict(scaling) if scaling else None),
            )
            self.store.add(job)
            created.append(job)
        return created

    def collect(self) -> list[Job]:
        """Phase 2: poll pending jobs; when all models are ready, aggregate + submit."""
        if self.folds is None:
            raise RuntimeError("collect requires a 51Folds client")
        finished: list[Job] = []
        for job in self.store.pending():
            state, runs = self.folds.try_collect(job.model_ids)
            if state == "pending":
                continue
            if state == "failed":
                self.store.update(job, status="failed")
                finished.append(job)
                continue
            try:
                agg = aggregate.aggregate_outcomes(runs)
                if job.qtype == "binary":
                    resp = self.mc.submit_binary(job.question_id, agg["Yes"], dry_run=self.dry_run)
                elif job.qtype == "multiple_choice":
                    resp = self.mc.submit_multiple_choice(job.question_id, agg, dry_run=self.dry_run)
                else:  # numeric / discrete
                    scaling = Scaling(**job.scaling)
                    masses = [agg[lab] for lab in job.labels]
                    cdf = bins_to_cdf(job.edges, masses, scaling)
                    viols = sanity.preflight_cdf(cdf, scaling, job.question_id, job.qtype)
                    if not sanity.commit_gate(viols):  # records WARNs, checks FATAL
                        fatal = "; ".join(v.message for v in viols if v.severity == sanity.FATAL)
                        raise ValueError(f"preflight FATAL: {fatal}")
                    warns = [v for v in viols if v.severity == sanity.WARN]
                    if warns:
                        self._log(f"  sanity: {len(warns)} WARN recorded to watch-list "
                                  f"({', '.join(v.code for v in warns)}); committing anyway")
                    resp = self.mc.submit_numeric(job.question_id, cdf, dry_run=self.dry_run)
                self.store.update(job, status="done", result={"agg": agg, "resp": resp})
                mode = "STAGED (dry-run)" if self.dry_run else "SUBMITTED"
                self._log(f"{mode} q{job.question_id} [{job.qtype}] agg={_round(agg)}")
            except Exception as e:
                self.store.update(job, status="error", result={"error": repr(e)})
                self._log(f"ERROR q{job.question_id} [{job.qtype}]: {e!r}")
            finished.append(job)
        return finished

    # -- blocking single-process loop (simple; ok for testing) --------------
    def run(
        self,
        tournaments: str | int | None = None,
        *,
        limit: int | None = 25,
    ) -> list[Result]:
        results: list[Result] = []
        for q in self.mc.iter_open_questions(tournaments=tournaments, max_questions=limit):
            results.append(self.process(q))
        return results
