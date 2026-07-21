"""Programmatic pre-submit sanity layer.

Consolidates the scattered checks (readiness, CDF validity, approximation
warnings) into severity-tagged violations:

  - FATAL  -> block the submission for that question
  - WARN   -> record to a persistent watch-list and PROCEED (non-fatal)

This mirrors a "recorded N violations; committed fine" workflow and is the
shape a detached standalone app needs: automated gating with an auditable
watch-list rather than a human reading log lines.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from . import config
from .cdf import Scaling, validate_cdf

FATAL = "FATAL"
WARN = "WARN"

WATCHLIST_PATH = config.REPO_ROOT / "state" / "violations.json"


@dataclass
class Violation:
    severity: str            # FATAL | WARN
    code: str                # short machine code, e.g. "cdf-invalid"
    message: str
    question_id: int | None = None


class WatchList:
    """Persistent, deduped store of recorded (non-fatal) violations."""

    def __init__(self, path: Path = WATCHLIST_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.items: list[Violation] = []
        if self.path.exists():
            self.items = [Violation(**d) for d in json.loads(self.path.read_text() or "[]")]

    def record(self, v: Violation) -> bool:
        """Add if not already on the list (by code+question). Returns True if new."""
        key = (v.code, v.question_id)
        if any((x.code, x.question_id) == key for x in self.items):
            return False
        self.items.append(v)
        self.path.write_text(json.dumps([asdict(i) for i in self.items], indent=2))
        return True


def preflight_cdf(cdf: list[float], scaling: Scaling,
                  question_id: int | None = None, qtype: str | None = None) -> list[Violation]:
    """Run all programmatic checks for a numeric/discrete submission."""
    v: list[Violation] = []
    try:
        validate_cdf(cdf, scaling)
    except Exception as e:  # monotonicity / bounds / step / length
        v.append(Violation(FATAL, "cdf-invalid", str(e), question_id))
    if qtype == "discrete" and (scaling.cdf_size - 1) > 5:
        v.append(Violation(
            WARN, "discrete-approx",
            f"{scaling.cdf_size - 1} integer outcomes approximated by 5-bin design",
            question_id))
    if scaling.open_lower_bound or scaling.open_upper_bound:
        v.append(Violation(WARN, "open-bound-tail",
                           "open bound(s): tail mass placed beyond range", question_id))
    return v


def commit_gate(violations: list[Violation], watchlist: WatchList | None = None) -> bool:
    """Record WARNs to the watch-list; return True if safe to commit (no FATAL)."""
    wl = watchlist or WatchList()
    for v in violations:
        if v.severity == WARN:
            wl.record(v)
    return not any(v.severity == FATAL for v in violations)
