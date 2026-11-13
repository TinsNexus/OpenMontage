"""Contract coverage for the PiAPI-hosted Seedance tool (no network)."""

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
    from tools.video.seedance_piapi import SeedancePiAPI

    monkeypatch.delenv("PIAPI_KEY", raising=False)
    if key:
        monkeypatch.setenv("PIAPI_API_KEY", key)
    else:
        monkeypatch.delenv("PIAPI_API_KEY", raising=False)
    return SeedancePiAPI()


def test_discovered_as_seedance_video_provider():
    from tools.tool_registry import ToolRegistry

    registry = ToolRegistry()
    registry.discover()
    tool = registry.get("seedance_piapi")
    assert tool is not None
    assert tool.provider == "seedance"
    assert tool.capability == "video_generation"


def test_status_follows_api_key(monkeypatch):
    assert _tool(monkeypatch, key=None).get_status() == ToolStatus.UNAVAILABLE
    assert _tool(monkeypatch).get_status() == ToolStatus.AVAILABLE


def test_cost_matches_piapi_pricing(monkeypatch):
    t = _tool(monkeypatch)
    assert t.estimate_cost({"prompt": "x", "model_variant": "2.5", "duration": 10, "resolution": "720p"}) == 6.0
    assert t.estimate_cost({"prompt": "x", "model_variant": "standard", "duration": 10}) == 2.0
    assert t.estimate_cost({"prompt": "x", "model_variant": "fast", "duration": 5, "resolution": "480p"}) == 0.24


def test_payload_text_to_video_25(monkeypatch):
    t = _tool(monkeypatch)
    p = t._build_payload(
        {"prompt": "city", "model_variant": "2.5", "duration": "20", "generate_audio": False}, "k"
    )
    assert p == {
        "model": "seedance",
        "task_type": "seedance-2.5",
        "input": {
            "prompt": "city",
            "mode": "text_to_video",
            "duration": 20,
            "resolution": "720p",
            "audio": False,
            "aspect_ratio": "16:9",
        },
    }


@pytest.mark.parametrize(
    "inputs, msg",
    [
        ({"model_variant": "standard", "duration": 20}, "4-15"),
        ({"model_variant": "2.5", "resolution": "1080p"}, "does not support 1080p"),
        ({"model_variant": "fast", "resolution": "1080p"}, "does not support 1080p"),
        ({"model_variant": "2.5", "less_restriction": True}, "not available for Seedance 2.5"),
        ({"operation": "reference_to_video"}, "1-15 references"),
        ({"operation": "image_to_video"}, "needs image_url"),
        ({"aspect_ratio": "auto"}, "only valid for image_to_video"),
    ],
)
def test_payload_validation(monkeypatch, inputs, msg):
    t = _tool(monkeypatch)
    with pytest.raises(ValueError, match=msg):
        t._build_payload({"prompt": "x", **inputs}, "k")


def test_less_restriction_task_type(monkeypatch):
    t = _tool(monkeypatch)
    p = t._build_payload({"prompt": "x", "model_variant": "fast", "less_restriction": True}, "k")
    assert p["task_type"] == "seedance-2-fast-less-restriction"


def test_reference_to_video_uploads_local_image(monkeypatch, tmp_path, fake_requests):
    calls, script = fake_requests
    img = tmp_path / "sasa.png"
    img.write_bytes(b"\x89PNG fake")
    script["post"].append(_Resp({"code": 200, "data": {"url": "https://cdn/sasa.png"}}))

    t = _tool(monkeypatch)
    p = t._build_payload(
        {
            "prompt": "@image1 fights",
            "operation": "reference_to_video",
            "reference_image_urls": ["https://cdn/room.png"],
            "reference_image_paths": [str(img)],
        },
        "k",
    )
    assert p["input"]["mode"] == "omni_reference"
    assert p["input"]["image_urls"] == ["https://cdn/room.png", "https://cdn/sasa.png"]
    url, kw = calls["post"][0]
    assert url == "https://upload.theapi.app/api/ephemeral_resource"
    assert kw["headers"]["x-api-key"] == "k"
    assert base64.b64decode(kw["json"]["file_data"]) == b"\x89PNG fake"
    assert kw["json"]["file_name"] == "sasa.png"


def test_execute_create_poll_download(monkeypatch, tmp_path, fake_requests):
    calls, script = fake_requests
    script["post"].append(_Resp({"code": 200, "data": {"task_id": "t-1", "status": "pending"}}))
    script["get"] += [
        _Resp({"code": 200, "data": {"task_id": "t-1", "status": "processing"}}),
        _Resp({"code": 200, "data": {"task_id": "t-1", "status": "completed",
                                     "output": {"video": "https://cdn/out.mp4"},
                                     "meta": {"usage": {"consume": 600}}}}),
        _Resp(content=b"MP4DATA"),
    ]
    out = tmp_path / "clip.mp4"
    r = _tool(monkeypatch).execute(
        {"prompt": "x", "model_variant": "2.5", "duration": 10, "output_path": str(out)}
    )
    assert r.success, r.error
    assert out.read_bytes() == b"MP4DATA"
    assert r.data["task_id"] == "t-1"
    assert r.data["model"] == "seedance-2.5"
    assert r.cost_usd == 6.0
    create_url, kw = calls["post"][0]
    assert create_url == "https://api.piapi.ai/api/v1/task"
    assert kw["headers"]["X-API-Key"] == "test-piapi-key"
    assert calls["get"][0][0] == "https://api.piapi.ai/api/v1/task/t-1"
    # prompt provenance sidecar for the Backlot gallery
    import json
    meta = json.loads((tmp_path / "clip.meta.json").read_text())
    assert meta["prompt"] == "x"
    assert meta["model"] == "seedance-2.5"
    assert meta["task_id"] == "t-1"
    assert meta["cost_usd"] == 6.0


def test_execute_reports_failed_task(monkeypatch, tmp_path, fake_requests):
    _, script = fake_requests
    script["post"].append(_Resp({"code": 200, "data": {"task_id": "t-2", "status": "pending"}}))
    script["get"].append(
        _Resp({"code": 200, "data": {"status": "failed", "error": {"message": "content rejected"}}})
    )
    r = _tool(monkeypatch).execute({"prompt": "x", "output_path": str(tmp_path / "o.mp4")})
    assert not r.success
    assert "t-2" in r.error and "content rejected" in r.error


def test_execute_surfaces_http_error_message(monkeypatch, tmp_path, fake_requests):
    _, script = fake_requests
    script["post"].append(_Resp({"code": 401, "message": "invalid api key"}, status=401))
    r = _tool(monkeypatch).execute({"prompt": "x", "output_path": str(tmp_path / "o.mp4")})
    assert not r.success
    assert "invalid api key" in r.error
