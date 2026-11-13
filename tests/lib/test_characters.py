"""Character library + tool integration + Backlot API (no network)."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from lib import characters as ch


@pytest.fixture
def lib_dir(tmp_path, monkeypatch):
    root = tmp_path / "characters"
    monkeypatch.setattr(ch, "CHARACTERS_DIR", root)
    return root


def _png(path: Path, color=(200, 30, 30)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (30, 40), color).save(path)
    return path


def test_slugify_vietnamese():
    assert ch.slugify("Sasa Đỏ — Nữ chiến binh") == "sasa-do-nu-chien-binh"
    assert ch.slugify("!!!") == "character"


def test_create_add_images_primary_and_identity(lib_dir, tmp_path):
    c = ch.create("Sasa", description="mô tả", identity="red jacket, ponytail.", tags=["hero", " "])
    assert c["id"] == "sasa" and c["tags"] == ["hero"] and c["primary_path"] is None
    assert ch.create("Sasa")["id"] == "sasa-2"                       # no overwrite on name clash

    c = ch.add_image("sasa", _png(tmp_path / "a.png"))
    assert c["primary_image"] == "ref_01.png"                        # first image becomes primary
    c = ch.add_image("sasa", _png(tmp_path / "b.jpg"), note="side")
    assert [i["file"] for i in c["images"]] == ["ref_01.png", "ref_02.jpg"]
    assert c["primary_image"] == "ref_01.png"
    c = ch.set_primary("sasa", "ref_02.jpg")
    assert c["primary_path"].endswith("ref_02.jpg")

    block = ch.identity_block(["sasa"])
    assert block.startswith("[identity_lock] Sasa is @image1: red jacket, ponytail.")
    assert ch.reference_paths(["sasa"]) == [str(lib_dir / "sasa" / "ref_02.jpg")]
    assert [x["id"] for x in ch.list_characters()] == ["sasa", "sasa-2"]


def test_errors(lib_dir, tmp_path):
    with pytest.raises(ValueError):
        ch.create("  ")
    with pytest.raises(KeyError):
        ch.get("nobody")
    with pytest.raises(ValueError):
        ch.get("../etc")
    ch.create("Empty")
    with pytest.raises(ValueError, match="no reference image"):
        ch.reference_paths(["empty"])
    (tmp_path / "x.txt").write_text("x")
    with pytest.raises(ValueError):
        ch.add_image("empty", tmp_path / "x.txt")
    with pytest.raises(ValueError):
        ch.set_primary("empty", "ref_09.png")


def test_seedance_payload_uses_library_character(lib_dir, tmp_path, monkeypatch):
    from tools.video.seedance_piapi import SeedancePiAPI

    ch.create("Sasa", identity="crimson jacket")
    ch.add_image("sasa", _png(tmp_path / "s.png"))
    uploads = []
    tool = SeedancePiAPI()
    monkeypatch.setattr(tool, "_upload", lambda p, k: uploads.append(p) or f"https://cdn/{Path(p).name}")
    p = tool._build_payload({"prompt": "@image1 fights in the rain", "operation": "reference_to_video",
                             "characters": ["sasa"], "reference_image_urls": ["https://cdn/room.png"]}, "k")
    assert p["input"]["image_urls"] == ["https://cdn/ref_01.png", "https://cdn/room.png"]
    assert p["input"]["prompt"].startswith("[identity_lock] Sasa is @image1: crimson jacket")
    assert p["input"]["prompt"].endswith("@image1 fights in the rain")
    with pytest.raises(ValueError, match="reference_to_video"):
        tool._build_payload({"prompt": "x", "characters": ["sasa"]}, "k")
    with pytest.raises(ValueError, match="unknown character"):
        tool._build_payload({"prompt": "x", "operation": "reference_to_video", "characters": ["ghost"]}, "k")
    no_block = tool._build_payload({"prompt": "x", "operation": "reference_to_video", "characters": ["sasa"],
                                    "character_identity_block": False}, "k")
    assert no_block["input"]["prompt"] == "x"


def test_piapi_image_payload_puts_characters_first(lib_dir, tmp_path, monkeypatch):
    from tools import piapi_client
    from tools.graphics.piapi_image import PiAPIImage

    ch.create("Sasa", identity="crimson jacket")
    ch.add_image("sasa", _png(tmp_path / "s.png"))
    monkeypatch.setattr(piapi_client, "upload", lambda p, k: f"https://cdn/{Path(p).name}")
    p = PiAPIImage()._build_payload({"prompt": "poster", "characters": ["sasa"],
                                     "image_urls": ["https://cdn/bg.png"]}, "k")
    assert p["input"]["image_urls"] == ["https://cdn/ref_01.png", "https://cdn/bg.png"]
    assert p["input"]["prompt"].startswith("Reference image 1 is Sasa: crimson jacket.")


# ---- Backlot API ---------------------------------------------------------------

@pytest.fixture
def client(lib_dir, tmp_path, monkeypatch):
    from backlot import server as server_mod
    from backlot import state as state_mod

    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", projects)
    monkeypatch.setattr(server_mod, "PROJECTS_DIR", projects)
    monkeypatch.setattr(server_mod, "_summary_cache", {})

    async def no_watch():
        return None

    monkeypatch.setattr(server_mod, "_watch_projects", no_watch)
    with TestClient(server_mod.create_app()) as c:
        c.projects = projects
        yield c


H = {"X-Backlot-Action": "character"}


def test_api_character_flow(client, tmp_path, monkeypatch):
    assert client.post("/api/characters", json={"name": "Sasa"}).status_code == 403
    c = client.post("/api/characters", json={"name": "Sasa", "identity": "red", "tags": ["a"]}, headers=H).json()
    assert c["id"] == "sasa"

    proj = client.projects / "film"
    _png(proj / "assets" / "images" / "hero.png")
    sources = client.get("/api/characters/sources").json()
    assert sources[0] == {"project_id": "film", "path": "assets/images/hero.png", "modified": sources[0]["modified"]}

    r = client.post("/api/characters/sasa/images", json={"project_id": "film", "path": "assets/images/hero.png"}, headers=H)
    assert r.status_code == 200 and r.json()["primary_image"] == "ref_01.png"
    assert client.post("/api/characters/sasa/images", headers=H,
                       json={"project_id": "film", "path": "../../etc/passwd"}).status_code == 403

    png = _png(tmp_path / "up.png").read_bytes()
    r = client.post("/api/characters/sasa/images", headers=H,
                    json={"file_name": "up.png", "data_base64": "data:image/png;base64," + base64.b64encode(png).decode()})
    assert r.status_code == 200 and len(r.json()["images"]) == 2
    assert client.post("/api/characters/sasa/images", headers=H,
                       json={"file_name": "x.exe", "data_base64": "AAAA"}).status_code == 422

    assert client.post("/api/characters/sasa/primary", json={"file": "ref_02.png"}, headers=H).json()["primary_image"] == "ref_02.png"
    assert client.post("/api/characters/sasa", json={"name": "Sasa Red"}, headers=H).json()["name"] == "Sasa Red"
    assert client.get("/character-media/sasa/ref_01.png").status_code == 200
    assert client.get("/character-media/sasa/character.json").status_code == 404     # only listed images
    assert client.get("/characters").status_code == 200

    from tools.base_tool import ToolResult
    from tools.graphics import piapi_image

    seen = {}

    def fake_execute(self, inputs):
        seen.update(inputs)
        _png(Path(inputs["output_path"]), (0, 0, 255))
        return ToolResult(success=True, data={}, cost_usd=0.03)

    monkeypatch.setattr(piapi_image.PiAPIImage, "execute", fake_execute)
    r = client.post("/api/characters/sasa/generate", json={"prompt": "side view"}, headers=H)
    assert r.status_code == 200 and len(r.json()["images"]) == 3
    assert seen["characters"] == ["sasa"]
    assert json.loads((ch.characters_dir() / "sasa" / "character.json").read_text())["images"][2]["source"] == "ai:nano-banana-2.1"


def test_reference_set_roles_and_identity(lib_dir, tmp_path):
    ch.create("Sasa", identity="crimson jacket")
    ch.add_image("sasa", _png(tmp_path / "full.png"), role="full_body")
    ch.add_image("sasa", _png(tmp_path / "other.png"))                       # role "other": never in the set
    ch.add_image("sasa", _png(tmp_path / "back.png"), role="back")
    ch.add_image("sasa", _png(tmp_path / "face.png"), role="face")
    ch.add_image("sasa", _png(tmp_path / "face2.png"), role="face")          # only the first face is used
    ch.add_image("sasa", _png(tmp_path / "side.png"), role="side")
    c = ch.get("sasa")
    assert [r["file"] for r in ch.reference_set(c)] == ["ref_01.png", "ref_04.png", "ref_03.png"]  # full, face, back
    assert [r["file"] for r in ch.reference_set(c, 4)][-1] == "ref_06.png"                           # + side (no face_34)
    assert len(ch.references(["sasa"], "full")[0]["refs"]) == 4                                       # all it has
    assert len(ch.reference_paths(["sasa"], mode="primary")) == 1

    block = ch.identity_block(["sasa"])
    assert "Sasa is shown in @image1–@image3, all the same person" in block
    assert "@image2 front face close-up" in block and "@image3 back view" in block

    ch.create("Bo", identity="blue coat")
    ch.add_image("bo", _png(tmp_path / "bo.png"))
    two = ch.identity_block(["sasa", "bo"])
    assert "Bo is @image4: blue coat" in two                                   # numbering continues
    assert ch.set_role("sasa", "ref_02.png", "side")["images"][1]["role"] == "side"
    with pytest.raises(ValueError):
        ch.set_role("sasa", "ref_02.png", "hero")
    with pytest.raises(ValueError):
        ch.add_image("sasa", _png(tmp_path / "x.png"), role="hero")


def test_tools_send_reference_set(lib_dir, tmp_path, monkeypatch):
    from tools import piapi_client
    from tools.graphics.piapi_image import PiAPIImage
    from tools.video.seedance_piapi import SeedancePiAPI

    ch.create("Sasa", identity="crimson jacket")
    ch.add_image("sasa", _png(tmp_path / "full.png"), role="full_body")
    ch.add_image("sasa", _png(tmp_path / "face.png"), role="face")
    tool = SeedancePiAPI()
    monkeypatch.setattr(tool, "_upload", lambda p, k: f"https://cdn/{Path(p).name}")
    p = tool._build_payload({"prompt": "go", "operation": "reference_to_video", "characters": ["sasa"]}, "k")
    assert p["input"]["image_urls"] == ["https://cdn/ref_01.png", "https://cdn/ref_02.png"]
    assert "@image2 front face close-up" in p["input"]["prompt"]
    p = tool._build_payload({"prompt": "go", "operation": "reference_to_video", "characters": ["sasa"],
                             "character_refs": "primary"}, "k")
    assert p["input"]["image_urls"] == ["https://cdn/ref_01.png"]

    monkeypatch.setattr(piapi_client, "upload", lambda p, k: f"https://cdn/{Path(p).name}")
    img = PiAPIImage()._build_payload({"prompt": "poster", "characters": ["sasa"]}, "k")
    assert img["input"]["image_urls"] == ["https://cdn/ref_01.png", "https://cdn/ref_02.png"]
    assert img["input"]["prompt"].startswith("Reference images 1 (full-body front view), 2 (front face close-up) all show Sasa")


def test_api_roles(client, tmp_path):
    ch.create("Sasa")
    ch.add_image("sasa", _png(tmp_path / "a.png"))
    assert {r["id"] for r in client.get("/api/characters/roles").json()} >= {"full_body", "face", "back"}
    r = client.post("/api/characters/sasa/role", json={"file": "ref_01.png", "role": "face"}, headers=H)
    assert r.status_code == 200 and r.json()["images"][0]["role"] == "face"
    assert client.post("/api/characters/sasa/role", json={"file": "ref_01.png", "role": "x"}, headers=H).status_code == 422
    proj = client.projects / "film"
    _png(proj / "assets" / "images" / "b.png")
    r = client.post("/api/characters/sasa/images", headers=H,
                    json={"project_id": "film", "path": "assets/images/b.png", "role": "back"})
    assert r.json()["images"][1]["role"] == "back"


def _sheet(path: Path, figures=((40, 120), (200, 300), (380, 470)), size=(520, 300)) -> Path:
    from PIL import ImageDraw

    img = Image.new("RGB", size, (205, 207, 210))                     # light grey backdrop
    d = ImageDraw.Draw(img)
    for x0, x1 in figures:
        d.rectangle([x0, 30, x1, 280], fill=(20, 20, 25))               # dark figure
        d.rectangle([x0 + 10, 60, x1 - 10, 120], fill=(150, 25, 35))    # red jacket
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path


def test_split_sheet_finds_panels(tmp_path):
    panels = ch.split_sheet(_sheet(tmp_path / "sheet.png"), tmp_path / "out")
    assert len(panels) == 3
    for (l, t, r, b), (x0, x1) in zip([p["box"] for p in panels], ((40, 120), (200, 300), (380, 470))):
        assert l <= x0 and r > x1                      # whole figure inside its crop
        assert t <= 30 and b > 280
    assert panels[0]["box"][2] <= 200 and panels[1]["box"][0] >= 120   # crops don't reach into neighbours
    with pytest.raises(ValueError):
        ch.split_sheet(_png(tmp_path / "blank.png", (210, 210, 210)), tmp_path / "out2")


def test_api_split_sheet_and_generate_options(client, tmp_path, monkeypatch):
    ch.create("Sasa")
    ch.add_image("sasa", _png(tmp_path / "a.png"), role="full_body")
    ch.add_image("sasa", _sheet(tmp_path / "s.png"), role="sheet")
    r = client.post("/api/characters/sasa/split", json={"file": "ref_02.png"}, headers=H)
    assert r.status_code == 200 and r.json()["split_panels"] == 3
    assert [i["role"] for i in r.json()["images"]] == ["full_body", "sheet", "other", "other", "other"]
    assert client.post("/api/characters/sasa/split", json={"file": "nope.png"}, headers=H).status_code == 404
    # a sheet is never part of the reference set sent to video models
    assert [x["role"] for x in ch.reference_set(ch.get("sasa"), 9)] == ["full_body"]

    from tools.base_tool import ToolResult
    from tools.graphics import piapi_image

    seen = {}

    def fake_execute(self, inputs):
        seen.update(inputs)
        _png(Path(inputs["output_path"]))
        return ToolResult(success=True, data={}, cost_usd=0.04)

    monkeypatch.setattr(piapi_image.PiAPIImage, "execute", fake_execute)
    r = client.post("/api/characters/sasa/generate", headers=H,
                    json={"prompt": "turnaround", "role": "sheet", "aspect": "16:9", "resolution": "2K"})
    assert r.status_code == 200
    assert seen["character_refs"] == "set" and seen["resolution"] == "2K" and seen["aspect_ratio"] == "16:9"
    assert client.post("/api/characters/sasa/generate", headers=H,
                       json={"prompt": "x", "resolution": "8K"}).status_code == 422


def test_full_mode_face_angles_and_equal_split(lib_dir, tmp_path):
    ch.create("Sasa", identity="crimson jacket")
    for name, role in (("full", "full_body"), ("back", "back"), ("side", "side"),
                       ("face", "face"), ("f34", "face_34"), ("fp", "face_profile")):
        ch.add_image("sasa", _png(tmp_path / f"{name}.png"), role=role)
    full = ch.references(["sasa"], "full")[0]["refs"]
    assert [r["role"] for r in full] == ["full_body", "face", "back", "face_34", "side", "face_profile"]
    block = ch.identity_block(["sasa"], mode="full")
    assert "@image1–@image6" in block and "@image6 profile face close-up" in block
    with pytest.raises(ValueError):
        ch.references(["sasa"], "everything")

    # touching panels: gap detection can't separate them, equal columns can
    touching = _sheet(tmp_path / "touch.png", figures=((0, 172), (173, 345), (346, 519)))
    eq = ch.split_sheet(touching, tmp_path / "eq", panels=3)
    assert [p["method"] for p in eq] == ["equal"] * 3 and [p["box"][0] for p in eq] == [0, 173, 347]


def test_pad_to_aspect_and_split_panels_are_seedance_safe(tmp_path):
    narrow = tmp_path / "narrow.png"
    Image.new("RGB", (30, 120), (205, 207, 210)).save(narrow)
    assert ch.pad_to_aspect(narrow) is True
    w, h = Image.open(narrow).size
    assert h == 120 and abs(w / h - 9 / 16) < 0.02
    assert ch.pad_to_aspect(narrow) is False                       # already fine
    wide = tmp_path / "wide.png"
    Image.new("RGB", (400, 100), (205, 207, 210)).save(wide)
    ch.pad_to_aspect(wide)
    assert Image.open(wide).size == (400, 160)

    panels = ch.split_sheet(_sheet(tmp_path / "s.png"), tmp_path / "out")
    assert all(p["width"] / p["height"] >= 9 / 16 - 0.01 for p in panels)


def test_seedance_rejects_narrow_reference_before_upload(tmp_path, monkeypatch):
    from tools import piapi_client
    from tools.video.seedance_piapi import SeedancePiAPI

    narrow = tmp_path / "n.png"
    Image.new("RGB", (30, 120), (0, 0, 0)).save(narrow)
    called = []
    monkeypatch.setattr(piapi_client, "upload", lambda p, k: called.append(p) or "u")
    with pytest.raises(ValueError, match="aspect 0.25"):
        SeedancePiAPI()._upload(str(narrow), "k")
    assert called == []
