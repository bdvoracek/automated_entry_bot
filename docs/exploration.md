# Exploration pipeline

The repo holds **two** pipelines over a shared `config.py` + `http.py` base. The production
pipeline (discover -> predict -> submit) is documented in the top-level [README](../README.md).
This document covers the **second** one: the systematic 51Folds characterization pipeline.

Its goal is not to answer one question well, but to **measure 51Folds itself** — spool every
question against all tiers many times, store every run, surface one tier to Metaculus, and use
Metaculus resolutions as a free scoring layer to compare cost against quality per tier.

## What it does

Every question is fanned out over **all tiers x N runs** — by default `("Overview", "Insight",
"Advanced")` x `10` = **30 models/question** (`TIERS`, `RUNS_PER_TIER` in `src/aeb/explore.py`).
Every model's prediction is stored. The **Advanced** tier's midpoint `(mean + median) / 2` is
the one surfaced to Metaculus for now (`SURFACE_TIER`). Because 51Folds builds take ~30 min,
`explore` (dispatch) and `collect` (poll + surface) are decoupled, exactly like the production
pipeline.

Per-tier **credit cost is captured at runtime** from the 51Folds balance delta across the
dispatch (`FoldsClient.credits()` before/after in `ExploreEngine.explore`), not hardcoded.
Observed so far: Overview ~10, Insight ~15, Advanced ~25 credits/model, i.e. ~500 credits for a
full 30-model question. Treat those as measured, not guaranteed.

## Components

| Module | Role |
|---|---|
| `aeb/explore.py` (`ExploreEngine`) | `explore(q, bin_design?)` fans out tiers x runs and stores 30 `ModelRun`s; `collect()` polls, stores outcomes, and surfaces the Advanced midpoint |
| `aeb/data/` | swappable storage layer: `Repository` ABC + `SqliteRepository`, and the document entities (`Question`, `ModelRun`, `BinDesign`, `SurfacedPrediction`, `Resolution`) each carrying `id` + partition key for a later Cosmos DB swap |
| `aeb/resulting.py` (`ResultingWorker`) | pulls Metaculus `resolution` / `status` + our forecast `score_data`, stores a `Resolution` per surfaced question |
| `aeb/analytics.py` (`cost_quality`) | per (question, tier): midpoint, cost, and Brier vs resolution; plus a per-tier avg-cost / avg-Brier summary |
| `aeb/elicit.py` (`elicit`) | question elicitation used when building context for a run |

State lives in a git-ignored SQLite DB at `state/exploration.db`.

## Run

Driven by `scripts/explore_cli.py` (dry-run by default; `--live` actually enters the surfaced
prediction):

```bash
python scripts/explore_cli.py scan [--tournament S] [--min-days N] [--dump]  # what's answerable
python scripts/explore_cli.py comps [--min-days N] [--top N]                 # competitions to enter
python scripts/explore_cli.py explore <post_id> [--live]   # binary/MC: fan out 30 models
python scripts/explore_cli.py collect [--live]             # poll runs, surface Advanced midpoint
python scripts/explore_cli.py result                       # pull Metaculus resolutions
python scripts/explore_cli.py analytics                    # cost-vs-quality per tier
python scripts/explore_cli.py status
```

`scripts/explore_collect_loop.py` is the long-running (LIVE) collect loop. Numeric/discrete
exploration needs a designed bin set, so it is driven via the `ExploreEngine` API
(`bin_design=...`), not the CLI's `explore` command.

## Relationship to production

Both pipelines discover the same Metaculus questions and both surface a `(mean + median) / 2`
midpoint. The difference: production runs one configured tier/N and submits on a schedule;
exploration runs all tiers x 10, keeps every run, and exists to tell us **which** tier/N is
worth using. Findings from it (e.g. ensemble sizing) feed back into the production defaults in
`aeb/config.py`.
