"""Persistent job store for the two-phase (dispatch -> collect) pipeline.

Because 51Folds models take ~30 min, we never block: a dispatch tick fires
all N models and records a job; later collect ticks poll until every model in
the job has succeeded, then aggregate + submit and mark the job done.

Backed by a single JSON file (stdlib-only). Swap for sqlite later if needed.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import config

DEFAULT_PATH = config.REPO_ROOT / "state" / "jobs.json"


@dataclass
class Job:
    question_id: int
    post_id: int
    qtype: str                       # binary | multiple_choice | numeric | discrete
    labels: list[str]                # 51Folds outcome labels (Yes/No, options, or bin labels)
    model_ids: list[str]
    status: str = "pending"          # pending | done | failed | error
    # numeric-only extras needed to build the CDF at collect time:
    edges: list[float] | None = None
    scaling: dict[str, Any] | None = None
    # bookkeeping:
    title: str = ""
    result: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.question_id}:{','.join(self.model_ids)}"


class JobStore:
    def __init__(self, path: Path = DEFAULT_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.jobs: list[Job] = []
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            self.jobs = [Job(**d) for d in json.loads(self.path.read_text() or "[]")]

    def save(self) -> None:
        self.path.write_text(json.dumps([asdict(j) for j in self.jobs], indent=2))

    def add(self, job: Job) -> None:
        self.jobs.append(job)
        self.save()

    def pending(self) -> list[Job]:
        return [j for j in self.jobs if j.status == "pending"]

    def has_open_job_for(self, question_id: int) -> bool:
        """True if we already have an unfinished job for this question (dedup)."""
        return any(j.question_id == question_id and j.status == "pending" for j in self.jobs)

    def update(self, job: Job, **changes: Any) -> None:
        for k, v in changes.items():
            setattr(job, k, v)
        self.save()
