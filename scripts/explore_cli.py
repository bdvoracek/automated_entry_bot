#!/usr/bin/env python3
"""CLI for the systematic 51Folds exploration pipeline.

  python scripts/explore_cli.py scan [--tournament S] [--min-days N] [--dump]  # what's answerable
  python scripts/explore_cli.py comps [--min-days N] [--top N]                 # competitions to enter
  python scripts/explore_cli.py explore <post_id> [--live]   # binary/MC: fan out 30 models
  python scripts/explore_cli.py collect [--live]             # poll runs, surface Advanced midpoint
  python scripts/explore_cli.py result                       # pull Metaculus resolutions
  python scripts/explore_cli.py analytics                    # cost-vs-quality per tier
  python scripts/explore_cli.py status

Numeric/discrete exploration needs a designed bin set, so it is driven via the
ExploreEngine API (bin_design=...) rather than this CLI's `explore` command.
Defaults to DRY-RUN; pass --live to actually enter the surfaced prediction.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aeb import analytics                       # noqa: E402
from aeb.data import SqliteRepository           # noqa: E402
from aeb.explore import ExploreEngine           # noqa: E402
from aeb.folds import FoldsClient               # noqa: E402
from aeb.metaculus import MetaculusClient       # noqa: E402
from aeb.resulting import ResultingWorker       # noqa: E402

DB = Path(__file__).resolve().parents[1] / "state" / "exploration.db"
COLLECTIONS = ["questions", "bin_designs", "model_runs", "surfaced_predictions", "resolutions"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["scan", "comps", "explore", "collect",
                                        "result", "analytics", "status"])
    ap.add_argument("post_id", nargs="?", type=int)
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--tournament", default=None, help="scan within one competition (slug/id)")
    ap.add_argument("--min-days", type=float, default=None, help="drop questions closing sooner")
    ap.add_argument("--dump", action="store_true", help="scan: print answerable question ids")
    ap.add_argument("--top", type=int, default=30, help="comps: show top N competitions")
    args = ap.parse_args()

    # scan / comps are read-only and need only Metaculus
    if args.command in ("scan", "comps"):
        from aeb import scan as scanmod
        mc = MetaculusClient(throttle=False)
        rep = scanmod.scan(mc, tournaments=args.tournament, min_days_to_close=args.min_days,
                           keep=args.dump)
        if args.command == "comps":
            window = f"closing >{args.min_days:g} days out" if args.min_days else "any close date"
            print(f"Competitions with answerable open questions ({window}):\n")
            for slug, name, n in rep.competitions()[:args.top]:
                print(f"  {n:>4}  {slug:<28} {name or ''}")
            print(f"\n{len(rep.by_competition)} competitions · {rep.total} answerable questions total")
            return
        print(f"Scan ({args.tournament or 'WHOLE SITE'}): {rep.total} answerable open questions")
        print("  by type  :", rep.by_type)
        print("  by bucket:", rep.by_bucket)
        print("  top competitions:")
        for slug, name, n in rep.competitions()[:10]:
            print(f"     {n:>4}  {slug}  {('· '+name) if name else ''}")
        if args.dump:
            ids = [f"{q.post_id}:{q.type}" for q in rep.questions
                   if scanmod.classify(q) == "answerable_now"]
            print(f"\n  answerable-now post ids ({len(ids)}):")
            print("   ", " ".join(ids[:200]) + (" ..." if len(ids) > 200 else ""))
        return

    repo = SqliteRepository(DB)

    if args.command == "status":
        for c in COLLECTIONS:
            print(f"  {c}: {len(repo.all(c))}")
        runs = repo.all("model_runs")
        print("  runs by tier:", dict(Counter(r["tier"] for r in runs)),
              "| by status:", dict(Counter(r["status"] for r in runs)))
        return

    if args.command == "analytics":
        rows, summary = analytics.cost_quality(repo)
        print("per (question, tier):")
        for r in rows:
            print(f"  q{r['question_id']} [{r['qtype']:<15}] {r['tier']:<9} "
                  f"cost={r['cost']:<7} n={r['n']} brier={r['brier']}")
        print("\nper-tier summary (cost vs quality):")
        for tier, s in summary.items():
            print(f"  {tier:<9} questions={s['questions']} avg_cost={s['avg_cost']} "
                  f"avg_brier={s['avg_brier']} scored={s['scored']}")
        return

    mc = MetaculusClient()
    if args.command == "result":
        got = ResultingWorker(mc, repo).poll()
        print(f"checked resolutions; {sum(r.resolved for r in got)} resolved of {len(got)}")
        return

    eng = ExploreEngine(mc, FoldsClient(), repo, dry_run=not args.live)
    if args.command == "explore":
        q = mc.get_question(args.post_id)
        if q is None or q.type not in ("binary", "multiple_choice"):
            print("explore CLI supports binary/multiple_choice only "
                  "(numeric needs a bin design via the API)")
            return
        runs = eng.explore(q)
        print(f"dispatched {len(runs)} models for q{q.question_id} [{q.type}]")
    elif args.command == "collect":
        surfaced = eng.collect()
        print(f"surfaced {len(surfaced)} prediction(s)")


if __name__ == "__main__":
    main()
