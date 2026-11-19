"""Content plans — multi-episode posting schedules (e.g. a views challenge).

Each plan is a folder under ``backlog/plans/<id>/`` (override the root with
``OPENMONTAGE_PLANS_DIR``) holding ``plan.json`` and, optionally, a markdown
schedule named by ``schedule_file``::

    {"id": "main-profile-1m-challenge", "title": "...", "start": "2026-11-16",
     "end": "2026-12-16", "target_views": 1000000, "views": 0,
     "episodes": [{"id": "EP.1", "title": "...", "post_date": "2026-11-22",
                   "project": "heartbreak-ep1"}]}

Backlot's ``/backlog`` page shows each plan as a block above the backlog list.
Like ``backlog/``, the folder is personal and gitignored.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from lib.paths import REPO_ROOT

PLANS_DIR = Path(os.environ.get("OPENMONTAGE_PLANS_DIR") or (REPO_ROOT / "backlog" / "plans"))
MAX_SCHEDULE_BYTES = 512_000


def plans_dir() -> Path:
    return PLANS_DIR


def _read_schedule(folder: Path, name: Any) -> str:
    if not isinstance(name, str) or not name or "/" in name or "\\" in name or name.startswith("."):
        return ""
    path = folder / name
    if not path.is_file() or path.stat().st_size > MAX_SCHEDULE_BYTES:
        return ""
    return path.read_text(encoding="utf-8")


def list_plans() -> list[dict[str, Any]]:
    """Every readable plan, newest end date first. Broken files are skipped."""
    root = plans_dir()
    if not root.is_dir():
        return []
    plans = []
    for folder in sorted(root.iterdir()):
        meta = folder / "plan.json"
        if not folder.is_dir() or folder.name.startswith((".", "_")) or not meta.is_file():
            continue
        try:
            plan = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(plan, dict):
            continue
        plan.setdefault("id", folder.name)
        plan["episodes"] = [e for e in plan.get("episodes") or [] if isinstance(e, dict)]
        plan["schedule_markdown"] = _read_schedule(folder, plan.get("schedule_file"))
        plans.append(plan)
    plans.sort(key=lambda p: str(p.get("end") or ""), reverse=True)
    return plans
