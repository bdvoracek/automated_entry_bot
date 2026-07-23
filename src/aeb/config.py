"""Configuration: load secrets from .env and expose runtime constants.

No third-party deps — a tiny .env parser keeps the scaffold dependency-free.
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path = REPO_ROOT / ".env") -> None:
    """Populate os.environ from a .env file (does not overwrite existing vars)."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip())


_load_dotenv()

# --- Endpoints -------------------------------------------------------------
METACULUS_BASE = "https://www.metaculus.com/api"
FOLDS_BASE = "https://api.51folds.ai/api/v1"

# Metaculus sits behind Cloudflare, which 1010-blocks bare python-urllib.
# A browser User-Agent is REQUIRED for every request.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# --- Secrets ---------------------------------------------------------------
METACULUS_TOKEN = os.environ.get("METACULUS_TOKEN", "")
FIFTYONEFOLDS_TOKEN = os.environ.get("FIFTYONEFOLDS_TOKEN", "")

# --- Pipeline defaults (tune freely) --------------------------------------
FOLDS_RUNS_PER_QUESTION = int(os.environ.get("FOLDS_RUNS_PER_QUESTION", "5"))  # N
FOLDS_MODEL_TYPE = os.environ.get("FOLDS_MODEL_TYPE", "Insight")  # Overview|Insight|Advanced
# 51Folds models take ~30 min to build — poll gently, allow a long ceiling.
FOLDS_POLL_INTERVAL_S = float(os.environ.get("FOLDS_POLL_INTERVAL_S", "60"))
FOLDS_POLL_TIMEOUT_S = float(os.environ.get("FOLDS_POLL_TIMEOUT_S", "3600"))

# Metaculus self-throttle: the reference bot sleeps ~3.5-4.5s between calls.
METACULUS_MIN_SLEEP_S = float(os.environ.get("METACULUS_MIN_SLEEP_S", "3.5"))
METACULUS_JITTER_S = float(os.environ.get("METACULUS_JITTER_S", "1.0"))

CDF_SIZE = 201  # Metaculus continuous_cdf point count (numeric/date)

# --- Monitor (new-question detection) -------------------------------------
# Recency sort for the monitor. Newest-open first so fresh questions surface
# ahead of low-hotness ones. VERIFIED live 2026-07-23: "-open_time" returns 200
# and sorts by open_time desc (whereas -hotness scatters open dates, burying new
# questions). Valid alternatives if ever needed: "-published_at", "-created_time".
MONITOR_ORDER_BY = os.environ.get("MONITOR_ORDER_BY", "-open_time")
# Tight cadence for short forecasting windows (some bot tournaments open a
# question for ~1h). Per-tournament polling is one cheap call per tick.
MONITOR_INTERVAL_S = float(os.environ.get("MONITOR_INTERVAL_S", "120"))
# Safety cap on pages walked per tournament per tick (page_size=100 each).
MONITOR_MAX_QUESTIONS = int(os.environ.get("MONITOR_MAX_QUESTIONS", "300"))
