"""Contract coverage for the PiAPI Ace-Step music tool (no network)."""

from __future__ import annotations

import sys
import types

import pytest

from tools.base_tool import ToolStatus


class _Resp:
    def __init__(self, body=None, status=200, content=b""):
        self._body = body
        self.status_code = status
        self.content = content
        self.text = str(body)

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture
def fake_requests(monkeypatch):
    calls = {"post": [], "get": []}
    script = {"post": [], "get": []}

    def post(url, **kw):
        calls["post"].append((url, kw))
        return script["post"].pop(0)

    def get(url, **kw):
        calls["get"].append((url, kw))
        return script["get"].pop(0)

    mod = types.ModuleType("requests")
    mod.post = post
    mod.get = get
    monkeypatch.setitem(sys.modules, "requests", mod)
    monkeypatch.setattr("time.sleep", lambda s: None)
    return calls, script


def _tool(monkeypatch, key="test-piapi-key"):
    from tools.audio.acestep_piapi import AceStepPiAPI

    monkeypatch.delenv("PIAPI_KEY", raising=False)
    if key:
        monkeypatch.setenv("PIAPI_API_KEY", key)
    else:
        monkeypatch.delenv("PIAPI_API_KEY", raising=False)
    return AceStepPiAPI()


def test_discovered_as_music_generation_tool():
    from tools.tool_registry import ToolRegistry

    registry = ToolRegistry()
    registry.discover()
    tool = registry.get("acestep_piapi")
    assert tool is not None
    assert tool.capability == "music_generation"
    assert tool.provider == "piapi"


def test_status_follows_api_key(monkeypatch):
    assert _tool(monkeypatch, key=None).get_status() == ToolStatus.UNAVAILABLE
    assert _tool(monkeypatch).get_status() == ToolStatus.AVAILABLE


def test_cost_matches_piapi_pricing(monkeypatch):
    t = _tool(monkeypatch)
    assert t.estimate_cost({"duration": 30}) == 0.015
    assert t.estimate_cost({"duration": 10}) == 0.005
    assert t.estimate_cost({}) == 0.015  # default 30s


def test_execute_validation(monkeypatch):
    t = _tool(monkeypatch)
    r = t.execute({"style_prompt": "  "})
    assert not r.success and "style_prompt" in r.error
    r = t.execute({"style_prompt": "x", "duration": 5})
    assert not r.success and "10-240" in r.error


def test_execute_defaults_to_instrumental_and_downloads(monkeypatch, tmp_path, fake_requests):
    calls, script = fake_requests
    script["post"].append(_Resp({"code": 200, "data": {"task_id": "t-1", "status": "pending"}}))
    script["get"] += [
        _Resp({"code": 200, "data": {"task_id": "t-1", "status": "processing"}}),
        _Resp({"code": 200, "data": {"task_id": "t-1", "status": "completed",
                                     "output": {"audio_url": "https://cdn/out.mp3"}}}),
        _Resp(content=b"MP3DATA"),
    ]
    out = tmp_path / "music.mp3"
    r = _tool(monkeypatch).execute({"style_prompt": "upbeat playful adventure", "duration": 30,
                                    "output_path": str(out)})
    assert r.success, r.error
    assert out.read_bytes() == b"MP3DATA"
    assert r.cost_usd == 0.015
    assert r.data["task_id"] == "t-1"
    create_url, kw = calls["post"][0]
    assert create_url == "https://api.piapi.ai/api/v1/task"
    assert kw["headers"]["X-API-Key"] == "test-piapi-key"
    assert kw["json"]["model"] == "Qubico/ace-step"
    assert kw["json"]["task_type"] == "txt2audio"
    assert kw["json"]["input"]["lyrics"] == "[inst]"  # instrumental default
    assert kw["json"]["input"]["duration"] == 30
    assert calls["get"][0][0] == "https://api.piapi.ai/api/v1/task/t-1"


def test_execute_custom_lyrics_and_negative_prompt(monkeypatch, tmp_path, fake_requests):
    calls, script = fake_requests
    script["post"].append(_Resp({"code": 200, "data": {"task_id": "t-2", "status": "completed",
                                                        "output": {"audio_url": "https://cdn/o.mp3"}}}))
    script["get"].append(_Resp(content=b"X"))
    _tool(monkeypatch).execute({
        "style_prompt": "cinematic strings", "negative_style_prompt": "distorted, sad",
        "lyrics": "la la la", "duration": 20, "output_path": str(tmp_path / "o.mp3"),
    })
    body = calls["post"][0][1]["json"]["input"]
    assert body["lyrics"] == "la la la" and body["negative_style_prompt"] == "distorted, sad"


def test_execute_reports_failed_task(monkeypatch, tmp_path, fake_requests):
    _, script = fake_requests
    script["post"].append(_Resp({"code": 200, "data": {"task_id": "t-3", "status": "pending"}}))
    script["get"].append(_Resp({"code": 200, "data": {"status": "failed", "error": {"message": "nope"}}}))
    r = _tool(monkeypatch).execute({"style_prompt": "x", "output_path": str(tmp_path / "o.mp3")})
    assert not r.success
    assert "t-3" in r.error and "nope" in r.error


def test_execute_no_api_key(monkeypatch):
    r = _tool(monkeypatch, key=None).execute({"style_prompt": "x"})
    assert not r.success and "PIAPI_API_KEY" in r.error
