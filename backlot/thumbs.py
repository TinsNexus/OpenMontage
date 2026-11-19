"""Thumbnails for the Backlot gallery.

Two ways to make a thumbnail for a generated video, both saved under
``projects/<id>/artifacts/thumbs/<video key>/``:

- **Frame grab** (free, local): ffmpeg pulls the frame at a timestamp at the
  video's full resolution.
- **AI thumbnail** (paid, ~$0.03): Google Nano Banana via PiAPI
  (``tools.graphics.piapi_image``) restyles a grabbed frame into a
  click-worthy cover, optionally with the title rendered on the image.

Every file gets a ``<name>.json`` sidecar describing how it was made.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

THUMBS_DIR = "artifacts/thumbs"
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}

ASPECTS = {
    "16:9": "landscape 16:9 (YouTube, Facebook feed)",
    "9:16": "vertical 9:16 cover (Reels, TikTok, Shorts)",
    "1:1": "square 1:1",
    "4:5": "portrait 4:5 (Instagram feed)",
}
AI_MODEL = "nano-banana-2.1"


def video_key(rel_video: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "__", rel_video)


def thumbs_dir(project_dir: Path, rel_video: str) -> Path:
    return project_dir / THUMBS_DIR / video_key(rel_video)


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def list_thumbs(project_dir: Path, rel_video: str) -> list[dict[str, Any]]:
    folder = thumbs_dir(project_dir, rel_video)
    if not folder.is_dir():
        return []
    out = []
    for img in folder.iterdir():
        if img.suffix.lower() not in IMAGE_EXT or not img.is_file():
            continue
        meta = _read_json(img.with_suffix(".json"))
        out.append({
            "path": img.relative_to(project_dir).as_posix(),
            "name": img.name,
            "kind": meta.get("kind", "frame"),
            "time_s": meta.get("time_s"),
            "aspect_ratio": meta.get("aspect_ratio"),
            "title_text": meta.get("title_text"),
            "cost_usd": meta.get("cost_usd"),
            "created_at": meta.get("created_at", img.stat().st_mtime),
        })
    out.sort(key=lambda t: t["created_at"], reverse=True)
    return out


def capture_frame(project_dir: Path, rel_video: str, time_s: float) -> dict[str, Any]:
    video = project_dir / rel_video
    if not video.is_file():
        raise FileNotFoundError(rel_video)
    t = max(0.0, float(time_s))
    folder = thumbs_dir(project_dir, rel_video)
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"frame_{t:07.2f}s.png".replace(" ", "0")
    result = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", str(video),
         "-frames:v", "1", str(out)],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0 or not out.is_file():
        raise RuntimeError(f"ffmpeg could not grab a frame at {t:.2f}s: {result.stderr.strip()[:200]}")
    _write_json(out.with_suffix(".json"), {"kind": "frame", "video": rel_video, "time_s": round(t, 3),
                                           "created_at": time.time()})
    return next(x for x in list_thumbs(project_dir, rel_video) if x["name"] == out.name)


def build_thumb_prompt(*, aspect: str, title_text: str, style_notes: str, video_prompt: Optional[str]) -> str:
    text_rule = (
        f'Render this exact headline as large, bold, high-contrast text that is easy to read on a phone: "{title_text}". '
        "Spell it exactly as given, including every diacritic; do not add any other words."
        if title_text.strip() else
        "Do not put any text, letters, logos or watermarks on the image."
    )
    context = f"\nWhat the video shows (for context only):\n{video_prompt[:1500]}" if video_prompt else ""
    return (
        f"Turn the reference image (a frame from the video) into a scroll-stopping video thumbnail, {ASPECTS[aspect]}. "
        "Keep the same main character — same face, hair and outfit — and the same setting and color palette. "
        "Make it punchier than a raw frame: tighter heroic framing on the main character, strong subject separation, "
        "dramatic lighting, rich contrast, crisp detail, cinematic photorealism, no cartoon look. "
        f"{text_rule} "
        f"{('Extra direction: ' + style_notes.strip()) if style_notes.strip() else ''}"
        f"{context}"
    ).strip()


def generate_ai_thumb(
    project_dir: Path, rel_video: str, *, frame_path: str, aspect: str = "16:9",
    title_text: str = "", style_notes: str = "", video_prompt: Optional[str] = None,
    resolution: str = "1K",
) -> dict[str, Any]:
    if aspect not in ASPECTS:
        raise ValueError(f"aspect must be one of {sorted(ASPECTS)}")
    frame = (project_dir / frame_path).resolve()
    try:
        frame.relative_to(project_dir.resolve())
    except ValueError:
        raise ValueError("frame path escapes project")
    if not frame.is_file() or frame.suffix.lower() not in IMAGE_EXT:
        raise FileNotFoundError(frame_path)

    from tools.graphics.piapi_image import PiAPIImage

    folder = thumbs_dir(project_dir, rel_video)
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"ai_{time.strftime('%Y%m%d-%H%M%S')}_{aspect.replace(':', 'x')}.png"
    prompt = build_thumb_prompt(aspect=aspect, title_text=title_text[:120], style_notes=style_notes[:500],
                                video_prompt=video_prompt)
    tool = PiAPIImage()
    inputs = {"prompt": prompt, "model": AI_MODEL, "aspect_ratio": aspect, "resolution": resolution,
              "output_format": "png", "image_path": str(frame), "output_path": str(out)}
    result = tool.execute(inputs)
    if not result.success:
        raise RuntimeError(result.error or "thumbnail generation failed")
    _write_json(out.with_suffix(".json"), {
        "kind": "ai", "video": rel_video, "source_frame": frame_path, "aspect_ratio": aspect,
        "title_text": title_text, "style_notes": style_notes, "model": AI_MODEL, "resolution": resolution,
        "prompt": prompt, "task_ids": (result.data or {}).get("task_ids"), "cost_usd": result.cost_usd,
        "created_at": time.time(),
    })
    return next(x for x in list_thumbs(project_dir, rel_video) if x["name"] == out.name)


def estimate_ai_cost(resolution: str = "1K") -> float:
    from tools.graphics.piapi_image import PiAPIImage

    return PiAPIImage().estimate_cost({"prompt": "x", "model": AI_MODEL, "resolution": resolution})
