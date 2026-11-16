"""Product library: storage, reference sets, project links, cart lines, piapi_image wiring."""

from __future__ import annotations

import json

import pytest
from PIL import Image

from lib import products as prod


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENMONTAGE_PRODUCTS_DIR", str(tmp_path / "products"))
    return tmp_path


def _img(path, color=(200, 30, 30)):
    Image.new("RGB", (300, 300), color).save(path)
    return path


def test_create_update_and_validate(root):
    p = prod.create("Tai nghe Đen X1", affiliate_url="https://s.shopee.vn/AbC123", price="199.000đ",
                    tags="audio, bluetooth")
    assert p["id"] == "tai-nghe-den-x1" and p["is_shopee"] and p["tags"] == ["audio", "bluetooth"]
    assert prod.create("Tai nghe Đen X1")["id"] == "tai-nghe-den-x1-2"
    with pytest.raises(ValueError):
        prod.update(p["id"], affiliate_url="shopee.vn/abc")  # not a full URL
    assert prod.update(p["id"], affiliate_url="https://example.com/x")["is_shopee"] is False
    with pytest.raises(ValueError):
        prod.create("  ")
    saved = json.loads((root / "products" / p["id"] / "product.json").read_text())
    assert "is_shopee" not in saved and "primary_path" not in saved


def test_images_primary_and_reference_set(root):
    pid = prod.create("Bình nước")["id"]
    with pytest.raises(ValueError):
        prod.references([pid])  # no photo yet
    a = _img(root / "a.jpeg")
    prod.add_image(pid, a)                       # first photo becomes primary
    prod.add_image(pid, _img(root / "b.png"), role="label")
    prod.add_image(pid, _img(root / "c.png"), role="in_use")
    p = prod.add_image(pid, _img(root / "d.png"), role="back")
    assert p["primary_image"] == "ref_01.jpg"
    refs = prod.references([pid])[0]["refs"]
    assert [r["role"] for r in refs] == ["front", "label", "back"]   # in_use is not in the set

    p = prod.remove_image(pid, "ref_01.jpg")
    assert p["primary_image"] == "ref_02.png"
    assert list((root / "products" / "_trash" / pid).glob("*ref_01.jpg"))


def test_lock_sentence_protects_label_text(root):
    pid = prod.create("Son Kem", look="matte red lipstick tube, gold cap")["id"]
    prod.add_image(pid, _img(root / "a.png"))
    item = prod.references([pid])[0]
    text = prod.lock_sentence(item["product"], [3], item["refs"])
    assert text.startswith("[product_lock] Reference image 3 is the product \"Son Kem\": matte red lipstick")
    assert "do not re-letter" in text


def test_project_links_and_cart(root):
    proj = root / "projects" / "demo"
    proj.mkdir(parents=True)
    (proj / "project.json").write_text(json.dumps({"title": "Demo", "pipeline_type": "images"}))
    a = prod.create("A", affiliate_url="https://s.shopee.vn/a", price="99k")
    b = prod.create("B")
    assert prod.link_project(proj, [a["id"], b["id"], a["id"]]) == ["a", "b"]
    assert json.loads((proj / "project.json").read_text())["title"] == "Demo"   # other keys kept
    assert prod.projects_using(root / "projects", "a") == ["demo"]
    with pytest.raises(KeyError):
        prod.link_project(proj, ["nope"])

    items = prod.resolve_for(proj)
    assert prod.cart_block(items, "facebook_reels") == "🛒 Mua A (99k): https://s.shopee.vn/a"  # B has no link
    assert "bio" in prod.cart_block(items, "instagram_reels")
    assert prod.cart_block([prod.get("b")], "facebook_post") == ""
    assert [p["id"] for p in prod.resolve_for(proj, ["b", "ghost"])] == ["b"]   # sidecar list wins, unknown skipped
    assert "do NOT write any URL" in prod.prompt_context(items)


def test_delete_moves_to_trash(root):
    pid = prod.create("X")["id"]
    assert "_trash" in prod.delete(pid)
    assert prod.list_products() == []


def test_piapi_image_puts_product_refs_after_characters(root, monkeypatch):
    from tools import piapi_client
    from tools.graphics.piapi_image import PiAPIImage

    pid = prod.create("Tai nghe")["id"]
    prod.add_image(pid, _img(root / "a.png"))
    prod.add_image(pid, _img(root / "b.png"), role="label")
    uploads = []
    monkeypatch.setattr(piapi_client, "upload", lambda path, key: uploads.append(path) or f"https://cdn/{len(uploads)}")

    payload = PiAPIImage()._build_payload({"prompt": "on a desk", "products": [pid],
                                            "image_paths": [str(_img(root / "extra.png"))]}, "k")
    text = payload["input"]["prompt"]
    assert text.startswith("[product_lock] Reference images 1 (front view), 2 (label / logo close-up)")
    assert text.endswith("on a desk")
    assert uploads[-1].endswith("extra.png") and len(payload["input"]["image_urls"]) == 3
    with pytest.raises(ValueError):
        PiAPIImage()._build_payload({"prompt": "x", "products": ["ghost"]}, "k")
