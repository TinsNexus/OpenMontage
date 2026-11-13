"""Free-form image generation for Backlot's Images page.

Generates with ``tools.graphics.piapi_image`` (Google Nano Banana via PiAPI)
and saves each result into ``projects/<id>/assets/images/`` next to a
``<stem>.meta.json`` sidecar (prompt, model, size, references, cost), so the
images show up on the project board and can be reused anywhere.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Optional

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
IMAGES_SUBDIR = "assets/images"
MAX_N = 4


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def options() -> dict[str, Any]:
    from tools.graphics import piapi_image as pi

    return {
        "models": [
            {"id": m, "pricing": prices, "aspects": sorted(pi._ASPECTS[m]),
             "resolutions": [] if "*" in prices else sorted(prices)}
            for m, prices in pi._PRICING.items()
        ],
        "default_model": "nano-banana-2.1",
        "max_n": MAX_N,
        "max_refs": pi._MAX_INPUT_IMAGES,
    }


def list_images(projects_dir: Path, limit: int = 400) -> list[dict[str, Any]]:
    """Images in every project's assets/images, newest first, with their sidecar metadata."""
    out: list[dict[str, Any]] = []
    if not projects_dir.is_dir():
        return out
    for project in sorted(p for p in projects_dir.iterdir() if p.is_dir()):
        folder = project / IMAGES_SUBDIR
        if not folder.is_dir():
            continue
        for img in folder.rglob("*"):
            if img.suffix.lower() not in IMAGE_EXT or not img.is_file():
                continue
            meta = _read_json(img.with_name(f"{img.stem}.meta.json"))
            out.append({
                "project_id": project.name,
                "path": img.relative_to(project).as_posix(),
                "name": img.name,
                "modified": img.stat().st_mtime,
                "prompt": meta.get("prompt"),
                "model": meta.get("model"),
                "aspect_ratio": meta.get("aspect_ratio"),
                "resolution": meta.get("resolution"),
                "characters": meta.get("characters") or [],
                "references": meta.get("references") or [],
                "cost_usd": meta.get("cost_usd"),
                "generated": bool(meta),
            })
    out.sort(key=lambda x: x["modified"], reverse=True)
    return out[:limit]


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:48] or "image"


def generate(
    project_dir: Path, *, prompt: str, model: str = "nano-banana-2.1", aspect: Optional[str] = None,
    resolution: str = "1K", n: int = 1, characters: Optional[list[str]] = None, character_refs: str = "set",
    reference_paths: Optional[list[str]] = None, reference_labels: Optional[list[str]] = None,
    name_hint: str = "",
) -> dict[str, Any]:
    """Generate ``n`` images into ``project_dir/assets/images``; returns saved entries + cost."""
    from tools.graphics.piapi_image import PiAPIImage

    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError("prompt is required")
    n = int(n)
    if not 1 <= n <= MAX_N:
        raise ValueError(f"n must be 1-{MAX_N}")

    folder = project_dir / IMAGES_SUBDIR
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = folder / f"img_{stamp}_{slug(name_hint or prompt)[:32]}.png"

    inputs: dict[str, Any] = {"prompt": prompt, "model": model, "resolution": resolution, "n": n,
                              "output_format": "png", "output_path": str(base)}
    if aspect:
        inputs["aspect_ratio"] = aspect
    if characters:
        inputs["characters"] = list(characters)
        inputs["character_refs"] = character_refs
    if reference_paths:
        inputs["image_paths"] = list(reference_paths)

    tool = PiAPIImage()
    result = tool.execute(inputs)
    written = result.artifacts or []
    per_image = round((result.cost_usd or 0) / max(len(written), 1), 4) if written else 0
    saved = []
    for path_str in written:
        path = Path(path_str)
        meta = {
            "prompt": prompt, "model": model, "aspect_ratio": aspect, "resolution": resolution,
            "characters": list(characters or []), "character_refs": character_refs if characters else None,
            "references": list(reference_labels or []), "task_ids": (result.data or {}).get("task_ids"),
            "cost_usd": per_image, "created_at": time.time(), "source": "backlot:images",
        }
        path.with_name(f"{path.stem}.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                                           encoding="utf-8")
        saved.append(path.relative_to(project_dir).as_posix())
    if not result.success:
        raise RuntimeError(result.error or "image generation failed"
                           + (f" ({len(saved)} of {n} images were saved)" if saved else ""))
    return {"project_id": project_dir.name, "images": saved, "cost_usd": result.cost_usd}
