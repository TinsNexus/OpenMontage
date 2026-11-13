"""Shared PiAPI helpers: auth, ephemeral uploads, task create + poll.

PiAPI fronts many vendors (Seedance, Gemini / Nano Banana, Flux, ...) behind
one task API:

    POST https://api.piapi.ai/api/v1/task       header X-API-Key
    GET  https://api.piapi.ai/api/v1/task/{id}

Used by ``tools.video.seedance_piapi`` and ``tools.graphics.piapi_image``.
"""

from __future__ import annotations

import base64
import os
import time
from pathlib import Path
from typing import Any, Callable

API_BASE = "https://api.piapi.ai/api/v1"
UPLOAD_URL = "https://upload.theapi.app/api/ephemeral_resource"
UPLOAD_MAX_BYTES = 10 * 1024 * 1024
UPLOAD_ATTEMPTS = 3
UPLOAD_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".wav", ".mp3"}
# The upload host times out on multi-MB base64 bodies, so larger still images
# are re-encoded in memory before sending (the file on disk is untouched).
UPLOAD_COMPRESS_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
UPLOAD_COMPRESS_OVER_BYTES = 500 * 1024
UPLOAD_COMPRESS_MAX_SIDE = 1600
UPLOAD_COMPRESS_JPEG_QUALITY = 88

# Status strings seen across PiAPI model families (case-insensitive).
_DONE = {"completed", "success"}
_FAILED = {"failed"}


def get_api_key() -> str | None:
    return os.environ.get("PIAPI_API_KEY") or os.environ.get("PIAPI_KEY")


def json_or_error(resp: Any, what: str) -> dict[str, Any]:
    """Parse a PiAPI response, raising with PiAPI's own message on failure."""
    try:
        body = resp.json()
    except Exception:
        body = None
    if resp.status_code >= 400 or not isinstance(body, dict):
        msg = (body or {}).get("message") if isinstance(body, dict) else (resp.text or "")[:300]
        raise RuntimeError(f"PiAPI {what} HTTP {resp.status_code}: {msg}")
    code = body.get("code")
    if code is not None and code != 200:
        raise RuntimeError(f"PiAPI {what} error {code}: {body.get('message')}")
    return body


def compress_image(raw: bytes, name: str) -> tuple[bytes, str]:
    """Shrink a large still image for upload: long side <= UPLOAD_COMPRESS_MAX_SIDE, JPEG.

    Returns ``(raw, name)`` unchanged for small files, non-images, unreadable
    data, or when re-encoding would not make the file smaller.
    """
    suffix = Path(name).suffix.lower()
    if suffix not in UPLOAD_COMPRESS_EXTENSIONS or len(raw) <= UPLOAD_COMPRESS_OVER_BYTES:
        return raw, name
    import io

    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(raw)) as img:
            img.load()
            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                rgba = img.convert("RGBA")
                flat = Image.new("RGB", rgba.size, (255, 255, 255))
                flat.paste(rgba, mask=rgba.getchannel("A"))
            else:
                flat = img.convert("RGB")
    except (OSError, UnidentifiedImageError):
        return raw, name
    flat.thumbnail((UPLOAD_COMPRESS_MAX_SIDE, UPLOAD_COMPRESS_MAX_SIDE), Image.LANCZOS)
    buf = io.BytesIO()
    flat.save(buf, format="JPEG", quality=UPLOAD_COMPRESS_JPEG_QUALITY, optimize=True)
    out = buf.getvalue()
    if len(out) >= len(raw):
        return raw, name
    return out, str(Path(name).with_suffix(".jpg"))


def upload(local_path: str, api_key: str) -> str:
    """Push a local file to PiAPI ephemeral storage (24h) and return its URL.

    Requires a PiAPI Creator plan or higher. Max 10 MB.
    """
    import requests

    path = Path(local_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Reference file not found: {local_path}")
    suffix = path.suffix.lower()
    if suffix not in UPLOAD_EXTENSIONS:
        raise ValueError(f"PiAPI upload supports {sorted(UPLOAD_EXTENSIONS)}; got {suffix or 'no extension'}")
    raw, file_name = compress_image(path.read_bytes(), path.name)
    if len(raw) > UPLOAD_MAX_BYTES:
        raise ValueError(
            f"{path.name} is {len(raw) / 1e6:.1f} MB; PiAPI ephemeral upload max is 10 MB. "
            "Compress it or pass a public URL instead."
        )
    payload = {"file_name": file_name[-128:], "file_data": base64.b64encode(raw).decode("ascii")}
    # The upload host occasionally drops the connection mid-request (BrokenPipe /
    # ConnectionReset). Uploads are free and idempotent, so retry a few times.
    for attempt in range(UPLOAD_ATTEMPTS):
        try:
            resp = requests.post(
                UPLOAD_URL,
                headers={"x-api-key": api_key, "Content-Type": "application/json"},
                json=payload,
                timeout=120,
            )
            break
        except (requests.ConnectionError, requests.Timeout):
            if attempt == UPLOAD_ATTEMPTS - 1:
                raise
            time.sleep(2 * (attempt + 1))
    body = json_or_error(resp, "upload")
    url = (body.get("data") or {}).get("url")
    if not url:
        raise RuntimeError(f"PiAPI upload returned no URL: {body.get('message') or body}")
    return url


def run_task(
    payload: dict[str, Any],
    api_key: str,
    *,
    label: str,
    timeout_s: int = 3600,
    poll_every_s: float = 10,
    on_task_id: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Create a task and poll until it completes. Returns the final ``data`` object.

    Raises RuntimeError on failure or timeout; the message always names the task_id
    once one exists so a long-running job can be checked by hand.
    """
    import requests

    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
    start = time.time()
    create = requests.post(f"{API_BASE}/task", headers=headers, json=payload, timeout=60)
    task = json_or_error(create, f"{label} create task").get("data") or {}
    task_id = task.get("task_id")
    if not task_id:
        raise RuntimeError(f"PiAPI {label} returned no task_id")
    if on_task_id:
        on_task_id(task_id)

    while True:
        status = str(task.get("status", "")).lower()
        if status in _DONE:
            task.setdefault("task_id", task_id)
            return task
        if status in _FAILED:
            err = task.get("error") or {}
            msg = err.get("message") or err.get("raw_message") or "unknown error"
            raise RuntimeError(f"PiAPI {label} task {task_id} failed: {msg} (content rejections are refunded)")
        if time.time() - start > timeout_s:
            raise RuntimeError(
                f"PiAPI {label} task {task_id} still '{status}' after {timeout_s}s; "
                f"it may still finish — check GET {API_BASE}/task/{task_id}"
            )
        time.sleep(poll_every_s)
        poll = requests.get(f"{API_BASE}/task/{task_id}", headers=headers, timeout=30)
        task = json_or_error(poll, f"{label} poll task").get("data") or {}
