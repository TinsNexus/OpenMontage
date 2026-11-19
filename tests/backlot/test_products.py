"""Backlot /api/products routes, product-aware image generation and captions with cart links (no network)."""

from __future__ import annotations

import base64
import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backlot import images as imagegen
from backlot import server as server_mod
from backlot import social
from backlot import state as state_mod
from lib import products as prod

H = {"X-Backlot-Action": "product"}


def _b64(color=(10, 120, 200)) -> str:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENMONTAGE_PRODUCTS_DIR", str(tmp_path / "products"))
    projects = tmp_path / "projects"
    demo = projects / "demo"
    (demo / "assets" / "images").mkdir(parents=True)
    (demo / "assets" / "video").mkdir(parents=True)
    (demo / "project.json").write_text(json.dumps({"title": "Demo"}))
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", projects)
    monkeypatch.setattr(server_mod, "PROJECTS_DIR", projects)
    monkeypatch.setattr(server_mod, "_summary_cache", {})

    async def no_watch():
        return None

    monkeypatch.setattr(server_mod, "_watch_projects", no_watch)
    from tools import piapi_client

    monkeypatch.setattr(piapi_client, "get_api_key", lambda: "k")
    return projects, demo


@pytest.fixture
def client(env):
    with TestClient(server_mod.create_app()) as c:
        yield c


def test_product_crud_and_images(client):
    assert "products.js" in client.get("/products").text
    assert client.post("/api/products", json={"name": "x"}).status_code == 403

    p = client.post("/api/products", headers=H, json={"name": "Tai nghe X1", "affiliate_url": "https://s.shopee.vn/z",
                                                       "price": "199k"}).json()
    assert p["is_shopee"] is True
    assert client.post("/api/products", headers=H, json={"name": "Bad", "affiliate_url": "nope"}).status_code == 422

    r = client.post(f"/api/products/{p['id']}/images", headers=H, json={"file_name": "a.png", "data_base64": _b64()})
    assert r.status_code == 200 and r.json()["primary_image"] == "ref_01.png"
    client.post(f"/api/products/{p['id']}/images", headers=H,
                json={"file_name": "b.png", "data_base64": _b64((1, 2, 3)), "role": "label"})
    assert client.post(f"/api/products/{p['id']}/images", headers=H,
                       json={"file_name": "a.gif", "data_base64": _b64()}).status_code == 422
    assert client.get(f"/product-media/{p['id']}/ref_01.png").status_code == 200
    assert client.get(f"/product-media/{p['id']}/../product.json").status_code == 404

    assert client.post(f"/api/products/{p['id']}/primary", headers=H, json={"file": "ref_02.png"}).json()["primary_image"] == "ref_02.png"
    assert client.post(f"/api/products/{p['id']}/role", headers=H, json={"file": "ref_01.png", "role": "bogus"}).status_code == 422
    assert client.post(f"/api/products/{p['id']}/images/delete", headers=H, json={"file": "ref_02.png"}).json()["primary_image"] == "ref_01.png"

    upd = client.post(f"/api/products/{p['id']}", headers=H, json={"price": "149k", "cta": "👉 Săn deal"}).json()
    assert upd["price"] == "149k" and upd["affiliate_url"] == "https://s.shopee.vn/z"

    r = client.post(f"/api/products/{p['id']}/projects", headers=H, json={"add": ["demo"]}).json()
    assert r["projects"] == ["demo"]
    assert client.get("/api/social/options").json()["project_products"] == {"demo": [p["id"]]}
    assert client.post(f"/api/products/{p['id']}/projects", headers=H, json={"remove": ["demo"]}).json()["projects"] == []

    assert client.get("/api/products/ghost").status_code == 404
    assert client.post(f"/api/products/{p['id']}/delete", headers=H).status_code == 200
    assert client.get("/api/products").json() == []


def test_generate_with_product_records_and_links(env, client, monkeypatch):
    projects, demo = env
    p = prod.create("Bình nước", affiliate_url="https://s.shopee.vn/b")
    seen = {}

    class FakeTool:
        def execute(self, inputs):
            seen.update(inputs)
            from pathlib import Path

            Image.new("RGB", (32, 32)).save(inputs["output_path"])
            return type("R", (), {"success": True, "artifacts": [inputs["output_path"]], "cost_usd": 0.03,
                                  "data": {}, "error": None})()

    import tools.graphics.piapi_image as pi
    monkeypatch.setattr(pi, "PiAPIImage", FakeTool)

    body = {"project_id": "demo", "prompt": "on a desk", "products": [p["id"]]}
    assert client.post("/api/images/generate", headers={"X-Backlot-Action": "image"},
                       json={**body, "products": ["ghost"]}).status_code == 404
    r = client.post("/api/images/generate", headers={"X-Backlot-Action": "image"}, json=body)
    assert r.status_code == 200, r.text
    assert seen["products"] == [p["id"]]
    assert prod.project_product_ids(demo) == [p["id"]]
    listed = imagegen.list_images(projects)
    assert listed[0]["products"] == [p["id"]]
    detail = client.get(f"/api/products/{p['id']}").json()
    assert detail["projects"] == ["demo"] and len(detail["generated"]) == 1


def test_captions_append_cart_verbatim(env, monkeypatch):
    _, demo = env
    a = prod.create("Bình nước", affiliate_url="https://s.shopee.vn/b", price="99k", description="Giữ lạnh 24h")
    prod.link_project(demo, [a["id"]])
    Image.new("RGB", (64, 64)).save(demo / "assets" / "images" / "x.png")
    (demo / "assets" / "video" / "v.mp4").write_bytes(b"0")
    (demo / "assets" / "video" / "v.meta.json").write_text(json.dumps({"prompt": "a bottle on a desk"}))
    prompts = []

    def chat(messages, model, api_key):
        content = messages[1]["content"]
        prompts.append(content if isinstance(content, str) else content[0]["text"])
        if "video" in prompts[-1].split("\n")[0]:
            return json.dumps({"titles": ["t"], "caption": "Mát lạnh cả ngày", "hashtags": ["#a"]}), {}
        return json.dumps({"captions": ["Bình xinh https://fake.link"], "hashtags": ["#b"]}), {}

    monkeypatch.setattr(social, "_chat", chat)

    rec = social.generate_social(demo, "assets/video/v.mp4", platform="facebook_reels")
    assert rec["cart"] == "🛒 Mua Bình nước (99k): https://s.shopee.vn/b"
    assert rec["products"][0]["url"] == "https://s.shopee.vn/b"
    assert "Giữ lạnh 24h" in prompts[-1] and "do NOT write any URL" in prompts[-1]

    rec = social.generate_image_caption(demo, "assets/images/x.png", platform="instagram_post", use_vision=False,
                                        notes="bình nước")
    assert "bio" in rec["cart"]

    rec = social.generate_image_caption(demo, "assets/images/x.png", platform="facebook_post", use_vision=False,
                                        notes="bình nước", products=[])
    assert rec["cart"] == "" and rec["products"] == []
    assert "promotes these products" not in prompts[-1]
