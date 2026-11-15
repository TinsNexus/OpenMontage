"""Facebook Page Insights tool (Meta Graph API, read-only).

Pulls analytics for a Facebook Page you manage: page-level insights, posts
with engagement counts, and Reels with per-video insights, then builds a
summary (top content, performance by media type, weekday and hour).

Auth comes from the environment only, never from tool inputs:

    FACEBOOK_PAGE_ACCESS_TOKEN   Page access token (pages_read_engagement,
                                 read_insights). Prefer a long-lived token.
    FACEBOOK_PAGE_ID             Optional. Resolved via /me when unset (works
                                 with a Page token).
    FACEBOOK_APP_SECRET          Optional. When set, every call carries an
                                 appsecret_proof (required if the app enables
                                 "Require App Secret").
    FACEBOOK_GRAPH_API_VERSION   Optional. Defaults to DEFAULT_GRAPH_VERSION.

Meta renames and retires Insights metrics between Graph versions, so metric
lists are inputs with conservative defaults, and an unknown metric is dropped
(and reported) instead of failing the whole call. Run
`operation: "probe_metrics"` to see which metrics the account accepts.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolTier,
)

DEFAULT_GRAPH_VERSION = "v24.0"
GRAPH_HOST = "https://graph.facebook.com"

# Conservative defaults. Old and new names are both listed where Meta has been
# migrating (e.g. impressions -> media views); whichever the API rejects is
# dropped and reported in `rejected_metrics`.
DEFAULT_PAGE_METRICS = [
    "page_impressions_unique",
    "page_post_engagements",
    "page_views_total",
    "page_fan_adds",
    "page_fan_removes",
    "page_follows",
    "page_daily_follows_unique",
    "page_media_view",
    "page_video_views",
]
DEFAULT_POST_METRICS = [
    "post_impressions_unique",
    "post_clicks",
    "post_media_view",
    "post_reactions_by_type_total",
]
DEFAULT_REEL_METRICS = [
    "blue_reels_play_count",
    "fb_reels_total_plays",
    "post_impressions_unique",
    "post_video_avg_time_watched",
    "post_video_view_time",
    "post_video_followers",
    "post_video_social_actions",
]

POST_FIELDS = (
    "id,message,created_time,permalink_url,status_type,shares,"
    "reactions.summary(total_count).limit(0),"
    "comments.summary(total_count).limit(0),"
    "attachments{media_type,type}"
)
REEL_FIELDS = "id,description,title,created_time,permalink_url,length"
PAGE_FIELDS = "id,name,fan_count,followers_count,category,link"

RATE_LIMIT_CODES = {4, 17, 32, 613, 80001}
INVALID_METRIC_CODE = 100
TOKEN_ERROR_CODE = 190
MAX_INSIGHTS_WINDOW_DAYS = 90  # day-period insights accept at most ~93 days


class GraphAPIError(RuntimeError):
    """Graph API error carrying Meta's error code/subcode."""

    def __init__(self, message: str, code: Optional[int] = None,
                 subcode: Optional[int] = None, status: Optional[int] = None):
        super().__init__(message)
        self.code = code
        self.subcode = subcode
        self.status = status


def _scrub(text: str) -> str:
    """Remove access tokens and appsecret proofs from any string."""
    return re.sub(r"(access_token|appsecret_proof)=[^&\s\"']+", r"\1=***", str(text))


class FacebookPageInsights(BaseTool):
    name = "facebook_page_insights"
    version = "0.1.0"
    tier = ToolTier.ANALYZE
    capability = "analysis"
    provider = "meta_graph"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC  # live data changes between calls
    runtime = ToolRuntime.API

    dependencies = ["env:FACEBOOK_PAGE_ACCESS_TOKEN", "python:requests"]
    install_instructions = (
        "Set FACEBOOK_PAGE_ACCESS_TOKEN in .env to a Page access token with "
        "pages_read_engagement and read_insights (create a Meta app at "
        "https://developers.facebook.com/apps, then use Graph API Explorer to "
        "get a Page token and exchange it for a long-lived one). Optionally "
        "set FACEBOOK_PAGE_ID, FACEBOOK_APP_SECRET, FACEBOOK_GRAPH_API_VERSION."
    )
    agent_skills = []

    capabilities = [
        "page_overview",
        "list_posts",
        "list_reels",
        "page_report",
        "probe_metrics",
    ]
    best_for = [
        "analytics for a Facebook Page you manage (reach, engagement, follows)",
        "finding which posts and reels performed best",
        "best weekday/hour to post, performance by media type",
    ]
    not_good_for = [
        "pages you do not manage (Graph API only returns insights to admins)",
        "downloading or analysing the video content itself (use video_downloader + video_analyzer)",
        "Instagram accounts",
    ]

    input_schema = {
        "type": "object",
        "required": ["operation"],
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["page_overview", "posts", "reels", "report", "probe_metrics"],
                "description": (
                    "page_overview: page fields + page insights. posts: posts with "
                    "engagement (+ per-post insights). reels: Reels with video insights. "
                    "report: all three plus a summary, written to output_dir. "
                    "probe_metrics: test which metric names the API accepts."
                ),
            },
            "days": {
                "type": "integer", "default": 28, "minimum": 1, "maximum": 730,
                "description": "Look-back window ending now (ignored when since is set).",
            },
            "since": {"type": "string", "description": "Start date YYYY-MM-DD (inclusive)."},
            "until": {"type": "string", "description": "End date YYYY-MM-DD (exclusive). Defaults to now."},
            "max_items": {
                "type": "integer", "default": 100, "minimum": 1, "maximum": 2000,
                "description": "Max posts / reels to fetch (pagination stops here).",
            },
            "include_post_insights": {
                "type": "boolean", "default": True,
                "description": "Fetch per-post insights (one extra call per post).",
            },
            "page_metrics": {"type": "array", "items": {"type": "string"}},
            "post_metrics": {"type": "array", "items": {"type": "string"}},
            "reel_metrics": {"type": "array", "items": {"type": "string"}},
            "timezone": {
                "type": "string", "default": "Asia/Ho_Chi_Minh",
                "description": "IANA timezone for weekday/hour analysis.",
            },
            "top_n": {"type": "integer", "default": 10, "minimum": 1, "maximum": 100},
            "output_dir": {
                "type": "string",
                "description": (
                    "Where to write insights.json and summary.md (required for "
                    "report). Use projects/<project-id>/artifacts/... ."
                ),
            },
        },
    }
    output_schema = {
        "type": "object",
        "properties": {
            "page": {"type": "object"},
            "page_insights": {"type": "object"},
            "posts": {"type": "array"},
            "reels": {"type": "array"},
            "summary": {"type": "object"},
            "rejected_metrics": {"type": "object"},
        },
    }

    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=256, disk_mb=20, network_required=True)
    retry_policy = RetryPolicy(max_retries=3, backoff_seconds=5.0, retryable_errors=["rate_limit"])
    side_effects = []  # read-only against Meta; writes local files only when output_dir is set
    user_visible_verification = [
        "Open summary.md and check the top posts match what Meta Business Suite shows",
    ]

    # ------------------------------------------------------------------ #
    # HTTP layer
    # ------------------------------------------------------------------ #

    def _token(self) -> str:
        token = os.environ.get("FACEBOOK_PAGE_ACCESS_TOKEN", "").strip()
        if not token:
            raise GraphAPIError("FACEBOOK_PAGE_ACCESS_TOKEN is not set.")
        return token

    def _base_url(self) -> str:
        version = os.environ.get("FACEBOOK_GRAPH_API_VERSION", "").strip() or DEFAULT_GRAPH_VERSION
        if not version.startswith("v"):
            version = f"v{version}"
        return f"{GRAPH_HOST}/{version}"

    def _auth_params(self) -> dict[str, str]:
        token = self._token()
        params = {"access_token": token}
        secret = os.environ.get("FACEBOOK_APP_SECRET", "").strip()
        if secret:
            params["appsecret_proof"] = hmac.new(
                secret.encode(), token.encode(), hashlib.sha256
            ).hexdigest()
        return params

    def _get(self, path_or_url: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """GET a Graph path (or a full paging URL) with retries on rate limits."""
        import requests  # lazy: tests swap the module in sys.modules

        if path_or_url.startswith("http"):
            url, query = path_or_url, None  # paging URLs already carry auth + cursor
        else:
            url = f"{self._base_url()}/{path_or_url.lstrip('/')}"
            query = {**(params or {}), **self._auth_params()}

        attempts = self.retry_policy.max_retries + 1
        for attempt in range(attempts):
            try:
                resp = requests.get(url, params=query, timeout=30)
            except Exception as exc:  # network error
                if attempt + 1 < attempts:
                    time.sleep(self.retry_policy.backoff_seconds * (attempt + 1))
                    continue
                raise GraphAPIError(f"Network error calling Graph API: {_scrub(exc)}") from None

            try:
                body = resp.json()
            except ValueError:
                body = {}

            err = body.get("error") if isinstance(body, dict) else None
            if resp.status_code < 400 and not err:
                return body

            err = err or {}
            code = err.get("code")
            subcode = err.get("error_subcode")
            message = err.get("message") or f"HTTP {resp.status_code}"
            if code in RATE_LIMIT_CODES and attempt + 1 < attempts:
                time.sleep(self.retry_policy.backoff_seconds * (attempt + 1))
                continue
            raise GraphAPIError(
                _scrub(f"Graph API error (code={code}, subcode={subcode}): {message}"),
                code=code, subcode=subcode, status=resp.status_code,
            )
        raise GraphAPIError("Graph API retries exhausted")  # pragma: no cover

    def _paginate(self, path: str, params: dict[str, Any], max_items: int,
                  stop: Optional[Any] = None) -> list[dict[str, Any]]:
        """Follow paging.next until max_items, the last page, or stop(item) is true.

        Items for which stop() returns true are not included (used to stop at
        the start of the date window on newest-first edges).
        """
        items: list[dict[str, Any]] = []
        body = self._get(path, params)
        while True:
            for item in body.get("data") or []:
                if stop is not None and stop(item):
                    return items
                items.append(item)
                if len(items) >= max_items:
                    return items
            next_url = (body.get("paging") or {}).get("next")
            if not next_url:
                return items
            body = self._get(next_url)

    # ------------------------------------------------------------------ #
    # Insights helpers (tolerant of retired metric names)
    # ------------------------------------------------------------------ #

    def _insights(self, path: str, metrics: list[str], extra: dict[str, Any],
                  rejected: dict[str, str]) -> list[dict[str, Any]]:
        """Fetch insights, dropping metrics the API rejects.

        Tries all metrics in one call; on an invalid-metric error, retries one
        metric at a time and records rejected names (with the API message) in
        `rejected`, so later calls skip them.
        """
        wanted = [m for m in metrics if m not in rejected]
        if not wanted:
            return []
        try:
            return self._get(path, {**extra, "metric": ",".join(wanted)}).get("data") or []
        except GraphAPIError as exc:
            if exc.code != INVALID_METRIC_CODE or len(wanted) == 1:
                if exc.code == INVALID_METRIC_CODE:
                    rejected[wanted[0]] = str(exc)
                    return []
                raise
        data: list[dict[str, Any]] = []
        failed = 0
        for metric in wanted:
            try:
                data.extend(self._get(path, {**extra, "metric": metric}).get("data") or [])
            except GraphAPIError as exc:
                if exc.code != INVALID_METRIC_CODE:
                    raise
                rejected[metric] = str(exc)
                failed += 1
        if failed == len(wanted) and len(wanted) > 1:
            # Code 100 is Graph's generic "invalid parameter": when every metric
            # fails, the cause is probably the object, date range or permission.
            self._warnings.append(
                f"Every metric failed on {path.split('/')[-1]} ({', '.join(wanted)}). "
                "This may not mean the metrics are retired: check the date range, "
                "Page permissions, and run probe_metrics."
            )
        return data

    @staticmethod
    def _lifetime_values(data: list[dict[str, Any]]) -> dict[str, Any]:
        """Collapse insights rows to {metric: latest value}."""
        out: dict[str, Any] = {}
        for row in data:
            values = row.get("values") or []
            if values:
                out[row.get("name")] = values[-1].get("value")
            elif "total_value" in row:
                out[row.get("name")] = (row.get("total_value") or {}).get("value")
        return out

    # ------------------------------------------------------------------ #
    # Time window
    # ------------------------------------------------------------------ #

    @staticmethod
    def _window(inputs: dict[str, Any]) -> tuple[datetime, datetime]:
        now = datetime.now(timezone.utc)
        until = now
        if inputs.get("until"):
            until = datetime.strptime(inputs["until"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if inputs.get("since"):
            since = datetime.strptime(inputs["since"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        else:
            since = until - timedelta(days=int(inputs.get("days", 28)))
        if since >= until:
            raise ValueError("since must be before until")
        return since, until

    @staticmethod
    def _parse_time(value: str) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")
        except ValueError:
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None

    # ------------------------------------------------------------------ #
    # Operations
    # ------------------------------------------------------------------ #

    def _page_id(self) -> str:
        page_id = os.environ.get("FACEBOOK_PAGE_ID", "").strip()
        if page_id:
            return page_id
        me = self._get("me", {"fields": "id,name"})
        if not me.get("id"):
            raise GraphAPIError("Could not resolve the Page id from /me; set FACEBOOK_PAGE_ID.")
        return me["id"]

    def _page_overview(self, page_id: str, inputs: dict[str, Any],
                       rejected: dict[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
        page = self._get(page_id, {"fields": PAGE_FIELDS})
        metrics = inputs.get("page_metrics") or DEFAULT_PAGE_METRICS
        since, until = self._window(inputs)

        series: dict[str, list[dict[str, Any]]] = defaultdict(list)
        start = since
        while start < until:
            end = min(start + timedelta(days=MAX_INSIGHTS_WINDOW_DAYS), until)
            rows = self._insights(
                f"{page_id}/insights", metrics,
                {"period": "day", "since": int(start.timestamp()), "until": int(end.timestamp())},
                rejected,
            )
            for row in rows:
                for v in row.get("values") or []:
                    series[row.get("name")].append({"date": v.get("end_time"), "value": v.get("value")})
            start = end

        # Chunk boundaries can return the same day twice: keep the last row per date.
        for name, points in series.items():
            by_date = {p["date"]: p for p in points}
            series[name] = sorted(by_date.values(), key=lambda p: p["date"] or "")

        totals: dict[str, Any] = {}
        for name, points in series.items():
            numeric = [p["value"] for p in points if isinstance(p["value"], (int, float))]
            if numeric:
                totals[name] = sum(numeric)
        page_insights = {
            "since": since.date().isoformat(),
            "until": until.date().isoformat(),
            "totals": totals,
            "daily": dict(series),
        }
        return page, page_insights

    def _posts(self, page_id: str, inputs: dict[str, Any],
               rejected: dict[str, str]) -> list[dict[str, Any]]:
        since, until = self._window(inputs)
        raw = self._paginate(
            f"{page_id}/posts",
            {"fields": POST_FIELDS, "since": int(since.timestamp()),
             "until": int(until.timestamp()), "limit": 100},
            int(inputs.get("max_items", 100)),
        )
        metrics = inputs.get("post_metrics") or DEFAULT_POST_METRICS
        with_insights = inputs.get("include_post_insights", True)
        posts = []
        for p in raw:
            attachments = ((p.get("attachments") or {}).get("data") or [{}])
            reactions = ((p.get("reactions") or {}).get("summary") or {}).get("total_count", 0)
            comments = ((p.get("comments") or {}).get("summary") or {}).get("total_count", 0)
            shares = (p.get("shares") or {}).get("count", 0)
            item = {
                "id": p.get("id"),
                "created_time": p.get("created_time"),
                "permalink_url": p.get("permalink_url"),
                "message": (p.get("message") or "")[:500],
                "status_type": p.get("status_type"),
                "media_type": (attachments[0].get("media_type") or "status").lower(),
                "reactions": reactions,
                "comments": comments,
                "shares": shares,
                "engagement": reactions + comments + shares,
            }
            if with_insights and p.get("id"):
                item["insights"] = self._lifetime_values(
                    self._insights(f"{p['id']}/insights", metrics, {}, rejected)
                )
            posts.append(item)
        return posts

    def _reels(self, page_id: str, inputs: dict[str, Any],
               rejected: dict[str, str]) -> list[dict[str, Any]]:
        since, until = self._window(inputs)

        def older_than_window(item: dict[str, Any]) -> bool:
            created = self._parse_time(item.get("created_time", ""))
            return bool(created and created < since)

        # video_reels is newest-first with no server-side date filter: stop
        # paginating at the first reel older than the window.
        raw = self._paginate(
            f"{page_id}/video_reels", {"fields": REEL_FIELDS, "limit": 50},
            int(inputs.get("max_items", 100)), stop=older_than_window,
        )
        metrics = inputs.get("reel_metrics") or DEFAULT_REEL_METRICS
        reels = []
        for r in raw:
            created = self._parse_time(r.get("created_time", ""))
            if created and not (since <= created < until):
                continue  # video_reels has no server-side date filter
            insights = self._lifetime_values(
                self._insights(f"{r['id']}/video_insights", metrics, {}, rejected)
            ) if r.get("id") else {}
            plays = next(
                (insights[k] for k in ("fb_reels_total_plays", "blue_reels_play_count")
                 if isinstance(insights.get(k), (int, float))),
                None,
            )
            reels.append({
                "id": r.get("id"),
                "created_time": r.get("created_time"),
                "permalink_url": r.get("permalink_url"),
                "description": (r.get("description") or r.get("title") or "")[:500],
                "length_s": r.get("length"),
                "plays": plays,
                "insights": insights,
            })
        return reels

    def _probe(self, page_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
        """Test each candidate metric on the page, the latest post and latest reel."""
        since, until = self._window({**inputs, "days": min(int(inputs.get("days", 28)), 28)})
        result: dict[str, Any] = {}

        def probe(path: str, metrics: list[str], extra: dict[str, Any]) -> dict[str, Any]:
            accepted, rejected = [], {}
            for m in metrics:
                try:
                    self._get(path, {**extra, "metric": m})
                    accepted.append(m)
                except GraphAPIError as exc:
                    if exc.code == TOKEN_ERROR_CODE:
                        raise
                    rejected[m] = str(exc)
            return {"accepted": accepted, "rejected": rejected}

        result["page"] = probe(
            f"{page_id}/insights", inputs.get("page_metrics") or DEFAULT_PAGE_METRICS,
            {"period": "day", "since": int(since.timestamp()), "until": int(until.timestamp())},
        )
        posts = self._get(f"{page_id}/posts", {"fields": "id", "limit": 1}).get("data") or []
        if posts:
            result["post"] = probe(
                f"{posts[0]['id']}/insights", inputs.get("post_metrics") or DEFAULT_POST_METRICS, {}
            )
        reels = self._get(f"{page_id}/video_reels", {"fields": "id", "limit": 1}).get("data") or []
        if reels:
            result["reel"] = probe(
                f"{reels[0]['id']}/video_insights", inputs.get("reel_metrics") or DEFAULT_REEL_METRICS, {}
            )
        return result

    # ------------------------------------------------------------------ #
    # Summary
    # ------------------------------------------------------------------ #

    def _summarize(self, posts: list[dict[str, Any]], reels: list[dict[str, Any]],
                   tz_name: str, top_n: int) -> dict[str, Any]:
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = timezone.utc
            tz_name = "UTC"

        weekday_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

        def bucket(items: list[dict[str, Any]], score_key: str) -> dict[str, Any]:
            by_day: dict[str, list[float]] = defaultdict(list)
            by_hour: dict[int, list[float]] = defaultdict(list)
            for it in items:
                score = it.get(score_key)
                created = self._parse_time(it.get("created_time", ""))
                if not isinstance(score, (int, float)) or not created:
                    continue
                local = created.astimezone(tz)
                by_day[weekday_names[local.weekday()]].append(score)
                by_hour[local.hour].append(score)

            def avg(d: dict) -> list[dict[str, Any]]:
                rows = [{"key": k, "count": len(v), "avg": round(sum(v) / len(v), 1)} for k, v in d.items()]
                return sorted(rows, key=lambda r: r["avg"], reverse=True)

            return {"by_weekday": avg(by_day), "by_hour": avg(by_hour)}

        summary: dict[str, Any] = {"timezone": tz_name}
        if posts:
            by_type: dict[str, list[int]] = defaultdict(list)
            for p in posts:
                by_type[p["media_type"]].append(p["engagement"])
            summary["posts"] = {
                "count": len(posts),
                "total_engagement": sum(p["engagement"] for p in posts),
                "avg_engagement": round(sum(p["engagement"] for p in posts) / len(posts), 1),
                "by_media_type": sorted(
                    [{"media_type": k, "count": len(v), "avg_engagement": round(sum(v) / len(v), 1)}
                     for k, v in by_type.items()],
                    key=lambda r: r["avg_engagement"], reverse=True,
                ),
                "top": [
                    {k: p.get(k) for k in ("id", "created_time", "media_type", "engagement",
                                           "reactions", "comments", "shares", "permalink_url", "message")}
                    for p in sorted(posts, key=lambda p: p["engagement"], reverse=True)[:top_n]
                ],
                **bucket(posts, "engagement"),
            }
        played = [r for r in reels if isinstance(r.get("plays"), (int, float))]
        if reels:
            summary["reels"] = {
                "count": len(reels),
                "total_plays": sum(r["plays"] for r in played) if played else None,
                "avg_plays": round(sum(r["plays"] for r in played) / len(played), 1) if played else None,
                "top": [
                    {k: r.get(k) for k in ("id", "created_time", "plays", "length_s", "permalink_url", "description")}
                    for r in sorted(played, key=lambda r: r["plays"], reverse=True)[:top_n]
                ],
                **bucket(reels, "plays"),
            }
        return summary

    @staticmethod
    def _summary_markdown(page: dict[str, Any], page_insights: dict[str, Any],
                          summary: dict[str, Any], rejected: dict[str, str],
                          warnings: Optional[list[str]] = None) -> str:
        def short(text: str, n: int = 80) -> str:
            text = " ".join((text or "").split())
            return text if len(text) <= n else text[: n - 1] + "…"

        lines = [f"# Facebook Page report: {page.get('name', '')}", ""]
        lines.append(
            f"Period: {page_insights.get('since')} → {page_insights.get('until')} "
            f"(timezone {summary.get('timezone')})  "
        )
        lines.append(
            f"Followers: {page.get('followers_count', 'n/a')} · Likes: {page.get('fan_count', 'n/a')}"
        )
        totals = page_insights.get("totals") or {}
        if totals:
            lines += ["", "## Page totals", "", "| Metric | Total |", "|---|---|"]
            lines += [f"| {k} | {v} |" for k, v in totals.items()]

        posts = summary.get("posts")
        if posts:
            lines += ["", "## Posts", "",
                      f"{posts['count']} posts, {posts['total_engagement']} engagements "
                      f"(avg {posts['avg_engagement']} per post; reactions + comments + shares).",
                      "", "| Media type | Posts | Avg engagement |", "|---|---|---|"]
            lines += [f"| {r['media_type']} | {r['count']} | {r['avg_engagement']} |"
                      for r in posts["by_media_type"]]
            lines += ["", "### Top posts", "", "| # | Date | Type | Engagement | Post |", "|---|---|---|---|---|"]
            for i, p in enumerate(posts["top"], 1):
                lines.append(
                    f"| {i} | {(p.get('created_time') or '')[:10]} | {p.get('media_type')} | "
                    f"{p.get('engagement')} | [{short(p.get('message')) or 'open'}]({p.get('permalink_url')}) |"
                )
            if posts.get("by_weekday"):
                lines += ["", "### Best weekdays (avg engagement)", ""]
                lines += [f"- {r['key']}: {r['avg']} ({r['count']} posts)" for r in posts["by_weekday"][:3]]
            if posts.get("by_hour"):
                lines += ["", "### Best hours (avg engagement)", ""]
                lines += [f"- {r['key']:02d}:00: {r['avg']} ({r['count']} posts)" for r in posts["by_hour"][:3]]

        reels = summary.get("reels")
        if reels:
            lines += ["", "## Reels", "", f"{reels['count']} reels, total plays {reels['total_plays']} "
                                          f"(avg {reels['avg_plays']})."]
            if reels["top"]:
                lines += ["", "| # | Date | Plays | Length (s) | Reel |", "|---|---|---|---|---|"]
                for i, r in enumerate(reels["top"], 1):
                    lines.append(
                        f"| {i} | {(r.get('created_time') or '')[:10]} | {r.get('plays')} | "
                        f"{r.get('length_s')} | [{short(r.get('description')) or 'open'}]({r.get('permalink_url')}) |"
                    )
            if reels.get("by_weekday"):
                lines += ["", "### Best weekdays (avg plays)", ""]
                lines += [f"- {r['key']}: {r['avg']} ({r['count']} reels)" for r in reels["by_weekday"][:3]]

        if warnings:
            lines += ["", "## Warnings", ""]
            lines += [f"- {w}" for w in warnings]
        if rejected:
            lines += ["", "## Metrics the API rejected", "",
                      "Run `operation: probe_metrics` to see the accepted list.", ""]
            lines += [f"- `{k}`" for k in sorted(rejected)]
        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------ #
    # Entry point
    # ------------------------------------------------------------------ #

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        start = time.time()
        operation = inputs.get("operation")
        if operation not in {"page_overview", "posts", "reels", "report", "probe_metrics"}:
            return ToolResult(success=False, error=f"Unknown operation: {operation!r}")
        output_dir = inputs.get("output_dir")
        if operation == "report" and not output_dir:
            return ToolResult(success=False, error="operation 'report' requires output_dir")

        rejected: dict[str, str] = {}
        self._warnings: list[str] = []
        data: dict[str, Any] = {"operation": operation}
        try:
            self._window(inputs)  # validate dates early
            page_id = self._page_id()
            data["page_id"] = page_id

            if operation == "probe_metrics":
                data["probe"] = self._probe(page_id, inputs)
            if operation in {"page_overview", "report"}:
                data["page"], data["page_insights"] = self._page_overview(page_id, inputs, rejected)
            if operation in {"posts", "report"}:
                data["posts"] = self._posts(page_id, inputs, rejected)
            if operation in {"reels", "report"}:
                try:
                    data["reels"] = self._reels(page_id, inputs, rejected)
                except GraphAPIError as exc:
                    if operation != "report" or exc.code == TOKEN_ERROR_CODE:
                        raise
                    data["reels"] = []
                    data["reels_error"] = str(exc)
            if operation in {"posts", "reels", "report"}:
                data["summary"] = self._summarize(
                    data.get("posts") or [], data.get("reels") or [],
                    inputs.get("timezone", "Asia/Ho_Chi_Minh"), int(inputs.get("top_n", 10)),
                )
        except GraphAPIError as exc:
            message = str(exc)
            if exc.code == TOKEN_ERROR_CODE:
                message += (
                    " — the Page access token is invalid or expired. Generate a new "
                    "long-lived Page token and update FACEBOOK_PAGE_ACCESS_TOKEN in .env."
                )
            elif exc.code in (10, 200) or (exc.code and 200 <= exc.code < 300):
                message += (
                    " — missing permission. The token needs pages_read_engagement and "
                    "read_insights, and you must be an admin of the Page."
                )
            return ToolResult(success=False, error=message, duration_seconds=time.time() - start)
        except ValueError as exc:
            return ToolResult(success=False, error=f"Invalid input: {exc}")

        data["rejected_metrics"] = rejected
        data["warnings"] = list(dict.fromkeys(self._warnings))
        data["fetched_at"] = datetime.now(timezone.utc).isoformat()

        artifacts: list[str] = []
        if output_dir:
            out = Path(output_dir)
            out.mkdir(parents=True, exist_ok=True)
            json_path = out / "insights.json"
            json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            artifacts.append(str(json_path))
            if operation == "report":
                md_path = out / "summary.md"
                md_path.write_text(
                    self._summary_markdown(data.get("page") or {}, data.get("page_insights") or {},
                                           data.get("summary") or {}, rejected, data["warnings"]),
                    encoding="utf-8",
                )
                artifacts.append(str(md_path))

        return ToolResult(
            success=True, data=data, artifacts=artifacts, cost_usd=0.0,
            duration_seconds=time.time() - start, model="meta-graph-api",
        )
