"""Assemble a unified-driver mapping from a driver dump + a cluster spec.

The semantic unification itself is agent work (see prompts/); this script is the
deterministic assembly step that turns its output into the mapping the Meta Mode
engine loads. It joins each (model, code) member back to its rank/points/baseline
from the dump, then runs aeb.directionality.apply_directions so mode_dir/invert
are computed the same way for every question.

  python scripts/build_mapping.py state/clusters_amzn-max-2029.json state/unified_drivers_amzn_advanced.json

Fails loudly on an unmatched member or an unclustered driver — a silent drop
would quietly remove a driver from every slider that should move it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aeb.directionality import apply_directions  # noqa: E402


def build(spec: dict, dump: dict) -> tuple[dict, dict]:
    models = [m for m, v in dump["models"].items() if v["status"] == "succeeded"]
    index = {(m, d["code"]): d for m in models for d in dump["models"][m]["drivers"]}
    seen: set = set()
    dirs: dict = {}
    unified = []

    for c in spec["clusters"]:
        members: dict = {}
        for entry in c["members"]:
            mid, code = entry[0], entry[1]
            direction = entry[2] if len(entry) > 2 else 1
            if mid not in models:
                continue          # model not finished yet — skip, rebuild later
            row = index.get((mid, code))
            if row is None:
                raise SystemExit(f"uid {c['uid']}: no driver {code!r} in model {mid}")
            if (mid, code) in seen:
                raise SystemExit(f"driver {mid}:{code} appears in more than one cluster")
            seen.add((mid, code))
            dirs[(mid, code)] = direction
            members.setdefault(mid, []).append({
                "code": code, "name": row["name"], "baseline": row["baseline"],
                "rank": row["rank"], "n_drivers": row["n_drivers"], "points": row["points"],
            })
        if members:
            unified.append({"uid": c["uid"], "name": c["name"], "members": members})

    missing = [f"{m}:{c}" for (m, c) in index if (m, c) not in seen]
    if missing:
        raise SystemExit(f"{len(missing)} driver(s) in no cluster: {missing}")

    doc = {"question_id": spec["question_id"], "tier": spec["tier"],
           "n_unified": len(unified), "models": models, "unified": unified}
    return apply_directions(doc, dirs), {"n_members": len(seen), "n_models": len(models)}


def main(argv: list[str]) -> None:
    if len(argv) < 2:
        print(__doc__)
        return
    spec = json.loads(Path(argv[0]).read_text())
    dump = json.loads((ROOT / "state" / f"drivers_{spec['question_id']}.json").read_text())
    doc, stats = build(spec, dump)
    out = Path(argv[1])
    out.write_text(json.dumps(doc, indent=2) + "\n")
    print(f"wrote {out}: {doc['n_unified']} unified drivers over "
          f"{stats['n_members']} members / {stats['n_models']} models")
    for u in doc["unified"]:
        inv = sum(1 for mems in u["members"].values() for m in mems if m["invert"])
        n = sum(len(v) for v in u["members"].values())
        flag = f"  ({inv} inverted)" if inv else ""
        print(f"  {u['uid']:>3}  {u['name']:<42} {len(u['members'])} models "
              f"{n} members  mode_dir={u['mode_dir']:+d}{flag}")


if __name__ == "__main__":
    main(sys.argv[1:])
