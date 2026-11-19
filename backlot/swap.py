"""Character swap jobs for Backlot's /swap page ("Thay nhân vật").

Each job is a project ``projects/swap-<slug>/`` (pipeline_type ``face-swap``)
whose state lives in ``swap.json``. The flow:

1. video    — downloaded from a link (yt-dlp) or uploaded; probed for fps/size.
2. range    — start/end seconds; priced at frames x $0.01.
3. character— uploaded, picked from the character library, or generated
              (Nano Banana, ~$0.03). Uploaded and generated images wait in
              ``pending`` until the user approves them; library images are
              already approved.
4. preview  — swap one frame ($0.01) to check the look.
5. run      — "test" (first 1 s of the range) or "full", in a background
              thread with progress written back to swap.json.

Paid steps go through the ``face_swap_frames_piapi`` and ``piapi_image``
tools. Frame caches live in ``.backlot/swap_work/<project>/`` (outside
``projects/`` so the watcher does not fire per frame); a rerun reuses them
and pays only for frames that are missing.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Optional

from backlot.state import PROJECTS_DIR, REPO_ROOT
from lib import characters as charlib

STATE_FILE = "swap.json"
PIPELINE_TYPE = "face-swap"
PREFIX = "swap-"
WORK_ROOT = REPO_ROOT / ".backlot" / "swap_work"
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
UPLOAD_MAX_BYTES = 500 * 1024 * 1024
IMAGE_MAX_BYTES = 20 * 1024 * 1024
MAX_RANGE_FRAMES = 600
PRICE_PER_FRAME = 0.01
CHARACTER_IMAGE_COST = 0.03
FACE_PROMPT = (
    "Head-and-shoulders portrait, face looking straight at the camera, whole face clearly visible and "
    "unobstructed, eyes open, neutral relaxed expression, soft even light, plain light grey backdrop, "
    "photorealistic, sharp focus."
)
MODES = {
    "face_frames": {"label": "Thay mặt — ghép từng frame", "price_per_frame": PRICE_PER_FRAME, "available": True},
    "face_video": {"label": "Thay mặt — video PiAPI", "available": False,
                   "reason": "PiAPI video face-swap đang lỗi (19/11/2026)"},
    "full_body": {"label": "Thay toàn thân", "available": False,
                  "reason": "Cần key DashScope/fal (Wan Animate), chưa cấu hình"},
}

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()
_active: dict[str, threading.Event] = {}   # project id -> cancel event of a running job


def _lock(pid: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(pid, threading.Lock())


def _dir(pid: str) -> Path:
    if not re.fullmatch(r"swap-[a-z0-9-]{1,80}", pid or ""):
        raise KeyError(pid)
    d = PROJECTS_DIR / pid
    if not (d / STATE_FILE).is_file():
        raise KeyError(pid)
    return d


def _read(pid: str) -> dict[str, Any]:
    return json.loads((_dir(pid) / STATE_FILE).read_text(encoding="utf-8"))


def _write(pid: str, data: dict[str, Any]) -> dict[str, Any]:
    d = PROJECTS_DIR / pid
    data["updated_at"] = time.time()
    tmp = d / (STATE_FILE + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(d / STATE_FILE)
    return data


def _update(pid: str, fn) -> dict[str, Any]:
    with _lock(pid):
        data = _read(pid)
        fn(data)
        return _write(pid, data)


def _view(data: dict[str, Any]) -> dict[str, Any]:
    """State for the UI: marks a 'running' job that no thread owns any more as interrupted."""
    out = json.loads(json.dumps(data))
    for key in ("run", "download"):
        block = out.get(key) or {}
        if block.get("status") in ("running", "downloading") and out["id"] not in _active \
                and not (key == "download" and out["id"] in _downloads):
            block["status"] = "interrupted"
    out["modes"] = MODES
    return out


_downloads: set[str] = set()


def list_jobs() -> list[dict[str, Any]]:
    if not PROJECTS_DIR.is_dir():
        return []
    out = []
    for d in PROJECTS_DIR.iterdir():
        if d.name.startswith(PREFIX) and (d / STATE_FILE).is_file():
            try:
                data = _view(_read(d.name))
            except (KeyError, ValueError, OSError):
                continue
            out.append({k: data.get(k) for k in ("id", "title", "created_at", "updated_at", "video",
                                                  "character", "run", "download")})
    out.sort(key=lambda j: j.get("updated_at") or 0, reverse=True)
    return out


def get(pid: str) -> dict[str, Any]:
    return _view(_read(pid))


def create(title: str) -> dict[str, Any]:
    from lib.checkpoint import init_project

    title = (title or "").strip() or "Thay nhân vật"
    slug = re.sub(r"[^a-z0-9]+", "-", charlib.slugify(title)).strip("-")[:40] or "job"
    pid = f"{PREFIX}{slug}-{time.strftime('%m%d-%H%M%S')}"
    n = 2
    while (PROJECTS_DIR / pid).exists():
        pid = f"{PREFIX}{slug}-{time.strftime('%m%d-%H%M%S')}-{n}"
        n += 1
    init_project(pid, title=title, pipeline_type=PIPELINE_TYPE, pipeline_dir=PROJECTS_DIR)
    data = {
        "id": pid, "title": title, "created_at": time.time(), "mode": "face_frames",
        "source": None, "video": None, "download": None,
        "range": None,
        "character": {"status": "none", "image": None, "origin": None, "history": []},
        "preview": None, "run": None, "outputs": [], "spent_usd": 0.0,
    }
    return _view(_write(pid, data))


def delete(pid: str) -> None:
    if pid in _active:
        raise ValueError("job is running — cancel it first")
    d = _dir(pid)
    trash = PROJECTS_DIR / "_trash"
    trash.mkdir(exist_ok=True)
    shutil.move(str(d), str(trash / f"{pid}-{int(time.time())}"))
    shutil.rmtree(WORK_ROOT / pid, ignore_errors=True)


# ---------------------------------------------------------------- video

def upload_path(pid: str, file_name: str) -> Path:
    suffix = Path(file_name or "").suffix.lower()
    if suffix not in VIDEO_EXT:
        raise ValueError(f"video must be one of {sorted(VIDEO_EXT)}")
    return _dir(pid) / "assets" / "video" / f"source{suffix}"


def finish_upload(pid: str, path: Path, original_name: str) -> dict[str, Any]:
    _clear_video(pid, keep=path)
    info = _probe(path)
    return _update(pid, lambda d: d.update(
        source={"kind": "upload", "name": original_name}, download=None,
        video=_video_block(pid, path, info), range=None, preview=None, run=None))


def _clear_video(pid: str, keep: Optional[Path] = None) -> None:
    for old in (_dir(pid) / "assets" / "video").glob("source.*"):
        if keep is None or old.resolve() != keep.resolve():
            old.unlink(missing_ok=True)
    shutil.rmtree(WORK_ROOT / pid, ignore_errors=True)


def _probe(path: Path) -> dict[str, Any]:
    from tools.video.face_swap_piapi import probe_video

    info = probe_video(str(path))
    if not info.get("duration") or not info.get("width"):
        raise ValueError("could not read the video (no duration or size)")
    return info


def _video_block(pid: str, path: Path, info: dict[str, Any]) -> dict[str, Any]:
    return {"path": path.relative_to(_dir(pid)).as_posix(), "duration": round(info["duration"], 3),
            "fps": round(info["fps"], 3), "width": info["width"], "height": info["height"],
            "has_audio": info["has_audio"]}


def start_download(pid: str, url: str) -> dict[str, Any]:
    url = (url or "").strip()
    if not re.match(r"^https?://", url):
        raise ValueError("link must start with http:// or https://")
    if pid in _downloads:
        raise ValueError("a download is already running")
    _dir(pid)
    data = _update(pid, lambda d: d.update(source={"kind": "link", "url": url},
                                           download={"status": "downloading", "started_at": time.time()}))
    _downloads.add(pid)
    threading.Thread(target=_download, args=(pid, url), daemon=True, name=f"swap-dl-{pid}").start()
    return _view(data)


def _download(pid: str, url: str) -> None:
    import tempfile

    try:
        from tools.analysis.video_downloader import VideoDownloader

        with tempfile.TemporaryDirectory() as tmp:
            res = VideoDownloader().execute({"url": url, "output_dir": tmp, "format": "video",
                                             "max_resolution": "1080p", "max_duration_seconds": 900})
            if not res.success:
                raise RuntimeError(res.error or "download failed")
            files = [p for p in Path(tmp).rglob("*") if p.suffix.lower() in VIDEO_EXT and p.is_file()]
            if not files:
                raise RuntimeError("download produced no video file")
            src = max(files, key=lambda p: p.stat().st_size)
            dest = _dir(pid) / "assets" / "video" / f"source{src.suffix.lower()}"
            _clear_video(pid)
            shutil.move(str(src), dest)
        info = _probe(dest)
        _update(pid, lambda d: d.update(
            video=_video_block(pid, dest, info), range=None, preview=None, run=None,
            download={"status": "done", "finished_at": time.time()}))
    except Exception as e:
        try:
            _update(pid, lambda d: d.update(download={"status": "failed", "error": str(e)[:500]}))
        except Exception:
            pass
    finally:
        _downloads.discard(pid)


def set_range(pid: str, start: float, end: float) -> dict[str, Any]:
    from tools.video.face_swap_frames_piapi import plan_frames

    data = _read(pid)
    if not data.get("video"):
        raise ValueError("add a video first")
    v = data["video"]
    plan = plan_frames({"duration": v["duration"], "fps": v["fps"], "width": v["width"], "height": v["height"]},
                       start=start, end=end, max_frames=MAX_RANGE_FRAMES)
    return _view(_update(pid, lambda d: d.update(range=plan)))


# ---------------------------------------------------------------- character

def _char_dest(pid: str, suffix: str) -> Path:
    folder = _dir(pid) / "assets" / "images"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"character_{int(time.time() * 1000)}{suffix}"


def _set_character(pid: str, path: Path, *, origin: str, status: str, **extra: Any) -> dict[str, Any]:
    rel = path.relative_to(_dir(pid)).as_posix()

    def apply(d: dict[str, Any]) -> None:
        old = d.get("character") or {}
        history = list(old.get("history") or [])
        if old.get("image"):
            history.append({k: old.get(k) for k in ("image", "origin", "status", "prompt", "char_id")})
        d["character"] = {"status": status, "image": rel, "origin": origin, "history": history[-20:],
                          "updated_at": time.time(), **extra}
        d["preview"] = None
    return _view(_update(pid, apply))


def character_from_upload(pid: str, file_name: str, data: bytes) -> dict[str, Any]:
    suffix = Path(file_name or "").suffix.lower()
    if suffix not in IMAGE_EXT:
        raise ValueError("image must be png, jpg or webp")
    if not data:
        raise ValueError("empty image")
    if len(data) > IMAGE_MAX_BYTES:
        raise ValueError("image larger than 20 MB")
    dest = _char_dest(pid, suffix)
    dest.write_bytes(data)
    _check_image(dest)
    return _set_character(pid, dest, origin="upload", status="pending", name=Path(file_name).stem)


def _check_image(path: Path) -> None:
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(path) as im:
            im.verify()
    except (OSError, UnidentifiedImageError):
        path.unlink(missing_ok=True)
        raise ValueError("file is not a readable image")


def character_from_library(pid: str, char_id: str, file: Optional[str] = None) -> dict[str, Any]:
    char = charlib.get(char_id)
    if not file:
        face = next((i["file"] for i in char["images"] if i.get("role") == "face"), None)
        file = face or char.get("primary_image")
    if not file:
        raise ValueError(f"{char['name']} has no image yet")
    src = charlib.image_path(char_id, file)
    dest = _char_dest(pid, src.suffix.lower())
    shutil.copy2(src, dest)
    return _set_character(pid, dest, origin="library", status="approved", char_id=char_id,
                          name=char["name"], library_file=file, approved_at=time.time())


def character_generate(pid: str, prompt: str, *, name: str = "", char_id: str = "") -> dict[str, Any]:
    """Generate a new face image (Nano Banana 2.1, 1K, ~$0.03) that waits for approval."""
    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError("describe the character first")
    from tools.graphics.piapi_image import PiAPIImage

    dest = _char_dest(pid, ".png")
    inputs = {"prompt": f"{prompt}\n\n{FACE_PROMPT}", "aspect_ratio": "3:4", "resolution": "1K",
              "output_format": "png", "output_path": str(dest)}
    if char_id:  # keep identity from a library character
        charlib.get(char_id)
        inputs["characters"] = [char_id]
        inputs["character_refs"] = "primary"
    res = PiAPIImage().execute(inputs)
    if not res.success:
        dest.unlink(missing_ok=True)
        raise RuntimeError(res.error or "image generation failed")
    cost = float(res.cost_usd or CHARACTER_IMAGE_COST)
    _update(pid, lambda d: d.update(spent_usd=round(float(d.get("spent_usd") or 0) + cost, 3)))
    return _set_character(pid, dest, origin="generate", status="pending", prompt=prompt,
                          name=name.strip(), char_id=char_id or None, cost_usd=cost)


def approve_character(pid: str, *, save_to_library: bool = False, name: str = "") -> dict[str, Any]:
    data = _read(pid)
    ch = data.get("character") or {}
    if not ch.get("image"):
        raise ValueError("no character image to approve")
    extra: dict[str, Any] = {}
    if save_to_library and not ch.get("char_id"):
        name = (name or ch.get("name") or "").strip()
        if not name:
            raise ValueError("give the character a name to save it to the library")
        created = charlib.create(name, description=ch.get("prompt") or "", tags=["swap"])
        charlib.add_image(created["id"], _dir(pid) / ch["image"], note=ch.get("prompt") or "",
                          source_label=f"{pid}/{ch['image']}", make_primary=True, role="face")
        extra = {"char_id": created["id"], "name": name}
    return _view(_update(pid, lambda d: d["character"].update(status="approved", approved_at=time.time(), **extra)))


def reject_character(pid: str) -> dict[str, Any]:
    return _view(_update(pid, lambda d: d["character"].update(status="rejected", rejected_at=time.time())))


# ---------------------------------------------------------------- swap

def _ready(data: dict[str, Any]) -> None:
    if not data.get("video"):
        raise ValueError("add a video first")
    if (data.get("character") or {}).get("status") != "approved":
        raise ValueError("approve the character image first")
    if data.get("mode", "face_frames") != "face_frames":
        raise ValueError("only 'Thay mặt — ghép từng frame' is available")


def preview(pid: str, at: float) -> dict[str, Any]:
    """Swap one frame at ``at`` seconds ($0.01). Runs inline (~10-60 s)."""
    from tools.video.face_swap_frames_piapi import FaceSwapFramesPiAPI

    data = _read(pid)
    _ready(data)
    d = _dir(pid)
    stamp = int(time.time())
    out = d / "artifacts" / "swap_preview" / f"preview_{stamp}.jpg"
    res = FaceSwapFramesPiAPI().execute({
        "mode": "preview", "preview_time": float(at or 0),
        "target_video_path": str(d / data["video"]["path"]),
        "face_image_path": str(d / data["character"]["image"]),
        "output_path": str(out), "work_dir": str(WORK_ROOT / pid / f"preview_{stamp}"),
    })
    shutil.rmtree(WORK_ROOT / pid / f"preview_{stamp}", ignore_errors=True)
    if not res.success:
        raise RuntimeError(res.error or "preview failed")
    cost = float(res.cost_usd or 0)

    def apply(x: dict[str, Any]) -> None:
        x["preview"] = {"time": res.data["time"], "after": out.relative_to(d).as_posix(),
                        "before": Path(res.data["before_path"]).relative_to(d).as_posix(),
                        "character": x["character"]["image"], "created_at": time.time()}
        x["spent_usd"] = round(float(x.get("spent_usd") or 0) + cost, 3)
    return _view(_update(pid, apply))


def run(pid: str, kind: str = "test") -> dict[str, Any]:
    """Start a background swap. ``test`` = first 1 s of the range, ``full`` = the whole range."""
    if kind not in ("test", "full"):
        raise ValueError("kind must be 'test' or 'full'")
    if pid in _active:
        raise ValueError("a swap is already running for this job")
    data = _read(pid)
    _ready(data)
    rng = data.get("range")
    if not rng:
        raise ValueError("set the start/end range first")
    start, end = rng["start"], rng["end"]
    if kind == "test":
        end = min(end, start + 1.0)
    frames = rng["frames"] if end >= rng["end"] else max(1, int(math.ceil((end - start) * rng["fps"] - 1e-6)))
    cancel = threading.Event()
    _active[pid] = cancel
    try:
        out = _update(pid, lambda d: d.update(run={
            "status": "running", "kind": kind, "start": start, "end": end, "total": frames, "done": 0,
            "failed": 0, "cost_usd": 0.0, "estimate_usd": round(frames * PRICE_PER_FRAME, 2),
            "started_at": time.time(), "character": d["character"]["image"]}))
    except Exception:
        _active.pop(pid, None)
        raise
    threading.Thread(target=_run, args=(pid, kind, start, end, cancel), daemon=True,
                     name=f"swap-run-{pid}").start()
    return _view(out)


def cancel(pid: str) -> dict[str, Any]:
    ev = _active.get(pid)
    if not ev:
        raise ValueError("nothing is running")
    ev.set()
    return get(pid)


def _run(pid: str, kind: str, start: float, end: float, cancel_ev: threading.Event) -> None:
    from tools.video.face_swap_frames_piapi import FaceSwapFramesPiAPI

    last_write = [0.0]

    def on_progress(p: dict[str, Any]) -> None:
        now = time.time()
        if now - last_write[0] < 1.0 and p["done"] + p["failed"] < p["total"]:
            return
        last_write[0] = now
        _update(pid, lambda d: d["run"].update(done=p["done"], failed=p["failed"], total=p["total"],
                                               cost_usd=p["cost_usd"]))

    try:
        data = _read(pid)
        d = _dir(pid)
        stamp = time.strftime("%m%d-%H%M%S")
        out = d / "renders" / f"swap_{kind}_{stamp}.mp4"
        res = FaceSwapFramesPiAPI().execute({
            "mode": "video", "start": start, "end": end, "max_frames": MAX_RANGE_FRAMES,
            "target_video_path": str(d / data["video"]["path"]),
            "face_image_path": str(d / data["character"]["image"]),
            "output_path": str(out), "work_dir": str(WORK_ROOT / pid / kind),
            "progress_callback": on_progress, "cancel_event": cancel_ev,
        })
        cost = float(res.cost_usd or 0)

        def finish(x: dict[str, Any]) -> None:
            x["spent_usd"] = round(float(x.get("spent_usd") or 0) + cost, 3)
            r = x["run"]
            r.update(finished_at=time.time(), cost_usd=cost)
            if res.success:
                r.update(status="done", output=out.relative_to(d).as_posix(), done=res.data["swapped"],
                         failed=len(res.data["failed_frames"]), errors=res.data.get("errors") or [],
                         cached=res.data.get("cached_frames", 0))
                x.setdefault("outputs", []).insert(0, {
                    "path": r["output"], "kind": kind, "start": start, "end": end,
                    "character": r.get("character"), "failed": r["failed"], "cost_usd": cost,
                    "created_at": time.time()})
            else:
                r.update(status="cancelled" if cancel_ev.is_set() else "failed", error=(res.error or "")[:600])
        _update(pid, finish)
    except Exception as e:
        try:
            _update(pid, lambda x: x["run"].update(status="failed", error=str(e)[:600], finished_at=time.time()))
        except Exception:
            pass
    finally:
        _active.pop(pid, None)
