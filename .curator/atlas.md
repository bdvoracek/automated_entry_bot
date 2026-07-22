# Atlas   (params: full-scan>25 files or >1500 lines; sweep every 8 runs or 30 days; change-budget 40 files/5%; contested-persist 3; run-claim 60min)

Current-state pointer map. One line per entry, grouped by lens. Pointers, not content;
the files remain the territory. Every entry is derived-at 624b590 unless noted.
The domain/API cross-cutting layer (51Folds + Metaculus semantics, locked design decisions,
exploration cost/quality findings) lives in the agent's off-repo memory, NOT in this repo, and
so is out of the Curator's scope; this Atlas maps only what is in the repo tree.

## Architecture (A1)

- TWO parallel pipelines share one foundation. The single most load-bearing, non-discoverable
  fact: `src/aeb/` is not one pipeline but two, over a shared base.
  -> src/aeb/   [canonical, core, derived-at 624b590]
- Shared foundation: config + stdlib HTTP, used by both pipelines.
  -> aeb/config.py; aeb/http.py::request   [canonical, core]
- PRODUCTION pipeline: discover -> predict -> aggregate -> submit, two-phase (dispatch then
  collect) because 51Folds builds take ~30min. State persisted to `state/` via jobstore.
  -> aeb/orchestrator.py::Orchestrator (dispatch/collect/process/run)   [canonical, core]
  -> supporting: aeb/metaculus.py; aeb/folds.py; aeb/aggregate.py::midpoint; aeb/cdf.py;
     aeb/bins.py; aeb/readiness.py; aeb/jobstore.py::JobStore; aeb/sanity.py; aeb/scan.py
     [canonical, validated]
- EXPLORATION pipeline: characterize 51Folds systematically (all tiers x 10 = 30 models/question),
  store every run, surface the Advanced-tier midpoint, then result + cost/quality analytics.
  State in `state/exploration.db` (SQLite). Undocumented in-repo (see A6 gap).
  -> aeb/explore.py::ExploreEngine (explore/collect/_surface)   [canonical, validated]
  -> supporting: aeb/data/ (see A4); aeb/resulting.py::ResultingWorker; aeb/analytics.py::cost_quality;
     aeb/elicit.py::elicit   [canonical, validated]
- Entry points (scripts) map to the two pipelines.
  -> production: scripts/run_pipeline.py; scripts/collect_loop.py; scripts/cdf_collect.py
  -> exploration: scripts/explore_cli.py; scripts/explore_collect_loop.py
  -> read-only demo: scripts/discover.py   [canonical, validated]

## Conventions (A2)

- stdlib-only runtime, zero third-party runtime deps (urllib, sqlite3). pytest is the only
  dev/test dep. The scaffold stays dependency-free on purpose.
  -> requirements.txt; aeb/config.py (docstring)   [canonical, core]
- Modern-Python type style throughout: `from __future__ import annotations`, PEP 604 unions
  (`X | None`), builtin generics (`list[float]`), dataclasses for value objects.
  -> aeb/config.py; aeb/metaculus.py::Question; aeb/cdf.py::Scaling   [canonical, validated]
- Swappable-backend pattern: ABC contract + concrete impl, sized for a later Cosmos DB swap.
  -> aeb/data/repository.py::Repository (ABC) vs aeb/data/sqlite_repo.py::SqliteRepository
     [canonical, validated]
- ASCII-only, module-level docstrings on each file.   [inferred, draft]

## Build / test / run / deploy (A3)

- Tests: `python -m pytest -q`. Covers the deterministic core (aggregate + CDF math), the
  data repository, and scan classification.
  -> tests/test_aggregate.py; tests/test_cdf.py; tests/test_repository.py; tests/test_scan.py
     [canonical, validated]
- Run entry points are the scripts; all default to dry_run and require `--live` to submit.
  -> README.md "Run"; scripts/*.py   [canonical, validated]
- NO CI configured: no `.github/workflows`, no pre-commit. Tests are run by hand only.
  -> (absence)   [inferred, draft, drift-guard: flag if CI is added but README's Run section is not]

## Interfaces and contracts (A4)

- Metaculus REST contract: discover (`/posts/?statuses=open`), submit
  (`/questions/forecast/`). CANONICAL invariant: `post_id != question_id` (submit against
  question_id; fetch/comment by post_id).
  -> aeb/metaculus.py::MetaculusClient; README.md "Notes"   [canonical, core; one rule, two sites,
     both agree]
- 51Folds REST contract: create/get/retry models, poll to done (~30min), N-ensemble dispatch;
  tiers Overview|Insight|Advanced.
  -> aeb/folds.py::FoldsClient   [canonical, validated]
  -> external source of truth: "51Folds API Documentation 2603-06.pdf" (untracked, repo root)
     [reference, out-of-tree]
- Storage contract: the Repository ABC (upsert/get/all/query/delete + save/load helpers) plus
  document-shaped entities carrying id + partition_key for Cosmos-readiness.
  -> aeb/data/repository.py::Repository; aeb/data/entities.py (Question, ModelRun, BinDesign,
     SurfacedPrediction, Resolution)   [canonical, validated]
- Numeric contract: 5-bin PMF + tails -> Metaculus 201-point continuous_cdf. Faithful port of
  the Continuous Distribution Agent template; bins.py parses that template's output block.
  -> aeb/cdf.py::bins_to_cdf; aeb/bins.py::parse_distribution_block;
     ContinuousDistributionAgent.txt   [canonical, core]

## Configuration and environment (A5)

- All runtime config is centralized in one module: endpoints, required browser User-Agent
  (Cloudflare 1010-blocks bare urllib), secrets, and ~8 tunable pipeline knobs.
  -> aeb/config.py   [canonical, core]
- Secrets: METACULUS_TOKEN, FIFTYONEFOLDS_TOKEN, loaded from a git-ignored `.env`.
  -> aeb/config.py; .gitignore; README.md "Setup"   [canonical, validated]
- CONFIG DRIFT (minor): README "Setup" documents only the 2 tokens; config.py also exposes
  FOLDS_RUNS_PER_QUESTION, FOLDS_MODEL_TYPE, poll interval/timeout, Metaculus throttle knobs.
  -> README.md "Setup" vs aeb/config.py:42-53
     [conflicting; authoritative aeb/config.py; disposition contested -> human glance]
- Persistent state is git-ignored: `state/` holds job state (jobstore), the exploration SQLite
  DB, and the sanity watch-list `state/violations.json`.
  -> .gitignore; aeb/jobstore.py; aeb/sanity.py::WatchList   [canonical, validated]
- Claude Code perms are broad (Bash/Read/Write *). Local overrides git-ignored.
  -> .claude/settings.json; .gitignore   [reference, stable]

## MD-loading hygiene / meta (A6)

- Target topology is minimal and flat: exactly one canonical in-repo doc (README) plus this
  Curator apparatus. No CLAUDE.md existed before this run; no `@import` graph, no
  `.claude/rules/`, no subdir docs. Nothing to consolidate or archive.
  -> README.md; CLAUDE.md (stub, created this run); ./curator.md   [canonical, core]
- README classification: canonical-doc. Tight, accurate for the production pipeline.   [canonical]
- DOC GAP (the one real finding): the exploration pipeline (explore.py, data/, resulting.py,
  analytics.py) has NO in-repo documentation. README covers only production. Not-covered, not
  wrong. A synthesized draft pointer sits under A1 above; writing an actual in-repo doc is a
  generative act deferred to the human's call.
  -> (gap) src/aeb/explore.py; src/aeb/data/   [provisional, draft, disposition contested]
- Non-.md load-bearing reference: ContinuousDistributionAgent.txt is an LLM prompt template
  whose output format bins.py parses; keep in place, pointed to from A4.   [reference, keep]
- Drift guard (this run's convention): on each run, re-check that (1) the two-pipeline split in
  A1 still holds, (2) README's Run/Setup sections still match scripts/ and config.py, (3) every
  Atlas symbol anchor still resolves. Recorded here rather than as tooling (no infra principle).
