"""Series wiki — a bible, free-form wiki pages and an episode list per series.

Layout (override the root with ``OPENMONTAGE_SERIES_DIR``)::

    series/<series-id>/series.json     metadata + episodes
    series/<series-id>/pages/<slug>.md wiki pages (markdown; first "# " line is the title)

``series.json``::

    {"id": "sasa", "title": "Sasa", "logline": "...", "status": "active",
     "characters": ["sasa"], "tags": [...],
     "episodes": [{"id": "e1a2b3", "number": 1, "title": "...", "summary": "...",
                   "status": "idea", "backlog_id": null, "project_id": null}],
     "created_at": ..., "updated_at": ...}

Episodes point at a Backlog item (``backlog_id``) and/or a production project
(``project_id``). Deleting a series moves its folder to ``series/_trash/``.
Backlot's ``/series`` page reads and edits these files. The folder is
gitignored like ``backlog/``.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any, Optional

from lib.backlog import STATUSES as EPISODE_STATUSES, slugify
from lib.paths import REPO_ROOT

SERIES_STATUSES = {
    "planning": "Đang lên ý tưởng",
    "active": "Đang sản xuất",
    "paused": "Tạm dừng",
    "ended": "Đã kết thúc",
}
OVERVIEW = "tong-quan"
MAX_PAGE_BYTES = 512_000
SERIES_FIELDS = ("title", "logline", "status", "characters", "tags")
EPISODE_FIELDS = ("number", "title", "summary", "status", "backlog_id", "project_id")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_EP_RE = re.compile(r"^[a-f0-9]{6,12}$")

DEFAULT_PAGES = {
    OVERVIEW: """# Tổng quan

**Logline:** {logline}

## Premise

Series nói về ai, họ muốn gì, điều gì cản họ.

## Công thức mỗi tập

- Độ dài:
- Giây 0–2 (hook):
- Thân tập:
- Kết tập:

## Các trang

- [[Thế giới]]
- [[Nhân vật]]
- [[Bối cảnh]]
""",
    "the-gioi": "# Thế giới\n\nLuật chơi của thế giới, thời đại, tông màu, những điều không bao giờ xảy ra.\n",
    "nhan-vat": "# Nhân vật\n\nMỗi nhân vật: mong muốn, nỗi sợ, cách đánh/cách nói, chi tiết nhận diện.\n",
    "boi-canh": "# Bối cảnh\n\nCác địa điểm dùng lại giữa các tập, kèm ảnh tham chiếu nếu có.\n",
}


def series_root() -> Path:
    return Path(os.environ.get("OPENMONTAGE_SERIES_DIR") or (REPO_ROOT / "series"))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _check_id(series_id: str) -> str:
    if not _ID_RE.match(series_id or ""):
        raise ValueError(f"invalid series id {series_id!r}")
    return series_id


def _check_slug(slug: str) -> str:
    if not _ID_RE.match(slug or ""):
        raise ValueError(f"invalid page slug {slug!r}")
    return slug


def _dir(series_id: str) -> Path:
    return series_root() / _check_id(series_id)


def _read(series_id: str) -> dict[str, Any]:
    path = _dir(series_id) / "series.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise KeyError(f"unknown series {series_id!r}")
    except json.JSONDecodeError as e:
        raise ValueError(f"{path} is not valid JSON: {e}")
    if not isinstance(data, dict):
        raise ValueError(f"{path} must hold an object")
    data.setdefault("episodes", [])
    data["id"] = series_id
    return data


def _write(series_id: str, data: dict[str, Any]) -> None:
    path = _dir(series_id) / "series.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = time.time()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _clean_list(value: Any) -> list[str]:
    items = value.split(",") if isinstance(value, str) else (value or [])
    out: list[str] = []
    for t in items:
        t = str(t).strip()
        if t and t not in out:
            out.append(t)
    return out


def _clean_series(fields: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in fields.items():
        if key not in SERIES_FIELDS:
            continue
        if key == "status":
            if value not in SERIES_STATUSES:
                raise ValueError(f"unknown series status {value!r}")
            out[key] = value
        elif key in ("characters", "tags"):
            out[key] = _clean_list(value)
        else:
            out[key] = str(value or "").strip()
    if "title" in out and not out["title"]:
        raise ValueError("title is required")
    return out


def _clean_ref(value: Any, name: str) -> Optional[str]:
    ref = str(value or "").strip()
    if not ref:
        return None
    if any(c in ref for c in "/\\:") or ref in (".", ".."):
        raise ValueError(f"invalid {name}")
    return ref


def _clean_episode(fields: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in fields.items():
        if key not in EPISODE_FIELDS:
            continue
        if key == "status":
            if value not in EPISODE_STATUSES:
                raise ValueError(f"unknown episode status {value!r}")
            out[key] = value
        elif key == "number":
            try:
                out[key] = max(1, min(9999, int(value)))
            except (TypeError, ValueError):
                raise ValueError("number must be a positive integer")
        elif key in ("backlog_id", "project_id"):
            out[key] = _clean_ref(value, key)
        else:
            out[key] = str(value or "").strip()
    if "title" in out and not out["title"]:
        raise ValueError("episode title is required")
    return out


def _page_title(text: str, slug: str) -> str:
    m = re.search(r"^#\s+(.+)$", text, re.M)
    return m.group(1).strip() if m else slug


def _pages(series_id: str) -> list[dict[str, Any]]:
    folder = _dir(series_id) / "pages"
    pages = []
    if folder.is_dir():
        for p in folder.glob("*.md"):
            if not _ID_RE.match(p.stem):
                continue
            text = p.read_text(encoding="utf-8", errors="replace")[:4000]
            pages.append({"slug": p.stem, "title": _page_title(text, p.stem), "updated_at": p.stat().st_mtime})
    pages.sort(key=lambda p: (p["slug"] != OVERVIEW, p["title"].lower()))
    return pages


def _decorate_episode(ep: dict[str, Any], backlog_index: dict[str, dict]) -> dict[str, Any]:
    b = backlog_index.get(ep.get("backlog_id") or "")
    project = ep.get("project_id")
    return {
        **ep,
        "status_label": EPISODE_STATUSES.get(ep.get("status"), ep.get("status")),
        "backlog": {"id": b["id"], "title": b["title"], "status": b.get("status")} if b else None,
        "project_exists": bool(project) and (REPO_ROOT / "projects" / project).is_dir(),
    }


def _backlog_index() -> dict[str, dict]:
    try:
        from lib import backlog
        return {i["id"]: i for i in backlog.list_items()}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# series
# ---------------------------------------------------------------------------

def list_series() -> list[dict[str, Any]]:
    root = series_root()
    out = []
    if not root.is_dir():
        return out
    for d in sorted(root.iterdir()):
        if not d.is_dir() or d.name.startswith(("_", ".")) or not (d / "series.json").is_file():
            continue
        try:
            data = _read(d.name)
        except (KeyError, ValueError):
            continue
        eps = data.get("episodes") or []
        out.append({
            "id": d.name,
            "title": data.get("title") or d.name,
            "logline": data.get("logline") or "",
            "status": data.get("status") or "planning",
            "status_label": SERIES_STATUSES.get(data.get("status"), data.get("status")),
            "characters": data.get("characters") or [],
            "episode_count": len(eps),
            "done_count": sum(1 for e in eps if e.get("status") == "done"),
            "updated_at": data.get("updated_at"),
        })
    out.sort(key=lambda s: -(s["updated_at"] or 0))
    return out


def get_series(series_id: str) -> dict[str, Any]:
    data = _read(series_id)
    index = _backlog_index()
    eps = sorted(data.get("episodes") or [], key=lambda e: (e.get("number") or 0, e.get("title") or ""))
    return {
        **data,
        "status_label": SERIES_STATUSES.get(data.get("status"), data.get("status")),
        "episodes": [_decorate_episode(e, index) for e in eps],
        "pages": _pages(series_id),
    }


def create_series(title: str, *, series_id: Optional[str] = None, **fields: Any) -> dict[str, Any]:
    clean = _clean_series({"title": title, "status": fields.pop("status", "planning"), **fields})
    root = series_root()
    base = series_id or slugify(clean["title"])
    _check_id(base)
    sid, n = base, 2
    while (root / sid).exists():
        sid, n = f"{base}-{n}", n + 1
    now = time.time()
    data = {"id": sid, "logline": "", "characters": [], "tags": [], **clean,
            "episodes": [], "created_at": now}
    _write(sid, data)
    pages = _dir(sid) / "pages"
    pages.mkdir(parents=True, exist_ok=True)
    for slug, text in DEFAULT_PAGES.items():
        (pages / f"{slug}.md").write_text(text.replace("{logline}", clean.get("logline") or "…"), encoding="utf-8")
    return get_series(sid)


def update_series(series_id: str, **fields: Any) -> dict[str, Any]:
    clean = _clean_series(fields)
    data = _read(series_id)
    data.update(clean)
    _write(series_id, data)
    return get_series(series_id)


def delete_series(series_id: str) -> str:
    """Move the series folder to series/_trash/ and return the new path."""
    src = _dir(series_id)
    if not (src / "series.json").is_file():
        raise KeyError(f"unknown series {series_id!r}")
    trash = series_root() / "_trash"
    trash.mkdir(parents=True, exist_ok=True)
    dest = trash / f"{series_id}-{int(time.time())}"
    src.replace(dest)
    return str(dest)


# ---------------------------------------------------------------------------
# pages
# ---------------------------------------------------------------------------

def read_page(series_id: str, slug: str) -> dict[str, Any]:
    _read(series_id)
    path = _dir(series_id) / "pages" / f"{_check_slug(slug)}.md"
    if not path.is_file():
        raise KeyError(f"unknown page {slug!r}")
    text = path.read_bytes()[:MAX_PAGE_BYTES].decode("utf-8", errors="replace")
    return {"slug": slug, "title": _page_title(text, slug), "text": text, "updated_at": path.stat().st_mtime}


def save_page(series_id: str, text: str, slug: Optional[str] = None) -> dict[str, Any]:
    """Create (no slug: derived from the "# " title) or overwrite a page."""
    _read(series_id)
    text = str(text or "")
    if len(text.encode("utf-8")) > MAX_PAGE_BYTES:
        raise ValueError("page is too large")
    folder = _dir(series_id) / "pages"
    folder.mkdir(parents=True, exist_ok=True)
    if slug:
        _check_slug(slug)
    else:
        title = _page_title(text, "")
        if not title:
            raise ValueError("a new page needs a '# Title' line")
        base = slugify(title)
        slug, n = base, 2
        while (folder / f"{slug}.md").exists():
            slug, n = f"{base}-{n}", n + 1
    path = folder / f"{slug}.md"
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    data = _read(series_id)
    _write(series_id, data)  # bump updated_at
    return read_page(series_id, slug)


def delete_page(series_id: str, slug: str) -> None:
    if slug == OVERVIEW:
        raise ValueError("the overview page cannot be deleted")
    path = _dir(series_id) / "pages" / f"{_check_slug(slug)}.md"
    if not path.is_file():
        raise KeyError(f"unknown page {slug!r}")
    trash = series_root() / "_trash" / series_id
    trash.mkdir(parents=True, exist_ok=True)
    path.replace(trash / f"{slug}-{int(time.time())}.md")


# ---------------------------------------------------------------------------
# episodes
# ---------------------------------------------------------------------------

def add_episode(series_id: str, title: str, **fields: Any) -> dict[str, Any]:
    data = _read(series_id)
    eps = data["episodes"]
    clean = _clean_episode({"title": title, "status": fields.pop("status", "idea"), **fields})
    clean.setdefault("number", max((e.get("number") or 0 for e in eps), default=0) + 1)
    ep = {"id": secrets.token_hex(3), "summary": "", "backlog_id": None, "project_id": None,
          **clean, "created_at": time.time()}
    eps.append(ep)
    _write(series_id, data)
    return _decorate_episode(ep, _backlog_index())


def update_episode(series_id: str, episode_id: str, **fields: Any) -> dict[str, Any]:
    if not _EP_RE.match(episode_id or ""):
        raise ValueError("invalid episode id")
    data = _read(series_id)
    clean = _clean_episode(fields)
    for ep in data["episodes"]:
        if ep.get("id") == episode_id:
            ep.update(clean)
            _write(series_id, data)
            return _decorate_episode(ep, _backlog_index())
    raise KeyError(f"unknown episode {episode_id!r}")


def delete_episode(series_id: str, episode_id: str) -> None:
    data = _read(series_id)
    kept = [e for e in data["episodes"] if e.get("id") != episode_id]
    if len(kept) == len(data["episodes"]):
        raise KeyError(f"unknown episode {episode_id!r}")
    data["episodes"] = kept
    _write(series_id, data)


def statuses() -> dict[str, list[dict[str, str]]]:
    return {
        "series": [{"id": k, "label": v} for k, v in SERIES_STATUSES.items()],
        "episode": [{"id": k, "label": v} for k, v in EPISODE_STATUSES.items()],
    }
