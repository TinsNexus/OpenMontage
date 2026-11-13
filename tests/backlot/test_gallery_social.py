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
