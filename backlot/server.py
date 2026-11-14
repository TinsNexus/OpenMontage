"""Backlot server — FastAPI app: board state API, SSE change feed, media.

The watcher observes ``projects/`` with watchfiles; on any change it bumps a
per-project version and wakes SSE subscribers, who tell the browser to
refetch state. The server never writes to project directories, with one
explicit exception: user-triggered ``POST /api/social/...`` and
``POST /api/thumbs/...`` save social copy and thumbnails under
``projects/<id>/artifacts/{social,thumbs}/`` (see ``backlot.social`` and
``backlot.thumbs``), and ``POST /api/images/...`` saves generated images
into ``projects/<id>/assets/images/`` (see ``backlot.images``). The
``/api/characters`` endpoints manage the shared character library outside
``projects/`` (see ``lib.characters``), and ``/api/backlog`` edits the
content backlog file (see ``lib.backlog``).
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Optional

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from backlot import images as imagegen, social, thumbs
from lib import backlog as backloglib, characters as charlib
from backlot.state import PROJECTS_DIR, REPO_ROOT, list_projects, load_board_state, summarize_project

UI_DIR = Path(__file__).resolve().parent / "ui"
THUMB_CACHE_DIR = REPO_ROOT / ".backlot" / "thumbs"
THUMB_WIDTHS = (320, 640, 960)

# Paths inside a project whose changes are pure noise for the board.
_IGNORE_PARTS = {"node_modules", ".git", "__pycache__", ".cache"}

SSE_HEARTBEAT_SECONDS = 15


def _ui_html(name: str, assets: tuple[str, ...]) -> HTMLResponse:
    html = (UI_DIR / name).read_text(encoding="utf-8")
    for asset in assets:
        path = UI_DIR / asset
        if path.is_file():
            version = str(int(path.stat().st_mtime))
            html = html.replace(f"/ui/{asset}", f"/ui/{asset}?v={version}")
    return HTMLResponse(html)


class ChangeHub:
    """Fan-out of project-change notifications to SSE subscribers.

    Subscriptions are filtered: a board subscribed to one project only ever
    receives that project's ids, so unrelated-project bursts can't flood its
    queue and starve out the one notification it actually needs.
    """

    def __init__(self) -> None:
        self._subscribers: dict[asyncio.Queue, Optional[str]] = {}

    def subscribe(self, project_id: Optional[str] = None) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=64)
        self._subscribers[q] = project_id
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.pop(q, None)

    def publish(self, project_id: str) -> None:
        for q, only in list(self._subscribers.items()):
            if only is not None and only != project_id:
                continue
            try:
                q.put_nowait(project_id)
            except asyncio.QueueFull:
                # Queue holds only THIS subscriber's relevant ids, so a full
                # queue already guarantees a pending wake-up → safe to drop.
                pass


hub = ChangeHub()

# Library summaries are expensive to derive (full state parse per project);
# cache per project and invalidate from the watcher.
_summary_cache: dict[str, dict] = {}


def _invalidate_summary(project_id: str) -> None:
    _summary_cache.pop(project_id, None)


def _cached_summaries() -> list[dict]:
    if not PROJECTS_DIR.is_dir():
        return []
    summaries = []
    for entry in sorted(PROJECTS_DIR.iterdir()):
        if not entry.is_dir() or entry.name.startswith(("_", ".")):
            continue
        cached = _summary_cache.get(entry.name)
        if cached is None:
            try:
                cached = summarize_project(entry)
            except Exception:
                cached = {
                    "project_id": entry.name, "title": entry.name,
                    "pipeline_type": "unknown", "has_pipeline_state": False,
                    "poster": None, "live": False, "last_activity": 0,
                    "active_stage": None, "awaiting_human": False,
                    "stage_states": [], "completed_count": 0,
                    "render_count": 0, "scene_count": 0, "error": "unreadable",
                }
            _summary_cache[entry.name] = cached
        summaries.append(cached)
    summaries.sort(key=lambda s: (not s["live"], -(s["last_activity"] or 0)))
    return summaries


# Watch-loop hot path: pure string comparison, no per-path filesystem calls
# (change batches can be thousands of paths during a render).
import os as _os

_PROJECTS_ROOT_STR = _os.path.normcase(str(PROJECTS_DIR.resolve()))


def _project_of_change(path_str: str) -> Optional[str]:
    """Map a changed filesystem path to a project id (None = irrelevant)."""
    norm = _os.path.normcase(_os.path.normpath(path_str))
    if not norm.startswith(_PROJECTS_ROOT_STR):
        return None
    rel = norm[len(_PROJECTS_ROOT_STR):].lstrip("\\/")
    if not rel:
        return None
    parts = rel.replace("\\", "/").split("/")
    if _IGNORE_PARTS.intersection(parts):
        return None
    return parts[0]


async def _watch_projects() -> None:
    """Background task: watch projects/ and publish debounced changes."""
    try:
        from watchfiles import awatch
    except ImportError:
        return  # watcher unavailable → board still works via manual refresh
    if not PROJECTS_DIR.is_dir():
        return
    async for changes in awatch(PROJECTS_DIR, recursive=True, step=400):
        touched: set[str] = set()
        for _change, path_str in changes:
            pid = _project_of_change(path_str)
            if pid:
                touched.add(pid)
        for pid in touched:
            _invalidate_summary(pid)
            hub.publish(pid)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Own and cleanly stop the project watcher with FastAPI's lifespan API."""

    task = asyncio.create_task(_watch_projects())
    app.state.watch_task = task
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def create_app() -> FastAPI:
    app = FastAPI(title="Backlot", docs_url=None, redoc_url=None, lifespan=_lifespan)

    # ---- API ----------------------------------------------------------

    @app.get("/api/health")
    async def health() -> dict:
        return {"ok": True, "app": "backlot"}

    @app.get("/api/projects")
    async def projects() -> list:
        return await asyncio.to_thread(_cached_summaries)

    @app.get("/api/project/{project_id}/state")
    async def project_state(project_id: str) -> dict:
        project_dir = _safe_project_dir(project_id)
        return await asyncio.to_thread(load_board_state, project_dir)

    @app.get("/api/project/{project_id}/events")
    async def project_events(project_id: str, request: Request) -> StreamingResponse:
        _safe_project_dir(project_id)  # 404 early for unknown projects

        async def stream():
            q = hub.subscribe(project_id)
            try:
                yield _sse({"type": "hello", "project_id": project_id})
                while True:
                    if await request.is_disconnected():
                        return
                    try:
                        await asyncio.wait_for(q.get(), timeout=SSE_HEARTBEAT_SECONDS)
                    except asyncio.TimeoutError:
                        yield _sse({"type": "heartbeat", "ts": time.time()})
                        continue
                    # Coalesce bursts: drain anything else queued.
                    while not q.empty():
                        try:
                            q.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                    yield _sse({"type": "change", "project_id": project_id})
            finally:
                hub.unsubscribe(q)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        })

    @app.get("/api/library/events")
    async def library_events(request: Request) -> StreamingResponse:
        async def stream():
            q = hub.subscribe()
            try:
                yield _sse({"type": "hello"})
                while True:
                    if await request.is_disconnected():
                        return
                    try:
                        changed = await asyncio.wait_for(q.get(), timeout=SSE_HEARTBEAT_SECONDS)
                    except asyncio.TimeoutError:
                        yield _sse({"type": "heartbeat", "ts": time.time()})
                        continue
                    while not q.empty():
                        try:
                            q.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                    yield _sse({"type": "change", "project_id": changed})
            finally:
                hub.unsubscribe(q)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        })

    # ---- Thumbnails (downscaled, cached on disk) ------------------------

    @app.get("/thumb/{project_id}/{file_path:path}")
    async def thumb(project_id: str, file_path: str, w: int = 640) -> FileResponse:
        project_dir = _safe_project_dir(project_id)
        target = (project_dir / file_path).resolve()
        try:
            target.relative_to(project_dir.resolve())
        except ValueError:
            raise HTTPException(status_code=403, detail="path escapes project")
        if not target.is_file():
            raise HTTPException(status_code=404, detail="media not found")
        width = min(THUMB_WIDTHS, key=lambda x: abs(x - w))
        cached = await asyncio.to_thread(_thumbnail_for, target, width)
        if cached is None:
            # Never fall back to raw video bytes for an <img> consumer (F-03);
            # non-thumbable images are safe to serve as-is.
            if target.suffix.lower() in {".mp4", ".webm", ".mov"}:
                raise HTTPException(status_code=404, detail="no poster frame available")
            return FileResponse(target)
        return FileResponse(cached, media_type="image/jpeg")

    # ---- Media (range requests handled by FileResponse) ---------------

    @app.get("/media/{project_id}/{file_path:path}")
    async def media(project_id: str, file_path: str) -> FileResponse:
        project_dir = _safe_project_dir(project_id)
        target = (project_dir / file_path).resolve()
        try:
            target.relative_to(project_dir.resolve())
        except ValueError:
            raise HTTPException(status_code=403, detail="path escapes project")
        if not target.is_file():
            raise HTTPException(status_code=404, detail="media not found")
        return FileResponse(target)

    # ---- Gallery + social copy -------------------------------------------

    @app.get("/api/videos")
    async def videos() -> list:
        return await asyncio.to_thread(social.list_videos, PROJECTS_DIR)

    @app.get("/api/social/options")
    async def social_options() -> dict:
        return {
            "platforms": [{"id": k, "label": v["label"]} for k, v in social.PLATFORMS.items()],
            "languages": [{"id": k, "label": v} for k, v in social.LANGUAGES.items()],
            "model": __import__("os").environ.get("BACKLOT_COPY_MODEL") or social.DEFAULT_MODEL,
            "thumb_aspects": [{"id": k, "label": v} for k, v in thumbs.ASPECTS.items()],
            "thumb_model": thumbs.AI_MODEL,
            "thumb_cost_usd": thumbs.estimate_ai_cost("1K"),
        }

    @app.post("/api/thumbs/{project_id}/frame")
    async def thumb_frame(project_id: str, request: Request, payload: dict = Body(...)) -> dict:
        _require_action(request, "thumb")
        project_dir = _safe_project_dir(project_id)
        rel = _safe_video(project_dir, payload.get("video"))
        try:
            return await asyncio.to_thread(thumbs.capture_frame, project_dir, rel, float(payload.get("time_s") or 0))
        except (TypeError, ValueError) as e:
            raise HTTPException(status_code=422, detail=str(e))
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/thumbs/{project_id}/ai")
    async def thumb_ai(project_id: str, request: Request, payload: dict = Body(...)) -> dict:
        _require_action(request, "thumb")
        project_dir = _safe_project_dir(project_id)
        rel = _safe_video(project_dir, payload.get("video"))
        prompt = social.resolve_prompt(project_dir, rel)["prompt"]
        try:
            return await asyncio.to_thread(
                thumbs.generate_ai_thumb, project_dir, rel,
                frame_path=str(payload.get("frame") or ""),
                aspect=str(payload.get("aspect") or "16:9"),
                title_text=str(payload.get("title_text") or ""),
                style_notes=str(payload.get("style_notes") or ""),
                video_prompt=prompt,
            )
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="frame not found — grab a frame first")
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except RuntimeError as e:
            raise HTTPException(status_code=502, detail=str(e))

    @app.post("/api/social/{project_id}")
    async def social_generate(project_id: str, request: Request, payload: dict = Body(...)) -> dict:
        _require_action(request, "social")
        project_dir = _safe_project_dir(project_id)
        rel = _safe_video(project_dir, payload.get("video"))
        try:
            return await asyncio.to_thread(
                social.generate_social, project_dir, rel,
                platform=str(payload.get("platform") or "facebook_reels"),
                language=str(payload.get("language") or "vi"),
                notes=str(payload.get("notes") or "")[:1000],
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except RuntimeError as e:
            raise HTTPException(status_code=502, detail=str(e))

    # ---- Images (free-form generation) ---------------------------------

    @app.get("/api/images")
    async def images_list() -> list:
        return await asyncio.to_thread(imagegen.list_images, PROJECTS_DIR)

    @app.get("/api/images/options")
    async def images_options() -> dict:
        def build() -> dict:
            opts = imagegen.options()
            opts["projects"] = [{"project_id": p.name, "title": (json.loads((p / "project.json").read_text())
                                                                  .get("title") if (p / "project.json").is_file() else p.name)}
                                for p in sorted((d for d in PROJECTS_DIR.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime, reverse=True)] if PROJECTS_DIR.is_dir() else []
            opts["characters"] = [{"id": c["id"], "name": c["name"], "primary_image": c["primary_image"]}
                                  for c in charlib.list_characters() if c["primary_image"]]
            return opts
        return await asyncio.to_thread(build)

    @app.post("/api/images/generate")
    async def images_generate(request: Request, payload: dict = Body(...)) -> dict:
        """Generate images into an existing project, or a new one when ``new_project`` is given."""
        _require_action(request, "image")
        import base64
        import re as _re
        import tempfile

        new_title = str(payload.get("new_project") or "").strip()
        if new_title:
            pid = _re.sub(r"[^a-z0-9]+", "-", charlib.slugify(new_title)).strip("-")[:60] or "images"
            if (PROJECTS_DIR / pid).exists():
                raise HTTPException(status_code=409, detail=f"project {pid} already exists — pick it from the list")
            from lib.checkpoint import init_project

            await asyncio.to_thread(init_project, pid, title=new_title, pipeline_type="images",
                                    pipeline_dir=PROJECTS_DIR)
        else:
            pid = str(payload.get("project_id") or "")
        project_dir = _safe_project_dir(pid)

        refs, labels = [], []
        for ref in payload.get("references") or []:
            ref_dir = _safe_project_dir(str(ref.get("project_id") or ""))
            src = (ref_dir / str(ref.get("path") or "")).resolve()
            try:
                src.relative_to(ref_dir.resolve())
            except ValueError:
                raise HTTPException(status_code=403, detail="reference path escapes project")
            if not src.is_file() or src.suffix.lower() not in imagegen.IMAGE_EXT:
                raise HTTPException(status_code=404, detail=f"reference not found: {ref.get('path')}")
            refs.append(str(src))
            labels.append(f"{ref_dir.name}/{ref.get('path')}")

        characters = [str(c) for c in (payload.get("characters") or [])]
        for cid in characters:
            try:
                charlib.get(cid)
            except (KeyError, ValueError):
                raise HTTPException(status_code=404, detail=f"unknown character: {cid}")

        with tempfile.TemporaryDirectory() as tmp:
            for i, up in enumerate(payload.get("uploads") or []):
                name = Path(str(up.get("file_name") or f"upload{i}.png")).name
                if Path(name).suffix.lower() not in imagegen.IMAGE_EXT:
                    raise HTTPException(status_code=422, detail="uploads must be png, jpg or webp")
                try:
                    data = base64.b64decode(str(up.get("data_base64") or "").split(",", 1)[-1], validate=True)
                except ValueError:
                    raise HTTPException(status_code=422, detail="upload is not valid base64")
                if len(data) > 10 * 1024 * 1024:
                    raise HTTPException(status_code=413, detail=f"{name} is larger than 10 MB")
                path = Path(tmp) / f"{i}_{name}"
                path.write_bytes(data)
                refs.append(str(path))
                labels.append(f"upload:{name}")
            try:
                return await asyncio.to_thread(
                    imagegen.generate, project_dir,
                    prompt=str(payload.get("prompt") or ""),
                    model=str(payload.get("model") or "nano-banana-2.1"),
                    aspect=str(payload.get("aspect") or "") or None,
                    resolution=str(payload.get("resolution") or "1K"),
                    n=int(payload.get("n") or 1),
                    characters=characters,
                    character_refs=str(payload.get("character_refs") or "set"),
                    reference_paths=refs, reference_labels=labels,
                    name_hint=str(payload.get("name") or ""),
                )
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e))
            except RuntimeError as e:
                raise HTTPException(status_code=502, detail=str(e))

    # ---- Backlog -------------------------------------------------------

    def _backlog_call(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e).strip("'\""))
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    @app.get("/api/backlog")
    async def backlog_list() -> dict:
        items = await asyncio.to_thread(_backlog_call, backloglib.list_items)
        return {"items": items, "statuses": backloglib.statuses()}

    @app.get("/api/backlog/{item_id}/script")
    async def backlog_script(item_id: str) -> dict:
        text = await asyncio.to_thread(_backlog_call, backloglib.read_script, item_id)
        return {"id": item_id, "text": text}

    @app.post("/api/backlog")
    async def backlog_create(request: Request, payload: dict = Body(...)) -> dict:
        _require_action(request, "backlog")
        fields = {k: v for k, v in payload.items() if k != "title"}
        return await asyncio.to_thread(_backlog_call, backloglib.create,
                                       str(payload.get("title") or ""), **fields)

    @app.post("/api/backlog/{item_id}")
    async def backlog_update(item_id: str, request: Request, payload: dict = Body(...)) -> dict:
        _require_action(request, "backlog")
        return await asyncio.to_thread(_backlog_call, backloglib.update, item_id, **payload)

    @app.post("/api/backlog/{item_id}/delete")
    async def backlog_delete(item_id: str, request: Request) -> dict:
        _require_action(request, "backlog")
        await asyncio.to_thread(_backlog_call, backloglib.delete, item_id)
        return {"deleted": item_id}

    # ---- Character library ---------------------------------------------

    def _char_or_404(char_id: str) -> dict:
        try:
            return charlib.get(char_id)
        except (KeyError, ValueError):
            raise HTTPException(status_code=404, detail=f"unknown character: {char_id}")

    @app.get("/api/characters")
    async def characters_list() -> list:
        return await asyncio.to_thread(charlib.list_characters)

    @app.get("/api/characters/roles")
    async def character_roles() -> list:
        return [{"id": k, "label": v} for k, v in charlib.ROLES.items()]

    @app.get("/api/characters/sources")
    async def character_sources() -> list:
        """Images already in projects that can be saved into a character."""
        def scan() -> list:
            out = []
            if not PROJECTS_DIR.is_dir():
                return out
            for project in sorted(p for p in PROJECTS_DIR.iterdir() if p.is_dir()):
                for sub in ("assets/images", "artifacts/thumbs"):
                    folder = project / sub
                    if folder.is_dir():
                        for img in sorted(folder.rglob("*")):
                            if img.suffix.lower() in charlib.IMAGE_EXT and img.is_file():
                                out.append({"project_id": project.name,
                                            "path": img.relative_to(project).as_posix(),
                                            "modified": img.stat().st_mtime})
            out.sort(key=lambda x: x["modified"], reverse=True)
            return out[:300]
        return await asyncio.to_thread(scan)

    @app.post("/api/characters")
    async def character_create(request: Request, payload: dict = Body(...)) -> dict:
        _require_action(request, "character")
        try:
            return await asyncio.to_thread(
                charlib.create, str(payload.get("name") or ""),
                description=str(payload.get("description") or ""),
                identity=str(payload.get("identity") or ""),
                tags=[str(t) for t in (payload.get("tags") or [])],
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    @app.post("/api/characters/{char_id}")
    async def character_update(char_id: str, request: Request, payload: dict = Body(...)) -> dict:
        _require_action(request, "character")
        _char_or_404(char_id)
        try:
            return await asyncio.to_thread(
                charlib.update, char_id, name=payload.get("name"), description=payload.get("description"),
                identity=payload.get("identity"), tags=payload.get("tags"),
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    @app.post("/api/characters/{char_id}/images")
    async def character_add_image(char_id: str, request: Request, payload: dict = Body(...)) -> dict:
        """Add a reference image from a project file or an uploaded (base64) file."""
        _require_action(request, "character")
        _char_or_404(char_id)
        note = str(payload.get("note") or "")
        primary = bool(payload.get("make_primary"))
        role = str(payload.get("role") or "other")
        if role not in charlib.ROLES:
            raise HTTPException(status_code=422, detail=f"role must be one of {list(charlib.ROLES)}")
        if payload.get("project_id"):
            project_dir = _safe_project_dir(str(payload["project_id"]))
            src = (project_dir / str(payload.get("path") or "")).resolve()
            try:
                src.relative_to(project_dir.resolve())
            except ValueError:
                raise HTTPException(status_code=403, detail="path escapes project")
            label = f"{payload['project_id']}/{payload.get('path')}"
            try:
                return await asyncio.to_thread(charlib.add_image, char_id, src, note=note,
                                               source_label=label, make_primary=primary, role=role)
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e))
        if payload.get("data_base64"):
            import base64
            import tempfile

            name = Path(str(payload.get("file_name") or "upload.png")).name
            suffix = Path(name).suffix.lower()
            if suffix not in charlib.IMAGE_EXT:
                raise HTTPException(status_code=422, detail="upload must be png, jpg or webp")
            raw = str(payload["data_base64"]).split(",", 1)[-1]
            try:
                data = base64.b64decode(raw, validate=True)
            except ValueError:
                raise HTTPException(status_code=422, detail="data_base64 is not valid base64")
            if len(data) > 20 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="image larger than 20 MB")
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / name
                path.write_bytes(data)
                try:
                    return await asyncio.to_thread(charlib.add_image, char_id, path, note=note,
                                                   source_label=f"upload:{name}", make_primary=primary,
                                                   role=role)
                except ValueError as e:
                    raise HTTPException(status_code=422, detail=str(e))
        raise HTTPException(status_code=422, detail="give project_id + path, or file_name + data_base64")

    @app.post("/api/characters/{char_id}/role")
    async def character_role(char_id: str, request: Request, payload: dict = Body(...)) -> dict:
        _require_action(request, "character")
        _char_or_404(char_id)
        try:
            return await asyncio.to_thread(charlib.set_role, char_id, str(payload.get("file") or ""),
                                           str(payload.get("role") or ""))
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    @app.post("/api/characters/{char_id}/split")
    async def character_split(char_id: str, request: Request, payload: dict = Body(...)) -> dict:
        """Cut a sheet image of this character into one reference image per panel (role "other")."""
        _require_action(request, "character")
        _char_or_404(char_id)
        file = str(payload.get("file") or "")
        try:
            n = int(payload["panels"]) if payload.get("panels") not in (None, "") else None
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="panels must be a number")
        if n is not None and not 1 <= n <= 12:
            raise HTTPException(status_code=422, detail="panels must be 1-12")

        def run() -> dict:
            import tempfile

            sheet = charlib.image_path(char_id, file)
            with tempfile.TemporaryDirectory() as tmp:
                panels = charlib.split_sheet(sheet, tmp, panels=n)
                char = None
                for i, p in enumerate(panels, start=1):
                    char = charlib.add_image(char_id, p["path"], note=f"cut from {file} panel {i}",
                                             source_label=f"sheet:{file}#{i}", role="other")
                return {**char, "split_panels": len(panels)}

        try:
            return await asyncio.to_thread(run)
        except KeyError:
            raise HTTPException(status_code=404, detail="image not found")
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    @app.post("/api/characters/{char_id}/primary")
    async def character_primary(char_id: str, request: Request, payload: dict = Body(...)) -> dict:
        _require_action(request, "character")
        _char_or_404(char_id)
        try:
            return await asyncio.to_thread(charlib.set_primary, char_id, str(payload.get("file") or ""))
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    @app.post("/api/characters/{char_id}/generate")
    async def character_generate(char_id: str, request: Request, payload: dict = Body(...)) -> dict:
        """New reference image via Nano Banana (~$0.03). Uses the primary image as identity anchor if any."""
        _require_action(request, "character")
        char = _char_or_404(char_id)
        prompt = str(payload.get("prompt") or "").strip()
        if not prompt:
            raise HTTPException(status_code=422, detail="prompt is required")
        role = str(payload.get("role") or "other")
        if role not in charlib.ROLES:
            raise HTTPException(status_code=422, detail=f"role must be one of {list(charlib.ROLES)}")

        def run() -> dict:
            import tempfile

            from tools.graphics.piapi_image import PiAPIImage

            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "gen.png"
                resolution = str(payload.get("resolution") or "1K")
                if resolution not in ("1K", "2K", "4K"):
                    raise ValueError("resolution must be 1K, 2K or 4K")
                inputs = {"prompt": prompt, "aspect_ratio": str(payload.get("aspect") or "3:4"),
                          "resolution": resolution, "output_format": "png", "output_path": str(out)}
                if char.get("primary_path"):
                    # New single angles are anchored on the primary image only, so they
                    # don't inherit drift from other generated references; a sheet
                    # gets the whole set so every view agrees.
                    inputs["characters"] = [char_id]
                    inputs["character_refs"] = "set" if role == "sheet" else "primary"
                else:
                    inputs["prompt"] = f"{char['name']}: {char.get('identity') or char.get('description') or ''}\n\n{prompt}"
                result = PiAPIImage().execute(inputs)
                if not result.success:
                    raise RuntimeError(result.error or "image generation failed")
                return charlib.add_image(char_id, out, note=prompt[:300], source_label="ai:nano-banana-2.1",
                                         make_primary=bool(payload.get("make_primary")), role=role)

        try:
            return await asyncio.to_thread(run)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except RuntimeError as e:
            raise HTTPException(status_code=502, detail=str(e))

    @app.get("/character-media/{char_id}/{file}")
    async def character_media(char_id: str, file: str) -> FileResponse:
        try:
            path = await asyncio.to_thread(charlib.image_path, char_id, file)
        except (KeyError, ValueError):
            raise HTTPException(status_code=404, detail="image not found")
        return FileResponse(path)

    # ---- UI ------------------------------------------------------------

    @app.get("/p/{project_id}")
    async def board_page(project_id: str) -> HTMLResponse:
        return _ui_html("board.html", ("board.css", "board.js"))

    @app.get("/p/{project_path:path}")
    async def board_page_path(project_path: str) -> HTMLResponse:
        return _ui_html("board.html", ("board.css", "board.js"))

    @app.get("/images")
    async def images_page() -> HTMLResponse:
        return _ui_html("images.html", ("board.css", "gallery.css", "images.js"))

    @app.get("/characters")
    async def characters_page() -> HTMLResponse:
        return _ui_html("characters.html", ("board.css", "gallery.css", "characters.js"))

    @app.get("/backlog")
    async def backlog_page() -> HTMLResponse:
        return _ui_html("backlog.html", ("board.css", "gallery.css", "backlog.css", "backlog.js"))

    @app.get("/gallery")
    async def gallery_page() -> HTMLResponse:
        return _ui_html("gallery.html", ("board.css", "gallery.css", "gallery.js"))

    @app.get("/")
    async def library_page() -> HTMLResponse:
        return _ui_html("index.html", ("board.css", "gallery.css", "library.js"))

    if UI_DIR.is_dir():
        app.mount("/ui", StaticFiles(directory=UI_DIR), name="ui")

    # The board is a long-lived SPA: a tab keeps running whatever board.js it
    # loaded, and browsers heuristically cache /ui assets. no-cache forces a
    # conditional revalidation (cheap 304 via ETag) on every load so UI fixes
    # show up on a plain refresh. Media/thumb responses keep normal caching.
    @app.middleware("http")
    async def ui_no_cache(request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path in ("/", "/gallery", "/images", "/characters", "/backlog") or path.startswith("/ui") or path.startswith("/p/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    return app


def _safe_project_dir(project_id: str) -> Path:
    # ':' rejects Windows drive-relative ids like "C:" (PROJECTS_DIR / "C:"
    # collapses back to PROJECTS_DIR itself).
    if any(c in project_id for c in "/\\:") or project_id in (".", ".."):
        raise HTTPException(status_code=400, detail="invalid project id")
    project_dir = PROJECTS_DIR / project_id
    if not project_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"unknown project: {project_id}")
    return project_dir


def _require_action(request: Request, action: str) -> None:
    """Writes (and paid calls) need a custom header: a cross-origin page cannot
    send one without a CORS preflight, which Backlot never answers."""
    if request.headers.get("x-backlot-action") != action:
        raise HTTPException(status_code=403, detail="missing X-Backlot-Action header")


def _safe_video(project_dir: Path, rel: object) -> str:
    target = (project_dir / str(rel or "")).resolve()
    try:
        rel_path = target.relative_to(project_dir.resolve()).as_posix()
    except ValueError:
        raise HTTPException(status_code=403, detail="path escapes project")
    if target.suffix.lower() not in social.VIDEO_EXT or not target.is_file():
        raise HTTPException(status_code=404, detail="video not found")
    return rel_path


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _thumbnail_for(source: Path, width: int) -> Optional[Path]:
    """Downscale an image (or extract a video poster frame) to a cached JPEG."""
    suffix = source.suffix.lower()
    is_image = suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    is_video = suffix in {".mp4", ".webm", ".mov"}
    if not (is_image or is_video):
        return None
    try:
        import hashlib
        stat = source.stat()
        key = hashlib.sha1(
            f"{source}|{stat.st_mtime_ns}|{stat.st_size}|{width}".encode()
        ).hexdigest()[:20]
        cached = THUMB_CACHE_DIR / f"{key}.jpg"
        if cached.is_file():
            return cached
        THUMB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        # Unique temp per request — concurrent misses for the same source
        # must not write (and replace from) the same temp file.
        import uuid
        tmp = THUMB_CACHE_DIR / f"{key}.{uuid.uuid4().hex[:8]}.tmp.jpg"
        if is_video:
            import subprocess
            result = subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-ss", "1.5",
                 "-i", str(source), "-frames:v", "1",
                 "-vf", f"scale={width}:-2", str(tmp)],
                capture_output=True, timeout=30,
            )
            if result.returncode != 0 or not tmp.is_file():
                return None
        else:
            from PIL import Image
            with Image.open(source) as img:
                img = img.convert("RGB")
                img.thumbnail((width, width * 3))
                img.save(tmp, "JPEG", quality=82)
        tmp.replace(cached)
        return cached
    except Exception:
        return None


app = create_app()
