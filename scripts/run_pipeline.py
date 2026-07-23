#!/usr/bin/env python3
"""Pipeline runner / scheduler for the two-phase (dispatch -> collect) loop.

Because 51Folds models take ~30 min, dispatch and collect are decoupled: a
loop dispatches new questions, then repeatedly collects until jobs finish.

Usage:
  python scripts/run_pipeline.py dispatch [tournament] [--live] [--limit N]
  python scripts/run_pipeline.py collect  [--live]
  python scripts/run_pipeline.py loop [tournament] [--live] [--limit N] [--interval S]
  python scripts/run_pipeline.py monitor [t1,t2,...] [--live] [--interval S] [--backfill]
  python scripts/run_pipeline.py status

monitor: tight-cadence, newest-first detection of freshly-opened questions per
tournament (comma-separated; omit for whole-site), dispatched the moment they
appear -- for tournaments with short (~1h) forecasting windows.

Defaults to DRY-RUN (Metaculus submission is staged, not posted). Pass --live
to actually submit. Numeric/discrete (CDF) questions are deferred by default.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aeb import config                     # noqa: E402
from aeb.folds import FoldsClient          # noqa: E402
from aeb.jobstore import JobStore          # noqa: E402
from aeb.metaculus import MetaculusClient  # noqa: E402
from aeb.monitor import Monitor            # noqa: E402
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
    ap.add_argument("command", choices=["dispatch", "collect", "loop", "monitor", "status"])
    ap.add_argument("tournament", nargs="?", default=None,
                    help="tournament slug/id; monitor accepts a comma-separated list")
    ap.add_argument("--live", action="store_true", help="actually submit (default: dry-run)")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--interval", type=int, default=None, help="loop tick seconds")
    ap.add_argument("--backfill", action="store_true",
                    help="monitor: also dispatch questions already open at first run")
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
        interval = args.interval or 1200
        while True:
            orch.dispatch(args.tournament, limit=args.limit)
            orch.collect()
            pend = len(orch.store.pending())
            print(f"[aeb] tick done; {pend} jobs pending; sleeping {interval}s")
            time.sleep(interval)
    elif args.command == "monitor":
        interval = args.interval or int(config.MONITOR_INTERVAL_S)
        tourneys = args.tournament.split(",") if args.tournament else [None]
        monitor = Monitor(orch.mc)
        print(f"[aeb] monitoring {tourneys} every {interval}s "
              f"(order_by={monitor.order_by}); backfill={args.backfill}")
        first = True
        while True:
            try:
                new = monitor.poll_all(tourneys, backfill=args.backfill and first)
                if new:
                    orch.dispatch_questions(new)
                orch.collect()  # advance any in-flight jobs from earlier ticks
                pend = len(orch.store.pending())
                print(f"[aeb] tick: {len(new)} new, {pend} pending; sleeping {interval}s")
            except Exception as e:  # keep the watcher alive across transient errors
                print(f"[aeb] tick error (continuing): {e!r}")
            first = False
            time.sleep(interval)


if __name__ == "__main__":
    main()
