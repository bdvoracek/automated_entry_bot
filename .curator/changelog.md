# Change log

One block per run. What the human glances at before merge.

## 2026-07-22 624b590 | run bootstrap-run1 | FULL | lenses: A1 A2 A3 A4 A5 A6

- CREATE .curator/atlas.md      -> current-state pointer map, 6 lenses   (first Atlas; no prior state)
- CREATE .curator/lineage.md    -> append-only decision log   (bootstrap entry + parked ambiguities)
- CREATE .curator/changelog.md  -> this file
- CREATE .curator/run-claim     -> one-run-at-a-time lock (stale after 60min)
- CREATE CLAUDE.md              -> curator stub (trigger channel) + minimal repo pointers   (none existed before)
- ADD    ./curator.md           -> the recipe, tracked on this branch (was untracked)
- SYNTHESIS: recorded the two-pipeline architecture (production + exploration) as the core
  A1 fact, since README documents only the production path.
- CONTESTED (parked, not fixed): README "Setup" lists 2 env tokens vs config.py's ~8 knobs
  (authoritative: config.py). Left for the human; not auto-edited.
- GAP REPORTED (not guessed): exploration pipeline (explore.py, data/, resulting.py,
  analytics.py) has no in-repo doc. Draft pointer filed in Atlas A1; writing a real doc deferred.
- No consolidation, demotion, archive, or cut: repo is small and clean, no duplicate or
  conflicting docs, no transient artifacts to harvest. No canonical removals.

drift-guard: established as an A6 convention (3 checks), no tooling added (no-infra principle).
tokens: within budget | surface (always-loaded MD): 0 -> ~18 lines (new CLAUDE.md stub) | budget: within
merge: awaiting human glance + ok. Nothing merged to main unattended.
