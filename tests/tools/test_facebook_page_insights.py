"""Contract coverage for the Facebook Page Insights tool (no network)."""

from __future__ import annotations

import json
import sys
import types
from urllib.parse import urlparse

import pytest

from tools.base_tool import ToolStatus

TOKEN = "EAAtest-secret-token"


class _Resp:
    def __init__(self, body, status=200):
        self._body = body
        self.status_code = status

    def json(self):
        return self._body


def _err(code, message="boom", subcode=None, status=400):
    return _Resp({"error": {"code": code, "message": message, "error_subcode": subcode}}, status)


@pytest.fixture
def graph(monkeypatch):
    """Fake `requests` routing on URL path; handlers return _Resp."""
    calls: list[tuple[str, dict]] = []
    routes: dict[str, object] = {}

    def get(url, params=None, timeout=None):
        calls.append((url, dict(params or {})))
        path = urlparse(url).path.split("/", 2)[-1]  # drop leading "/vXX.X/"
        handler = routes.get(url) or routes.get(path)
        if handler is None:
            raise AssertionError(f"unexpected call {path}")
        return handler(params or {}) if callable(handler) else handler

    mod = types.ModuleType("requests")
    mod.get = get
    monkeypatch.setitem(sys.modules, "requests", mod)
    monkeypatch.setattr("time.sleep", lambda s: None)
    for k in ("FACEBOOK_PAGE_ID", "FACEBOOK_APP_SECRET", "FACEBOOK_GRAPH_API_VERSION"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("FACEBOOK_PAGE_ACCESS_TOKEN", TOKEN)
    # Default: a Page token (User-only edge /me/accounts does not exist).
    routes["me/accounts"] = _err(100, "(#100) Tried accessing nonexisting field (accounts)")
    return calls, routes


def _tool():
    from tools.analysis.facebook_page_insights import FacebookPageInsights
    return FacebookPageInsights()


def test_status_depends_on_token(monkeypatch):
    monkeypatch.delenv("FACEBOOK_PAGE_ACCESS_TOKEN", raising=False)
    assert _tool().get_status() == ToolStatus.UNAVAILABLE
    monkeypatch.setenv("FACEBOOK_PAGE_ACCESS_TOKEN", TOKEN)
    assert _tool().get_status() == ToolStatus.AVAILABLE


def test_registry_discovers_tool():
    from tools.tool_registry import registry
    registry.discover()
    assert registry.get("facebook_page_insights") is not None


def test_posts_paginate_and_resolve_page_id(graph):
    calls, routes = graph
    routes["me"] = _Resp({"id": "123", "name": "My Page"})
    next_url = "https://graph.facebook.com/v24.0/123/posts?after=CUR&access_token=" + TOKEN
    routes["123/posts"] = _Resp({
        "data": [{
            "id": "123_1", "created_time": "2026-11-01T12:00:00+0000", "message": "hello",
            "reactions": {"summary": {"total_count": 10}},
            "comments": {"summary": {"total_count": 2}},
            "shares": {"count": 3},
            "attachments": {"data": [{"media_type": "video"}]},
        }],
        "paging": {"next": next_url},
    })
    routes[next_url] = _Resp({"data": [{
        "id": "123_2", "created_time": "2026-11-02T01:00:00+0000",
        "reactions": {"summary": {"total_count": 1}},
        "comments": {"summary": {"total_count": 0}},
    }]})

    result = _tool().execute({"operation": "posts", "include_post_insights": False})

    assert result.success, result.error
    posts = result.data["posts"]
    assert [p["id"] for p in posts] == ["123_1", "123_2"]
    assert posts[0]["engagement"] == 15 and posts[0]["media_type"] == "video"
    assert posts[1]["media_type"] == "status"
    assert result.data["summary"]["posts"]["top"][0]["id"] == "123_1"
    # 12:00 UTC -> 19:00 in Asia/Ho_Chi_Minh
    assert result.data["summary"]["posts"]["by_hour"][0]["key"] == 19
    # Auth goes in params on direct calls, never as an input.
    assert calls[0][1]["access_token"] == TOKEN


def test_invalid_metric_is_dropped_not_fatal(graph):
    calls, routes = graph
    routes["me"] = _Resp({"id": "123"})
    routes["123/posts"] = _Resp({"data": [
        {"id": "123_1", "created_time": "2026-11-01T12:00:00+0000"},
        {"id": "123_2", "created_time": "2026-11-02T12:00:00+0000"},
    ]})

    def insights(params):
        metric = params["metric"]
        if "post_dead" in metric:
            return _err(100, "(#100) The value must be a valid insights metric")
        return _Resp({"data": [{"name": metric, "period": "lifetime", "values": [{"value": 42}]}]})

    routes["123_1/insights"] = insights
    routes["123_2/insights"] = insights

    result = _tool().execute({"operation": "posts", "post_metrics": ["post_clicks", "post_dead"]})

    assert result.success, result.error
    assert result.data["posts"][0]["insights"] == {"post_clicks": 42}
    assert "post_dead" in result.data["rejected_metrics"]
    # Second post skips the rejected metric: one call, not a failed batch first.
    second = [p for u, p in calls if u.endswith("123_2/insights")]
    assert [p["metric"] for p in second] == ["post_clicks"]


def test_expired_token_error_is_clear_and_scrubbed(graph):
    calls, routes = graph
    routes["me"] = _err(190, f"Error validating access token: access_token={TOKEN}")

    result = _tool().execute({"operation": "posts"})

    assert not result.success
    assert "code=190" in result.error and "expired" in result.error
    assert TOKEN not in result.error


def test_rate_limit_is_retried(graph):
    calls, routes = graph
    responses = [_err(4, "Application request limit reached"), _Resp({"id": "123"})]
    routes["me"] = lambda params: responses.pop(0)
    routes["123/posts"] = _Resp({"data": []})

    result = _tool().execute({"operation": "posts"})

    assert result.success, result.error
    assert len([c for c in calls if c[0].endswith("/me")]) == 2


def test_report_writes_files(graph, tmp_path, monkeypatch):
    calls, routes = graph
    monkeypatch.setenv("FACEBOOK_PAGE_ID", "123")
    monkeypatch.setenv("FACEBOOK_APP_SECRET", "s3cret")
    routes["123"] = _Resp({"id": "123", "name": "My Page", "followers_count": 500, "fan_count": 450})
    routes["123/insights"] = _Resp({"data": [{
        "name": "page_post_engagements", "period": "day",
        "values": [{"value": 5, "end_time": "2026-11-01T08:00:00+0000"},
                   {"value": 7, "end_time": "2026-11-02T08:00:00+0000"}],
    }]})
    routes["123/posts"] = _Resp({"data": [{
        "id": "123_1", "created_time": "2026-11-01T12:00:00+0000", "message": "Tập 1",
        "permalink_url": "https://facebook.com/123_1",
        "reactions": {"summary": {"total_count": 4}}, "comments": {"summary": {"total_count": 1}},
    }]})
    routes["123/video_reels"] = _Resp({"data": [
        {"id": "v1", "created_time": "2026-11-03T10:00:00+0000", "description": "reel"},
        {"id": "old", "created_time": "2020-01-01T10:00:00+0000"},  # outside window
    ]})
    routes["v1/video_insights"] = _Resp({"data": [
        {"name": "fb_reels_total_plays", "period": "lifetime", "values": [{"value": 900}]},
    ]})

    out = tmp_path / "fb"
    result = _tool().execute({
        "operation": "report", "since": "2026-10-20", "until": "2026-11-10",
        "include_post_insights": False, "output_dir": str(out),
    })

    assert result.success, result.error
    assert result.data["page_insights"]["totals"]["page_post_engagements"] == 12
    assert [r["id"] for r in result.data["reels"]] == ["v1"]
    assert result.data["summary"]["reels"]["total_plays"] == 900
    saved = json.loads((out / "insights.json").read_text())
    md = (out / "summary.md").read_text()
    assert saved["page"]["name"] == "My Page"
    assert "My Page" in md and "Tập 1" in md
    assert TOKEN not in (out / "insights.json").read_text()
    assert all("appsecret_proof" in p for u, p in calls)


def test_report_requires_output_dir(graph):
    result = _tool().execute({"operation": "report"})
    assert not result.success and "output_dir" in result.error


def test_multi_chunk_page_insights_dedupe_boundary_days(graph, monkeypatch):
    calls, routes = graph
    monkeypatch.setenv("FACEBOOK_PAGE_ID", "123")
    routes["123"] = _Resp({"id": "123", "name": "My Page"})
    chunks = [
        [("2026-03-01", 1), ("2026-03-31", 2)],
        [("2026-03-31", 2), ("2026-04-15", 3)],  # boundary day returned again
    ]

    def insights(params):
        rows = chunks.pop(0) if chunks else []
        return _Resp({"data": [{"name": "page_post_engagements", "values": [
            {"end_time": f"{d}T08:00:00+0000", "value": v} for d, v in rows]}]})

    routes["123/insights"] = insights

    result = _tool().execute({"operation": "page_overview", "since": "2026-01-01",
                              "until": "2026-05-01", "page_metrics": ["page_post_engagements"]})

    assert result.success, result.error
    assert len([u for u, _ in calls if u.endswith("123/insights")]) == 2
    assert result.data["page_insights"]["totals"]["page_post_engagements"] == 6
    assert len(result.data["page_insights"]["daily"]["page_post_engagements"]) == 3


def test_all_metrics_failing_adds_warning(graph):
    calls, routes = graph
    routes["me"] = _Resp({"id": "123"})
    routes["123/posts"] = _Resp({"data": [{"id": "123_1", "created_time": "2026-11-01T12:00:00+0000"}]})
    routes["123_1/insights"] = _err(100, "(#100) Tried accessing nonexisting field")

    result = _tool().execute({"operation": "posts", "post_metrics": ["a", "b"]})

    assert result.success, result.error
    assert result.data["warnings"] and "probe_metrics" in result.data["warnings"][0]


def test_reels_stop_paginating_before_window(graph):
    calls, routes = graph
    routes["me"] = _Resp({"id": "123"})
    next_url = "https://graph.facebook.com/v24.0/123/video_reels?after=X"
    routes["123/video_reels"] = _Resp({
        "data": [{"id": "new", "created_time": "2026-11-10T10:00:00+0000"},
                 {"id": "old", "created_time": "2025-01-01T10:00:00+0000"}],
        "paging": {"next": next_url},
    })
    routes["new/video_insights"] = _Resp({"data": []})

    result = _tool().execute({"operation": "reels", "since": "2026-11-01", "until": "2026-11-14"})

    assert result.success, result.error
    assert [r["id"] for r in result.data["reels"]] == ["new"]
    assert not any(u == next_url for u, _ in calls)


PAGE_TOKEN = "EAApage-token-for-tisorr"


def test_user_token_without_page_id_lists_pages(graph):
    calls, routes = graph
    routes["me/accounts"] = _Resp({"data": [
        {"id": "111", "name": "Tisorr", "access_token": PAGE_TOKEN},
        {"id": "222", "name": "BingeBox", "access_token": "other"},
    ]})

    result = _tool().execute({"operation": "posts"})

    assert not result.success
    assert "User token" in result.error and "Tisorr (111)" in result.error
    assert PAGE_TOKEN not in result.error


def test_user_token_switches_to_page_token(graph, monkeypatch):
    calls, routes = graph
    monkeypatch.setenv("FACEBOOK_PAGE_ID", "111")
    routes["me/accounts"] = _Resp({"data": [{"id": "111", "name": "Tisorr", "access_token": PAGE_TOKEN}]})
    routes["111/posts"] = _Resp({"data": []})

    result = _tool().execute({"operation": "posts"})

    assert result.success, result.error
    posts_call = next(p for u, p in calls if u.endswith("111/posts"))
    assert posts_call["access_token"] == PAGE_TOKEN
    assert PAGE_TOKEN not in json.dumps(result.data)


def test_user_token_with_unknown_page_id(graph, monkeypatch):
    calls, routes = graph
    monkeypatch.setenv("FACEBOOK_PAGE_ID", "999")
    routes["me/accounts"] = _Resp({"data": [{"id": "111", "name": "Tisorr", "access_token": PAGE_TOKEN}]})

    result = _tool().execute({"operation": "posts"})

    assert not result.success and "999" in result.error and "Tisorr" in result.error


def test_probe_survives_missing_reels_edge(graph):
    calls, routes = graph
    routes["me"] = _Resp({"id": "123"})
    routes["123/insights"] = _Resp({"data": []})
    routes["123/posts"] = _Resp({"data": []})
    routes["123/video_reels"] = _err(100, "(#100) Tried accessing nonexisting field (video_reels)")

    result = _tool().execute({"operation": "probe_metrics", "page_metrics": ["page_post_engagements"]})

    assert result.success, result.error
    assert result.data["probe"]["page"]["accepted"] == ["page_post_engagements"]
    assert "video_reels" in result.data["probe"]["reel"]["error"]


def test_snapshot_metric_total_is_latest_value(graph, monkeypatch):
    calls, routes = graph
    monkeypatch.setenv("FACEBOOK_PAGE_ID", "123")
    routes["123"] = _Resp({"id": "123", "name": "My Page"})
    routes["123/insights"] = _Resp({"data": [{"name": "page_follows", "values": [
        {"end_time": "2026-11-0%dT08:00:00+0000" % d, "value": v} for d, v in ((1, 7), (2, 8), (3, 13))]}]})

    result = _tool().execute({"operation": "page_overview", "since": "2026-11-01",
                              "until": "2026-11-04", "page_metrics": ["page_follows"]})

    assert result.data["page_insights"]["totals"]["page_follows"] == 13
