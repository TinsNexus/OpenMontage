"""Contract coverage for the frame-by-frame PiAPI face swap tool (no network)."""

from __future__ import annotations

import shutil
import subprocess
import sys
import types

import pytest

needs_ffmpeg = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg/ffprobe not installed"
)


class _Resp:
    def __init__(self, content=b""):
        self.content = content
        self.status_code = 200

    def raise_for_status(self):
        pass


def _tool(monkeypatch):
    from tools.video.face_swap_frames_piapi import FaceSwapFramesPiAPI

    monkeypatch.delenv("PIAPI_KEY", raising=False)
    monkeypatch.setenv("PIAPI_API_KEY", "k")
    monkeypatch.setattr("time.sleep", lambda s: None)
    return FaceSwapFramesPiAPI()


def _clip(path, seconds=1, size="640x360", fps=10, audio=True):
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size={size}:rate={fps}:duration={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "aac", "-shortest"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True)
    return path


def _face(tmp_path):
    from PIL import Image

    p = tmp_path / "face.jpg"
    Image.new("RGB", (64, 64), (200, 160, 140)).save(p)
    return p


@pytest.fixture
def fake_piapi(monkeypatch, tmp_path):
    """Fake PiAPI: every swap returns a red JPEG; frames listed in ``fail`` always error."""
    from PIL import Image
    import io

    buf = io.BytesIO()
    Image.new("RGB", (640, 360), (255, 0, 0)).save(buf, format="JPEG")
    red = buf.getvalue()
    state = {"uploads": [], "tasks": [], "fail": set()}

    def upload(path, key):
        state["uploads"].append(path)
        return f"https://up/{path.split('/')[-1]}"

    def run_task(payload, key, **kw):
        target = payload["input"]["target_image"].rsplit("/", 1)[-1]
        state["tasks"].append(target)
        if target in state["fail"]:
            raise RuntimeError("The image download timed out")
        return {"task_id": f"t-{target}", "output": {"image_url": f"https://out/{target}"}}

    monkeypatch.setattr("tools.piapi_client.upload", upload)
    monkeypatch.setattr("tools.piapi_client.run_task", run_task)
    mod = types.ModuleType("requests")
    mod.get = lambda url, **kw: _Resp(red)
    monkeypatch.setitem(sys.modules, "requests", mod)
    return state


def test_plan_frames_range_and_cost():
    from tools.video.face_swap_frames_piapi import plan_frames

    info = {"duration": 10.0, "fps": 24.0, "width": 1920, "height": 1080}
    p = plan_frames(info, start=2, end=7)
    assert (p["frames"], p["fps"], p["cost_usd"]) == (120, 24.0, 1.2)
    assert (p["width"], p["height"]) == (1280, 720)


def test_plan_frames_caps_fps_and_limit():
    from tools.video.face_swap_frames_piapi import plan_frames

    info = {"duration": 30.0, "fps": 60.0, "width": 720, "height": 1280}
    assert plan_frames(info, end=5)["fps"] == 30.0
    with pytest.raises(ValueError, match="limit is 100"):
        plan_frames(info, end=10, max_frames=100)
    with pytest.raises(ValueError, match="empty range"):
        plan_frames(info, start=5, end=5)


def test_plan_frames_single_frame_at_24fps():
    from tools.video.face_swap_frames_piapi import plan_frames

    info = {"duration": 1.04, "fps": 24.0, "width": 854, "height": 480}
    assert plan_frames(info, start=0.5, end=0.5 + 1 / 24, max_frames=1)["frames"] == 1


def test_payload_shape(monkeypatch):
    tool = _tool(monkeypatch)
    assert tool.build_payload("https://t.jpg", "https://f.jpg") == {
        "model": "Qubico/image-toolkit", "task_type": "face-swap",
        "input": {"target_image": "https://t.jpg", "swap_image": "https://f.jpg"},
    }


def test_registered():
    from tools.tool_registry import registry

    registry.discover()
    assert registry.get("face_swap_frames_piapi") is not None


@needs_ffmpeg
def test_video_mode_swaps_assembles_and_keeps_audio(monkeypatch, tmp_path, fake_piapi):
    from tools.video.face_swap_piapi import probe_video

    tool = _tool(monkeypatch)
    clip = _clip(tmp_path / "src.mp4", seconds=1, fps=10)
    seen = []
    out = tmp_path / "out.mp4"
    res = tool.execute({"face_image_path": str(_face(tmp_path)), "target_video_path": str(clip),
                        "output_path": str(out), "work_dir": str(tmp_path / "work"),
                        "progress_callback": seen.append})
    assert res.success, res.error
    assert res.data["frames"] == 10 and res.data["swapped"] == 10
    assert res.cost_usd == 0.1
    assert seen[-1]["done"] == 10
    info = probe_video(str(out))
    assert info["has_audio"] and info["fps"] == pytest.approx(10, abs=0.1)
    assert info["frames"] == 10


@needs_ffmpeg
def test_resume_does_not_repay(monkeypatch, tmp_path, fake_piapi):
    tool = _tool(monkeypatch)
    clip = _clip(tmp_path / "src.mp4", seconds=1, fps=10, audio=False)
    args = {"face_image_path": str(_face(tmp_path)), "target_video_path": str(clip),
            "output_path": str(tmp_path / "out.mp4"), "work_dir": str(tmp_path / "work")}
    fake_piapi["fail"] = {"00003.jpg"}
    first = tool.execute(args)
    assert first.success and first.data["failed_frames"] == ["00003.jpg"]
    assert first.cost_usd == 0.09
    # 3 attempts in the pool + 3 in the second pass, then filled from a swapped neighbour
    assert fake_piapi["tasks"].count("00003.jpg") == 6
    assert not (tmp_path / "work" / "frames_out" / "00003.jpg").exists()  # dropped so a rerun retries it
    fake_piapi["fail"] = set()
    fake_piapi["tasks"].clear()
    second = tool.execute(args)
    assert second.success and second.data["failed_frames"] == []
    assert fake_piapi["tasks"] == ["00003.jpg"]  # only the missing frame is paid for again
    assert second.cost_usd == 0.01


@needs_ffmpeg
def test_preview_mode_one_frame(monkeypatch, tmp_path, fake_piapi):
    tool = _tool(monkeypatch)
    clip = _clip(tmp_path / "src.mp4", seconds=2, fps=10, audio=False)
    out = tmp_path / "prev.jpg"
    res = tool.execute({"face_image_path": str(_face(tmp_path)), "target_video_path": str(clip),
                        "mode": "preview", "preview_time": 1.5, "output_path": str(out)})
    assert res.success, res.error
    assert out.exists() and (tmp_path / "prev_before.jpg").exists()
    assert res.cost_usd == 0.01 and len(fake_piapi["tasks"]) == 1


@needs_ffmpeg
def test_all_frames_fail_reports_error(monkeypatch, tmp_path, fake_piapi):
    tool = _tool(monkeypatch)
    clip = _clip(tmp_path / "src.mp4", seconds=1, fps=2, audio=False)
    fake_piapi["fail"] = {"00001.jpg", "00002.jpg"}
    res = tool.execute({"face_image_path": str(_face(tmp_path)), "target_video_path": str(clip),
                        "work_dir": str(tmp_path / "w")})
    assert not res.success and "timed out" in res.error
