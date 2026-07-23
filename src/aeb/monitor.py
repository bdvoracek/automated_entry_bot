"""Monitor Metaculus for newly-opened questions, per tournament.

Some bot tournaments open a question for only ~1 hour, so detection has to be
fast and cheap. Two ideas do the work:

  - Recency sort. We ask the API for newest-open-first (config.MONITOR_ORDER_BY)
    instead of -hotness, so a brand-new question is on page 1 rather than buried
    behind hundreds of hotter ones.
  - Per-tournament watermark. We remember the newest open_time we have already
    seen for each tournament and stop scanning as soon as we cross back below it,
    so a tick is normally a single API call that returns only what is new.

The watermark is an *efficiency* layer, not a correctness gate: actually acting
on a question still runs through the orchestrator's jobstore dedup and the
already-forecast check, so a mis-set watermark can never cause a double submit,
only a little extra scanning. State is a small JSON file (stdlib-only), swappable
for the data-layer Repository later like the rest of the pipeline.
"""
from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from . import config
from .metaculus import MetaculusClient, Question

DEFAULT_PATH = config.REPO_ROOT / "state" / "monitor.json"
WHOLE_SITE = "__site__"          # watermark key when no tournament filter is used
SEEN_IDS_CAP = 500               # bound the fallback dedup ring per key


def _parse_time(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


def _key(tournament: str | int | None) -> str:
    return WHOLE_SITE if tournament is None else str(tournament)


@dataclass
class _Mark:
    """Per-tournament watermark: newest open_time seen + a ring of recent ids."""
    high_open_time: str | None = None
    seen_ids: deque[int] = field(default_factory=lambda: deque(maxlen=SEEN_IDS_CAP))

    def to_doc(self) -> dict[str, Any]:
        return {"high_open_time": self.high_open_time, "seen_ids": list(self.seen_ids)}

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> "_Mark":
        return cls(high_open_time=doc.get("high_open_time"),
                   seen_ids=deque(doc.get("seen_ids", []), maxlen=SEEN_IDS_CAP))


class WatermarkStore:
    """Persistent per-tournament high-watermarks (JSON file)."""

    def __init__(self, path: Path = DEFAULT_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.marks: dict[str, _Mark] = {}
        if self.path.exists():
            raw = json.loads(self.path.read_text() or "{}")
            self.marks = {k: _Mark.from_doc(v) for k, v in raw.items()}

    def get(self, key: str) -> _Mark:
        return self.marks.setdefault(key, _Mark())

    def save(self) -> None:
        self.path.write_text(json.dumps(
            {k: m.to_doc() for k, m in self.marks.items()}, indent=2))


class Monitor:
    """Detect newly-opened, forecastable questions per tournament."""

    def __init__(
        self,
        mc: MetaculusClient,
        store: WatermarkStore | None = None,
        *,
        order_by: str = config.MONITOR_ORDER_BY,
        max_questions: int = config.MONITOR_MAX_QUESTIONS,
        log: Callable[[str], None] | None = None,
    ):
        self.mc = mc
        self.store = store if store is not None else WatermarkStore()
        self.order_by = order_by
        self.max_questions = max_questions
        self._log = log or (lambda m: print(f"[monitor] {m}", flush=True))

    def poll(self, tournament: str | int | None = None, *, backfill: bool = False) -> list[Question]:
        """Return forecastable questions newly opened since the last poll.

        Cold start (no watermark yet): unless backfill=True, record the current
        frontier and return nothing, so we do not flood-dispatch the whole
        existing backlog on first run -- we only act on questions that open from
        now on.
        """
        key = _key(tournament)
        mark = self.store.get(key)
        cold = mark.high_open_time is None and not mark.seen_ids
        cutoff = _parse_time(mark.high_open_time)

        new: list[Question] = []
        newest_seen = cutoff
        # Walk newest-first over ALL open questions (unfiltered) so the early-stop
        # sees every open_time; we apply the forecastable filter ourselves.
        for q in self.mc.iter_open_questions(
            tournaments=tournament, order_by=self.order_by,
            forecastable_only=False, skip_already_forecast=False,
            page_size=100, max_questions=self.max_questions,
        ):
            ot = _parse_time(q.open_time)
            # Early stop: recency-sorted, so once we drop to/under the watermark
            # everything after is older too. (Only when we can trust the ordering.)
            if cutoff is not None and ot is not None and ot <= cutoff:
                break
            if newest_seen is None or (ot is not None and ot > newest_seen):
                newest_seen = ot
            already = q.post_id in mark.seen_ids
            if q.can_forecast and not q.already_forecast and not already:
                if not (cold and not backfill):
                    new.append(q)
            mark.seen_ids.append(q.post_id)

        if newest_seen is not None:
            iso = newest_seen.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            if mark.high_open_time is None or iso > mark.high_open_time:
                mark.high_open_time = iso
        self.store.save()

        if cold and not backfill:
            self._log(f"{key}: cold start, frontier set to {mark.high_open_time}; "
                      "watching for questions opening from now")
        elif new:
            self._log(f"{key}: {len(new)} new question(s): "
                      + ", ".join(f"q{q.question_id}" for q in new))
        return new

    def poll_all(self, tournaments: Iterable[str | int | None],
                 *, backfill: bool = False) -> list[Question]:
        """Poll several tournaments in one tick; flatten the new questions."""
        found: list[Question] = []
        for t in tournaments:
            found.extend(self.poll(t, backfill=backfill))
        return found
