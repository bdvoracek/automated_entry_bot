"""Dump every model's driver catalogue for a job — raw material for the
semantic-unification and directionality passes.

Emits one JSON doc: per model, the drivers in influence order (rank 0 = most
influential) with the current baseline state and the Negligible/Extreme pole
descriptors that directionality reads.

  python scripts/dump_drivers.py state/amzn_job.json            # summary to stdout
  python scripts/dump_drivers.py state/amzn_job.json --json     # full doc to stdout
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aeb.folds import FoldsClient  # noqa: E402


def _descriptors(cat_entry: dict) -> dict[str, str]:
    """Pull the pole descriptors out of a catalogue entry (shape varies)."""
    sd = cat_entry.get("stateDescriptors") or cat_entry.get("statedescriptors") or []
    out: dict[str, str] = {}
    if isinstance(sd, dict):
        items = sd.items()
    else:
        # live shape: [{"name": "Negligent"|"Low"|..., "description": "..."}]
        items = [(d.get("name") or d.get("state"), d.get("description") or d.get("descriptor"))
                 for d in sd if isinstance(d, dict)]
    for state, desc in items:
        if state and desc:
            out[str(state).strip().capitalize()] = str(desc)
    return out


def collect(job: dict) -> dict:
    fc = FoldsClient()
    doc: dict = {"question_id": job["id"], "tier": job["tier"], "models": {}}
    for mid in job["model_ids"]:
        m = fc.get_model(mid)
        by_code = {c.get("code"): c for c in (m.drivers or [])}
        rows = []
        order = m.driver_order or list(by_code)
        for rank, code in enumerate(order):
            cat = by_code.get(code, {})
            d = _descriptors(cat)
            rows.append({
                "code": code,
                "name": cat.get("name") or cat.get("driver") or code,
                "baseline": (m.driver_states or {}).get(code),
                "rank": rank,
                "n_drivers": len(order),
                "points": len(order) - rank,
                "neg": d.get("Negligible") or d.get("Negligent") or "",
                "ext": d.get("Extreme") or "",
            })
        doc["models"][mid] = {"status": m.status, "outcomes": m.outcomes, "drivers": rows}
    return doc


def main(argv: list[str]) -> None:
    if not argv:
        print(__doc__)
        return
    path = Path(argv[0])
    if not path.is_absolute():
        path = ROOT / path
    job = json.loads(path.read_text())
    doc = collect(job)
    out = ROOT / "state" / f"drivers_{job['id']}.json"
    out.write_text(json.dumps(doc, indent=2) + "\n")
    if "--json" in argv:
        print(json.dumps(doc, indent=2))
    else:
        for mid, m in doc["models"].items():
            print(f"{mid} [{m['status']}] {len(m['drivers'])} drivers")
            for d in m["drivers"]:
                print(f"   {d['rank']:>2} {d['code']:<8} {d['name'][:48]:<48} {d['baseline']}")
    print(f"\nwrote {out}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1:])
