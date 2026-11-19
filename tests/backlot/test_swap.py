"""Backlot /api/swap: job lifecycle without network (paid tools are faked)."""

from __future__ import annotations

import base64
import io
import shutil
import subprocess
import time

import pytest

pytestmark = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                                reason="ffmpeg/ffprobe not installed")
H = {"X-Backlot-Action": "swap"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import backlot.state as state
    import backlot.server as server
    import backlot.swap as swap

    projects = tmp_path / "projects"
    projects.mkdir()
    for mod in (state, server, swap):
        monkeypatch.setattr(mod, "PROJECTS_DIR", projects, raising=False)
    monkeypatch.setattr(swap, "WORK_ROOT", tmp_path / "work")
    monkeypatch.setenv("OPENMONTAGE_CHARACTERS_DIR", str(tmp_path / "chars"))
    monkeypatch.setattr("lib.characters.CHARACTERS_DIR", tmp_path / "chars")
    with TestClient(server.create_app()) as c:
        yield c


def _clip(path, seconds=2, fps=10):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"testsrc=size=640x360:rate={fps}:duration={seconds}", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def _png():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (60, 80), (200, 150, 130)).save(buf, format="PNG")
    return buf.getvalue()


class _FakeSwap:
    calls: list = []

    def execute(self, inputs):
        from pathlib import Path

        from tools.base_tool import ToolResult

        _FakeSwap.calls.append(inputs)
        out = Path(inputs["output_path"])
        out.parent.mkdir(parents=True, exist_ok=True)
        if inputs["mode"] == "preview":
            out.write_bytes(_png())
            before = out.with_name(out.stem + "_before.jpg")
            before.write_bytes(_png())
            return ToolResult(success=True, cost_usd=0.01,
                              data={"time": inputs["preview_time"], "before_path": str(before)})
        if inputs.get("progress_callback"):
            inputs["progress_callback"]({"total": 10, "done": 10, "failed": 0, "cost_usd": 0.1})
        out.write_bytes(b"MP4")
        return ToolResult(success=True, cost_usd=0.1,
                          data={"swapped": 10, "failed_frames": [], "errors": [], "cached_frames": 0})


def test_requires_action_header(client):
    assert client.post("/api/swap", json={"title": "x"}).status_code == 403


def test_full_flow(client, tmp_path, monkeypatch):
    monkeypatch.setattr("tools.video.face_swap_frames_piapi.FaceSwapFramesPiAPI", _FakeSwap)
    job = client.post("/api/swap", json={"title": "NOVA chạy xe"}, headers=H).json()
    jid = job["id"]
    assert jid.startswith("swap-nova-chay-xe-") and job["character"]["status"] == "none"
    assert client.get("/swap").status_code == 200

    clip = _clip(tmp_path / "in.mp4").read_bytes()
    r = client.post(f"/api/swap/{jid}/upload", content=clip, headers={**H, "X-File-Name": "in.mp4"})
    assert r.status_code == 200, r.text
    assert r.json()["video"]["fps"] == 10 and r.json()["video"]["duration"] == pytest.approx(2, abs=0.1)

    r = client.post(f"/api/swap/{jid}/range", json={"start": 0.5, "end": 1.5}, headers=H)
    assert r.json()["range"]["frames"] == 10 and r.json()["range"]["cost_usd"] == 0.1

    # Running before approval is refused.
    assert client.post(f"/api/swap/{jid}/run", json={"kind": "test"}, headers=H).status_code == 422

    data = "data:image/png;base64," + base64.b64encode(_png()).decode()
    r = client.post(f"/api/swap/{jid}/character/upload", json={"file_name": "nova.png", "data_base64": data}, headers=H)
    assert r.json()["character"]["status"] == "pending"
    assert client.post(f"/api/swap/{jid}/preview", json={"time": 1}, headers=H).status_code == 422

    r = client.post(f"/api/swap/{jid}/character/approve", json={"save_to_library": True, "name": "NOVA test"}, headers=H)
    ch = r.json()["character"]
    assert ch["status"] == "approved" and ch["char_id"] == "nova-test"
    assert any(c["id"] == "nova-test" for c in client.get("/api/swap/options").json()["characters"])

    r = client.post(f"/api/swap/{jid}/preview", json={"time": 1}, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["preview"]["after"].startswith("artifacts/swap_preview/")

    r = client.post(f"/api/swap/{jid}/run", json={"kind": "test"}, headers=H)
    assert r.status_code == 200 and r.json()["run"]["status"] == "running"
    for _ in range(50):
        job = client.get(f"/api/swap/{jid}").json()
        if job["run"]["status"] != "running":
            break
        time.sleep(0.05)
    assert job["run"]["status"] == "done", job["run"]
    assert job["outputs"][0]["path"].startswith("renders/swap_test_")
    assert job["spent_usd"] == pytest.approx(0.11)
    assert _FakeSwap.calls[-1]["end"] - _FakeSwap.calls[-1]["start"] == pytest.approx(1.0)

    assert client.post(f"/api/swap/{jid}/delete", headers=H).status_code == 200
    assert client.get(f"/api/swap/{jid}").status_code == 404


def test_reject_and_library_pick(client, tmp_path):
    from lib import characters as charlib

    c = charlib.create("Mika")
    img = tmp_path / "m.png"
    img.write_bytes(_png())
    charlib.add_image(c["id"], img, role="face")
    jid = client.post("/api/swap", json={"title": "t"}, headers=H).json()["id"]
    data = base64.b64encode(_png()).decode()
    client.post(f"/api/swap/{jid}/character/upload", json={"file_name": "a.png", "data_base64": data}, headers=H)
    r = client.post(f"/api/swap/{jid}/character/reject", headers=H)
    assert r.json()["character"]["status"] == "rejected"
    r = client.post(f"/api/swap/{jid}/character/library", json={"char_id": c["id"]}, headers=H)
    ch = r.json()["character"]
    assert ch["status"] == "approved" and ch["origin"] == "library" and len(ch["history"]) == 1


def test_range_limit_and_bad_link(client, tmp_path):
    jid = client.post("/api/swap", json={"title": "t"}, headers=H).json()["id"]
    assert client.post(f"/api/swap/{jid}/link", json={"url": "ftp://x"}, headers=H).status_code == 422
    clip = _clip(tmp_path / "long.mp4", seconds=2, fps=10).read_bytes()
    client.post(f"/api/swap/{jid}/upload", content=clip, headers={**H, "X-File-Name": "long.mp4"})
    assert client.post(f"/api/swap/{jid}/range", json={"start": 1, "end": 1}, headers=H).status_code == 422
    assert client.post(f"/api/swap/{jid}/upload", content=b"x", headers={**H, "X-File-Name": "a.exe"}).status_code == 422
