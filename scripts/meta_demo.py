"""Drive Interactive Meta Mode from the CLI (default: Advanced Brent, q:44704).

  python scripts/meta_demo.py list                 # the N unified drivers + neutral state
  python scripts/meta_demo.py move 11:-2 9:+1       # Hormuz down 2, ME/Iran up 1 -> fan out
  python scripts/meta_demo.py move 11:-2 --dry      # show resolved per-model states, no PUT
  python scripts/meta_demo.py reset                 # restore all models to baseline

A move blocks while all touched models recompute (server-side, async) — expect
minutes, not seconds. Use --dry to preview the driver shifts instantly.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aeb.folds import index_to_state, state_to_index  # noqa: E402
from aeb.meta import MetaEngine, load_mapping, resolve_states  # noqa: E402

DEFAULT_MAPPING = Path(__file__).resolve().parents[1] / "state" / "unified_drivers_44704_advanced.json"


def _pct(d: dict[str, float]) -> str:
    return "  ".join(f"{k}={v*100:5.1f}%" for k, v in d.items())


def cmd_list(mapping) -> None:
    print(f"Unified drivers for q:{mapping.question_id} [{mapping.tier}]  "
          f"N={mapping.n} over {len(mapping.models)} models\n")
    print(f"{'UID':>3}  {'UNIFIED DRIVER':<40} {'neutral':<9} models  members")
    print("-" * 78)
    for u in mapping.unified:
        bi = mapping.unified_baseline_index(u.uid)
        neutral = index_to_state(round(bi)) if bi is not None else "-"
        print(f"{u.uid:>3}  {u.name:<40} {neutral:<9} {u.models_covered()}/{len(mapping.models)}"
              f"      {u.member_count()}")
    print("\ndelta range per driver ~ [-4,+4]; a move nudges every member from its own baseline.")


def _parse_deltas(tokens: list[str]) -> dict[int, int]:
    deltas = {}
    for t in tokens:
        if ":" not in t:
            raise SystemExit(f"bad delta token {t!r}; use UID:DELTA e.g. 11:-2")
        uid, d = t.split(":", 1)
        deltas[int(uid)] = int(d)
    return deltas


def cmd_move(mapping, tokens: list[str], dry: bool) -> None:
    deltas = _parse_deltas([t for t in tokens if not t.startswith("--")])
    for uid in deltas:
        mapping.by_uid(uid)  # validates uid exists
    label = ", ".join(f"{mapping.by_uid(u).name} {d:+d}" for u, d in deltas.items())
    print(f"Meta setting: {label}\n")

    resolved, changes = resolve_states(mapping, deltas)
    if not changes:
        print("(no driver states change under this setting)")
        return
    print(f"{len(changes)} driver shift(s) across {len({c['model'] for c in changes})} model(s):")
    for c in changes:
        print(f"  {c['model']}  {c['code']:<7} {c['from']:>10} -> {c['to']:<10} ({c['unified']})")

    if dry:
        print("\n--dry: no PUT sent.")
        return

    engine = MetaEngine(mapping)
    print("\nCapturing baseline, then firing PUT /drivers to touched models and polling ...")
    result = engine.move(deltas)
    print("\nBASELINE : " + _pct(result.baseline))
    print("ADJUSTED : " + _pct(result.adjusted))
    print("DELTA    : " + "  ".join(f"{k}={v*100:+5.1f}pp" for k, v in result.diff().items()))


def cmd_reset(mapping) -> None:
    print("Resetting all models to baseline states ...")
    MetaEngine(mapping).reset()
    print("done (models recomputing back to baseline).")


def main(argv: list[str]) -> None:
    if not argv:
        print(__doc__)
        return
    mapping = load_mapping(DEFAULT_MAPPING)
    cmd, rest = argv[0], argv[1:]
    if cmd == "list":
        cmd_list(mapping)
    elif cmd == "move":
        cmd_move(mapping, rest, dry="--dry" in rest)
    elif cmd == "reset":
        cmd_reset(mapping)
    else:
        raise SystemExit(f"unknown command {cmd!r} (use list | move | reset)")


if __name__ == "__main__":
    main(sys.argv[1:])
