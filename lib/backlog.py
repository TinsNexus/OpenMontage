"""Content backlog — video ideas and finished scripts waiting for production.

All items live in one JSON file, ``backlog/backlog.json`` (override with
``OPENMONTAGE_BACKLOG_FILE``)::

    {"items": [{"id": "cho-pho-cho-que", "title": "...", "status": "scripted",
                "script_path": "projects/cho-pho-cho-que/script.md", ...}]}

An item can point at a script file inside the repo (``script_path``,
repo-relative) and at a project folder (``project_id``) once production
starts. Backlot's ``/backlog`` page reads and edits this file.

The folder is gitignored like ``characters/``; commit it or sync it yourself
if the backlog should be shared.
"""

from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Any, Optional

from lib.paths import REPO_ROOT

BACKLOG_FILE = Path(os.environ.get("OPENMONTAGE_BACKLOG_FILE") or (REPO_ROOT / "backlog" / "backlog.json"))

STATUSES = {
    "idea": "Ý tưởng",
    "scripted": "Đã có kịch bản",
    "in_production": "Đang sản xuất",
    "done": "Hoàn thành",
    "dropped": "Bỏ",
}
SCRIPT_EXT = {".md", ".txt", ".json"}
MAX_SCRIPT_BYTES = 512_000
EDITABLE = ("title", "summary", "status", "tags", "pipeline", "project_id", "script_path", "notes", "priority")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def backlog_file() -> Path:
    return BACKLOG_FILE


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.replace("đ", "d").replace("Đ", "D"))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:64] or "item"


def _read() -> list[dict[str, Any]]:
    path = backlog_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except json.JSONDecodeError as e:
        raise ValueError(f"{path} is not valid JSON: {e}")
    items = data.get("items") if isinstance(data, dict) else data
    return [i for i in (items or []) if isinstance(i, dict) and i.get("id")]


def _write(items: list[dict[str, Any]]) -> None:
    path = backlog_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _clean_script_path(value: Any) -> Optional[str]:
    """Repo-relative path to a text script inside the repo, or None."""
    raw = str(value or "").strip()
    if not raw:
        return None
    target = (REPO_ROOT / raw).resolve()
    try:
        rel = target.relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        raise ValueError("script_path must be inside the repository")
    if target.suffix.lower() not in SCRIPT_EXT:
        raise ValueError(f"script_path must be one of {sorted(SCRIPT_EXT)}")
    return rel


def _clean(fields: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in fields.items():
        if key not in EDITABLE:
            continue
        if key == "status":
            if value not in STATUSES:
                raise ValueError(f"unknown status {value!r}")
            out[key] = value
        elif key == "tags":
            items = value.split(",") if isinstance(value, str) else (value or [])
            out[key] = [str(t).strip() for t in items if str(t).strip()]
        elif key == "script_path":
            out[key] = _clean_script_path(value)
        elif key == "project_id":
            pid = str(value or "").strip()
            if pid and (any(c in pid for c in "/\\:") or pid in (".", "..")):
                raise ValueError("invalid project_id")
            out[key] = pid or None
        elif key == "priority":
            try:
                out[key] = max(0, min(3, int(value)))
            except (TypeError, ValueError):
                raise ValueError("priority must be 0-3")
        else:
            out[key] = str(value or "").strip()
    if "title" in out and not out["title"]:
        raise ValueError("title is required")
    return out


def _decorate(item: dict[str, Any]) -> dict[str, Any]:
    script = item.get("script_path")
    project = item.get("project_id")
    return {
        **item,
        "status_label": STATUSES.get(item.get("status"), item.get("status")),
        "script_exists": bool(script) and (REPO_ROOT / script).is_file(),
        "project_exists": bool(project) and (REPO_ROOT / "projects" / project).is_dir(),
    }


def list_items() -> list[dict[str, Any]]:
    items = [_decorate(i) for i in _read()]
    order = list(STATUSES)
    items.sort(key=lambda i: (order.index(i["status"]) if i.get("status") in order else len(order),
                              -(i.get("priority") or 0), -(i.get("updated_at") or 0)))
    return items


def get(item_id: str) -> dict[str, Any]:
    for item in _read():
        if item["id"] == item_id:
            return _decorate(item)
    raise KeyError(f"unknown backlog item {item_id!r}")


def create(title: str, *, item_id: Optional[str] = None, **fields: Any) -> dict[str, Any]:
    clean = _clean({"title": title, "status": fields.pop("status", "idea"), **fields})
    items = _read()
    taken = {i["id"] for i in items}
    base = item_id or slugify(clean["title"])
    if not _SLUG_RE.match(base):
        raise ValueError(f"invalid backlog id {base!r}")
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    now = time.time()
    item = {"id": slug, "summary": "", "tags": [], "pipeline": "", "project_id": None,
            "script_path": None, "notes": "", "priority": 0, **clean,
            "created_at": now, "updated_at": now}
    items.append(item)
    _write(items)
    return _decorate(item)


def update(item_id: str, **fields: Any) -> dict[str, Any]:
    clean = _clean(fields)
    items = _read()
    for item in items:
        if item["id"] == item_id:
            item.update(clean)
            item["updated_at"] = time.time()
            _write(items)
            return _decorate(item)
    raise KeyError(f"unknown backlog item {item_id!r}")


def delete(item_id: str) -> None:
    items = _read()
    kept = [i for i in items if i["id"] != item_id]
    if len(kept) == len(items):
        raise KeyError(f"unknown backlog item {item_id!r}")
    _write(kept)


def read_script(item_id: str) -> Optional[str]:
    script = get(item_id).get("script_path")
    if not script:
        return None
    path = REPO_ROOT / _clean_script_path(script)
    if not path.is_file():
        return None
    data = path.read_bytes()[:MAX_SCRIPT_BYTES]
    return data.decode("utf-8", errors="replace")


def statuses() -> list[dict[str, str]]:
    return [{"id": k, "label": v} for k, v in STATUSES.items()]
