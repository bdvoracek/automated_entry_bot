"""Interactive Meta Mode UI — local server wiring the dark slider panel to MetaEngine.

Stdlib only (http.server). The 51Folds bearer token stays server-side; the page
talks to these JSON endpoints:

  GET  /                -> the single-page UI (scripts/meta_ui.html)
  GET  /api/model       -> question, unified drivers (+membership), outcomes, baseline
  POST /api/move  {deltas:{uid:delta}}  -> fan out, poll, return adjusted + timings
  POST /api/reset       -> restore all models to baseline

Run:  python scripts/meta_ui.py         (then open http://localhost:8765)
A move mutates model driver states live; Reset (and startup) restore baseline.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aeb.aggregate import aggregate_outcomes  # noqa: E402
from aeb.meta import MetaEngine, load_mapping  # noqa: E402

MAPPING_PATH = ROOT / "state" / "unified_drivers_44704_advanced.json"
DB_PATH = ROOT / "state" / "exploration.db"
HTML_PATH = Path(__file__).with_suffix(".html")
PORT = 8765

mp = load_mapping(MAPPING_PATH)
engine = MetaEngine(mp)
_lock = threading.Lock()          # serialize fan-outs (one recompute at a time)
_baseline: dict[str, float] = {}  # cached true baseline distribution
_outcome_order: list[str] = []


def _question_title() -> str:
    try:
        con = sqlite3.connect(DB_PATH)
        row = con.execute("SELECT doc FROM questions WHERE pk=?", (str(mp.question_id),)).fetchone()
        con.close()
        if row:
            return json.loads(row[0]).get("title", f"q:{mp.question_id}")
    except Exception:
        pass
    return f"q:{mp.question_id}"


def _capture_baseline() -> None:
    global _baseline, _outcome_order
    per = {mid: engine.fc.get_model(mid).outcomes for mid in mp.models}
    per = {k: v for k, v in per.items() if v}
    _baseline = aggregate_outcomes(per.values())
    _outcome_order = list(next(iter(per.values())).keys())


def _model_payload() -> dict:
    drivers = []
    for u in mp.sorted_by_weight(descending=True):   # Most-to-Least by default
        bi = mp.unified_baseline_index(u.uid)
        members = [{"model": mid, "code": m["code"], "name": m["name"],
                    "baseline": m["baseline"], "rank": m.get("rank")}
                   for mid, mems in u.members.items() for m in mems]
        members.sort(key=lambda m: (m["rank"] is None, m["rank"]))  # most influential first
        drivers.append({
            "uid": u.uid, "name": u.name,
            "neutral_idx": bi, "models_covered": u.models_covered(),
            "member_count": u.member_count(), "members": members,
            "weight": u.weight(), "influence_points": u.influence_points(),
        })
    return {
        "question": _question_title(),
        "tier": mp.tier, "n_models": len(mp.models), "n_unified": mp.n,
        "outcomes": _outcome_order, "baseline": _baseline, "drivers": drivers,
    }


def _run_move(deltas: dict[int, int]) -> dict:
    """Fan a meta setting out to all touched models, poll, aggregate. Instrumented
    with per-model recompute times for the UI status line."""
    changes = engine.apply(deltas)                 # GET+PUT only the models that change
    touched = dict(engine._pending)                # {mid: pre_updatedAt}
    t0 = time.time()
    done: dict[str, float] = {}
    while len(done) < len(touched) and time.time() - t0 < 120:
        time.sleep(3)
        for mid, pre in touched.items():
            if mid in done:
                continue
            m = engine.fc.get_model(mid)
            if m.status == "succeeded" and m.outcomes and (m.raw or {}).get("updatedAt") != pre:
                done[mid] = round(time.time() - t0, 1)
    per = {mid: engine.fc.get_model(mid).outcomes for mid in mp.models}
    per = {k: v for k, v in per.items() if v}
    adjusted = aggregate_outcomes(per.values()) if per else dict(_baseline)
    times = list(done.values())
    return {
        "adjusted": adjusted, "baseline": _baseline, "per_model": per,
        "changes": changes,
        "timings": {"n_touched": len(touched), "n_done": len(done),
                    "total_s": round(time.time() - t0, 1),
                    "span": [min(times), max(times)] if times else [0, 0]},
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json")

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            self._send(200, HTML_PATH.read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/model":
            self._json(_model_payload())
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)
        if not _lock.acquire(blocking=False):
            return self._json({"error": "busy — a recompute is already running"}, 409)
        try:
            if self.path == "/api/move":
                deltas = {int(k): int(v) for k, v in (body.get("deltas") or {}).items()}
                self._json(_run_move(deltas))
            elif self.path == "/api/reset":
                engine.reset()
                # poll back to baseline before responding
                t0 = time.time()
                while engine._pending and time.time() - t0 < 120:
                    time.sleep(3)
                    if engine.try_collect()[0] == "ready":
                        break
                _capture_baseline()
                self._json({"baseline": _baseline})
            else:
                self._json({"error": "unknown endpoint"}, 404)
        except Exception as e:  # surface engine/API errors to the UI
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)
        finally:
            _lock.release()


def main() -> None:
    print(f"Meta Mode UI — q:{mp.question_id} [{mp.tier}] {len(mp.models)} models, N={mp.n}")
    print("Capturing baseline distribution ...")
    _capture_baseline()
    print("  baseline:", "  ".join(f"{k}={v*100:.1f}%" for k, v in _baseline.items()))
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"\n  ->  http://localhost:{PORT}\n(Ctrl-C to stop)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
