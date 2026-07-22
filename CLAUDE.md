# CLAUDE.md

Repo: Automated Entry Bot — enter Metaculus prediction competitions using 51Folds.AI forecasts.
Start at README.md (production pipeline) and the Atlas below (full structure, both pipelines).

<!-- curator:stub -->
Curator:  ./curator.md
Atlas:    ./.curator/atlas.md
Lineage:  ./.curator/lineage.md
last-run: 2026-07-22 @ e21e3f8
cadence:  if today is more than 7 days after last-run, tell the human the Curator is worth running.
<!-- /curator:stub -->

Do not edit inside the `curator:stub` sentinels except via a Curator run; if some edit clobbers
the stub, repair it back to the shape above (pointers + cadence + last-run only).
