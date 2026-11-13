"""Contract coverage for the PiAPI-hosted Kling tool (no network)."""

from __future__ import annotations

import base64
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
    monkeypatch.setattr("tools.video._shared.probe_output", lambda p: {"duration": 10.0})
    return calls, script


def _tool(monkeypatch, key="test-piapi-key"):
    from tools.video.kling_piapi import KlingPiAPI

    monkeypatch.delenv("PIAPI_KEY", raising=False)
    if key:
        monkeypatch.setenv("PIAPI_API_KEY", key)
    else:
        monkeypatch.delenv("PIAPI_API_KEY", raising=False)
    return KlingPiAPI()


def test_discovered_as_kling_video_provider():
    from tools.tool_registry import ToolRegistry

    registry = ToolRegistry()
    registry.discover()
    tool = registry.get("kling_piapi")
    assert tool is not None
    assert tool.provider == "kling"
    assert tool.capability == "video_generation"


def test_status_follows_api_key(monkeypatch):
    assert _tool(monkeypatch, key=None).get_status() == ToolStatus.UNAVAILABLE
    assert _tool(monkeypatch).get_status() == ToolStatus.AVAILABLE


def test_cost_matches_piapi_pricing(monkeypatch):
    t = _tool(monkeypatch)
    assert t.estimate_cost({"prompt": "x", "version": "4.0", "duration": 10, "mode": "std"}) == 1.67
    assert t.estimate_cost({"prompt": "x", "version": "4.0", "duration": 10, "mode": "pro"}) == 2.5
    assert t.estimate_cost({"prompt": "x", "version": "3.0", "duration": 10, "mode": "std", "enable_audio": True}) == 1.5
    assert t.estimate_cost({"prompt": "x", "version": "2.6", "duration": 5, "mode": "std"}) == 0.20
    assert t.estimate_cost({"prompt": "x", "version": "2.6", "duration": 10, "mode": "pro"}) == 0.66


def test_payload_text_to_video_default(monkeypatch):
    t = _tool(monkeypatch)
    p = t._build_payload({"prompt": "city street", "duration": 5}, "k")
    assert p == {
        "model": "kling",
        "task_type": "video_generation",
        "input": {
            "version": "2.6",
            "mode": "std",
            "prompt": "city street",
            "duration": 5,
            "aspect_ratio": "16:9",
        },
    }


@pytest.mark.parametrize(
    "inputs, msg",
    [
        ({"version": "4.0-flash", "mode": "pro"}, "std"),
        ({"version": "2.1-master", "mode": "std"}, "pro"),
        ({"version": "2.6", "duration": 7}, "5 or 10"),
        ({"version": "4.0", "duration": 1}, "3-30"),
        ({"negative_prompt": "bad", "version": "4.0"}, "not accepted by 4.0"),
        ({"aspect_ratio": "21:9", "version": "2.6"}, "4.0 / 4.0-flash"),
        ({"image_tail_url": "https://cdn/last.png"}, "requires image_url"),
        ({"enable_audio": True, "version": "4.0"}, "not accepted by Kling 4.0"),
        ({"enable_audio": True, "version": "2.6", "mode": "std"}, "requires mode 'pro'"),
        ({"multi_shots": [{"prompt": "a"}], "version": "2.6"}, "only available for version 3.0"),
    ],
)
def test_payload_validation(monkeypatch, inputs, msg):
    t = _tool(monkeypatch)
    with pytest.raises(ValueError, match=msg):
        t._build_payload({"prompt": "x", **inputs}, "k")


def test_multi_shots_payload(monkeypatch):
    t = _tool(monkeypatch)
    p = t._build_payload(
        {"version": "3.0", "multi_shots": [{"prompt": "a", "duration": 5}, {"prompt": "b", "duration": 5}]}, "k"
    )
    assert p["input"]["multi_shots"] == [
        {"prompt": "a", "duration": 5}, {"prompt": "b", "duration": 5},
    ]
    assert "prompt" not in p["input"] or p["input"].get("multi_shots")


def test_image_to_video_uploads_local_image(monkeypatch, tmp_path, fake_requests):
    calls, script = fake_requests
    img = tmp_path / "vy.png"
    img.write_bytes(b"\x89PNG fake")
    script["post"].append(_Resp({"code": 200, "data": {"url": "https://cdn/vy.png"}}))

    t = _tool(monkeypatch)
    p = t._build_payload({"prompt": "ride off", "image_path": str(img)}, "k")
    assert p["input"]["image_url"] == "https://cdn/vy.png"
    url, kw = calls["post"][0]
    assert url == "https://upload.theapi.app/api/ephemeral_resource"
    assert kw["headers"]["x-api-key"] == "k"
    assert base64.b64decode(kw["json"]["file_data"]) == b"\x89PNG fake"


def test_execute_create_poll_download(monkeypatch, tmp_path, fake_requests):
    calls, script = fake_requests
    script["post"].append(_Resp({"code": 200, "data": {"task_id": "t-1", "status": "pending"}}))
    script["get"] += [
        _Resp({"code": 200, "data": {"task_id": "t-1", "status": "processing"}}),
        _Resp({"code": 200, "data": {"task_id": "t-1", "status": "completed",
                                     "output": {"video": "https://cdn/out.mp4"},
                                     "meta": {"usage": {"consume": 500}}}}),
        _Resp(content=b"MP4DATA"),
    ]
    out = tmp_path / "clip.mp4"
    r = _tool(monkeypatch).execute(
        {"prompt": "x", "version": "4.0", "duration": 10, "mode": "std", "output_path": str(out)}
    )
    assert r.success, r.error
    assert out.read_bytes() == b"MP4DATA"
    assert r.data["task_id"] == "t-1"
    assert r.data["model"] == "kling-4.0"
    assert r.cost_usd == 1.67
    create_url, kw = calls["post"][0]
    assert create_url == "https://api.piapi.ai/api/v1/task"
    assert kw["headers"]["X-API-Key"] == "test-piapi-key"
    assert kw["json"]["model"] == "kling"
    assert calls["get"][0][0] == "https://api.piapi.ai/api/v1/task/t-1"
    import json
    meta = json.loads((tmp_path / "clip.meta.json").read_text())
    assert meta["prompt"] == "x"
    assert meta["model"] == "kling-4.0"
    assert meta["task_id"] == "t-1"
    assert meta["cost_usd"] == 1.67


def test_execute_reports_failed_task(monkeypatch, tmp_path, fake_requests):
    _, script = fake_requests
    script["post"].append(_Resp({"code": 200, "data": {"task_id": "t-2", "status": "pending"}}))
    script["get"].append(
        _Resp({"code": 200, "data": {"status": "failed", "error": {"message": "content rejected"}}})
    )
    r = _tool(monkeypatch).execute({"prompt": "x", "output_path": str(tmp_path / "o.mp4")})
    assert not r.success
    assert "t-2" in r.error and "content rejected" in r.error


def test_execute_no_api_key(monkeypatch):
    r = _tool(monkeypatch, key=None).execute({"prompt": "x"})
    assert not r.success and "PIAPI_API_KEY" in r.error
