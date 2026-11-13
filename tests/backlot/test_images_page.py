"""Backlot Images page: free-form generation into a project (no network)."""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backlot import images as imagegen
from backlot import server as server_mod
from backlot import state as state_mod
from lib import characters as ch
from tools.base_tool import ToolResult
from tools.graphics import piapi_image

H = {"X-Backlot-Action": "image"}


def _png_bytes(color=(10, 120, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (24, 24), color).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def client(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", projects)
    monkeypatch.setattr(server_mod, "PROJECTS_DIR", projects)
    monkeypatch.setattr(server_mod, "_summary_cache", {})
    monkeypatch.setattr(server_mod, "THUMB_CACHE_DIR", tmp_path / "thumbs")
    monkeypatch.setattr(ch, "CHARACTERS_DIR", tmp_path / "characters")

    async def no_watch():
        return None

    monkeypatch.setattr(server_mod, "_watch_projects", no_watch)
    with TestClient(server_mod.create_app()) as c:
        c.projects = projects
        c.tmp = tmp_path
        yield c


@pytest.fixture
def fake_tool(monkeypatch):
    seen = {}

    def execute(self, inputs):
        seen.update(inputs)
        n = int(inputs.get("n", 1))
        base = Path(inputs["output_path"])
        paths = [base] if n == 1 else [base.with_name(f"{base.stem}_{i + 1}{base.suffix}") for i in range(n)]
        for p in paths:
            p.write_bytes(_png_bytes())
        return ToolResult(success=True, data={"task_ids": ["t"] * n}, artifacts=[str(p) for p in paths],
                          cost_usd=0.03 * n)

    monkeypatch.setattr(piapi_image.PiAPIImage, "execute", execute)
    return seen


def test_options_lists_models_projects_characters(client):
    (client.projects / "film").mkdir()
    (client.projects / "film" / "project.json").write_text(json.dumps({"title": "Film"}))
    ch.create("Sasa")
    ch.create("Empty")
    ch.add_image("sasa", _write(client.tmp / "s.png"))
    o = client.get("/api/images/options").json()
    models = {m["id"]: m for m in o["models"]}
    assert models["nano-banana-2.1"]["resolutions"] == ["1K", "2K", "4K"]
    assert models["gemini-2.5-flash-image"]["resolutions"] == []
    assert o["projects"] == [{"project_id": "film", "title": "Film"}]
    assert [c["id"] for c in o["characters"]] == ["sasa"]          # characters without images are hidden


def _write(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_png_bytes())
    return path


def test_generate_into_new_project_with_refs(client, fake_tool):
    src = client.projects / "film"
    _write(src / "assets" / "images" / "bg.png")
    ch.create("Sasa")
    ch.add_image("sasa", _write(client.tmp / "s.png"))
    body = {
        "prompt": "Sasa on a rooftop poster", "model": "nano-banana-2.1", "aspect": "9:16", "resolution": "2K", "n": 2,
        "new_project": "Sasa Posters", "characters": ["sasa"], "character_refs": "primary",
        "references": [{"project_id": "film", "path": "assets/images/bg.png"}],
        "uploads": [{"file_name": "logo.png", "data_base64": "data:image/png;base64," + base64.b64encode(_png_bytes()).decode()}],
    }
    assert client.post("/api/images/generate", json=body).status_code == 403
    r = client.post("/api/images/generate", json=body, headers=H)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["project_id"] == "sasa-posters" and len(out["images"]) == 2 and out["cost_usd"] == 0.06
    assert (client.projects / "sasa-posters" / "project.json").is_file()
    assert fake_tool["characters"] == ["sasa"] and fake_tool["character_refs"] == "primary"
    assert fake_tool["aspect_ratio"] == "9:16" and fake_tool["resolution"] == "2K" and fake_tool["n"] == 2
    assert len(fake_tool["image_paths"]) == 2                        # project ref + upload
    meta = json.loads((client.projects / "sasa-posters" / out["images"][0]).with_name(
        Path(out["images"][0]).stem + ".meta.json").read_text())
    assert meta["prompt"] == "Sasa on a rooftop poster" and meta["cost_usd"] == 0.03
    assert meta["references"] == ["film/assets/images/bg.png", "upload:logo.png"]

    listed = client.get("/api/images").json()
    gen = [i for i in listed if i["project_id"] == "sasa-posters"]
    assert len(gen) == 2 and all(i["generated"] and i["characters"] == ["sasa"] for i in gen)
    assert any(i["project_id"] == "film" and not i["generated"] for i in listed)   # plain images listed too

    again = client.post("/api/images/generate", json={**body, "n": 1}, headers=H)
    assert again.status_code == 409                                  # new project name already taken


def test_generate_validation(client, fake_tool):
    (client.projects / "film").mkdir()
    ok = {"prompt": "x", "project_id": "film"}
    assert client.post("/api/images/generate", json={**ok, "prompt": " "}, headers=H).status_code == 422
    assert client.post("/api/images/generate", json={**ok, "n": 9}, headers=H).status_code == 422
    assert client.post("/api/images/generate", json={**ok, "project_id": "nope"}, headers=H).status_code == 404
    assert client.post("/api/images/generate", json={**ok, "characters": ["ghost"]}, headers=H).status_code == 404
    assert client.post("/api/images/generate", headers=H,
                       json={**ok, "references": [{"project_id": "film", "path": "../../x.png"}]}).status_code == 403
    assert client.post("/api/images/generate", headers=H,
                       json={**ok, "uploads": [{"file_name": "a.exe", "data_base64": "AA=="}]}).status_code == 422
    assert client.get("/images").status_code == 200


def test_generate_reports_tool_failure(client, monkeypatch):
    (client.projects / "film").mkdir()
    monkeypatch.setattr(piapi_image.PiAPIImage, "execute",
                        lambda self, i: ToolResult(success=False, error="PiAPI says no"))
    r = client.post("/api/images/generate", json={"prompt": "x", "project_id": "film"}, headers=H)
    assert r.status_code == 502 and "PiAPI says no" in r.json()["detail"]
