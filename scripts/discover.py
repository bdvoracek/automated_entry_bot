#!/usr/bin/env python3
"""Read-only demo: list forecastable open questions across Metaculus.

Proves the discovery + filter stage against the live API. No writes.

Usage:
  python scripts/discover.py                 # whole site
  python scripts/discover.py <tournament>    # e.g. bot-testing-area
  python scripts/discover.py <tournament> 30 # limit
"""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aeb.metaculus import MetaculusClient  # noqa: E402


def main() -> None:
    tournament = (sys.argv[1] if len(sys.argv) > 1 else None) or None
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 20

    mc = MetaculusClient()
    scope = tournament or "WHOLE SITE"
    print(f"Forecastable open questions ({scope}), limit {limit}:\n")
    by_type: Counter[str] = Counter()
    for q in mc.iter_open_questions(tournaments=tournament, max_questions=limit):
        by_type[q.type] += 1
        cp = q.community_centers[0] if q.community_centers else None
        print(f"  post {q.post_id:>6} q{q.question_id:<6} [{q.type:<15}] "
              f"perm={q.user_permission} cp={cp}  {q.title[:60]}")
    print("\nby type:", dict(by_type))


if __name__ == "__main__":
    main()
