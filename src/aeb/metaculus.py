"""Metaculus client: discover forecastable questions, dedup, submit forecasts.

Key facts baked in from live reconnaissance:
  - Cloudflare 1010 requires a browser User-Agent (handled in http.py).
  - post_id != question_id. Submit against question_id; fetch/comment by post_id.
  - Forecast endpoint is competition-agnostic (takes a bare question_id).
  - Gate on user_permission == "forecaster" to know we may submit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from . import config
from .http import request, throttle_sleep

FORECAST_TYPES = "binary,multiple_choice,numeric,discrete"


@dataclass
class Question:
    post_id: int
    question_id: int
    type: str                       # binary | multiple_choice | numeric | discrete
    title: str
    user_permission: str | None
    status: str | None
    options: list[str] | None = None            # multiple_choice
    scaling: dict[str, Any] | None = None       # numeric/discrete
    open_upper_bound: bool = True
    open_lower_bound: bool = True
    cp_reveal_time: str | None = None
    open_time: str | None = None    # when the question entered its forecasting window (ISO)
    already_forecast: bool = False
    community_centers: list[float] | None = None  # opportunistic anchor, often None for bots
    tournaments: list[dict[str, Any]] = field(default_factory=list)  # [{slug, name, id}]
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def can_forecast(self) -> bool:
        return self.user_permission == "forecaster" and self.status == "open"


def _parse(post: dict[str, Any]) -> Question | None:
    q = post.get("question")
    if not q:
        return None  # groups / notebooks / non-question posts
    agg = ((q.get("aggregations") or {}).get("recency_weighted") or {}).get("latest") or {}
    mf_latest = (q.get("my_forecasts") or {}).get("latest") or {}
    projects = post.get("projects") or {}
    tournaments = [
        {"slug": t.get("slug"), "name": t.get("name"), "id": t.get("id")}
        for t in (projects.get("tournament") or [])
    ]
    return Question(
        post_id=post["id"],
        question_id=q["id"],
        type=q.get("type", ""),
        title=post.get("title", ""),
        user_permission=post.get("user_permission"),
        status=q.get("status"),
        options=q.get("options"),
        scaling=q.get("scaling"),
        open_upper_bound=q.get("open_upper_bound", True),
        open_lower_bound=q.get("open_lower_bound", True),
        cp_reveal_time=q.get("cp_reveal_time"),
        open_time=(q.get("open_time") or q.get("scheduled_open_time")
                   or post.get("published_at")),
        already_forecast=mf_latest.get("forecast_values") is not None,
        community_centers=agg.get("centers"),
        tournaments=tournaments,
        raw=post,
    )


class MetaculusClient:
    def __init__(self, token: str | None = None, throttle: bool = True):
        self.token = token or config.METACULUS_TOKEN
        if not self.token:
            raise RuntimeError("METACULUS_TOKEN missing (set it in .env)")
        self.throttle = throttle

    def _hdr(self) -> dict[str, str]:
        return {"Authorization": f"Token {self.token}"}

    def _get(self, path: str, **params: Any) -> Any:
        if self.throttle:
            throttle_sleep()
        _, data = request("GET", config.METACULUS_BASE + path, headers=self._hdr(), params=params)
        return data

    # -- discovery ----------------------------------------------------------
    def iter_open_questions(
        self,
        tournaments: str | int | None = None,
        *,
        forecastable_only: bool = True,
        skip_already_forecast: bool = True,
        page_size: int = 50,
        max_questions: int | None = None,
        order_by: str = "-hotness",
    ) -> Iterable[Question]:
        """Yield open questions. tournaments=None searches the WHOLE site.

        order_by defaults to -hotness (relevance) for the pipeline; the monitor
        passes a recency sort (config.MONITOR_ORDER_BY) so brand-new questions
        surface first instead of being buried by low hotness.
        """
        offset, yielded = 0, 0
        while True:
            params: dict[str, Any] = {
                "limit": page_size,
                "offset": offset,
                "order_by": order_by,
                "statuses": "open",
                "forecast_type": FORECAST_TYPES,
                "with_cp": "true",
                "include_description": "true",
            }
            if tournaments is not None:
                params["tournaments"] = tournaments
            data = self._get("/posts/", **params)
            results = data.get("results", []) if isinstance(data, dict) else []
            if not results:
                return
            for post in results:
                q = _parse(post)
                if q is None:
                    continue
                if forecastable_only and not q.can_forecast:
                    continue
                if skip_already_forecast and q.already_forecast:
                    continue
                yield q
                yielded += 1
                if max_questions and yielded >= max_questions:
                    return
            offset += page_size

    def get_question(self, post_id: int) -> Question | None:
        return _parse(self._get(f"/posts/{post_id}/", with_cp="true"))

    # -- submission ---------------------------------------------------------
    def _submit(self, question_id: int, payload: dict[str, Any], dry_run: bool) -> dict[str, Any]:
        body = [{"question": question_id, "source": "api", **payload}]
        if dry_run:
            return {"dry_run": True, "would_post": body}
        if self.throttle:
            throttle_sleep()
        status, data = request(
            "POST", config.METACULUS_BASE + "/questions/forecast/",
            headers=self._hdr(), json_body=body,
        )
        return {"status": status, "response": data}

    def submit_binary(self, question_id: int, p_yes: float, *, dry_run: bool = False) -> dict[str, Any]:
        p = min(0.999, max(0.001, p_yes))
        return self._submit(question_id, {
            "probability_yes": p,
            "probability_yes_per_category": None,
            "continuous_cdf": None,
        }, dry_run)

    def submit_multiple_choice(
        self, question_id: int, per_option: dict[str, float], *, dry_run: bool = False,
    ) -> dict[str, Any]:
        labels = list(per_option)
        clamped = [min(0.99, max(0.01, per_option[l])) for l in labels]
        total = sum(clamped)
        norm = [c / total for c in clamped]
        norm[-1] += 1.0 - sum(norm)  # fix rounding residual
        return self._submit(question_id, {
            "probability_yes": None,
            "probability_yes_per_category": dict(zip(labels, norm)),
            "continuous_cdf": None,
        }, dry_run)

    def submit_numeric(self, question_id: int, cdf: list[float], *, dry_run: bool = False) -> dict[str, Any]:
        return self._submit(question_id, {
            "probability_yes": None,
            "probability_yes_per_category": None,
            "continuous_cdf": cdf,
        }, dry_run)

    def withdraw(self, question_id: int) -> dict[str, Any]:
        """Retract a standing forecast. Sets my_forecasts.latest.end_time."""
        if self.throttle:
            throttle_sleep()
        status, data = request(
            "POST", config.METACULUS_BASE + "/questions/withdraw/",
            headers=self._hdr(), json_body=[{"question": question_id}],
        )
        return {"status": status, "response": data}
