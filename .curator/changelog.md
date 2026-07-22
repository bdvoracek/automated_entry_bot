# Change log

One block per run. What the human glances at before merge.

## 2026-07-22 | run gaps-run1 | INCREMENTAL | lenses: A5 A6 (gap closure, human-authorized)

- CREATE docs/exploration.md    -> in-repo doc for the exploration pipeline   (closes bootstrap A6 gap)
- EDIT   README.md "Setup"      -> document tunable env vars + name config.py authoritative   (closes A5 drift)
- EDIT   README.md intro        -> cross-link the two pipelines / docs/exploration.md
- UPDATE .curator/atlas.md      -> A5 + A6 entries moved contested/draft -> validated
- APPEND .curator/lineage.md    -> run-2 resolution entry (supersedes the two parked items)
- UPDATE CLAUDE.md stub         -> last-run bumped to this run's commit
- Both bootstrap-parked contested items now resolved; none left open. No new gaps found.
tokens: within budget | surface (always-loaded MD): ~18 lines CLAUDE.md unchanged (docs are load-on-demand) | budget: within
merge: human-authorized ("take care of the parked gaps"); merged to main.

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
