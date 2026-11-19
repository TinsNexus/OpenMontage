"""Contract coverage for the PiAPI Wan and Hailuo video tools (no network)."""

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


def _key(monkeypatch, key="test-piapi-key"):
    monkeypatch.delenv("PIAPI_KEY", raising=False)
    if key:
        monkeypatch.setenv("PIAPI_API_KEY", key)
    else:
        monkeypatch.delenv("PIAPI_API_KEY", raising=False)


def _wan(monkeypatch, key="test-piapi-key"):
    from tools.video.wan_piapi import WanPiAPI

    _key(monkeypatch, key)
    return WanPiAPI()


def _hailuo(monkeypatch, key="test-piapi-key"):
    from tools.video.hailuo_piapi import HailuoPiAPI

    _key(monkeypatch, key)
    return HailuoPiAPI()


def _completed(output, task_id="t-1"):
    return [
        _Resp({"code": 200, "data": {"task_id": task_id, "status": "processing"}}),
        _Resp({"code": 200, "data": {"task_id": task_id, "status": "completed", "output": output}}),
        _Resp(content=b"MP4DATA"),
    ]


# ---------------------------------------------------------------- discovery


@pytest.mark.parametrize("name,provider", [("wan_piapi", "wan"), ("hailuo_piapi", "hailuo")])
def test_discovered_as_video_provider(name, provider):
    from tools.tool_registry import ToolRegistry

    registry = ToolRegistry()
    registry.discover()
    tool = registry.get(name)
    assert tool is not None
    assert tool.provider == provider
    assert tool.capability == "video_generation"


def test_status_follows_api_key(monkeypatch):
    assert _wan(monkeypatch, key=None).get_status() == ToolStatus.UNAVAILABLE
    assert _wan(monkeypatch).get_status() == ToolStatus.AVAILABLE
    assert _hailuo(monkeypatch, key=None).get_status() == ToolStatus.UNAVAILABLE
    assert _hailuo(monkeypatch).get_status() == ToolStatus.AVAILABLE


# ---------------------------------------------------------------- Wan


@pytest.mark.parametrize("inputs,cost", [
    ({}, 0.40),
    ({"resolution": "1080p", "duration": 10}, 1.20),
    ({"resolution": "1080P", "duration": 15}, 1.80),
    ({"duration": 15}, 1.20),
    ({"version": "2.2"}, 0.28),
    ({"version": "2.1"}, 0.28),
    ({"version": "2.1-1.3b"}, 0.12),
    ({"duration": 7}, 0.0),
])
def test_wan_cost_matches_piapi_pricing(monkeypatch, inputs, cost):
    assert _wan(monkeypatch).estimate_cost({"prompt": "x", **inputs}) == cost


def test_wan26_text_to_video_payload(monkeypatch):
    p = _wan(monkeypatch)._build_payload(
        {"prompt": "a cat", "resolution": "1080p", "duration": 10, "aspect_ratio": "9:16", "seed": 7}, "k"
    )
    assert p["model"] == "Wan"
    assert p["task_type"] == "wan26-txt2video"
    assert p["input"] == {
        "prompt": "a cat", "resolution": "1080P", "duration": 10, "prompt_extend": True,
        "shot_type": "single", "audio": True, "seed": 7, "watermark": False, "aspect_ratio": "9:16",
    }


def test_wan26_image_to_video_uploads_and_skips_aspect(monkeypatch, tmp_path, fake_requests):
    calls, script = fake_requests
    img = tmp_path / "hero.png"
    img.write_bytes(b"PNG")
    script["post"].append(_Resp({"code": 200, "data": {"url": "https://cdn/hero.png"}}))
    p = _wan(monkeypatch)._build_payload(
        {"prompt": "she turns", "image_path": str(img), "generate_audio": False, "shot_type": "multi"}, "k"
    )
    assert p["task_type"] == "wan26-img2video"
    assert p["input"]["image"] == "https://cdn/hero.png"
    assert p["input"]["audio"] is False
    assert p["input"]["shot_type"] == "multi"
    assert "aspect_ratio" not in p["input"]
    assert calls["post"][0][0] == "https://upload.theapi.app/api/ephemeral_resource"


def test_wan26_audio_url_replaces_audio_flag(monkeypatch):
    p = _wan(monkeypatch)._build_payload({"prompt": "x", "audio_url": "https://cdn/a.mp3"}, "k")
    assert p["input"]["audio_url"] == "https://cdn/a.mp3"
    assert "audio" not in p["input"]


@pytest.mark.parametrize("inputs,task_type,extra", [
    ({"version": "2.2"}, "wan22-txt2video-14b", {"aspect_ratio": "16:9"}),
    ({"version": "2.2", "image_url": "https://cdn/i.png"}, "wan22-img2video-14b", {"image": "https://cdn/i.png"}),
    ({"version": "2.1", "aspect_ratio": "9:16"}, "txt2video-14b", {"aspect_ratio": "9:16"}),
    ({"version": "2.1", "image_url": "https://cdn/i.png"}, "img2video-14b",
     {"image": "https://cdn/i.png", "aspect_ratio": "16:9"}),
    ({"version": "2.1", "image_url": "https://cdn/a.png", "end_image_url": "https://cdn/b.png"},
     "img2video-14b-keyframe",
     {"start_image": "https://cdn/a.png", "end_image": "https://cdn/b.png", "aspect_ratio": "16:9"}),
    ({"version": "2.1-1.3b"}, "txt2video-1.3b", {"aspect_ratio": "16:9"}),
])
def test_wanx_payloads(monkeypatch, inputs, task_type, extra):
    p = _wan(monkeypatch)._build_payload({"prompt": "x", **inputs}, "k")
    assert p["model"] == "Qubico/wanx"
    assert p["task_type"] == task_type
    assert p["input"] == {"prompt": "x", **extra}


@pytest.mark.parametrize("inputs,msg", [
    ({"version": "3.0"}, "Unknown Wan version"),
    ({"resolution": "480p"}, "720p or 1080p"),
    ({"duration": 8}, "5, 10 or 15"),
    ({"aspect_ratio": "21:9"}, "aspect_ratio"),
    ({"shot_type": "multi", "prompt_extend": False}, "prompt_extend"),
    ({"end_image_url": "https://cdn/b.png", "image_url": "https://cdn/a.png"}, "keyframe"),
    ({"version": "2.2", "aspect_ratio": "1:1"}, "16:9 or 9:16"),
    ({"version": "2.1-1.3b", "image_url": "https://cdn/a.png"}, "text-to-video only"),
    ({"version": "2.1", "end_image_url": "https://cdn/b.png"}, "needs a start image"),
    ({"prompt": ""}, "prompt is required"),
])
def test_wan_payload_validation(monkeypatch, inputs, msg):
    with pytest.raises(ValueError, match=msg):
        _wan(monkeypatch)._build_payload({"prompt": "x", **inputs}, "k")


def test_wan_execute_create_poll_download(monkeypatch, tmp_path, fake_requests):
    import json

    calls, script = fake_requests
    script["post"].append(_Resp({"code": 200, "data": {"task_id": "t-1", "status": "pending"}}))
    script["get"] += _completed({"video_url": "https://cdn/out.mp4"})
    out = tmp_path / "clip.mp4"
    r = _wan(monkeypatch).execute(
        {"prompt": "x", "resolution": "1080p", "duration": 10, "output_path": str(out)}
    )
    assert r.success, r.error
    assert out.read_bytes() == b"MP4DATA"
    assert r.data["model"] == "wan-2.6"
    assert r.data["resolution"] == "1080p"
    assert r.cost_usd == 1.20
    assert calls["post"][0][1]["json"]["task_type"] == "wan26-txt2video"
    assert calls["get"][-1][0] == "https://cdn/out.mp4"
    meta = json.loads((tmp_path / "clip.meta.json").read_text())
    assert meta["model"] == "wan-2.6" and meta["cost_usd"] == 1.20 and meta["task_id"] == "t-1"


def test_wan_execute_rejects_invalid_before_network(monkeypatch, fake_requests):
    calls, _ = fake_requests
    r = _wan(monkeypatch).execute({"prompt": "x", "duration": 7})
    assert not r.success and "Invalid Wan" in r.error
    assert calls["post"] == []


def test_wan_execute_no_api_key(monkeypatch):
    r = _wan(monkeypatch, key=None).execute({"prompt": "x"})
    assert not r.success and "PIAPI_API_KEY" in r.error


# ---------------------------------------------------------------- Hailuo


@pytest.mark.parametrize("inputs,cost", [
    ({}, 0.23),
    ({"duration": 10}, 0.45),
    ({"resolution": "1080p"}, 0.40),
    ({"model": "v2.3-fast"}, 0.16),
    ({"model": "v2.3-fast", "duration": 10}, 0.26),
    ({"model": "v2.3-fast", "resolution": "1080p"}, 0.26),
    ({"resolution": "1080p", "duration": 10}, 0.0),
])
def test_hailuo_cost_matches_piapi_pricing(monkeypatch, inputs, cost):
    assert _hailuo(monkeypatch).estimate_cost({"prompt": "x", **inputs}) == cost


def test_hailuo_payload(monkeypatch):
    p = _hailuo(monkeypatch)._build_payload(
        {"prompt": "autumn wind", "resolution": "1080p", "image_url": "https://cdn/i.png"}, "k"
    )
    assert p == {
        "model": "hailuo",
        "task_type": "video_generation",
        "input": {"prompt": "autumn wind", "model": "v2.3", "expand_prompt": False,
                  "duration": 6, "resolution": 1080, "image_url": "https://cdn/i.png"},
        "config": {"service_mode": "public"},
    }


@pytest.mark.parametrize("inputs,msg", [
    ({"model": "v2.0"}, "model must be"),
    ({"resolution": "720p"}, "resolution must be"),
    ({"duration": 5}, "6 or 10"),
    ({"resolution": "1080p", "duration": 10}, "6 s only"),
    ({"prompt": "y" * 2001}, "max is 2000"),
])
def test_hailuo_payload_validation(monkeypatch, inputs, msg):
    with pytest.raises(ValueError, match=msg):
        _hailuo(monkeypatch)._build_payload({"prompt": "x", **inputs}, "k")


def test_hailuo_rejects_out_of_range_image_before_upload(monkeypatch, tmp_path, fake_requests):
    from PIL import Image

    calls, _ = fake_requests
    img = tmp_path / "strip.png"
    Image.new("RGB", (1200, 300)).save(img)
    r = _hailuo(monkeypatch).execute({"prompt": "x", "image_path": str(img)})
    assert not r.success and "aspect 4.00" in r.error
    assert calls["post"] == []


def test_hailuo_execute_create_poll_download(monkeypatch, tmp_path, fake_requests):
    calls, script = fake_requests
    script["post"].append(_Resp({"code": 200, "data": {"task_id": "h-1", "status": "pending"}}))
    script["get"] += _completed({"video": "https://img.theapi.app/ephemeral/x.mp4"}, task_id="h-1")
    out = tmp_path / "h.mp4"
    r = _hailuo(monkeypatch).execute({"prompt": "x", "model": "v2.3-fast", "output_path": str(out)})
    assert r.success, r.error
    assert out.read_bytes() == b"MP4DATA"
    assert r.data["model"] == "hailuo-v2.3-fast"
    assert r.data["resolution"] == "768p"
    assert r.cost_usd == 0.16
    assert calls["post"][0][1]["json"]["config"] == {"service_mode": "public"}


def test_hailuo_execute_reports_missing_video(monkeypatch, tmp_path, fake_requests):
    _, script = fake_requests
    script["post"].append(_Resp({"code": 200, "data": {"task_id": "h-2", "status": "pending"}}))
    script["get"] += _completed({}, task_id="h-2")[:2]
    r = _hailuo(monkeypatch).execute({"prompt": "x", "output_path": str(tmp_path / "h.mp4")})
    assert not r.success and "without a video URL" in r.error


# ---------------------------------------------------------------- shared


def test_find_video_url_handles_output_shapes():
    from tools.video.piapi_video_common import find_video_url

    assert find_video_url({"video": "https://a/v.mp4"}) == "https://a/v.mp4"
    assert find_video_url({"video_url": "https://a/v.mp4"}) == "https://a/v.mp4"
    assert find_video_url({"works": [{"video": {"resource": "https://a/w.mp4"}}]}) == "https://a/w.mp4"
    assert find_video_url({"image_url": None, "thumb": "https://a/t.png"}) is None
    assert find_video_url(None) is None
