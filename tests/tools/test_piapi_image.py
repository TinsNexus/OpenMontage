"""Contract coverage for the PiAPI Nano Banana image tool (no network)."""

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
    from tools.graphics.piapi_image import PiAPIImage

    monkeypatch.delenv("PIAPI_API_KEY", raising=False)
    if key:
        monkeypatch.setenv("PIAPI_KEY", key)
    else:
        monkeypatch.delenv("PIAPI_KEY", raising=False)
    return PiAPIImage()


def test_discovered_as_image_generation_tool():
    from tools.tool_registry import ToolRegistry

    registry = ToolRegistry()
    registry.discover()
    tool = registry.get("piapi_image")
    assert tool is not None
    assert tool.capability == "image_generation"
    assert tool.provider == "piapi"


def test_status_follows_either_key_name(monkeypatch):
    assert _tool(monkeypatch, key=None).get_status() == ToolStatus.UNAVAILABLE
    assert _tool(monkeypatch).get_status() == ToolStatus.AVAILABLE


def test_cost(monkeypatch):
    t = _tool(monkeypatch)
    assert t.estimate_cost({"prompt": "x", "n": 3}) == 0.09
    assert t.estimate_cost({"prompt": "x", "model": "nano-banana-pro", "resolution": "4K"}) == 0.18
    assert t.estimate_cost({"prompt": "x", "model": "gemini-2.5-flash-image", "resolution": "4K"}) == 0.03


def test_payload_defaults(monkeypatch):
    p = _tool(monkeypatch)._build_payload({"prompt": " portrait ", "aspect_ratio": "3:4"}, "k")
    assert p == {
        "model": "gemini",
        "task_type": "nano-banana-2.1",
        "input": {"prompt": "portrait", "output_format": "png", "aspect_ratio": "3:4", "resolution": "1K"},
    }


def test_payload_flash_has_no_resolution_and_jpeg_spelling(monkeypatch):
    p = _tool(monkeypatch)._build_payload(
        {"prompt": "x", "model": "gemini-2.5-flash-image", "output_format": "jpg"}, "k"
    )
    assert "resolution" not in p["input"]
    assert p["input"]["output_format"] == "jpeg"


@pytest.mark.parametrize(
    "inputs, msg",
    [
        ({"prompt": "  "}, "non-empty"),
        ({"prompt": "x", "model": "nano-banana-pro", "aspect_ratio": "8:1"}, "does not support aspect_ratio"),
        ({"prompt": "x", "resolution": "8K"}, "1K, 2K or 4K"),
        ({"prompt": "x", "safety_level": "high"}, "only supported by nano-banana-pro"),
        ({"prompt": "x", "image_urls": ["u"] * 15}, "At most 14"),
        ({"prompt": "x", "model": "dall-e"}, "Unknown model"),
    ],
)
def test_payload_validation(monkeypatch, inputs, msg):
    with pytest.raises(ValueError, match=msg):
        _tool(monkeypatch)._build_payload(inputs, "k")


def test_execute_n_images_with_local_reference(monkeypatch, tmp_path, fake_requests):
    calls, script = fake_requests
    ref = tmp_path / "ref.jpg"
    ref.write_bytes(b"JPEG")
    script["post"] += [
        _Resp({"code": 200, "data": {"url": "https://cdn/ref.jpg"}}),  # upload
        _Resp({"code": 200, "data": {"task_id": "a", "status": "pending"}}),
        _Resp({"code": 200, "data": {"task_id": "b", "status": "Completed",
                                     "output": {"image_url": "https://cdn/b.png"}}}),
    ]
    script["get"] += [
        _Resp({"code": 200, "data": {"task_id": "a", "status": "Completed",
                                     "output": {"image_urls": ["https://cdn/a.png"]}}}),
        _Resp(content=b"IMG-A"),
        _Resp(content=b"IMG-B"),
    ]
    out = tmp_path / "sasa.png"
    r = _tool(monkeypatch).execute({"prompt": "Sasa", "n": 2, "image_path": str(ref), "output_path": str(out)})
    assert r.success, r.error
    assert r.data["outputs"] == [str(tmp_path / "sasa_1.png"), str(tmp_path / "sasa_2.png")]
    assert (tmp_path / "sasa_1.png").read_bytes() == b"IMG-A"
    assert (tmp_path / "sasa_2.png").read_bytes() == b"IMG-B"
    assert r.data["task_ids"] == ["a", "b"]
    assert r.cost_usd == 0.06
    # upload happened once, then two task creates carrying the uploaded URL
    assert calls["post"][0][0] == "https://upload.theapi.app/api/ephemeral_resource"
    for url, kw in calls["post"][1:]:
        assert url == "https://api.piapi.ai/api/v1/task"
        assert kw["headers"]["X-API-Key"] == "test-piapi-key"
        assert kw["json"]["input"]["image_urls"] == ["https://cdn/ref.jpg"]


def test_execute_failure_keeps_partial_results(monkeypatch, tmp_path, fake_requests):
    _, script = fake_requests
    script["post"] += [
        _Resp({"code": 200, "data": {"task_id": "a", "status": "completed",
                                     "output": {"image_url": "https://cdn/a.png"}}}),
        _Resp({"code": 200, "data": {"task_id": "b", "status": "failed",
                                     "error": {"message": "prompt blocked"}}}),
    ]
    script["get"].append(_Resp(content=b"IMG-A"))
    r = _tool(monkeypatch).execute({"prompt": "x", "n": 2, "output_path": str(tmp_path / "o.png")})
    assert not r.success
    assert "prompt blocked" in r.error and "1/2" in r.error
    assert r.artifacts == [str(tmp_path / "o_1.png")]
    assert r.cost_usd == 0.03


def test_upload_retries_dropped_connections(monkeypatch, tmp_path):
    import requests as real_requests

    from tools import piapi_client

    img = tmp_path / "a.png"
    img.write_bytes(b"PNG")
    attempts = []

    def post(url, **kw):
        attempts.append(url)
        if len(attempts) < 3:
            raise real_requests.ConnectionError("Broken pipe")
        return _Resp({"code": 200, "data": {"url": "https://cdn/a.png"}})

    monkeypatch.setattr(real_requests, "post", post)
    monkeypatch.setattr("time.sleep", lambda s: None)
    assert piapi_client.upload(str(img), "k") == "https://cdn/a.png"
    assert len(attempts) == 3

    attempts.clear()
    monkeypatch.setattr(real_requests, "post", lambda url, **kw: (_ for _ in ()).throw(real_requests.ConnectionError("x")))
    with pytest.raises(real_requests.ConnectionError):
        piapi_client.upload(str(img), "k")


def _noisy_png(path, size, mode="RGB"):
    import os as _os

    from PIL import Image

    Image.frombytes(mode, size, _os.urandom(size[0] * size[1] * len(mode))).save(path)


def test_upload_compresses_large_images(monkeypatch, tmp_path):
    import base64 as b64
    import io

    import requests as real_requests
    from PIL import Image

    from tools import piapi_client

    img = tmp_path / "ref.png"
    _noisy_png(img, (2400, 1800))
    assert img.stat().st_size > piapi_client.UPLOAD_COMPRESS_OVER_BYTES
    sent = []
    monkeypatch.setattr(real_requests, "post", lambda url, **kw: sent.append(kw["json"]) or
                        _Resp({"code": 200, "data": {"url": "https://cdn/ref.jpg"}}))

    assert piapi_client.upload(str(img), "k") == "https://cdn/ref.jpg"
    body = sent[0]
    assert body["file_name"] == "ref.jpg"
    data = b64.b64decode(body["file_data"])
    assert len(data) < img.stat().st_size
    with Image.open(io.BytesIO(data)) as out:
        assert out.format == "JPEG"
        assert max(out.size) == piapi_client.UPLOAD_COMPRESS_MAX_SIDE
        assert out.size[0] / out.size[1] == pytest.approx(2400 / 1800, rel=0.01)


def test_compress_image_flattens_alpha_and_skips_small_or_other_files(tmp_path):
    import io

    from PIL import Image

    from tools import piapi_client

    rgba = tmp_path / "a.png"
    _noisy_png(rgba, (1200, 1200), mode="RGBA")
    data, name = piapi_client.compress_image(rgba.read_bytes(), "a.png")
    assert name == "a.jpg"
    with Image.open(io.BytesIO(data)) as out:
        assert out.mode == "RGB"

    assert piapi_client.compress_image(b"tiny", "s.png") == (b"tiny", "s.png")
    big = b"\0" * (piapi_client.UPLOAD_COMPRESS_OVER_BYTES + 1)
    assert piapi_client.compress_image(big, "clip.mp4") == (big, "clip.mp4")
    assert piapi_client.compress_image(big, "broken.png") == (big, "broken.png")
