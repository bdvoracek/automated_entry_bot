"""Document-shaped entities for the systematic-exploration data model.

All entities serialize to plain dicts (documents) via to_doc() and rebuild via
from_doc(), carrying `id` + `_pk` (partition key = question_id) so the same
records work over SQLite now and Cosmos DB later.
"""
from __future__ import annotations

import dataclasses
from dataclasses import asdict, dataclass, field
from typing import Any, ClassVar


@dataclass
class Entity:
    COLLECTION: ClassVar[str] = ""

    @property
    def id(self) -> str:  # pragma: no cover - overridden
        raise NotImplementedError

    @property
    def partition_key(self) -> str:  # pragma: no cover - overridden
        raise NotImplementedError

    def to_doc(self) -> dict[str, Any]:
        d = asdict(self)
        d["id"] = self.id
        d["_pk"] = self.partition_key
        d["_collection"] = self.COLLECTION
        return d

    @classmethod
    def from_doc(cls, doc: dict[str, Any]):
        names = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in doc.items() if k in names})


@dataclass
class Question(Entity):
    COLLECTION: ClassVar[str] = "questions"
    question_id: int
    post_id: int
    type: str
    title: str
    tournament: str | None = None
    unit: str = ""
    scaling: dict[str, Any] | None = None
    options: list[str] | None = None
    open_lower_bound: bool = True
    open_upper_bound: bool = True
    close_time: str | None = None
    resolve_time: str | None = None
    resolution_criteria: str = ""
    first_seen: str | None = None

    @property
    def id(self) -> str:
        return f"q:{self.question_id}"

    @property
    def partition_key(self) -> str:
        return str(self.question_id)


@dataclass
class ModelRun(Entity):
    """One of the 30 models per question (3 tiers x 10 runs). Full granularity."""
    COLLECTION: ClassVar[str] = "model_runs"
    question_id: int
    tier: str                       # Overview | Insight | Advanced
    run_index: int                  # 0..9 within the tier
    folds_model_id: str
    labels: list[str] = field(default_factory=list)
    outcomes: dict[str, float] = field(default_factory=dict)   # label -> prob (when succeeded)
    status: str = "pending"
    cost_credits: float | None = None
    created_at: str | None = None
    completed_at: str | None = None

    @property
    def id(self) -> str:
        return f"run:{self.folds_model_id}"

    @property
    def partition_key(self) -> str:
        return str(self.question_id)


@dataclass
class BinDesign(Entity):
    """The 5-bin design for a numeric/discrete question (from the Continuous
    Distribution Agent), needed to rebuild the CDF at collect time."""
    COLLECTION: ClassVar[str] = "bin_designs"
    question_id: int
    labels: list[str]
    edges: list[float]
    scaling: dict[str, Any]
    anchor: float | None = None
    source_context: str = ""
    created_at: str | None = None

    @property
    def id(self) -> str:
        return f"bins:{self.question_id}"

    @property
    def partition_key(self) -> str:
        return str(self.question_id)


@dataclass
class SurfacedPrediction(Entity):
    """The aggregate actually entered into Metaculus (Advanced-tier midpoint for now)."""
    COLLECTION: ClassVar[str] = "surfaced_predictions"
    question_id: int
    post_id: int
    qtype: str
    tier_used: str
    method: str                     # e.g. "(mean+median)/2"
    aggregate: dict[str, float] = field(default_factory=dict)   # per-label/bin masses
    payload: dict[str, Any] = field(default_factory=dict)       # exact Metaculus payload
    dry_run: bool = True
    metaculus_response: dict[str, Any] | None = None
    submitted_at: str | None = None

    @property
    def id(self) -> str:
        return f"pred:{self.question_id}:{self.tier_used}"

    @property
    def partition_key(self) -> str:
        return str(self.question_id)


@dataclass
class Resolution(Entity):
    """Metaculus's resolution + our bot's score, mapped back to the question."""
    COLLECTION: ClassVar[str] = "resolutions"
    question_id: int
    post_id: int
    resolved: bool = False
    resolution_value: Any = None                 # resolved outcome (string / number)
    resolved_at: str | None = None
    metaculus_score_data: dict[str, Any] | None = None
    checked_at: str | None = None

    @property
    def id(self) -> str:
        return f"res:{self.question_id}"

    @property
    def partition_key(self) -> str:
        return str(self.question_id)
