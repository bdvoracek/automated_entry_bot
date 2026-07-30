"""Interactive Meta Mode UI — local server, multi-question.

Stdlib only. The 51Folds bearer token stays server-side. Serves one or more
"question packs" (e.g. Brent, Gold); the page picks via ?q=<key>.

  GET  /?q=gold          -> the single-page UI
  GET  /api/model?q=...  -> question, unified drivers (+CI/role), outcomes,
                            baseline, CDF, spot, and causal fragments
  POST /api/move?q=...   {deltas:{uid:delta}} -> fan out, poll, adjusted + timings
  POST /api/reset?q=...  -> restore baseline

Run:  python scripts/meta_ui.py   (open http://localhost:8765)
"""
from __future__ import annotations

import json
import sqlite3
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aeb.aggregate import aggregate_outcomes  # noqa: E402
from aeb.cdf import Scaling, bins_to_cdf, location_to_nominal  # noqa: E402
from aeb.meta import MetaEngine, load_mapping  # noqa: E402

DB_PATH = ROOT / "state" / "exploration.db"
HTML_PATH = Path(__file__).with_suffix(".html")
PORT = 8765
STATE = ROOT / "state"


def _scaling(sc: dict) -> Scaling:
    return Scaling(range_min=sc["range_min"], range_max=sc["range_max"],
                   zero_point=sc.get("zero_point"),
                   open_lower_bound=sc.get("open_lower_bound", True),
                   open_upper_bound=sc.get("open_upper_bound", True),
                   cdf_size=sc.get("cdf_size", 201))


def _bins_from_db(qid):
    con = sqlite3.connect(DB_PATH)
    row = con.execute("SELECT doc FROM bin_designs WHERE pk=?", (str(qid),)).fetchone()
    trow = con.execute("SELECT doc FROM questions WHERE pk=?", (str(qid),)).fetchone()
    con.close()
    d = json.loads(row[0])
    title = json.loads(trow[0]).get("title", str(qid)) if trow else str(qid)
    return title, d["labels"], d["edges"], _scaling(d["scaling"])


def _bins_from_job(path):
    j = json.loads(Path(path).read_text())
    return j["question"], j["bin_labels"], j["bin_edges"], _scaling(j["scaling"])


class Pack:
    """Everything the UI needs for one question, plus its own MetaEngine/lock."""

    def __init__(self, key, title, mapping_path, labels, edges, scaling, spot, causal_path):
        self.key, self.title, self.spot = key, title, spot
        self.mp = load_mapping(mapping_path)
        self.engine = MetaEngine(self.mp)
        self.labels, self.edges, self.scaling = labels, edges, scaling
        n = scaling.cdf_size
        self.cdf_x = [round(location_to_nominal(i / (n - 1), scaling), 4) for i in range(n)]
        cj = json.loads(Path(causal_path).read_text()) if Path(causal_path).exists() else {}
        self.fragments = cj.get("fragments", [])
        self.ci = {int(k): v for k, v in cj.get("drivers", {}).items()}
        self.lock = threading.Lock()
        self.baseline: dict = {}
        self.order: list = []

    def capture_baseline(self):
        per = {mid: self.engine.fc.get_model(mid).outcomes for mid in self.mp.models}
        per = {k: v for k, v in per.items() if v}
        self.baseline = aggregate_outcomes(per.values())
        self.order = list(next(iter(per.values())).keys())

    def to_cdf(self, agg):
        # key off the models' actual outcome labels (the API may reformat the
        # ones we submitted, e.g. strip commas), ordered ascending = bin order
        masses = [agg.get(lab, 0.0) for lab in (self.order or self.labels)]
        return [round(x, 6) for x in bins_to_cdf(self.edges, masses, self.scaling)]

    def model_payload(self):
        mp = self.mp
        drivers = []
        for u in mp.sorted_by_weight(descending=True):
            bi = mp.unified_baseline_index(u.uid)
            members = [{"model": mid, "code": m["code"], "name": m["name"],
                        "baseline": m["baseline"], "rank": m.get("rank"),
                        "dir": int(m.get("dir", 0)), "invert": bool(m.get("invert"))}
                       for mid, mems in u.members.items() for m in mems]
            members.sort(key=lambda m: (m["rank"] is None, m["rank"]))
            ci = self.ci.get(u.uid, {})
            drivers.append({
                "uid": u.uid, "name": u.name, "neutral_idx": bi,
                "models_covered": u.models_covered(), "member_count": u.member_count(),
                "members": members, "weight": u.weight(),
                "influence_points": u.influence_points(), "mode_dir": u.mode_dir,
                "ci": ci.get("ci", 0), "role": ci.get("role", "driver"),
                "reach": ci.get("reach", 0), "betweenness": ci.get("betweenness", 0),
            })
        return {
            "key": self.key, "question": self.title, "tier": mp.tier,
            "n_models": len(mp.models), "n_unified": mp.n, "outcomes": self.order,
            "baseline": self.baseline, "drivers": drivers,
            "cdf": self.to_cdf(self.baseline), "cdf_x": self.cdf_x,
            "range": [self.scaling.range_min, self.scaling.range_max],
            "bin_edges": self.edges, "bin_labels": self.order or self.labels,
            "spot": self.spot, "insights": self.fragments,
            "questions": [{"key": k, "title": p.title} for k, p in PACKS.items()],
        }

    def run_move(self, deltas):
        eng = self.engine
        changes = eng.apply(deltas)
        touched = dict(eng._pending)
        t0 = time.time()
        done = {}
        while len(done) < len(touched) and time.time() - t0 < 120:
            time.sleep(3)
            for mid, pre in touched.items():
                if mid in done:
                    continue
                m = eng.fc.get_model(mid)
                if m.status == "succeeded" and m.outcomes and (m.raw or {}).get("updatedAt") != pre:
                    done[mid] = round(time.time() - t0, 1)
        per = {mid: eng.fc.get_model(mid).outcomes for mid in self.mp.models}
        per = {k: v for k, v in per.items() if v}
        adjusted = aggregate_outcomes(per.values()) if per else dict(self.baseline)
        times = list(done.values())
        return {"adjusted": adjusted, "baseline": self.baseline, "per_model": per,
                "cdf": self.to_cdf(adjusted), "cdf_baseline": self.to_cdf(self.baseline),
                "changes": changes,
                "timings": {"n_touched": len(touched), "n_done": len(done),
                            "total_s": round(time.time() - t0, 1),
                            "span": [min(times), max(times)] if times else [0, 0]}}

    def reset(self):
        eng = self.engine
        eng.reset()
        t0 = time.time()
        while eng._pending and time.time() - t0 < 120:
            time.sleep(3)
            if eng.try_collect()[0] == "ready":
                break
        self.capture_baseline()
        return {"baseline": self.baseline, "cdf": self.to_cdf(self.baseline)}


# ---- question registry ------------------------------------------------------
def _build_packs():
    packs = {}
    bt, bl, be, bs = _bins_from_db(44704)
    packs["brent"] = Pack("brent", bt, STATE / "unified_drivers_44704_advanced.json",
                          bl, be, bs, 88, STATE / "causal_44704_advanced.json")
    gt, gl, ge, gs = _bins_from_job(STATE / "gold_job.json")
    packs["gold"] = Pack("gold", gt, STATE / "unified_drivers_gold_advanced.json",
                         gl, ge, gs, 4080, STATE / "causal_gold_advanced.json")
    return packs


PACKS: dict = {}
DEFAULT_Q = "gold"


def _pack(qs):
    return PACKS.get((qs.get("q", [DEFAULT_Q])[0]), PACKS[DEFAULT_Q])


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode(), "application/json")

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/" or u.path.startswith("/index"):
            self._send(200, HTML_PATH.read_bytes(), "text/html; charset=utf-8")
        elif u.path == "/api/model":
            self._json(_pack(parse_qs(u.query)).model_payload())
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        u = urlparse(self.path)
        pack = _pack(parse_qs(u.query))
        n = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)
        if not pack.lock.acquire(blocking=False):
            return self._json({"error": "busy — a recompute is already running"}, 409)
        try:
            if u.path == "/api/move":
                deltas = {int(k): int(v) for k, v in (body.get("deltas") or {}).items()}
                self._json(pack.run_move(deltas))
            elif u.path == "/api/reset":
                self._json(pack.reset())
            else:
                self._json({"error": "unknown endpoint"}, 404)
        except Exception as e:
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)
        finally:
            pack.lock.release()


def main():
    global PACKS
    PACKS = _build_packs()
    for k, p in PACKS.items():
        print(f"capturing baseline: {k} ({len(p.mp.models)} models) ...", flush=True)
        p.capture_baseline()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"\n  ->  http://localhost:{PORT}   questions: {list(PACKS)}\n(Ctrl-C to stop)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
