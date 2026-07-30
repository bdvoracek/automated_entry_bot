"""Interactive Meta Mode — relative-shift fan-out over a unified-driver layer.

A *unified driver* clusters, per model, that model's own driver(s) that cover one
concept. The clustering is produced by the semantic-unification agent and stored
as JSON (see state/unified_drivers_<qid>_<tier>.json), e.g. every Advanced Brent
model's Hurricane/Hormuz/OPEC/... drivers rolled into N=15 unified drivers.

A *meta setting* is one delta per unified driver in roughly [-4, +4]. Applying it
shifts every member driver up/down from ITS OWN baseline state (clamped to
Negligible..Extreme) — relative shift, not absolute set-all, so the ensemble's
spread is preserved. The full driver set is then PUT to all N models (the API
requires all drivers), which triggers an async recompute; we poll all models and
re-aggregate the adjusted outcome distribution via (mean+median)/2.

Data flow:  load_mapping -> MetaEngine(deltas).apply() -> .collect() -> MetaResult
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import config
from .aggregate import aggregate_outcomes
from .folds import (
    DRIVER_STATES,
    FoldsClient,
    index_to_state,
    state_to_index,
)


@dataclass
class UnifiedDriver:
    uid: int
    name: str
    # model_id -> [{code, name, baseline}]  (a model may have 0, 1 or 2 members)
    members: dict[str, list[dict[str, Any]]]

    def member_count(self) -> int:
        return sum(len(v) for v in self.members.values())

    def models_covered(self) -> int:
        return sum(1 for v in self.members.values() if v)

    def influence_points(self) -> int:
        """Sum of member rank-points, where a member's points = n_drivers - its
        influence position in its model (top-ranked driver scores highest)."""
        return sum(m.get("points", 0) for members in self.members.values() for m in members)

    def weight(self) -> int:
        """Importance weight = influence points x number of models it appears in.
        Rewards drivers that both rank highly within models and recur across them."""
        return self.influence_points() * self.models_covered()


@dataclass
class UnifiedMapping:
    question_id: int
    tier: str
    models: list[str]
    unified: list[UnifiedDriver]

    @property
    def n(self) -> int:
        return len(self.unified)

    def sorted_by_weight(self, descending: bool = True) -> list[UnifiedDriver]:
        """Unified drivers ranked by importance weight (see UnifiedDriver.weight).
        descending=True is 'Most to Least', False is 'Least to Most'."""
        return sorted(self.unified,
                      key=lambda u: (u.weight(), u.influence_points()),
                      reverse=descending)

    def by_uid(self, uid: int) -> UnifiedDriver:
        for u in self.unified:
            if u.uid == uid:
                return u
        raise KeyError(f"no unified driver uid={uid}")

    def uid_for_name(self, name: str) -> int:
        for u in self.unified:
            if u.name.lower() == name.lower():
                return u.uid
        raise KeyError(f"no unified driver named {name!r}")

    def baseline_states(self) -> dict[str, dict[str, str]]:
        """model_id -> {driver_code: baseline_state} across ALL its drivers."""
        out: dict[str, dict[str, str]] = {m: {} for m in self.models}
        for u in self.unified:
            for mid, members in u.members.items():
                for mem in members:
                    out[mid][mem["code"]] = mem["baseline"]
        return out

    def unified_baseline_index(self, uid: int) -> float | None:
        """Mean baseline ordinal across all members of a unified driver (for UI
        neutral position). None if the driver has no members anywhere."""
        idxs = [state_to_index(m["baseline"])
                for members in self.by_uid(uid).members.values()
                for m in members]
        return sum(idxs) / len(idxs) if idxs else None


def load_mapping(path: str | Path) -> UnifiedMapping:
    raw = json.loads(Path(path).read_text())
    unified = [UnifiedDriver(uid=u["uid"], name=u["name"], members=u["members"])
               for u in raw["unified"]]
    return UnifiedMapping(question_id=raw["question_id"], tier=raw["tier"],
                          models=raw["models"], unified=unified)


def resolve_states(
    mapping: UnifiedMapping, deltas: dict[int, int],
) -> tuple[dict[str, dict[str, str]], list[dict[str, Any]]]:
    """Apply per-unified-driver deltas as a relative shift from each member's
    baseline. Returns (model_id -> full {code: state}, change_log).

    A driver not touched by any non-zero delta keeps its baseline state, so the
    resulting dict always contains ALL of a model's drivers (PUT needs them all).
    """
    resolved: dict[str, dict[str, str]] = {m: {} for m in mapping.models}
    changes: list[dict[str, Any]] = []
    for u in mapping.unified:
        delta = int(deltas.get(u.uid, 0))
        for mid, members in u.members.items():
            for mem in members:
                b = state_to_index(mem["baseline"])
                new = index_to_state(b + delta)          # clamps to 0..4
                resolved[mid][mem["code"]] = new
                if new != mem["baseline"]:
                    changes.append({"model": mid, "uid": u.uid, "unified": u.name,
                                    "code": mem["code"], "from": mem["baseline"],
                                    "to": new, "delta": delta})
    return resolved, changes


@dataclass
class MetaResult:
    deltas: dict[int, int]
    adjusted: dict[str, float]            # aggregated adjusted distribution
    per_model: dict[str, dict[str, float]]
    baseline: dict[str, float] | None = None
    changes: list[dict[str, Any]] = field(default_factory=list)

    def diff(self) -> dict[str, float]:
        """Adjusted minus baseline, per outcome label (empty if no baseline)."""
        if not self.baseline:
            return {}
        return {k: self.adjusted[k] - self.baseline.get(k, 0.0) for k in self.adjusted}


class MetaEngine:
    """Fan a meta setting out to all N models and collect the adjusted forecast."""

    def __init__(self, mapping: UnifiedMapping, client: FoldsClient | None = None):
        self.mapping = mapping
        self.fc = client or FoldsClient()
        # Models we PUT in the last apply(), each mapped to its pre-apply
        # updatedAt. collect() treats them as pending until that stamp advances,
        # which avoids reading a stale "succeeded" before the recompute flips in.
        self._pending: dict[str, str | None] = {}

    # -- baseline ----------------------------------------------------------
    def baseline_distribution(self) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
        """Aggregate the current (unmodified) outcomes of all N models. No PUT."""
        per = {}
        for mid in self.mapping.models:
            m = self.fc.get_model(mid)
            if m.outcomes:
                per[mid] = m.outcomes
        return aggregate_outcomes(per.values()), per

    # -- apply -------------------------------------------------------------
    def apply(self, deltas: dict[int, int]) -> list[dict[str, Any]]:
        """PUT the shifted driver states to every model whose target state
        actually differs from what the server currently holds (a no-op PUT is
        rejected 400 "No driver states were changed"). Fires the async recompute;
        poll with collect(). Returns the change log (vs baseline)."""
        resolved, changes = resolve_states(self.mapping, deltas)
        self._pending = {}
        for mid, target in resolved.items():
            m = self.fc.get_model(mid)
            current = m.driver_states or {}
            if all(target.get(c) == current.get(c) for c in target):
                continue  # nothing to change on this model -> would 400
            self.fc.set_drivers(mid, target)
            self._pending[mid] = (m.raw or {}).get("updatedAt")
        return changes

    def reset(self) -> None:
        """Restore every model to its baseline states (skips already-baseline)."""
        self.apply({})

    # -- collect -----------------------------------------------------------
    def try_collect(self) -> tuple[str, dict[str, dict[str, float]]]:
        """Non-blocking. state = 'pending' | 'ready' | 'failed'; runs populated
        only when ready. Mirrors FoldsClient.try_collect semantics."""
        per: dict[str, dict[str, float]] = {}
        pending = False
        for mid in self.mapping.models:
            m = self.fc.get_model(mid)
            # A just-applied model isn't done until its updatedAt advances past
            # the pre-apply stamp AND it's back to succeeded with fresh outcomes.
            if mid in self._pending:
                stale = (m.raw or {}).get("updatedAt") == self._pending[mid]
                if m.status != "succeeded" or not m.outcomes or stale:
                    if m.status == "failed":
                        return "failed", {}
                    pending = True
                    continue
            if m.status == "succeeded":
                if m.outcomes:
                    per[mid] = m.outcomes
                else:
                    pending = True          # succeeded but probs not visible yet
            elif m.status == "failed":
                return "failed", {}
            else:
                pending = True
        return ("pending", {}) if pending else ("ready", per)

    def collect(
        self,
        deltas: dict[int, int],
        *,
        baseline: dict[str, float] | None = None,
        changes: list[dict[str, Any]] | None = None,
        interval: float | None = None,
        timeout: float | None = None,
    ) -> MetaResult:
        """Poll all models until the recompute lands, then aggregate."""
        import time
        interval = interval or config.FOLDS_POLL_INTERVAL_S
        deadline = time.monotonic() + (timeout or config.FOLDS_POLL_TIMEOUT_S)
        while True:
            state, per = self.try_collect()
            if state == "ready":
                return MetaResult(deltas=deltas,
                                  adjusted=aggregate_outcomes(per.values()),
                                  per_model=per, baseline=baseline,
                                  changes=changes or [])
            if state == "failed":
                raise RuntimeError("a model failed during meta recompute")
            if time.monotonic() > deadline:
                raise TimeoutError("meta recompute still pending after timeout")
            time.sleep(interval)

    def move(self, deltas: dict[int, int], *, with_baseline: bool = True) -> MetaResult:
        """Convenience: capture baseline -> apply -> block -> aggregate."""
        base = None
        if with_baseline:
            base, _ = self.baseline_distribution()
        changes = self.apply(deltas)
        return self.collect(deltas, baseline=base, changes=changes)
