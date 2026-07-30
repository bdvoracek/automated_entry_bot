"""51Folds client: create prediction models, poll to completion, aggregate.

Model lifecycle (async):
  POST /models            -> 202, returns modelId[] (needs X-Idempotency-Key)
  GET  /models/{id}       -> status pending|running|succeeded|failed
                             on success: current.outcomes[] = {label, probability}
  POST /models/{id}/retry -> re-enqueue a failed model
  GET  /credits/me        -> remaining credit balance

Outcomes must be 2-5 mutually exclusive labels. For a CDF problem we always
spool up a 5-category model whose outcomes are the designed bins.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from . import config
from .http import request


class FoldsError(RuntimeError):
    pass


# Ordinal driver states, weakest -> strongest. The write API accepts these exact
# strings; the 51Folds UI labels them Min/Low/Med/High/Max (see API docs p.8).
# Note: a model's stateDescriptors sometimes spell the floor "Negligent"; the
# current-state and write paths use "Negligible". We normalize both to the latter.
DRIVER_STATES: tuple[str, ...] = ("Negligible", "Low", "Medium", "High", "Extreme")
_STATE_INDEX = {s.lower(): i for i, s in enumerate(DRIVER_STATES)}
_STATE_INDEX["negligent"] = 0  # tolerate the descriptor spelling on read
UI_STATE_LABELS = {"Negligible": "Min", "Low": "Low", "Medium": "Med",
                   "High": "High", "Extreme": "Max"}


def state_to_index(state: str) -> int:
    """Map a driver state string to its ordinal 0..4 (raises on unknown)."""
    try:
        return _STATE_INDEX[str(state).strip().lower()]
    except KeyError as e:
        raise ValueError(f"unknown driver state {state!r}") from e


def index_to_state(i: int) -> str:
    """Map an ordinal to a canonical state, clamping into range."""
    return DRIVER_STATES[max(0, min(len(DRIVER_STATES) - 1, i))]


@dataclass
class FoldsModel:
    model_id: str
    status: str
    outcomes: dict[str, float]      # label -> probability (when succeeded)
    raw: dict[str, Any]
    drivers: list[dict[str, Any]] = None  # catalogue: [{code, name, stateDescriptors?}]
    driver_states: dict[str, str] = None  # code -> current state (normalized)
    driver_order: list[str] = None        # codes in current.drivers order = influence rank (most->least)


class FoldsClient:
    def __init__(self, token: str | None = None):
        self.token = token or config.FIFTYONEFOLDS_TOKEN
        if not self.token:
            raise RuntimeError("FIFTYONEFOLDS_TOKEN missing (set it in .env)")

    def _hdr(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        h = {"Authorization": f"Bearer {self.token}"}
        if extra:
            h.update(extra)
        return h

    # -- lifecycle ----------------------------------------------------------
    def create_model(
        self,
        question: str,
        outcomes: list[str],
        *,
        model_type: str | None = None,
        additional_context: str | None = None,
        generate_driver_content: bool = False,
        generate_takeaway_content: bool = False,
        idempotency_key: str | None = None,
    ) -> list[str]:
        """Create a model (batch). Returns the model id(s). 202 Accepted."""
        if not 2 <= len(outcomes) <= 5:
            raise ValueError("51Folds requires between 2 and 5 outcomes")
        body: dict[str, Any] = {
            "question": question,
            "outcomes": outcomes,
            "type": model_type or config.FOLDS_MODEL_TYPE,
            "generateDriverContent": generate_driver_content,
            "generateTakeAwayContent": generate_takeaway_content,
            # Live API requires this field even though the docs mark it optional.
            "additionalContext": additional_context or "",
        }
        headers = self._hdr({"X-Idempotency-Key": idempotency_key or str(uuid.uuid4())})
        _, data = request("POST", config.FOLDS_BASE + "/models", headers=headers, json_body=body)
        ids = (data or {}).get("data", {}).get("modelId", [])
        if not ids:
            raise FoldsError(f"create_model returned no modelId: {data}")
        return ids

    def get_model(self, model_id: str) -> FoldsModel:
        _, data = request("GET", config.FOLDS_BASE + f"/models/{model_id}", headers=self._hdr())
        d = (data or {}).get("data", {})
        # Live API returns capitalized status ("Running"/"Succeeded"); normalize.
        status = str(d.get("status", "unknown")).lower()
        # `probability` is only present once succeeded; skip outcomes lacking it.
        current = d.get("current", {}) or {}
        outcomes = {
            o["label"]: float(o["probability"])
            for o in current.get("outcomes", [])
            if o.get("probability") is not None
        }
        catalogue = d.get("drivers") or []
        # current.drivers is ordered by influence (most -> least); its array
        # position is the driver's rank within this model. The catalogue array,
        # by contrast, is alphabetical, so rank must come from current.drivers.
        driver_states: dict[str, str] = {}
        driver_order: list[str] = []
        for c in current.get("drivers", []) or []:
            code, st = c.get("code"), c.get("state")
            if code:
                driver_order.append(code)
                if st is not None:
                    driver_states[code] = index_to_state(state_to_index(st))
        return FoldsModel(model_id=d.get("modelId", model_id), status=status,
                          outcomes=outcomes, raw=d, drivers=catalogue,
                          driver_states=driver_states, driver_order=driver_order)

    def set_drivers(self, model_id: str, states: dict[str, str]) -> str:
        """Set ALL driver states and trigger a recompute. PUT /models/{id}/drivers.

        The API requires every driver in the catalogue to be supplied; a partial
        body 400s ("One or more drivers were not supplied"). Returns the new
        status (202 -> "running"); poll get_model() for the recomputed outcomes.
        """
        body = {"drivers": [{"code": code, "state": index_to_state(state_to_index(st))}
                            for code, st in states.items()]}
        _, data = request("PUT", config.FOLDS_BASE + f"/models/{model_id}/drivers",
                          headers=self._hdr(), json_body=body)
        return str((data or {}).get("data", {}).get("status", "unknown")).lower()

    def retry_model(self, model_id: str) -> None:
        request("POST", config.FOLDS_BASE + f"/models/{model_id}/retry", headers=self._hdr())

    def credits(self) -> float:
        _, data = request("GET", config.FOLDS_BASE + "/credits/me", headers=self._hdr())
        return float((data or {}).get("data", {}).get("amount", 0))

    def poll_until_done(
        self,
        model_id: str,
        *,
        interval: float | None = None,
        timeout: float | None = None,
        retry_failed: bool = True,
    ) -> FoldsModel:
        """Block until the model succeeds or fails (optionally retry once)."""
        interval = interval or config.FOLDS_POLL_INTERVAL_S
        deadline = time.monotonic() + (timeout or config.FOLDS_POLL_TIMEOUT_S)
        retried = False
        while True:
            m = self.get_model(model_id)
            if m.status == "succeeded":
                return m
            if m.status == "failed":
                if retry_failed and not retried:
                    self.retry_model(model_id)
                    retried = True
                else:
                    return m
            if time.monotonic() > deadline:
                raise TimeoutError(f"model {model_id} still {m.status} after timeout")
            time.sleep(interval)

    def dispatch_ensemble(
        self,
        question: str,
        outcomes: list[str],
        *,
        n: int | None = None,
        model_type: str | None = None,
        additional_context: str | None = None,
    ) -> list[str]:
        """Fire N models concurrently and return their ids WITHOUT polling.

        Each create is a fast 202; the ~30-min builds then run concurrently
        server-side. Use with try_collect() for a non-blocking pipeline.
        """
        n = n or config.FOLDS_RUNS_PER_QUESTION
        model_ids: list[str] = []
        for _ in range(n):
            model_ids.extend(self.create_model(
                question, outcomes, model_type=model_type,
                additional_context=additional_context,
            ))
        return model_ids

    def try_collect(
        self, model_ids: list[str], *, retry_failed: bool = True,
    ) -> tuple[str, list[dict[str, float]]]:
        """Non-blocking check. Returns (state, runs).

        state = "pending" (some still building), "ready" (all succeeded ->
        runs populated), or "failed" (a model failed and can't be retried).
        """
        runs: list[dict[str, float]] = []
        any_pending = False
        for mid in model_ids:
            m = self.get_model(mid)
            if m.status == "succeeded":
                if m.outcomes:
                    runs.append(m.outcomes)
                else:
                    any_pending = True  # succeeded but probabilities not yet visible
            elif m.status == "failed":
                if retry_failed:
                    self.retry_model(mid)
                    any_pending = True
                else:
                    return "failed", []
            else:  # pending / running / unknown
                any_pending = True
        if any_pending:
            return "pending", []
        return "ready", runs

    def run_ensemble(
        self,
        question: str,
        outcomes: list[str],
        *,
        n: int | None = None,
        model_type: str | None = None,
        additional_context: str | None = None,
    ) -> list[dict[str, float]]:
        """Spool up N models on the same question and return each run's outcome map.

        NOTE: uses a distinct idempotency key per run so all N actually execute.
        Concurrency here is sequential-create + poll; a threaded/async version
        can be dropped in without changing callers.
        """
        n = n or config.FOLDS_RUNS_PER_QUESTION
        model_ids: list[str] = []
        for _ in range(n):
            model_ids.extend(self.create_model(
                question, outcomes, model_type=model_type,
                additional_context=additional_context,
            ))
        runs: list[dict[str, float]] = []
        for mid in model_ids:
            m = self.poll_until_done(mid)
            if m.status == "succeeded" and m.outcomes:
                runs.append(m.outcomes)
        if not runs:
            raise FoldsError("no successful 51Folds runs to aggregate")
        return runs
