"""Contract coverage for the PiAPI Luma (Ray2) video tool (no network)."""

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
    monkeypatch.setattr("tools.video._shared.probe_output", lambda p: {"duration": 5.0})
    return calls, script


def _luma(monkeypatch, key="test-piapi-key"):
    from tools.video.luma_piapi import LumaPiAPI

    monkeypatch.delenv("PIAPI_KEY", raising=False)
    if key:
        monkeypatch.setenv("PIAPI_API_KEY", key)
    else:
        monkeypatch.delenv("PIAPI_API_KEY", raising=False)
    return LumaPiAPI()


def test_discovered_as_video_provider():
    from tools.tool_registry import ToolRegistry

    registry = ToolRegistry()
    registry.discover()
    tool = registry.get("luma_piapi")
    assert tool is not None
    assert tool.provider == "luma"
    assert tool.capability == "video_generation"


def test_status_follows_api_key(monkeypatch):
    assert _luma(monkeypatch, key=None).get_status() == ToolStatus.UNAVAILABLE
    assert _luma(monkeypatch).get_status() == ToolStatus.AVAILABLE


@pytest.mark.parametrize("inputs,cost", [({}, 0.20), ({"duration": 9}, 0.40), ({"duration": 7}, 0.0)])
def test_cost_matches_piapi_pricing(monkeypatch, inputs, cost):
    assert _luma(monkeypatch).estimate_cost({"prompt": "x", **inputs}) == cost


def test_text_to_video_payload(monkeypatch):
    p = _luma(monkeypatch)._build_payload({"prompt": "a fox", "aspect_ratio": "9:16", "duration": 9}, "k")
    assert p["model"] == "luma" and p["task_type"] == "video_generation"
    assert p["config"] == {"service_mode": "public"}
    assert p["input"] == {"prompt": "a fox", "model": "ray-v2", "duration": 9, "aspect_ratio": "9:16", "loop": False}


def test_start_and_end_frames(monkeypatch, tmp_path):
    tool = _luma(monkeypatch)
    uploaded = []
    monkeypatch.setattr("tools.piapi_client.upload", lambda path, key: uploaded.append(path) or "https://up/end.png")
    end = tmp_path / "end.png"
    end.write_bytes(b"png")
    p = tool._build_payload(
        {"prompt": "x", "image_url": "https://a/start.png", "end_image_path": str(end), "loop": True}, "k"
    )
    assert p["input"]["start_image"] == "https://a/start.png"
    assert p["input"]["end_image"] == "https://up/end.png"
    assert p["input"]["loop"] is True
    assert uploaded == [str(end)]


@pytest.mark.parametrize("inputs,msg", [
    ({"duration": 10}, "5 or 9"),
    ({"aspect_ratio": "2:1"}, "aspect_ratio"),
    ({"model": "ray-v1"}, "model"),
    ({"prompt": ""}, "prompt is required"),
])
def test_payload_validation(monkeypatch, inputs, msg):
    with pytest.raises(ValueError, match=msg):
        _luma(monkeypatch)._build_payload({"prompt": "x", **inputs}, "k")


def test_execute_create_poll_download(monkeypatch, tmp_path, fake_requests):
    calls, script = fake_requests
    script["post"].append(_Resp({"code": 200, "data": {"task_id": "l-1", "status": "pending"}}))
    script["get"] += [
        _Resp({"code": 200, "data": {"task_id": "l-1", "status": "processing"}}),
        _Resp({"code": 200, "data": {"task_id": "l-1", "status": "completed",
                                      "output": {"video": "https://img.theapi.app/ephemeral/x.mp4"}}}),
        _Resp(content=b"MP4DATA"),
    ]
    out = tmp_path / "l.mp4"
    r = _luma(monkeypatch).execute({"prompt": "x", "duration": 9, "output_path": str(out)})
    assert r.success, r.error
    assert out.read_bytes() == b"MP4DATA"
    assert r.data["model"] == "luma-ray-v2"
    assert r.cost_usd == 0.40
    assert (tmp_path / "l.meta.json").exists()
    assert calls["post"][0][1]["json"]["input"]["duration"] == 9


def test_execute_rejects_invalid_before_network(monkeypatch, fake_requests):
    calls, _ = fake_requests
    r = _luma(monkeypatch).execute({"prompt": "x", "duration": 10})
    assert not r.success and "Invalid Luma" in r.error
    assert calls["post"] == []


def test_execute_no_api_key(monkeypatch):
    r = _luma(monkeypatch, key=None).execute({"prompt": "x"})
    assert not r.success and "PIAPI_API_KEY" in r.error
