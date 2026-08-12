"""Dispatch a bespoke (non-Metaculus) 5-bin question as an N-model 51Folds ensemble.

Reads a job file (state/<key>_job.json) holding the question text, the 5 designed
bin labels, the tier and the additionalContext, fires N creates (fast 202s; the
~30min builds then run concurrently server-side), and writes the returned model
ids back into the job file. Idempotent by refusal: re-running on a job that
already has model_ids is a no-op unless --force.

  python scripts/dispatch_job.py state/amzn_job.json            # dry run
  python scripts/dispatch_job.py state/amzn_job.json --live     # actually create
  python scripts/dispatch_job.py state/amzn_job.json --status   # poll build state
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aeb.folds import FoldsClient  # noqa: E402

N_MODELS = 10


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _save(path: Path, job: dict) -> None:
    path.write_text(json.dumps(job, indent=2) + "\n")


def cmd_status(job: dict) -> None:
    fc = FoldsClient()
    ids = job.get("model_ids") or []
    if not ids:
        print("no model_ids yet — dispatch first")
        return
    counts: dict[str, int] = {}
    for mid in ids:
        m = fc.get_model(mid)
        counts[m.status] = counts.get(m.status, 0) + 1
        outc = f"  {len(m.outcomes)} outcomes" if m.outcomes else ""
        print(f"  {mid:<6} {m.status:<12}{outc}")
    print("  " + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))


def cmd_dispatch(path: Path, job: dict, live: bool, force: bool) -> None:
    if job.get("model_ids") and not force:
        raise SystemExit(f"{path.name} already has {len(job['model_ids'])} model_ids "
                         f"(use --force to dispatch another batch)")
    print(f"question : {job['question']}")
    print(f"tier     : {job['tier']}   models: {N_MODELS}")
    print(f"outcomes : {job['outcomes']}")
    print(f"context  : {(job.get('additional_context') or '')[:160]}...")
    if not live:
        print("\n--live not passed; nothing created.")
        return
    fc = FoldsClient()
    ids = fc.dispatch_ensemble(
        job["question"], job["outcomes"], n=N_MODELS,
        model_type=job["tier"], additional_context=job.get("additional_context") or "",
    )
    job["model_ids"] = ids
    _save(path, job)
    print(f"\ncreated {len(ids)} models: {ids}\nwritten to {path}")


def main(argv: list[str]) -> None:
    if not argv:
        print(__doc__)
        return
    path = Path(argv[0])
    if not path.is_absolute():
        path = ROOT / path
    job = _load(path)
    if "--status" in argv:
        cmd_status(job)
    else:
        cmd_dispatch(path, job, live="--live" in argv, force="--force" in argv)


if __name__ == "__main__":
    main(sys.argv[1:])
