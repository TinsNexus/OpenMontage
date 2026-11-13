"""Gallery listing, prompt provenance and social-copy generation (no network)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backlot import server as server_mod
from backlot import social
from backlot import state as state_mod


@pytest.fixture
def projects_root(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", root)
    monkeypatch.setattr(server_mod, "PROJECTS_DIR", root)
    monkeypatch.setattr(server_mod, "_summary_cache", {})
    monkeypatch.setattr(server_mod, "THUMB_CACHE_DIR", tmp_path / "thumbs")
    return root


@pytest.fixture
def client(projects_root, monkeypatch):
    async def no_watch():
        return None

    monkeypatch.setattr(server_mod, "_watch_projects", no_watch)
    with TestClient(server_mod.create_app()) as c:
        yield c


def _project(root: Path, pid="fight") -> Path:
    p = root / pid
    (p / "assets" / "video").mkdir(parents=True)
    (p / "renders").mkdir()
    (p / "artifacts").mkdir()
    (p / "project.json").write_text(json.dumps({"project_id": pid, "title": "Rooftop Fight"}))
    return p


def test_list_videos_resolves_prompts(projects_root):
    p = _project(projects_root)
    (p / "artifacts" / "seedance_prompt_v1.txt").write_text("PROMPT ONE")
    (p / "artifacts" / "seedance_prompt_v2.txt").write_text("PROMPT TWO")
    (p / "assets" / "video" / "clip_v1_720p.mp4").write_bytes(b"x")            # version tag
    (p / "assets" / "video" / "clip_v2_720p.mp4").write_bytes(b"x")
    (p / "assets" / "video" / "inline.mp4").write_bytes(b"x")                   # sidecar prompt
    (p / "assets" / "video" / "inline.meta.json").write_text(json.dumps({"prompt": "INLINE", "model": "m", "cost_usd": 1.1}))
    (p / "renders" / "final.mp4").write_bytes(b"x")                             # derived
    (p / "renders" / "final.meta.json").write_text(json.dumps({"derived_from": "assets/video/clip_v2_720p.mp4"}))
    (p / "reference.mp4").write_bytes(b"x")                                     # not a generated video

    vids = {v["path"]: v for v in social.list_videos(projects_root)}
    assert set(vids) == {"assets/video/clip_v1_720p.mp4", "assets/video/clip_v2_720p.mp4",
                         "assets/video/inline.mp4", "renders/final.mp4"}
    assert vids["assets/video/clip_v1_720p.mp4"]["prompt"] == "PROMPT ONE"
    assert vids["assets/video/clip_v2_720p.mp4"]["prompt"] == "PROMPT TWO"
    assert vids["assets/video/inline.mp4"]["prompt"] == "INLINE"
    assert vids["assets/video/inline.mp4"]["cost_usd"] == 1.1
    assert vids["renders/final.mp4"]["prompt"] == "PROMPT TWO"
    assert vids["renders/final.mp4"]["kind"] == "render"
    assert vids["renders/final.mp4"]["project_title"] == "Rooftop Fight"


def test_parse_copy_normalises_hashtags():
    reply = 'Sure!\n```json\n{"titles": ["A", ""], "caption": " Hi ", "hashtags": ["sasa", "#Sasa", "#ai video", "#Shorts"]}\n```'
    out = social.parse_copy(reply)
    assert out == {"titles": ["A"], "caption": "Hi", "hashtags": ["#sasa", "#aivideo", "#Shorts"]}


def test_parse_copy_rejects_empty():
    with pytest.raises(ValueError):
        social.parse_copy("no json here")
    with pytest.raises(ValueError):
        social.parse_copy('{"titles": [], "caption": ""}')


def test_build_messages_mentions_platform_language_and_prompt():
    msgs = social.build_messages(platform="youtube_shorts", language="vi", project_title="T",
                                 video_name="v.mp4", prompt="ROOFTOP RAIN", notes="kênh Sasa")
    user = msgs[1]["content"]
    assert "YouTube Shorts" in user and "#Shorts" in user
    assert "Vietnamese" in user and "ROOFTOP RAIN" in user and "kênh Sasa" in user


def test_generate_social_saves_and_keeps_history(projects_root, monkeypatch):
    p = _project(projects_root)
    (p / "assets" / "video" / "clip.mp4").write_bytes(b"x")
    (p / "assets" / "video" / "clip.meta.json").write_text(json.dumps({"prompt": "P"}))
    monkeypatch.setenv("PIAPI_KEY", "k")
    replies = iter([
        '{"titles": ["T1"], "caption": "C1", "hashtags": ["#a"]}',
        '{"titles": ["T2"], "caption": "C2", "hashtags": ["#b"]}',
    ])
    seen = {}

    def fake_chat(messages, model, api_key):
        seen["model"], seen["key"] = model, api_key
        return next(replies), {"total_tokens": 10}

    monkeypatch.setattr(social, "_chat", fake_chat)
    social.generate_social(p, "assets/video/clip.mp4", platform="tiktok")
    rec = social.generate_social(p, "assets/video/clip.mp4", platform="tiktok", language="en")
    assert seen == {"model": social.DEFAULT_MODEL, "key": "k"}
    assert rec["caption"] == "C2" and rec["language"] == "en"
    assert [h["caption"] for h in rec["history"]] == ["C1"]
    saved = json.loads(social.social_path(p, "assets/video/clip.mp4").read_text())
    assert saved["titles"] == ["T2"]
    listed = social.list_videos(projects_root)[0]
    assert listed["social"]["caption"] == "C2"


def test_api_videos_and_social_endpoint(client, projects_root, monkeypatch):
    p = _project(projects_root)
    (p / "assets" / "video" / "clip.mp4").write_bytes(b"x")
    monkeypatch.setenv("PIAPI_KEY", "k")
    monkeypatch.setattr(social, "_chat", lambda m, model, key: ('{"titles":["T"],"caption":"C","hashtags":["#x"]}', {}))

    assert [v["path"] for v in client.get("/api/videos").json()] == ["assets/video/clip.mp4"]
    opts = client.get("/api/social/options").json()
    assert {p["id"] for p in opts["platforms"]} >= {"facebook_reels", "tiktok", "youtube_shorts"}

    body = {"video": "assets/video/clip.mp4", "platform": "facebook_reels", "language": "vi"}
    # cross-site requests without the custom header are refused before any spend
    assert client.post("/api/social/fight", json=body).status_code == 403
    hdr = {"X-Backlot-Action": "social"}
    r = client.post("/api/social/fight", json=body, headers=hdr)
    assert r.status_code == 200 and r.json()["caption"] == "C"
    assert client.post("/api/social/fight", json={**body, "video": "../../etc/passwd"}, headers=hdr).status_code in (403, 404)
    assert client.post("/api/social/fight", json={**body, "platform": "myspace"}, headers=hdr).status_code == 422
    assert client.get("/gallery").status_code == 200


def test_social_endpoint_reports_missing_key(client, projects_root, monkeypatch):
    p = _project(projects_root)
    (p / "assets" / "video" / "clip.mp4").write_bytes(b"x")
    monkeypatch.delenv("PIAPI_KEY", raising=False)
    monkeypatch.delenv("PIAPI_API_KEY", raising=False)
    r = client.post("/api/social/fight", json={"video": "assets/video/clip.mp4", "platform": "tiktok"},
                    headers={"X-Backlot-Action": "social"})
    assert r.status_code == 502 and "PIAPI" in r.json()["detail"]


# ---- thumbnails --------------------------------------------------------------

import shutil
import subprocess

from backlot import thumbs

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _tiny_video(path: Path) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=10",
                    "-t", "2", "-pix_fmt", "yuv420p", str(path)], check=True)


@needs_ffmpeg
def test_capture_frame_and_list(projects_root):
    p = _project(projects_root)
    _tiny_video(p / "assets" / "video" / "clip.mp4")
    t = thumbs.capture_frame(p, "assets/video/clip.mp4", 1.25)
    assert t["kind"] == "frame" and t["time_s"] == 1.25
    assert (p / t["path"]).is_file() and t["path"].startswith("artifacts/thumbs/")
    listed = social.list_videos(projects_root)[0]["thumbs"]
    assert [x["path"] for x in listed] == [t["path"]]


def test_thumb_prompt_text_rules():
    with_text = thumbs.build_thumb_prompt(aspect="9:16", title_text="Một mình giữa mưa", style_notes="", video_prompt="P")
    assert "Một mình giữa mưa" in with_text and "diacritic" in with_text and "vertical 9:16" in with_text
    no_text = thumbs.build_thumb_prompt(aspect="16:9", title_text="  ", style_notes="neon", video_prompt=None)
    assert "Do not put any text" in no_text and "neon" in no_text


@needs_ffmpeg
def test_generate_ai_thumb_uses_piapi_image(projects_root, monkeypatch):
    from tools.base_tool import ToolResult
    from tools.graphics import piapi_image

    p = _project(projects_root)
    _tiny_video(p / "assets" / "video" / "clip.mp4")
    frame = thumbs.capture_frame(p, "assets/video/clip.mp4", 0.5)
    seen = {}

    def fake_execute(self, inputs):
        seen.update(inputs)
        Path(inputs["output_path"]).write_bytes(b"PNG")
        return ToolResult(success=True, data={"task_ids": ["t1"]}, cost_usd=0.03)

    monkeypatch.setattr(piapi_image.PiAPIImage, "execute", fake_execute)
    t = thumbs.generate_ai_thumb(p, "assets/video/clip.mp4", frame_path=frame["path"], aspect="9:16",
                                 title_text="Sasa", video_prompt="rooftop")
    assert t["kind"] == "ai" and t["aspect_ratio"] == "9:16" and t["cost_usd"] == 0.03
    assert seen["image_path"].endswith(frame["name"]) and seen["aspect_ratio"] == "9:16"
    assert seen["model"] == thumbs.AI_MODEL and '"Sasa"' in seen["prompt"]
    with pytest.raises(ValueError):
        thumbs.generate_ai_thumb(p, "assets/video/clip.mp4", frame_path="../../x.png")
    with pytest.raises(ValueError):
        thumbs.generate_ai_thumb(p, "assets/video/clip.mp4", frame_path=frame["path"], aspect="2:1")


@needs_ffmpeg
def test_thumb_endpoints(client, projects_root, monkeypatch):
    from tools.base_tool import ToolResult
    from tools.graphics import piapi_image

    p = _project(projects_root)
    _tiny_video(p / "assets" / "video" / "clip.mp4")
    body = {"video": "assets/video/clip.mp4", "time_s": 1}
    assert client.post("/api/thumbs/fight/frame", json=body).status_code == 403
    hdr = {"X-Backlot-Action": "thumb"}
    frame = client.post("/api/thumbs/fight/frame", json=body, headers=hdr).json()
    assert frame["kind"] == "frame"

    def fake_execute(self, inputs):
        Path(inputs["output_path"]).write_bytes(b"PNG")
        return ToolResult(success=True, data={}, cost_usd=0.03)

    monkeypatch.setattr(piapi_image.PiAPIImage, "execute", fake_execute)
    ai = client.post("/api/thumbs/fight/ai", headers=hdr,
                     json={"video": "assets/video/clip.mp4", "frame": frame["path"], "aspect": "16:9"})
    assert ai.status_code == 200 and ai.json()["kind"] == "ai"
    missing = client.post("/api/thumbs/fight/ai", headers=hdr,
                          json={"video": "assets/video/clip.mp4", "frame": "artifacts/nope.png"})
    assert missing.status_code == 404
    opts = client.get("/api/social/options").json()
    assert opts["thumb_model"] == thumbs.AI_MODEL and opts["thumb_cost_usd"] == 0.03
