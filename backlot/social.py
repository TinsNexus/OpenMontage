"""Video gallery + social copy (title / caption / hashtags) for Backlot.

Two jobs:

1. Read-only: list every generated video under ``projects/*/assets/video`` and
   ``projects/*/renders`` together with the generation prompt that produced
   it, so a person can review output and prompt side by side.
2. Write (explicit user action only): draft platform-ready title, caption and
   hashtags with an LLM through PiAPI's OpenAI-compatible chat endpoint, and
   save the result under ``projects/<id>/artifacts/social/``.

Videos made outside OpenMontage can be uploaded (``save_upload``); they live
in the hidden ``projects/_uploads`` folder (the Library skips ``_`` folders).
A video with no generation prompt is *read* instead: frames sampled evenly
across it are sent to the vision model together with a local faster-whisper
transcript of its speech (cached in the video's ``.meta.json``).

Prompt provenance, in order of preference:
- a sidecar ``<video stem>.meta.json`` next to the video
  (``{"prompt": ...}`` or ``{"prompt_file": "artifacts/..."}``,
  or ``{"derived_from": "assets/video/x.mp4"}`` for trims/re-encodes);
- ``artifacts/*prompt_v<N>*`` matching a ``_v<N>`` tag in the video name;
- the project's only ``artifacts/*prompt*`` file.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

VIDEO_EXT = {".mp4", ".webm", ".mov"}
VIDEO_DIRS = ("assets/video", "renders")
SOCIAL_DIR = "artifacts/social"
PROMPT_MAX_CHARS = 6000
UPLOAD_PROJECT = "_uploads"
UPLOAD_DIR = "assets/video"
UPLOAD_MAX_BYTES = 1024 * 1024 * 1024
TRANSCRIPT_MAX_CHARS = 4000
FRAME_WIDTH = 512
WHISPER_MODEL = "small"

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
                    "uploaded": project_dir.name == UPLOAD_PROJECT,
                    "original_name": meta.get("original_name"),
                    "transcript": meta.get("transcript"),
                    "social": _read_json(social_path(project_dir, rel)),
                    "thumbs": list_thumbs(project_dir, rel),
                })
    out.sort(key=lambda v: v["modified"], reverse=True)
    return out


# ---------------------------------------------------------------------------
# Uploads (videos made outside OpenMontage)
# ---------------------------------------------------------------------------

def upload_project_dir(projects_dir: Path) -> Path:
    """The hidden project that holds uploaded videos (created on first use)."""
    project_dir = projects_dir / UPLOAD_PROJECT
    (project_dir / UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
    meta = project_dir / "project.json"
    if not meta.exists():
        meta.write_text(json.dumps({"title": "Video tải lên", "project_id": UPLOAD_PROJECT}, ensure_ascii=False,
                                   indent=2), encoding="utf-8")
    return project_dir


def upload_target(projects_dir: Path, file_name: str) -> tuple[Path, str]:
    """Pick a fresh, safe path for an uploaded file. Returns ``(abs_path, rel_path)``."""
    name = Path(str(file_name or "")).name
    suffix = Path(name).suffix.lower()
    if suffix not in VIDEO_EXT:
        raise ValueError(f"video must be one of {sorted(VIDEO_EXT)}")
    stem = re.sub(r"[^\w.-]+", "_", Path(name).stem, flags=re.UNICODE).strip("._")[:80] or "video"
    project_dir = upload_project_dir(projects_dir)
    folder = project_dir / UPLOAD_DIR
    target = folder / f"{stem}{suffix}"
    n = 2
    while target.exists():
        target = folder / f"{stem}_{n}{suffix}"
        n += 1
    return target, target.relative_to(project_dir).as_posix()


def finish_upload(video: Path, original_name: str) -> None:
    """Write the upload's sidecar so the gallery knows where it came from."""
    _write_json(_sidecar(video), {"source": "upload", "original_name": Path(original_name).name,
                                  "uploaded_at": time.time()})


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Reading a video that has no prompt: sampled frames + speech transcript
# ---------------------------------------------------------------------------

def _probe(video: Path) -> dict[str, Any]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type",
         "-of", "json", str(video)],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe could not read the video: {result.stderr.strip()[:200]}")
    data = json.loads(result.stdout or "{}")
    duration = float((data.get("format") or {}).get("duration") or 0)
    has_audio = any(s.get("codec_type") == "audio" for s in data.get("streams") or [])
    return {"duration": duration, "has_audio": has_audio}


def sample_frames(video: Path, duration: float) -> list[tuple[float, str]]:
    """Grab 4-10 evenly spaced frames, return ``[(time_s, base64 jpeg), ...]``."""
    count = int(min(10, max(4, duration // 3))) if duration > 0 else 1
    times = [duration * (i + 0.5) / count for i in range(count)] if duration > 0 else [0.0]
    frames: list[tuple[float, str]] = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, t in enumerate(times):
            out = Path(tmp) / f"f{i}.jpg"
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", str(video),
                 "-frames:v", "1", "-vf", f"scale={FRAME_WIDTH}:-2", "-q:v", "4", str(out)],
                capture_output=True, text=True, timeout=60,
            )
            if out.is_file() and out.stat().st_size:
                frames.append((t, base64.b64encode(out.read_bytes()).decode("ascii")))
    if not frames:
        raise RuntimeError("ffmpeg could not extract any frame from the video")
    return frames


def transcribe(video: Path) -> str:
    """Speech in the video as plain text (local faster-whisper; '' when silent/unavailable)."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return ""
    model = WhisperModel(os.environ.get("BACKLOT_WHISPER_MODEL") or WHISPER_MODEL, device="cpu",
                         compute_type="int8")
    segments, _info = model.transcribe(str(video), vad_filter=True)
    return " ".join(s.text.strip() for s in segments if s.text.strip()).strip()


def read_video(video: Path) -> dict[str, Any]:
    """Frames + transcript for the copywriter. The transcript is cached in the sidecar."""
    info = _probe(video)
    frames = sample_frames(video, info["duration"])
    sidecar = _sidecar(video)
    meta = _read_json(sidecar) or {}
    transcript = meta.get("transcript")
    if transcript is None:
        transcript = ""
        if info["has_audio"]:
            try:
                transcript = transcribe(video)
            except Exception as e:  # transcription is a bonus; never block the copy on it
                meta["transcript_error"] = str(e)[:200]
        meta["transcript"] = transcript
        meta["duration_seconds"] = meta.get("duration_seconds") or round(info["duration"], 2)
        _write_json(sidecar, meta)
    return {"frames": frames, "transcript": transcript, "duration": info["duration"]}


# ---------------------------------------------------------------------------
# Social copy generation (writes artifacts/social/*.json)
# ---------------------------------------------------------------------------

def build_messages(
    *, platform: str, language: str, project_title: str, video_name: str,
    prompt: Optional[str], notes: str = "", reading: Optional[dict[str, Any]] = None,
    ai_generated: bool = True,
) -> list[dict[str, Any]]:
    p = PLATFORMS[platform]
    lang = LANGUAGES[language]
    system = (
        "You are a senior short-form video social media copywriter. You write titles, captions and "
        "hashtags that stop the scroll without lying about the content. Return ONLY a JSON object, "
        "no markdown fences."
    )
    if reading:
        frames = reading["frames"]
        stamps = ", ".join(f"{t:.1f}s" for t, _ in frames)
        transcript = (reading.get("transcript") or "").strip()
        source = f"""You cannot play the video, so here is what it contains:
- {len(frames)} frames sampled evenly across its {reading['duration']:.1f}s runtime, attached in order (at {stamps}).
- What is said in it (automatic speech transcript, may contain recognition errors):
<transcript>
{transcript[:TRANSCRIPT_MAX_CHARS] if transcript else '(no speech detected)'}
</transcript>"""
        grounding = "- Describe only what the frames and transcript show; do not invent plot, names or events."
    else:
        source = f"""The video was generated by an AI video model from this prompt (it describes what is on screen):
<generation_prompt>
{(prompt or '(prompt unavailable — infer only from the project title and file name, keep it generic)')[:PROMPT_MAX_CHARS]}
</generation_prompt>"""
        grounding = ("- Describe only what the prompt says is on screen; do not invent plot, names or events.\n"
                     "- Do not copy prompt jargon (camera specs, \"identity_lock\", shot timings) into the copy.")
    disclosure = ("- The video is AI-generated: add a short, natural AI-made note in the caption "
                  "(platforms require disclosure)." if ai_generated else
                  "- Do not call the video AI-generated.")
    user = f"""Write social copy for one short video.

Platform: {p['label']}
Platform rules: {p['rules']}
Language: write titles and caption in {lang}. Hashtags may mix {lang} and English, no spaces inside a hashtag.
Project: {project_title}
Video file: {video_name}

{source}

{('Creator notes: ' + notes.strip()) if notes.strip() else ''}

Requirements:
{grounding}
{disclosure}
- Hashtags start with #, no duplicates.

JSON shape:
{{"titles": ["option 1", "option 2", "option 3"], "caption": "...", "hashtags": ["#...", "..."]}}"""
    if reading:
        content: list[dict[str, Any]] = [{"type": "text", "text": user}]
        content += [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                    for _, b64 in reading["frames"]]
        return [{"role": "system", "content": system}, {"role": "user", "content": content}]
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
    notes: str = "", model: Optional[str] = None, ai_generated: bool = True,
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
    # No generation prompt (uploads, hand-made clips): watch and listen instead.
    reading = None
    if not prov["prompt"]:
        try:
            reading = read_video(project_dir / rel_video)
        except (RuntimeError, OSError, subprocess.SubprocessError, ValueError):
            if project_dir.name == UPLOAD_PROJECT:
                raise RuntimeError("could not read the uploaded video (ffmpeg failed) — is the file a valid video?")
            # project clips keep the old behaviour: generic copy from title + file name
    original = (prov["meta"] or {}).get("original_name")
    messages = build_messages(
        platform=platform, language=language,
        project_title="(uploaded video)" if project_dir.name == UPLOAD_PROJECT else _project_title(project_dir),
        video_name=original or Path(rel_video).name, prompt=prov["prompt"], notes=notes,
        reading=reading, ai_generated=ai_generated,
    )
    reply, usage = _chat(messages, model, api_key)
    copy = parse_copy(reply)

    record = {
        **copy,
        "platform": platform,
        "language": language,
        "notes": notes,
        "ai_generated": ai_generated,
        "model": model,
        "usage": {k: usage.get(k) for k in ("prompt_tokens", "completion_tokens", "total_tokens") if k in usage},
        "prompt_source": prov["source"] or (
            f"{len(reading['frames'])} khung hình" + (" + lời thoại" if reading["transcript"] else "")
            if reading else None),
        "created_at": time.time(),
    }
    path = social_path(project_dir, rel_video)
    existing = _read_json(path) or {}
    history = (existing.get("history") or [])[-9:]
    if existing.get("caption"):
        history.append({k: existing.get(k) for k in ("titles", "caption", "hashtags", "platform", "language", "created_at")})
    record["history"] = history
    _write_json(path, record)
    return record
