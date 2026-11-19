"""Image captions on the Images page: vision first, prompt fallback (no network)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backlot import images as imagegen
from backlot import server as server_mod
from backlot import social
from backlot import state as state_mod

REPLY = json.dumps({"captions": ["Sasa đứng giữa mưa neon 🌧️", "Một mình, sáu đối thủ"],
                    "hashtags": ["#Sasa", "sasa", "#AIart"], "alt_text": "Cô gái đứng trên mái nhà trong mưa."})


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    p = root / "sasa-posters"
    folder = p / "assets" / "images"
    folder.mkdir(parents=True)
    (p / "project.json").write_text(json.dumps({"title": "Sasa Posters"}))
    Image.new("RGB", (2000, 1200), (30, 30, 60)).save(folder / "poster.png")
    (folder / "poster.meta.json").write_text(json.dumps({"prompt": "Sasa on a rainy neon rooftop, 8k, --ar 16:9"}))
    Image.new("RGB", (400, 400), (200, 10, 10)).save(folder / "upload.jpg")  # no sidecar: not AI, no prompt
    from tools import piapi_client

    monkeypatch.setattr(piapi_client, "get_api_key", lambda: "k")
    return root, p


def _fake_chat(monkeypatch, refuse_images=False):
    calls = []

    def chat(messages, model, api_key):
        content = messages[1]["content"]
        has_image = isinstance(content, list)
        calls.append({"image": has_image, "text": content[0]["text"] if has_image else content})
        if has_image and refuse_images:
            raise RuntimeError("PiAPI chat HTTP 400: image input not supported")
        return REPLY, {"total_tokens": 900}

    monkeypatch.setattr(social, "_chat", chat)
    return calls


def test_parse_image_copy_normalises():
    out = social.parse_image_copy("ok " + REPLY)
    assert out["caption"] == "Sasa đứng giữa mưa neon 🌧️" and len(out["captions"]) == 2
    assert out["hashtags"] == ["#Sasa", "#AIart"]  # duplicate (case-insensitive) dropped
    with pytest.raises(ValueError):
        social.parse_image_copy('{"captions": []}')


def test_caption_uses_vision_and_saves(project, monkeypatch):
    root, p = project
    calls = _fake_chat(monkeypatch)

    rec = social.generate_image_caption(p, "assets/images/poster.png", platform="instagram_post")

    assert rec["vision"] is True and calls[0]["image"] is True
    assert "AI-generated" in calls[0]["text"]  # sidecar present -> disclosure requirement
    assert rec["alt_text"].startswith("Cô gái")
    saved = json.loads(social.social_path(p, "assets/images/poster.png").read_text())
    assert saved["kind"] == "image" and saved["platform"] == "instagram_post"

    social.generate_image_caption(p, "assets/images/poster.png", platform="facebook_post")
    assert len(json.loads(social.social_path(p, "assets/images/poster.png").read_text())["history"]) == 1

    listed = {i["name"]: i for i in imagegen.list_images(root)}
    assert listed["poster.png"]["social"]["caption"] == rec["caption"]
    assert listed["upload.jpg"]["social"] is None


def test_falls_back_to_prompt_when_images_refused(project, monkeypatch):
    _, p = project
    calls = _fake_chat(monkeypatch, refuse_images=True)

    rec = social.generate_image_caption(p, "assets/images/poster.png", platform="threads")

    assert rec["vision"] is False and "image input not supported" in rec["vision_error"]
    assert [c["image"] for c in calls] == [True, False]


def test_no_prompt_and_vision_refused_asks_for_notes(project, monkeypatch):
    _, p = project
    _fake_chat(monkeypatch, refuse_images=True)

    with pytest.raises(RuntimeError, match="add notes"):
        social.generate_image_caption(p, "assets/images/upload.jpg", platform="facebook_post")
    rec = social.generate_image_caption(p, "assets/images/upload.jpg", platform="facebook_post",
                                        notes="Ảnh chụp poster in tại xưởng")
    assert rec["vision"] is False


def test_validation(project):
    _, p = project
    with pytest.raises(ValueError):
        social.generate_image_caption(p, "assets/images/poster.png", platform="myspace")
    with pytest.raises(FileNotFoundError):
        social.generate_image_caption(p, "assets/images/missing.png", platform="facebook_post")


def test_image_is_downscaled_before_sending(project):
    _, p = project
    import base64
    import io

    url = social._image_data_url(p / "assets" / "images" / "poster.png")
    with Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))) as im:
        assert max(im.size) == social.VISION_MAX_SIDE and im.format == "JPEG"


def test_caption_endpoint(project, monkeypatch):
    root, _ = project
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", root)
    monkeypatch.setattr(server_mod, "PROJECTS_DIR", root)
    monkeypatch.setattr(server_mod, "_summary_cache", {})

    async def no_watch():
        return None

    monkeypatch.setattr(server_mod, "_watch_projects", no_watch)
    _fake_chat(monkeypatch)
    body = {"project_id": "sasa-posters", "path": "assets/images/poster.png", "platform": "facebook_post"}
    with TestClient(server_mod.create_app()) as c:
        assert c.post("/api/images/caption", json=body).status_code == 403
        H = {"X-Backlot-Action": "social"}
        r = c.post("/api/images/caption", headers=H, json=body)
        assert r.status_code == 200 and r.json()["caption"]
        assert c.post("/api/images/caption", headers=H, json={**body, "path": "../../x.png"}).status_code == 403
        assert c.post("/api/images/caption", headers=H, json={**body, "path": "assets/images/nope.png"}).status_code == 404
        assert c.post("/api/images/caption", headers=H, json={**body, "platform": "x"}).status_code == 422
        opts = c.get("/api/images/options").json()
        assert {p["id"] for p in opts["caption_platforms"]} >= {"facebook_post", "instagram_post"}


def test_hashtags_are_stripped_from_captions():
    reply = json.dumps({"captions": ["Dòng 1\nDòng 2\n\n#A #B\n#C", "Không tag"], "hashtags": ["#A"]})
    out = social.parse_image_copy(reply)
    assert out["captions"] == ["Dòng 1\nDòng 2", "Không tag"]


def test_ai_disclosure_override(project, monkeypatch):
    _, p = project
    calls = _fake_chat(monkeypatch)
    rec = social.generate_image_caption(p, "assets/images/upload.jpg", platform="facebook_post", ai_generated=True)
    assert rec["ai_generated"] is True and "AI-generated" in calls[0]["text"]
    rec = social.generate_image_caption(p, "assets/images/poster.png", platform="facebook_post", ai_generated=False)
    assert rec["ai_generated"] is False and "AI-generated" not in calls[1]["text"]
