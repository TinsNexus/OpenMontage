"""Contract coverage for the PiAPI video face-swap tool (no network)."""

from __future__ import annotations

import shutil
import subprocess
import sys
import types

import pytest

from tools.base_tool import ToolStatus

needs_ffmpeg = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg/ffprobe not installed"
)


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


def _tool(monkeypatch, key="test-piapi-key"):
    from tools.video.face_swap_piapi import FaceSwapPiAPI

    monkeypatch.delenv("PIAPI_KEY", raising=False)
    if key:
        monkeypatch.setenv("PIAPI_API_KEY", key)
    else:
        monkeypatch.delenv("PIAPI_API_KEY", raising=False)
    return FaceSwapPiAPI()


def _make_clip(path, seconds=2, size="1920x1080", fps=60, audio=True):
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size={size}:rate={fps}:duration={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac", "-shortest"]
    cmd.append(str(path))
    subprocess.run(cmd, check=True)
    return path


def _face(tmp_path):
    from PIL import Image

    p = tmp_path / "face.jpg"
    Image.new("RGB", (64, 64), (200, 160, 140)).save(p)
    return p


def test_status_needs_key(monkeypatch):
    assert _tool(monkeypatch, key=None).get_status() == ToolStatus.UNAVAILABLE


def test_registered_in_registry():
    from tools.tool_registry import registry

    registry.discover()
    tool = registry.get("face_swap_piapi")
    assert tool is not None
    assert tool.capability == "video_post"
    assert tool.agent_skills == ["face-swap-piapi"]


def test_payload_shape(monkeypatch):
    tool = _tool(monkeypatch)
    payload = tool.build_payload("https://x/face.jpg", "https://x/v.mp4",
                                 {"swap_faces_index": "0, 1", "target_faces_index": "1,0"})
    assert payload == {
        "model": "Qubico/video-toolkit",
        "task_type": "face-swap",
        "input": {
            "swap_image": "https://x/face.jpg",
            "target_video": "https://x/v.mp4",
            "swap_faces_index": "0,1",
            "target_faces_index": "1,0",
        },
    }


def test_bad_face_index(monkeypatch):
    tool = _tool(monkeypatch)
    with pytest.raises(ValueError):
        tool.build_payload("a", "b", {"target_faces_index": "first"})


def test_plan_caps_fps_scale_and_frames():
    from tools.video.face_swap_piapi import plan_prepare

    info = {"width": 1080, "height": 1920, "fps": 60.0, "duration": 10.0, "frames": 600,
            "size_bytes": 30_000_000, "format_name": "mov,mp4", "codec": "h264", "has_audio": True}
    plan = plan_prepare(info)
    assert plan["needs_encode"]
    assert plan["fps"] == 30.0
    assert plan["frames"] == 300
    assert (plan["width"], plan["height"]) == (720, 1280)


def test_plan_refuses_over_600_frames():
    from tools.video.face_swap_piapi import plan_prepare

    info = {"width": 1280, "height": 720, "fps": 30.0, "duration": 25.0, "frames": 750,
            "size_bytes": 5_000_000, "format_name": "mov,mp4", "codec": "h264", "has_audio": False}
    with pytest.raises(ValueError, match="Trim it to <= 20.0s"):
        plan_prepare(info)


def test_plan_small_mp4_untouched():
    from tools.video.face_swap_piapi import plan_prepare

    info = {"width": 720, "height": 1280, "fps": 24.0, "duration": 5.0, "frames": 120,
            "size_bytes": 3_000_000, "format_name": "mov,mp4,m4a", "codec": "h264", "has_audio": True}
    plan = plan_prepare(info)
    assert not plan["needs_encode"]
    assert plan["frames"] == 120


@needs_ffmpeg
def test_dry_run_prepares_and_prices(monkeypatch, tmp_path):
    from tools.video.face_swap_piapi import probe_video

    tool = _tool(monkeypatch, key=None)  # dry run needs no key
    clip = _make_clip(tmp_path / "src.mov", seconds=2, size="1920x1080", fps=60)
    out = tmp_path / "out.mp4"
    res = tool.execute({"face_image_path": str(_face(tmp_path)), "target_video_path": str(clip),
                        "dry_run": True, "output_path": str(out)})
    assert res.success, res.error
    assert res.data["frames"] == 60
    assert res.data["estimated_cost_usd"] == 0.24
    prepared = probe_video(res.data["prepared_video"])
    assert prepared["height"] <= 720 and prepared["width"] <= 1280
    assert prepared["fps"] == pytest.approx(30, abs=0.1)
    assert tool.estimate_cost({"target_video_path": str(clip)}) == 0.24


@needs_ffmpeg
def test_execute_uploads_runs_and_restores_audio(monkeypatch, tmp_path):
    tool = _tool(monkeypatch)
    clip = _make_clip(tmp_path / "src.mp4", seconds=1, size="640x360", fps=24, audio=True)
    silent = _make_clip(tmp_path / "silent.mp4", seconds=1, size="640x360", fps=24, audio=False)

    uploads, created = [], []
    monkeypatch.setattr("tools.piapi_client.upload",
                        lambda p, k: uploads.append(p) or f"https://up/{len(uploads)}")

    def fake_run(payload, key, **kw):
        created.append(payload)
        kw["on_task_id"]("t-9")
        return {"task_id": "t-9", "status": "completed", "output": {"video_url": "https://out/v.mp4"}}

    monkeypatch.setattr("tools.piapi_client.run_task", fake_run)
    mod = types.ModuleType("requests")
    mod.get = lambda url, **kw: _Resp(content=silent.read_bytes())
    monkeypatch.setitem(sys.modules, "requests", mod)

    out = tmp_path / "swapped.mp4"
    res = tool.execute({"face_image_path": str(_face(tmp_path)), "target_video_path": str(clip),
                        "output_path": str(out)})
    assert res.success, res.error
    assert len(uploads) == 2  # face + video (already within limits, sent as-is)
    assert uploads[1] == str(clip)
    assert created[0]["input"]["target_video"] == "https://up/2"
    assert res.data["task_id"] == "t-9"
    assert res.cost_usd == 0.1  # 24 frames x $0.004
    assert res.data["audio_restored"] is True
    assert (tmp_path / "swapped.meta.json").exists()


@needs_ffmpeg
def test_url_outside_limits_refused(monkeypatch, tmp_path):
    tool = _tool(monkeypatch)
    clip = _make_clip(tmp_path / "big.mp4", seconds=1, size="1920x1080", fps=24, audio=False)
    res = tool.execute({"face_image_url": "https://x/f.jpg", "target_video_url": str(clip)})
    assert not res.success
    assert "target_video_path" in res.error
