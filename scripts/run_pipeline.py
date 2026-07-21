#!/usr/bin/env python3
"""Pipeline runner / scheduler for the two-phase (dispatch -> collect) loop.

Because 51Folds models take ~30 min, dispatch and collect are decoupled: a
loop dispatches new questions, then repeatedly collects until jobs finish.

Usage:
  python scripts/run_pipeline.py dispatch [tournament] [--live] [--limit N]
  python scripts/run_pipeline.py collect  [--live]
  python scripts/run_pipeline.py loop [tournament] [--live] [--limit N] [--interval S]
  python scripts/run_pipeline.py status

Defaults to DRY-RUN (Metaculus submission is staged, not posted). Pass --live
to actually submit. Numeric/discrete (CDF) questions are deferred by default.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aeb.folds import FoldsClient          # noqa: E402
from aeb.jobstore import JobStore          # noqa: E402
from aeb.metaculus import MetaculusClient  # noqa: E402
from aeb.orchestrator import Orchestrator  # noqa: E402


def build(dry_run: bool) -> Orchestrator:
    return Orchestrator(MetaculusClient(), FoldsClient(), dry_run=dry_run)


def cmd_status() -> None:
    store = JobStore()
    from collections import Counter
    by = Counter(j.status for j in store.jobs)
    print("jobs:", dict(by), f"(total {len(store.jobs)})")
    for j in store.jobs:
        print(f"  q{j.question_id} [{j.qtype}] {j.status} models={len(j.model_ids)} {j.title[:45]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["dispatch", "collect", "loop", "status"])
    ap.add_argument("tournament", nargs="?", default=None)
    ap.add_argument("--live", action="store_true", help="actually submit (default: dry-run)")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--interval", type=int, default=1200, help="loop tick seconds")
    args = ap.parse_args()

    if args.command == "status":
        cmd_status()
        return

    orch = build(dry_run=not args.live)
    mode = "LIVE" if args.live else "DRY-RUN"
    print(f"[aeb] {args.command} ({mode}) tournament={args.tournament or 'WHOLE SITE'}")

    if args.command == "dispatch":
        orch.dispatch(args.tournament, limit=args.limit)
    elif args.command == "collect":
        orch.collect()
    elif args.command == "loop":
        while True:
            orch.dispatch(args.tournament, limit=args.limit)
            orch.collect()
            pend = len(orch.store.pending())
            print(f"[aeb] tick done; {pend} jobs pending; sleeping {args.interval}s")
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
