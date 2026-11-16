"""Product library — items you sell or promote (e.g. Shopee affiliate products).

A product is a folder under ``products/`` (override with ``OPENMONTAGE_PRODUCTS_DIR``)::

    products/tai-nghe-x1/
        product.json        # name, description, affiliate_url, price, tags, images
        ref_01.jpg          # product photos (the primary one anchors the look)
        ref_02.jpg

Image tools (``piapi_image``) accept ``products: ["tai-nghe-x1"]``: the
product photos are sent as reference images with a ``[product_lock]``
instruction so the generated scene shows the same product — shape, colours,
logo and label text unchanged. Videos use the product in two hops: generate a
scene image with the product, then animate it as the first frame of an
image-to-video clip.

A project lists the products it promotes in ``project.json["products"]``;
social captions for that project's videos and images then get the cart link
appended verbatim (never written by the model, which mangles URLs).

The folder is gitignored like ``characters/``: it holds personal commercial
data and uploaded photos.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import urlparse

from lib.characters import slugify
from lib.paths import REPO_ROOT

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
MANIFEST = "product.json"
ROLES = {
    "front": "front view",
    "back": "back view",
    "side": "side view",
    "detail": "close-up detail",
    "label": "label / logo close-up",
    "packaging": "packaging",
    "in_use": "product in use",
    "scale": "size reference",
    "other": "extra photo",
}
SET_ROLES = ("label", "back", "side", "packaging", "detail")
DEFAULT_SET_SIZE = 3
MAX_SET_SIZE = 6
SHOPEE_HOSTS = ("shopee.vn", "shope.ee", "shp.ee", "shopee.com", "shopee.co.id", "shopee.ph", "shopee.sg",
                "shopee.co.th", "shopee.com.my", "shopee.tw", "shopee.com.br")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def products_dir() -> Path:
    return Path(os.environ.get("OPENMONTAGE_PRODUCTS_DIR") or (REPO_ROOT / "products"))


def _dir(slug: str) -> Path:
    if not _SLUG_RE.match(slug or ""):
        raise ValueError(f"invalid product id {slug!r}")
    return products_dir() / slug


def is_shopee(url: str) -> bool:
    host = (urlparse(url or "").hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in SHOPEE_HOSTS)


def clean_url(url: Optional[str]) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or " " in url:
        raise ValueError("affiliate link must be a full http(s) URL, e.g. https://s.shopee.vn/...")
    return url


def _load(slug: str) -> dict[str, Any]:
    path = _dir(slug) / MANIFEST
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise KeyError(f"unknown product {slug!r}")
    except json.JSONDecodeError as e:
        raise ValueError(f"{path} is not valid JSON: {e}")
    data["id"] = slug
    data.setdefault("images", [])
    return data


def _save(data: dict[str, Any]) -> dict[str, Any]:
    folder = _dir(data["id"])
    folder.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = time.time()
    clean = {k: v for k, v in data.items() if k not in ("primary_path", "is_shopee")}
    tmp = folder / (MANIFEST + ".tmp")
    tmp.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(folder / MANIFEST)
    return data


def _with_paths(data: dict[str, Any]) -> dict[str, Any]:
    folder = _dir(data["id"])
    images = [img for img in data.get("images", []) if (folder / img["file"]).is_file()]
    primary = data.get("primary_image")
    if primary not in {img["file"] for img in images}:
        primary = images[0]["file"] if images else None
    return {**data, "images": images, "primary_image": primary,
            "primary_path": str(folder / primary) if primary else None,
            "is_shopee": is_shopee(data.get("affiliate_url") or "")}


def list_products() -> list[dict[str, Any]]:
    root = products_dir()
    if not root.is_dir():
        return []
    out = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir() and (p / MANIFEST).is_file()):
        try:
            out.append(_with_paths(_load(folder.name)))
        except (KeyError, ValueError):
            continue
    out.sort(key=lambda c: c.get("updated_at") or 0, reverse=True)
    return out


def get(slug: str) -> dict[str, Any]:
    return _with_paths(_load(slug))


def _text_fields(fields: dict[str, Any], data: dict[str, Any]) -> None:
    for key in ("name", "description", "look", "price", "cta"):
        if key in fields and fields[key] is not None:
            data[key] = str(fields[key]).strip()
    if "affiliate_url" in fields and fields["affiliate_url"] is not None:
        data["affiliate_url"] = clean_url(str(fields["affiliate_url"]))
    if fields.get("tags") is not None:
        tags = fields["tags"]
        if isinstance(tags, str):
            tags = tags.split(",")
        data["tags"] = [str(t).strip() for t in tags if str(t).strip()]


def create(name: str, *, description: str = "", affiliate_url: str = "", price: str = "", look: str = "",
           tags: Iterable[str] | str = (), cta: str = "") -> dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ValueError("name is required")
    base = slugify(name)
    if base == "character":
        base = "product"
    candidate, n = base, 2
    while (products_dir() / candidate).exists():
        candidate, n = f"{base}-{n}", n + 1
    data: dict[str, Any] = {"id": candidate, "images": [], "primary_image": None, "created_at": time.time()}
    _text_fields({"name": name, "description": description, "affiliate_url": affiliate_url, "price": price,
                  "look": look, "tags": tags, "cta": cta}, data)
    return get(_save(data)["id"])


def update(slug: str, **fields: Any) -> dict[str, Any]:
    data = _load(slug)
    _text_fields(fields, data)
    if not data.get("name"):
        raise ValueError("name is required")
    return get(_save(data)["id"])


def delete(slug: str) -> str:
    """Move the product folder to products/_trash (recoverable)."""
    folder = _dir(slug)
    if not (folder / MANIFEST).is_file():
        raise KeyError(f"unknown product {slug!r}")
    trash = products_dir() / "_trash"
    trash.mkdir(parents=True, exist_ok=True)
    dest = trash / f"{slug}-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.move(str(folder), str(dest))
    return str(dest)


def _check_role(role: str) -> str:
    if role not in ROLES:
        raise ValueError(f"role must be one of {list(ROLES)}")
    return role


def add_image(slug: str, source: Path | str, *, note: str = "", source_label: str = "",
              make_primary: bool = False, role: str = "front") -> dict[str, Any]:
    _check_role(role)
    src = Path(source)
    if not src.is_file() or src.suffix.lower() not in IMAGE_EXT:
        raise ValueError(f"not an image file: {src.name}")
    data = _load(slug)
    folder = _dir(slug)
    ext = ".jpg" if src.suffix.lower() == ".jpeg" else src.suffix.lower()
    i = len(data["images"]) + 1
    while (folder / f"ref_{i:02d}{ext}").exists():
        i += 1
    dest = folder / f"ref_{i:02d}{ext}"
    shutil.copy2(src, dest)
    data["images"].append({"file": dest.name, "role": role, "note": note.strip(),
                           "source": source_label or src.name, "added_at": time.time()})
    if make_primary or not data.get("primary_image"):
        data["primary_image"] = dest.name
    return get(_save(data)["id"])


def remove_image(slug: str, file: str) -> dict[str, Any]:
    data = _load(slug)
    if file not in {img["file"] for img in data["images"]}:
        raise ValueError(f"{file} is not an image of {slug}")
    data["images"] = [img for img in data["images"] if img["file"] != file]
    trash = products_dir() / "_trash" / slug
    trash.mkdir(parents=True, exist_ok=True)
    src = _dir(slug) / file
    if src.is_file():
        shutil.move(str(src), str(trash / f"{int(time.time())}_{file}"))
    if data.get("primary_image") == file:
        data["primary_image"] = data["images"][0]["file"] if data["images"] else None
    return get(_save(data)["id"])


def set_role(slug: str, file: str, role: str) -> dict[str, Any]:
    _check_role(role)
    data = _load(slug)
    for img in data["images"]:
        if img["file"] == file:
            img["role"] = role
            return get(_save(data)["id"])
    raise ValueError(f"{file} is not an image of {slug}")


def set_primary(slug: str, file: str) -> dict[str, Any]:
    data = _load(slug)
    if file not in {img["file"] for img in data["images"]}:
        raise ValueError(f"{file} is not an image of {slug}")
    data["primary_image"] = file
    return get(_save(data)["id"])


def image_path(slug: str, file: str) -> Path:
    data = get(slug)
    if file not in {img["file"] for img in data["images"]}:
        raise KeyError(file)
    return _dir(slug) / file


# ---------------------------------------------------------------------------
# Generation helpers
# ---------------------------------------------------------------------------

def reference_set(product: dict[str, Any], size: int = DEFAULT_SET_SIZE) -> list[dict[str, str]]:
    """Primary photo first, then at most one label / back / side / packaging / detail photo."""
    if not product.get("primary_image"):
        raise ValueError(f"product {product['id']!r} has no photo yet")
    folder = _dir(product["id"])
    by_file = {img["file"]: img for img in product["images"]}
    primary = product["primary_image"]
    out = [{"file": primary, "path": str(folder / primary), "role": by_file.get(primary, {}).get("role") or "front"}]
    for role in SET_ROLES:
        if len(out) >= max(1, size):
            break
        match = next((img for img in product["images"] if img.get("role") == role and img["file"] != primary), None)
        if match:
            out.append({"file": match["file"], "path": str(folder / match["file"]), "role": role})
    return out[: max(1, size)]


def references(slugs: Iterable[str], size: int = DEFAULT_SET_SIZE) -> list[dict[str, Any]]:
    """Per product: ``{"product": ..., "refs": [{"path", "role", "file"}, ...]}``."""
    size = max(1, min(int(size), MAX_SET_SIZE))
    return [{"product": p, "refs": reference_set(p, size)} for p in (get(s) for s in slugs)]


def lock_sentence(product: dict[str, Any], numbers: list[int], refs: list[dict[str, str]]) -> str:
    """Prompt text binding reference image numbers to one product (label fidelity first)."""
    if len(numbers) == 1:
        label = f"Reference image {numbers[0]} is"
    else:
        which = ", ".join(f"{n} ({ROLES.get(r['role'], r['role'])})" for n, r in zip(numbers, refs))
        label = f"Reference images {which} all show"
    look = (product.get("look") or product.get("description") or "").strip().rstrip(".")
    return (f"[product_lock] {label} the product \"{product['name']}\"" + (f": {look}" if look else "") + ". "
            "Show this exact product: same shape, proportions, colours, materials, logo and printed label text, "
            "copied from the reference — do not re-letter, translate, blur or invent any text on it, do not "
            "change the brand, do not add a second copy. Keep it clearly visible and in focus.")


# ---------------------------------------------------------------------------
# Projects and captions
# ---------------------------------------------------------------------------

def _project_json(project_dir: Path) -> dict[str, Any]:
    try:
        data = json.loads((project_dir / "project.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def project_product_ids(project_dir: Path) -> list[str]:
    ids = _project_json(project_dir).get("products") or []
    return [str(i) for i in ids if isinstance(i, str)]


def set_project_products(project_dir: Path, ids: Iterable[str]) -> list[str]:
    """Replace the products a project promotes (writes project.json)."""
    path = project_dir / "project.json"
    if not path.is_file():
        raise FileNotFoundError(f"{project_dir.name} has no project.json")
    clean: list[str] = []
    for i in ids:
        get(str(i))  # validates
        if i not in clean:
            clean.append(str(i))
    data = _project_json(project_dir)
    data["products"] = clean
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return clean


def link_project(project_dir: Path, ids: Iterable[str]) -> list[str]:
    """Add products to a project's list (keeps existing ones)."""
    return set_project_products(project_dir, [*project_product_ids(project_dir), *ids])


def projects_using(projects_root: Path, slug: str) -> list[str]:
    if not projects_root.is_dir():
        return []
    return sorted(p.name for p in projects_root.iterdir()
                  if p.is_dir() and slug in project_product_ids(p))


def resolve_for(project_dir: Path, meta_products: Optional[Iterable[str]] = None) -> list[dict[str, Any]]:
    """Products for one piece of media: its own sidecar list, else the project's list. Unknown ids are skipped."""
    ids = list(meta_products or []) or project_product_ids(project_dir)
    out = []
    for i in ids:
        try:
            out.append(get(str(i)))
        except (KeyError, ValueError):
            continue
    return out


# Platforms where a link typed in the caption is not clickable.
NO_LINK_PLATFORMS = {"instagram_post", "instagram_reels", "tiktok", "tiktok_photo"}


def cart_block(products: list[dict[str, Any]], platform: str = "", language: str = "vi") -> str:
    """Deterministic shopping lines appended to a caption."""
    lines = []
    with_link = [p for p in products if p.get("affiliate_url")]
    if not with_link:
        return ""
    vi = language == "vi"
    if platform in NO_LINK_PLATFORMS:
        lines.append("🛒 Link mua hàng ở bio / bình luận đầu tiên" if vi else "🛒 Shop link in bio / first comment")
        return "\n".join(lines)
    for p in with_link:
        price = f" ({p['price']})" if p.get("price") else ""
        lead = (p.get("cta") or "").strip() or ("🛒 Mua" if vi else "🛒 Shop")
        lines.append(f"{lead} {p['name']}{price}: {p['affiliate_url']}")
    return "\n".join(lines)


def link_list(products: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [{"id": p["id"], "name": p["name"], "url": p.get("affiliate_url") or "", "price": p.get("price") or ""}
            for p in products]


def prompt_context(products: list[dict[str, Any]]) -> str:
    """Text for the copywriter prompt: what is being promoted (links are added by code)."""
    if not products:
        return ""
    rows = []
    for p in products:
        bits = [p["name"]]
        if p.get("price"):
            bits.append(f"price {p['price']}")
        if p.get("description"):
            bits.append(p["description"][:400])
        rows.append("- " + " — ".join(bits))
    return ("This post promotes these products (affiliate). Mention the product naturally and end with a short "
            "call to action to buy; do NOT write any URL or link — the shop link is appended automatically:\n"
            + "\n".join(rows))
