# Automated Entry Bot

Automate entry into prediction competitions using **51Folds.AI** forecasts.
First platform: **Metaculus** (all competitions we can answer, not just the AI benchmark).

This README covers the **production** pipeline (discover -> predict -> submit). A second,
**exploration** pipeline systematically characterizes 51Folds (all tiers x 10 runs/question,
cost-vs-quality analytics) over the same shared base — see [docs/exploration.md](docs/exploration.md).

## Pipeline

```
scheduler (~20 min)
  discover open questions   GET /posts/?statuses=open        (whole site or a tournament)
    gate: user_permission == "forecaster", skip already-forecast
    route by type:
      binary          -> outcomes [Yes, No]
      multiple_choice -> outcomes = options (<=5)
      numeric/discrete-> readiness gate -> Continuous Distribution Agent designs
                         5 bins (+ tails), CONSTRAINED to the Metaculus axis
    spool up N concurrent 51Folds models  POST /models
    poll each to completion, retry failures
    aggregate the N runs:  (mean + median) / 2   per outcome/bin
    map -> Metaculus payload (probability_yes | per_category | 201-pt CDF)
    submit  POST /questions/forecast/
```

## Layout

| Module | Role |
|---|---|
| `aeb/config.py` | `.env` loading, endpoints, defaults |
| `aeb/http.py` | stdlib HTTP (browser UA for Cloudflare, retries, throttle) |
| `aeb/metaculus.py` | discover / dedup / submit (binary, MC, numeric) |
| `aeb/folds.py` | create / poll / retry 51Folds models, run N-ensemble |
| `aeb/aggregate.py` | `(mean + median) / 2` ensemble aggregation |
| `aeb/cdf.py` | 5-bin PMF + tails -> Metaculus 201-point CDF |
| `aeb/bins.py` | Continuous Distribution Agent prompt + parser (LLM injected) |
| `aeb/readiness.py` | elicitation gate before CDF conversion |
| `aeb/orchestrator.py` | the discover -> predict -> submit loop |
| `scripts/discover.py` | read-only demo of the discovery stage |

## Setup

Secrets live in a git-ignored `.env`:

```
METACULUS_TOKEN=...          # Metaculus bot account access token
FIFTYONEFOLDS_TOKEN=...       # 51Folds bearer token (still needed)
```

Everything else has a sane default in `aeb/config.py` and can be overridden via the same `.env`
(shown with defaults):

```
FOLDS_RUNS_PER_QUESTION=5        # N: concurrent 51Folds models per question
FOLDS_MODEL_TYPE=Insight         # Overview | Insight | Advanced
FOLDS_POLL_INTERVAL_S=60         # builds take ~30 min; poll gently
FOLDS_POLL_TIMEOUT_S=3600
METACULUS_MIN_SLEEP_S=3.5        # self-throttle between Metaculus calls
METACULUS_JITTER_S=1.0
```

`aeb/config.py` is the authoritative list of tunable knobs.

## Run

```bash
python scripts/discover.py                 # list forecastable questions (read-only)
python -m pytest -q                        # unit tests (aggregate + CDF math)
```

## Status

- ✅ Metaculus access verified live: site-wide discovery, `user_permission` gate,
  and a confirmed sandbox forecast submission (HTTP 201).
- ✅ Deterministic core implemented + tested: aggregation and CDF construction.
- ⏳ Needs wiring to run live: the **51Folds bearer token**, and an **LLM runner**
  (LLM + web search) for the Continuous Distribution Agent (numeric bin design).
- Submission defaults to `dry_run=True` in the orchestrator until the above land.

## Notes

- `post_id` != `question_id`: submit against `question_id`, fetch/comment by `post_id`.
- The human Community Prediction is generally **not** exposed to bot accounts on
  live human questions; the CDF anchor uses it only opportunistically.
