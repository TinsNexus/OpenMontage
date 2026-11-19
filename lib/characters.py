"""Shared character library — reusable cast across projects.

A character is a folder under ``characters/`` (override with
``OPENMONTAGE_CHARACTERS_DIR``)::

    characters/sasa/
        character.json      # name, description, identity prompt, images, tags
        ref_01.png          # reference images (first / "primary" one anchors identity)
        ref_02.png

Generation tools (``seedance_piapi``, ``piapi_image``) accept
``characters: ["sasa"]`` and pull the primary reference image plus an
``[identity_lock]`` text block from here, so a character designed once is
reused instead of regenerated — and looks the same in every project.

The folder is gitignored like ``projects/``; commit it or sync it yourself if
the cast should be shared with other people/machines.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Optional

from lib.paths import REPO_ROOT

CHARACTERS_DIR = Path(os.environ.get("OPENMONTAGE_CHARACTERS_DIR") or (REPO_ROOT / "characters"))
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
MANIFEST = "character.json"

# Image roles, in the order a reference set is assembled after the primary image.
ROLES = {
    "full_body": "full-body front view",
    "face": "front face close-up",
    "face_34": "three-quarter face close-up",
    "face_profile": "profile face close-up",
    "back": "back view",
    "side": "side profile",
    "action": "action pose",
    "front_34": "three-quarter front view",
    "sheet": "character turnaround sheet",
    "other": "extra reference",
}
# "sheet" images are never sent to video models by default: a frame with
# several copies of the character invites duplicated characters in the output.
# Added after the primary, at most one each, in this order.
SET_ROLES = ("face", "back", "face_34", "side", "face_profile")
DEFAULT_SET_SIZE = 3      # "set": primary + front face + back
FULL_SET_SIZE = 6         # "full": + three-quarter face, side, profile face
MODES = {"primary": 1, "set": DEFAULT_SET_SIZE, "full": FULL_SET_SIZE}
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def characters_dir() -> Path:
    return CHARACTERS_DIR


def slugify(name: str) -> str:
    text = unicodedata.normalize("NFKD", name.replace("đ", "d").replace("Đ", "D"))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:64] or "character"


def _dir(slug: str) -> Path:
    if not _SLUG_RE.match(slug or ""):
        raise ValueError(f"invalid character id {slug!r}")
    return characters_dir() / slug


def _load(slug: str) -> dict[str, Any]:
    path = _dir(slug) / MANIFEST
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise KeyError(f"unknown character {slug!r}")
    except json.JSONDecodeError as e:
        raise ValueError(f"{path} is not valid JSON: {e}")
    data["id"] = slug
    data.setdefault("images", [])
    return data


def _save(data: dict[str, Any]) -> dict[str, Any]:
    folder = _dir(data["id"])
    folder.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = time.time()
    tmp = folder / (MANIFEST + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(folder / MANIFEST)
    return data


def _with_paths(data: dict[str, Any]) -> dict[str, Any]:
    folder = _dir(data["id"])
    images = [img for img in data.get("images", []) if (folder / img["file"]).is_file()]
    primary = data.get("primary_image") or (images[0]["file"] if images else None)
    return {**data, "images": images, "primary_image": primary,
            "primary_path": str(folder / primary) if primary else None}


def list_characters() -> list[dict[str, Any]]:
    root = characters_dir()
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


def create(name: str, *, description: str = "", identity: str = "", tags: Iterable[str] = (),
           slug: Optional[str] = None) -> dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ValueError("name is required")
    base = slug or slugify(name)
    candidate, n = base, 2
    while (characters_dir() / candidate).exists():
        candidate, n = f"{base}-{n}", n + 1
    now = time.time()
    return get(_save({
        "id": candidate, "name": name, "description": description.strip(), "identity": identity.strip(),
        "tags": [t.strip() for t in tags if t and t.strip()], "images": [], "primary_image": None,
        "created_at": now,
    })["id"])


def update(slug: str, **fields: Any) -> dict[str, Any]:
    data = _load(slug)
    for key in ("name", "description", "identity"):
        if key in fields and fields[key] is not None:
            data[key] = str(fields[key]).strip()
    if fields.get("tags") is not None:
        data["tags"] = [str(t).strip() for t in fields["tags"] if str(t).strip()]
    if not data.get("name"):
        raise ValueError("name is required")
    return get(_save(data)["id"])


def _check_role(role: str) -> str:
    if role not in ROLES:
        raise ValueError(f"role must be one of {list(ROLES)}")
    return role


def add_image(slug: str, source: Path | str, *, note: str = "", source_label: str = "",
              make_primary: bool = False, role: str = "other") -> dict[str, Any]:
    _check_role(role)
    src = Path(source)
    if not src.is_file() or src.suffix.lower() not in IMAGE_EXT:
        raise ValueError(f"not an image file: {src.name}")
    data = _load(slug)
    folder = _dir(slug)
    used = {img["file"] for img in data["images"]}
    i = len(data["images"]) + 1
    while f"ref_{i:02d}{src.suffix.lower()}" in used or (folder / f"ref_{i:02d}{src.suffix.lower()}").exists():
        i += 1
    dest = folder / f"ref_{i:02d}{src.suffix.lower()}"
    shutil.copy2(src, dest)
    data["images"].append({"file": dest.name, "role": role, "note": note.strip(),
                           "source": source_label or src.name, "added_at": time.time()})
    if make_primary or not data.get("primary_image"):
        data["primary_image"] = dest.name
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
# Character sheets
# ---------------------------------------------------------------------------

# Video models reject references outside roughly 0.4–2.5 width/height (Seedance:
# "Invalid input"). Panels cut from a turnaround sheet are often ~0.3, so pad them.
REF_MIN_ASPECT = 9 / 16
REF_MAX_ASPECT = 2.5


def pad_to_aspect(src: Path | str, dest: Optional[Path | str] = None, *, min_aspect: float = REF_MIN_ASPECT,
                  max_aspect: float = REF_MAX_ASPECT) -> bool:
    """Pad an image with its own backdrop colour so width/height falls inside [min, max].

    Writes to ``dest`` (default: in place). Returns True when padding was added.
    """
    import numpy as np
    from PIL import Image

    path = Path(src)
    img = Image.open(path).convert("RGB")
    w, h = img.size
    ratio = w / h
    if min_aspect <= ratio <= max_aspect:
        if dest and Path(dest) != path:
            img.save(dest)
        return False
    arr = np.asarray(img)
    edge = np.concatenate([arr[0], arr[-1], arr[:, 0], arr[:, -1]])
    color = tuple(int(c) for c in np.median(edge, axis=0))
    if ratio < min_aspect:
        new_w, new_h = int(round(h * min_aspect)), h
    else:
        new_w, new_h = w, int(round(w / max_aspect))
    canvas = Image.new("RGB", (new_w, new_h), color)
    canvas.paste(img, ((new_w - w) // 2, (new_h - h) // 2))
    canvas.save(dest or path)
    return True


def split_sheet(sheet: Path | str, out_dir: Path | str, *, pad: float = 0.03,
                min_panel_frac: float = 0.06, panels: Optional[int] = None,
                min_aspect: Optional[float] = REF_MIN_ASPECT) -> list[dict[str, Any]]:
    """Cut a turnaround sheet (figures on a plain light backdrop) into one image per panel.

    Columns are classed as "figure" when enough pixels are dark or saturated
    (backdrop is light and grey); runs of figure columns become panels, each
    cropped with a little backdrop padding and trimmed vertically. Returns
    ``[{"path", "box": (l, t, r, b), "width", "height"}, ...]`` left to right.
    """
    import numpy as np
    from PIL import Image

    src = Path(sheet)
    img = Image.open(src).convert("RGB")
    hsv = np.asarray(img.convert("HSV"), dtype=np.int16)
    sat, val = hsv[..., 1], hsv[..., 2]
    figure = (val < 150) | (sat > 45)
    w, h = img.size

    col = figure.mean(axis=0) > 0.02
    # Close tiny holes (thin gaps inside one figure, e.g. between legs).
    gap_close = max(2, int(w * 0.01))
    runs: list[list[int]] = []
    for x in np.flatnonzero(col):
        if runs and x - runs[-1][1] <= gap_close:
            runs[-1][1] = int(x)
        else:
            runs.append([int(x), int(x)])
    runs = [r for r in runs if (r[1] - r[0] + 1) >= w * min_panel_frac]

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    results = []

    if panels and len(runs) != panels:
        # Panels touch (e.g. shoulders filling every close-up): fall back to equal columns.
        for i in range(panels):
            l, r = round(i * w / panels), round((i + 1) * w / panels)
            crop = img.crop((l, 0, r, h))
            path = out / f"{src.stem}_panel{i + 1}.png"
            crop.save(path)
            if min_aspect:
                pad_to_aspect(path, min_aspect=min_aspect)
                crop = Image.open(path)
            results.append({"path": str(path), "box": (l, 0, r, h), "width": crop.width, "height": crop.height,
                            "method": "equal"})
        return results
    if not runs:
        raise ValueError("no panels found — is the backdrop plain and light?")
    px = int(w * pad)
    for i, (x0, x1) in enumerate(runs):
        left = runs[i - 1][1] if i else 0
        right = runs[i + 1][0] if i + 1 < len(runs) else w - 1
        l = max(left + (x0 - left) // 2, x0 - px)
        r = min(x1 + (right - x1) // 2, x1 + px) + 1
        rows = np.flatnonzero(figure[:, x0:x1 + 1].mean(axis=1) > 0.01)
        t = max(0, int(rows[0]) - px) if rows.size else 0
        b = min(h, int(rows[-1]) + px + 1) if rows.size else h
        crop = img.crop((l, t, r, b))
        path = out / f"{src.stem}_panel{i + 1}.png"
        crop.save(path)
        if min_aspect:
            pad_to_aspect(path, min_aspect=min_aspect)
            crop = Image.open(path)
        results.append({"path": str(path), "box": (l, t, r, b), "width": crop.width, "height": crop.height,
                        "method": "gaps"})
    return results


# ---------------------------------------------------------------------------
# Generation helpers
# ---------------------------------------------------------------------------

def resolve(slugs: Iterable[str]) -> list[dict[str, Any]]:
    """Characters in the given order, each guaranteed to have a primary image."""
    out = []
    for slug in slugs:
        c = get(slug)
        if not c["primary_path"]:
            raise ValueError(f"character {slug!r} has no reference image yet")
        out.append(c)
    return out


def reference_set(char: dict[str, Any], size: int = DEFAULT_SET_SIZE) -> list[dict[str, str]]:
    """Primary image first, then at most one face / back / side image, capped at ``size``.

    A small, consistent set beats many mixed images: more references with
    drifting looks make the model average the face.
    """
    folder = _dir(char["id"])
    images = {img["file"]: img for img in char["images"]}
    primary = char["primary_image"]
    out = [{"file": primary, "path": str(folder / primary),
            "role": images.get(primary, {}).get("role") or "full_body"}]
    for role in SET_ROLES:
        if len(out) >= max(1, size):
            break
        match = next((img for img in char["images"] if img.get("role") == role and img["file"] != primary), None)
        if match:
            out.append({"file": match["file"], "path": str(folder / match["file"]), "role": role})
    return out[: max(1, size)]


def references(slugs: Iterable[str], mode: str = "set", size: Optional[int] = None) -> list[dict[str, Any]]:
    """Per character: ``{"char": ..., "refs": [{"path", "role", "file"}, ...]}``.

    ``mode``: ``"primary"`` (1 image), ``"set"`` (primary + front face + back, the
    default) or ``"full"`` (up to 6: + three-quarter face, side, profile face).
    ``size`` overrides the mode's image count.
    """
    if mode not in MODES:
        raise ValueError(f"character reference mode must be one of {list(MODES)}")
    n = size if size is not None else MODES[mode]
    return [{"char": c, "refs": reference_set(c, n)} for c in resolve(slugs)]


def reference_paths(slugs: Iterable[str], mode: str = "set", size: Optional[int] = None) -> list[str]:
    return [r["path"] for item in references(slugs, mode, size) for r in item["refs"]]


def identity_block(slugs: Iterable[str], start_index: int = 1, mode: str = "set",
                   size: Optional[int] = None) -> str:
    """``[identity_lock]`` text naming which @imageN references belong to each character."""
    lines, i = [], start_index
    for item in references(slugs, mode, size):
        c, refs = item["char"], item["refs"]
        tags = [f"@image{i + k}" for k in range(len(refs))]
        i += len(refs)
        look = (c.get("identity") or c.get("description") or "").rstrip(".")
        if len(refs) == 1:
            who = f"{c['name']} is {tags[0]}"
        else:
            parts = "; ".join(f"{t} {ROLES.get(r['role'], r['role'])}" for t, r in zip(tags, refs))
            who = f"{c['name']} is shown in {tags[0]}–{tags[-1]}, all the same person ({parts})"
        lines.append(
            f"[identity_lock] {who}: {look}. Maintain exact appearance from "
            f"{tags[0] if len(tags) == 1 else 'all of ' + tags[0] + '–' + tags[-1]} in every shot — "
            "no face morph, no drift, no deformation; do not alter clothing category or primary color. "
            "Only one of this character."
        )
    return "\n".join(lines)
