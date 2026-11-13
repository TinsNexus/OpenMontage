"""Video gallery + social copy (title / caption / hashtags) for Backlot.

Two jobs:

1. Read-only: list every generated video under ``projects/*/assets/video`` and
   ``projects/*/renders`` together with the generation prompt that produced
   it, so a person can review output and prompt side by side.
2. Write (explicit user action only): draft platform-ready title, caption and
   hashtags with an LLM through PiAPI's OpenAI-compatible chat endpoint, and
   save the result under ``projects/<id>/artifacts/social/``.

Prompt provenance, in order of preference:
- a sidecar ``<video stem>.meta.json`` next to the video
  (``{"prompt": ...}`` or ``{"prompt_file": "artifacts/..."}``,
  or ``{"derived_from": "assets/video/x.mp4"}`` for trims/re-encodes);
- ``artifacts/*prompt_v<N>*`` matching a ``_v<N>`` tag in the video name;
- the project's only ``artifacts/*prompt*`` file.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

VIDEO_EXT = {".mp4", ".webm", ".mov"}
VIDEO_DIRS = ("assets/video", "renders")
SOCIAL_DIR = "artifacts/social"
PROMPT_MAX_CHARS = 6000

PLATFORMS: dict[str, dict[str, str]] = {
    "facebook_reels": {
        "label": "Facebook Reels",
        "rules": "Hook in the first line (visible before 'See more'). Caption 1-3 short lines, "
                 "may use 1-3 emoji. 5-10 hashtags at the end.",
    },
    "tiktok": {
        "label": "TikTok",
        "rules": "Caption under 150 characters, punchy, conversational. 3-6 hashtags mixing broad and niche.",
    },
    "youtube_shorts": {
        "label": "YouTube Shorts",
        "rules": "Titles under 70 characters, curiosity-driven, no clickbait lies. Caption is the description: "
                 "2-3 sentences. 3-5 hashtags and always include #Shorts.",
    },
    "instagram_reels": {
        "label": "Instagram Reels",
        "rules": "First line is the hook. Caption 1-4 lines with line breaks, light emoji. 8-15 hashtags.",
    },
}
LANGUAGES = {"vi": "Vietnamese", "en": "English"}
DEFAULT_MODEL = "claude-sonnet-4-6"
CHAT_URL = "https://api.piapi.ai/v1/chat/completions"


# ---------------------------------------------------------------------------
# Listing + prompt provenance (read-only)
# ---------------------------------------------------------------------------

def list_thumbs(project_dir: Path, rel_video: str) -> list[dict[str, Any]]:
    from backlot import thumbs

    return thumbs.list_thumbs(project_dir, rel_video)


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _read_json(path: Path) -> Optional[dict]:
    text = _read_text(path)
    if text is None:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _sidecar(video: Path) -> Path:
    return video.with_name(f"{video.stem}.meta.json")


def social_path(project_dir: Path, rel_video: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "__", rel_video)
    return project_dir / SOCIAL_DIR / f"{safe}.json"


def resolve_prompt(project_dir: Path, rel_video: str, _depth: int = 0) -> dict[str, Any]:
    """Return ``{"prompt": str|None, "source": str|None, "meta": dict}`` for a video."""
    video = project_dir / rel_video
    meta = _read_json(_sidecar(video)) or {}
    if meta.get("prompt"):
        return {"prompt": meta["prompt"], "source": _sidecar(video).name, "meta": meta}
    if meta.get("prompt_file"):
        text = _read_text(project_dir / meta["prompt_file"])
        if text:
            return {"prompt": text, "source": meta["prompt_file"], "meta": meta}
    if meta.get("derived_from") and _depth < 4:
        parent = resolve_prompt(project_dir, meta["derived_from"], _depth + 1)
        if parent["prompt"]:
            return {**parent, "meta": {**parent["meta"], **meta}}

    artifacts = project_dir / "artifacts"
    candidates = sorted(p for p in artifacts.glob("*prompt*") if p.suffix in {".txt", ".md"}) if artifacts.is_dir() else []
    tag = re.search(r"_v(\d+)", Path(rel_video).stem)
    if tag:
        for p in candidates:
            if re.search(rf"_v{tag.group(1)}(?!\d)", p.stem):
                return {"prompt": _read_text(p), "source": f"artifacts/{p.name}", "meta": meta}
    if len(candidates) == 1:
        return {"prompt": _read_text(candidates[0]), "source": f"artifacts/{candidates[0].name}", "meta": meta}
    return {"prompt": None, "source": None, "meta": meta}


def _project_title(project_dir: Path) -> str:
    data = _read_json(project_dir / "project.json") or {}
    return data.get("title") or project_dir.name


def list_videos(projects_dir: Path) -> list[dict[str, Any]]:
    """Every generated video, newest first, with its prompt and saved social copy."""
    out: list[dict[str, Any]] = []
    if not projects_dir.is_dir():
        return out
    for project_dir in sorted(p for p in projects_dir.iterdir() if p.is_dir()):
        title = _project_title(project_dir)
        for sub in VIDEO_DIRS:
            folder = project_dir / sub
            if not folder.is_dir():
                continue
            for video in sorted(folder.rglob("*")):
                if video.suffix.lower() not in VIDEO_EXT or not video.is_file():
                    continue
                rel = video.relative_to(project_dir).as_posix()
                stat = video.stat()
                prov = resolve_prompt(project_dir, rel)
                meta = prov["meta"]
                out.append({
                    "project_id": project_dir.name,
                    "project_title": title,
                    "path": rel,
                    "name": video.name,
                    "kind": "render" if sub == "renders" else "clip",
                    "size_bytes": stat.st_size,
                    "modified": stat.st_mtime,
                    "prompt": prov["prompt"],
                    "prompt_source": prov["source"],
                    "model": meta.get("model"),
                    "cost_usd": meta.get("cost_usd"),
                    "duration_seconds": meta.get("duration_seconds"),
                    "resolution": meta.get("resolution"),
                    "social": _read_json(social_path(project_dir, rel)),
                    "thumbs": list_thumbs(project_dir, rel),
                })
    out.sort(key=lambda v: v["modified"], reverse=True)
    return out


# ---------------------------------------------------------------------------
# Social copy generation (writes artifacts/social/*.json)
# ---------------------------------------------------------------------------

def build_messages(
    *, platform: str, language: str, project_title: str, video_name: str,
    prompt: Optional[str], notes: str = "",
) -> list[dict[str, str]]:
    p = PLATFORMS[platform]
    lang = LANGUAGES[language]
    system = (
        "You are a senior short-form video social media copywriter. You write titles, captions and "
        "hashtags that stop the scroll without lying about the content. Return ONLY a JSON object, "
        "no markdown fences."
    )
    user = f"""Write social copy for one AI-generated short video.

Platform: {p['label']}
Platform rules: {p['rules']}
Language: write titles and caption in {lang}. Hashtags may mix {lang} and English, no spaces inside a hashtag.
Project: {project_title}
Video file: {video_name}

The video was generated by an AI video model from this prompt (it describes what is on screen):
<generation_prompt>
{(prompt or '(prompt unavailable — infer only from the project title and file name, keep it generic)')[:PROMPT_MAX_CHARS]}
</generation_prompt>

{('Creator notes: ' + notes.strip()) if notes.strip() else ''}

Requirements:
- Describe only what the prompt says is on screen; do not invent plot, names or events.
- Do not copy prompt jargon (camera specs, "identity_lock", shot timings) into the copy.
- The video is AI-generated: add a short, natural AI-made note in the caption (platforms require disclosure).
- Hashtags start with #, no duplicates.

JSON shape:
{{"titles": ["option 1", "option 2", "option 3"], "caption": "...", "hashtags": ["#...", "..."]}}"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse_copy(text: str) -> dict[str, Any]:
    """Pull the JSON object out of a model reply and normalise it."""
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        raise ValueError("model reply contained no JSON object")
    data = json.loads(match.group(0))
    titles = [str(t).strip() for t in (data.get("titles") or []) if str(t).strip()]
    if not titles and data.get("title"):
        titles = [str(data["title"]).strip()]
    caption = str(data.get("caption") or "").strip()
    tags: list[str] = []
    for raw in data.get("hashtags") or []:
        tag = "#" + re.sub(r"\s+", "", str(raw)).lstrip("#")
        if len(tag) > 1 and tag.lower() not in {t.lower() for t in tags}:
            tags.append(tag)
    if not titles or not caption:
        raise ValueError("model reply missing titles or caption")
    return {"titles": titles[:5], "caption": caption, "hashtags": tags[:30]}


def _chat(messages: list[dict[str, str]], model: str, api_key: str) -> tuple[str, dict]:
    import requests

    resp = requests.post(
        CHAT_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model, "messages": messages, "temperature": 0.8},
        timeout=120,
    )
    try:
        body = resp.json()
    except ValueError:
        body = {}
    if resp.status_code >= 400:
        err = body.get("error") if isinstance(body, dict) else None
        msg = (err or {}).get("message") if isinstance(err, dict) else (body.get("message") if body else resp.text[:200])
        raise RuntimeError(f"PiAPI chat HTTP {resp.status_code}: {msg}")
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"PiAPI chat returned no message: {str(body)[:200]}")
    return content, body.get("usage") or {}


def generate_social(
    project_dir: Path, rel_video: str, *, platform: str, language: str = "vi",
    notes: str = "", model: Optional[str] = None,
) -> dict[str, Any]:
    if platform not in PLATFORMS:
        raise ValueError(f"unknown platform {platform!r}; expected one of {sorted(PLATFORMS)}")
    if language not in LANGUAGES:
        raise ValueError(f"unknown language {language!r}; expected one of {sorted(LANGUAGES)}")
    if not (project_dir / rel_video).is_file():
        raise FileNotFoundError(rel_video)

    from tools import piapi_client

    api_key = piapi_client.get_api_key()
    if not api_key:
        raise RuntimeError("PIAPI_API_KEY / PIAPI_KEY is not set; captions are written via PiAPI's chat API")

    model = model or os.environ.get("BACKLOT_COPY_MODEL") or DEFAULT_MODEL
    prov = resolve_prompt(project_dir, rel_video)
    messages = build_messages(
        platform=platform, language=language, project_title=_project_title(project_dir),
        video_name=Path(rel_video).name, prompt=prov["prompt"], notes=notes,
    )
    reply, usage = _chat(messages, model, api_key)
    copy = parse_copy(reply)

    record = {
        **copy,
        "platform": platform,
        "language": language,
        "notes": notes,
        "model": model,
        "usage": {k: usage.get(k) for k in ("prompt_tokens", "completion_tokens", "total_tokens") if k in usage},
        "prompt_source": prov["source"],
        "created_at": time.time(),
    }
    path = social_path(project_dir, rel_video)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_json(path) or {}
    history = (existing.get("history") or [])[-9:]
    if existing.get("caption"):
        history.append({k: existing.get(k) for k in ("titles", "caption", "hashtags", "platform", "language", "created_at")})
    record["history"] = history
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return record
