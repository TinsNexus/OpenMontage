"""Small helpers shared by the PiAPI single-image video tools (Wan, Hailuo).

PiAPI's model families do not agree on where the finished video URL lives in
``data.output`` (``video``, ``video_url``, a nested list, ...), so
``find_video_url`` searches the output for the first MP4-looking URL.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_URL_KEYS = ("video", "video_url", "url")


def find_video_url(output: Any) -> str | None:
    """Return the video URL from a PiAPI task ``output`` object, or None."""
    if isinstance(output, str):
        return output if output.startswith("http") and ".mp4" in output.lower() else None
    if isinstance(output, dict):
        for key in _URL_KEYS:
            val = output.get(key)
            if isinstance(val, str) and val.startswith("http"):
                return val
        for val in output.values():
            found = find_video_url(val)
            if found:
                return found
    if isinstance(output, list):
        for val in output:
            found = find_video_url(val)
            if found:
                return found
    return None


def check_image_aspect(local_path: str, lo: float, hi: float, model: str) -> None:
    """Raise ValueError when a local image is outside a model's accepted width/height range."""
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(local_path) as img:
            w, h = img.size
    except (OSError, UnidentifiedImageError):
        return  # unreadable here; let the API judge it
    if not lo <= w / h <= hi:
        raise ValueError(
            f"{Path(local_path).name} is {w}x{h} (aspect {w / h:.2f}); {model} needs {lo}-{hi}. "
            "Pad or crop the image first."
        )


def write_sidecar(video_path: Path, meta: dict[str, Any]) -> None:
    """Write ``<stem>.meta.json`` next to the video (prompt provenance for Backlot's gallery).

    Best effort: a sidecar failure must never fail a paid, successful generation.
    """
    try:
        sidecar = video_path.with_name(f"{video_path.stem}.meta.json")
        sidecar.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
