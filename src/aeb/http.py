"""Minimal stdlib HTTP helper with browser UA, retries and optional throttle.

Kept dependency-free (urllib) because that is what actually works against
Metaculus's Cloudflare in this environment.
"""
from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from . import config


class HttpError(RuntimeError):
    def __init__(self, status: int, body: str, url: str):
        super().__init__(f"HTTP {status} for {url}: {body[:300]}")
        self.status = status
        self.body = body
        self.url = url


def request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_body: Any | None = None,
    timeout: float = 30.0,
    retries: int = 3,
    backoff: float = 2.0,
) -> tuple[int, Any]:
    """Perform an HTTP request, returning (status, parsed_json_or_text).

    Retries on 429/5xx and transient network errors with exponential backoff.
    Raises HttpError on non-retryable 4xx.
    """
    if params:
        url = url + "?" + urllib.parse.urlencode(params, doseq=True)
    hdrs = {"Accept": "application/json", "User-Agent": config.USER_AGENT}
    if headers:
        hdrs.update(headers)
    data = None
    if json_body is not None:
        data = json.dumps(json_body).encode()
        hdrs.setdefault("Content-Type", "application/json")

    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode() or ""
                try:
                    return resp.status, json.loads(raw)
                except json.JSONDecodeError:
                    return resp.status, raw
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:500]
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(backoff ** attempt + random.random())
                continue
            raise HttpError(e.code, body, url) from e
        except (urllib.error.URLError, TimeoutError) as e:  # transient network
            last_exc = e
            if attempt < retries:
                time.sleep(backoff ** attempt + random.random())
                continue
            raise HttpError(0, repr(e), url) from e
    raise HttpError(0, repr(last_exc), url)  # pragma: no cover


def throttle_sleep() -> None:
    """Sleep the Metaculus-friendly interval before a call."""
    time.sleep(random.uniform(
        config.METACULUS_MIN_SLEEP_S,
        config.METACULUS_MIN_SLEEP_S + config.METACULUS_JITTER_S,
    ))
