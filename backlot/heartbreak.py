"""Heartbreak studio — Backlot's /heartbreak episode factory.

Builds "wordless heartbreak" reels (no-dialogue 3D-cartoon comedy) from the
formula in ``skills/creative/prompting/wordless-heartbreak-formula.md``.

Each episode is a normal cinematic-pipeline project plus an extra
``studio.json`` (see docs/briefs/heartbreak-studio.md §3)::

    projects/heartbreak-<slug>/
        studio.json            # slots, prompts, model, music plan, spend, stage
        artifacts/clipA.txt    # one prompt file per clip
        checkpoint_*.json      # research/proposal/script/scene_plan (lib.checkpoint)

Milestone 1 covers episode creation, AI prompt writing (PiAPI chat, ~$0.01),
manual prompt edits and the price table. Clip generation (M3) and compose (M4)
come later. The only paid call in this module is ``write_prompts()``.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from backlot.state import PROJECTS_DIR, REPO_ROOT
from lib import characters as charlib
from lib.checkpoint import init_project, write_checkpoint

PIPELINE_TYPE = "cinematic"
SLOT_ORDER = ("HERO", "CRUSH", "RIVAL", "BUDDY1", "BUDDY2", "BARD", "NEW")
BEATS = ("WOO", "DUMP", "FLASH", "DRINK", "SONG", "PEAK", "TWIST", "HOOK")
LENGTHS = {"short": (2, 4), "long": (5, 12)}
LENGTH_LABELS = {
    "short": "bản ngắn 2–4 clip (25–45 giây)",
    "long": "bản dài 5–12 clip (70–85 giây)",
}
# Every price-table candidate accepts 4–15 s (Seedance 2 tiers + Kling 3.0),
# so a prompt written for any row of the table stays valid for all of them.
DURATION_RANGE = (4, 15)
MAX_PROMPT_CHARS = 4000       # seedance_piapi prompt limit
COLD_OPEN_MAX_WORDS = 8
FORMULA_PATH = REPO_ROOT / "skills" / "creative" / "prompting" / "wordless-heartbreak-formula.md"
# The studio's locked default: Seedance 2 fast @ 720p (brief §2).
DEFAULT_MODEL = {"tool": "seedance_piapi", "model_variant": "fast", "resolution": "720p"}
SLUG_RE = re.compile(r"^heartbreak-[a-z0-9][a-z0-9-]{0,63}$")

_lock = threading.Lock()


# ---------------------------------------------------------------------------
# system prompt (the formula, trimmed to its prompt-writing sections)
# ---------------------------------------------------------------------------

_SYSTEM_INSTRUCTIONS = """Bạn là đạo diễn prompt cho series reel hoạt hình 3D THẤT TÌNH KHÔNG LỜI (wordless heartbreak) trên Facebook Reels.

Dưới đây là "công thức" (formula) của series — tuân thủ chặt: timeline beat, quy tắc cold open, tỉ lệ 9:16, phong cách 3D cartoon, bản đồ nhạc.

Nhiệm vụ: viết prompt tạo video (Seedance / Kling) cho từng clip của tập này.

Bắt buộc:
- Prompt bằng tiếng ANH. Thay mọi tên nhân vật bằng đúng câu `identity` được cung cấp — model không hiểu tên slot.
- Chỉ dùng các @imageN đã liệt kê trong tin nhắn người dùng (@image1 = HERO, @image2 = CRUSH, ...).
- Mỗi clip: 1 hành động + 1 biểu cảm phóng đại; kết thúc bằng "No text, no speech."
- Cold open: một dòng chữ ngắn tối đa 8 TỪ, do người dựng chèn lúc ghép video — KHÔNG viết chữ này vào prompt video.
- Trả về JSON THUẦN, không kèm giải thích, đúng mẫu trong tin nhắn người dùng.
"""


def _system_prompt() -> str:
    """The formula file minus its non-prompt sections (§1 why-it-works, §10 metrics)."""
    text = FORMULA_PATH.read_text(encoding="utf-8")
    parts = re.split(r"(?m)^## ", text)
    kept = [parts[0]] + [p for p in parts[1:] if not p.startswith(("1. ", "10. "))]
    return _SYSTEM_INSTRUCTIONS + "\n" + "\n## ".join(kept)


# ---------------------------------------------------------------------------
# io helpers
# ---------------------------------------------------------------------------

def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _slugify(title: str) -> str:
    text = unicodedata.normalize("NFKD", title.replace("đ", "d").replace("Đ", "D"))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:48] or "tap-moi"


def _project_dir(slug: str) -> Path:
    # slug also comes from the URL: never let it walk out of PROJECTS_DIR.
    if not SLUG_RE.match(slug or ""):
        raise KeyError(f"tập không tồn tại: {slug}")
    return PROJECTS_DIR / slug


def _load_studio(slug: str) -> dict[str, Any]:
    data = _read_json(_project_dir(slug) / "studio.json", None)
    if not isinstance(data, dict):
        raise KeyError(f"tập không tồn tại: {slug}")
    return data


def _save_studio(slug: str, studio: dict[str, Any]) -> None:
    studio["updated_at"] = time.time()
    _write_json(_project_dir(slug) / "studio.json", studio)


def _save_artifact(slug: str, name: str, data: dict[str, Any]) -> None:
    _write_json(_project_dir(slug) / "artifacts" / f"{name}.json", data)


def _write_clip_file(slug: str, clip: dict[str, Any]) -> None:
    _write_text(_project_dir(slug) / "artifacts" / f"clip{clip['id']}.txt", clip["prompt"].rstrip() + "\n")


def _write_ckpt(slug: str, stage: str, status: str, artifacts: dict[str, Any], *,
                human_approved: bool = False, metadata: Optional[dict] = None) -> None:
    write_checkpoint(
        PROJECTS_DIR, slug, stage, status, artifacts,
        pipeline_type=PIPELINE_TYPE,
        human_approved=human_approved,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# validation helpers
# ---------------------------------------------------------------------------

def _validate_slots(raw: Any) -> dict[str, Optional[str]]:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("slots phải là object {SLOT: character_id}.")
    out: dict[str, Optional[str]] = {slot: None for slot in SLOT_ORDER}
    for slot, cid in raw.items():
        if slot not in SLOT_ORDER:
            raise ValueError(f"Slot không hợp lệ: {slot}. Chỉ dùng: {', '.join(SLOT_ORDER)}.")
        if cid in (None, ""):
            continue
        cid = str(cid).strip()
        try:
            charlib.get(cid)
        except (KeyError, ValueError):
            raise ValueError(f"Nhân vật không tồn tại: {cid}") from None
        out[slot] = cid
    if not out["HERO"]:
        raise ValueError("Cần chọn HERO (kẻ si tình) cho tập này.")
    return out


def _as_int(raw: Any, what: str) -> int:
    if isinstance(raw, bool):
        raise ValueError(f"{what} phải là số nguyên; got {raw!r}.")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{what} phải là số; got {raw!r}.") from None
    if value != int(value):
        raise ValueError(f"{what} phải là số nguyên; got {raw!r}.")
    return int(value)


def _as_float(raw: Any, what: str) -> float:
    if isinstance(raw, bool):
        raise ValueError(f"{what} phải là số; got {raw!r}.")
    try:
        return float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{what} phải là số; got {raw!r}.") from None


def _check_image_refs(prompt: str, n_images: int, where: str) -> None:
    bad = [int(m) for m in re.findall(r"@image(\d+)", prompt) if not 1 <= int(m) <= n_images]
    if bad:
        raise ValueError(
            f"{where}: dùng @image{bad[0]} nhưng tập chỉ có {n_images} ảnh tham chiếu "
            f"(@image1–@image{n_images})."
        )


def _parse_json_reply(reply: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", reply or "", re.S)
    if not match:
        raise ValueError("Trả lời của AI không chứa JSON.")
    try:
        data = json.loads(match.group(0))
    except ValueError as e:
        raise ValueError(f"Trả lời của AI không phải JSON hợp lệ: {e}") from None
    if not isinstance(data, dict):
        raise ValueError("Trả lời của AI phải là một JSON object.")
    return data


def _reference_mapping(studio: dict[str, Any]) -> list[dict[str, str]]:
    """Filled slots in formula order: ``@image1`` = first slot, and so on."""
    mapping = []
    for slot in SLOT_ORDER:
        cid = studio.get("slots", {}).get(slot)
        if not cid:
            continue
        char = charlib.get(cid)          # KeyError propagates -> 404
        identity = str(char.get("identity") or "").strip()
        if not identity:
            raise ValueError(f"Nhân vật {cid} (slot {slot}) chưa có trường identity.")
        mapping.append({"slot": slot, "character": cid,
                        "name": str(char.get("name") or cid), "identity": identity})
    if not mapping:
        raise ValueError("Tập chưa có nhân vật nào trong các slot.")
    return mapping


def _validate_plan(reply: str, studio: dict[str, Any], n_images: int) -> dict[str, Any]:
    """Validate the model's plan against the brief's M1 rules.

    2–4 clips for ``short`` (5–12 for ``long``), every duration inside the
    tools' shared 4–15 s range, prompts referencing only existing ``@imageN``,
    and a cold-open line of at most 8 words.
    """
    data = _parse_json_reply(reply)

    raw_clips = data.get("clips")
    if not isinstance(raw_clips, list) or not raw_clips:
        raise ValueError("Trả lời của AI thiếu danh sách clips.")
    lo, hi = LENGTHS[studio.get("length", "short")]
    if not lo <= len(raw_clips) <= hi:
        raise ValueError(f"Bản {studio.get('length')} cần {lo}–{hi} clip; AI trả về {len(raw_clips)}.")

    clips: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_clips:
        if not isinstance(raw, dict):
            raise ValueError("Mỗi clip phải là object {id, beats, duration, prompt}.")
        cid = str(raw.get("id") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9]{1,4}", cid):
            raise ValueError(f"id clip không hợp lệ: {cid!r} (dùng A, B, C ...).")
        if cid in seen:
            raise ValueError(f"id clip trùng lặp: {cid}")
        seen.add(cid)

        beats = raw.get("beats")
        if not isinstance(beats, list) or not beats:
            raise ValueError(f"Clip {cid} thiếu beats.")
        norm_beats = []
        for beat in beats:
            beat = str(beat).strip().upper()
            if beat not in BEATS:
                raise ValueError(f"Clip {cid}: beat không hợp lệ {beat!r}. Chỉ dùng: {', '.join(BEATS)}.")
            norm_beats.append(beat)

        duration = _as_int(raw.get("duration"), f"duration của clip {cid}")
        if not DURATION_RANGE[0] <= duration <= DURATION_RANGE[1]:
            raise ValueError(
                f"Clip {cid}: duration phải {DURATION_RANGE[0]}–{DURATION_RANGE[1]} giây; got {duration}."
            )

        prompt = str(raw.get("prompt") or "").strip()
        if not prompt:
            raise ValueError(f"Clip {cid} thiếu prompt.")
        if len(prompt) > MAX_PROMPT_CHARS:
            raise ValueError(f"Clip {cid}: prompt tối đa {MAX_PROMPT_CHARS} ký tự; got {len(prompt)}.")
        _check_image_refs(prompt, n_images, f"clip {cid}")

        clips.append({"id": cid, "beats": norm_beats, "duration": duration, "prompt": prompt})

    cold = data.get("cold_open")
    if not isinstance(cold, dict):
        raise ValueError("Thiếu cold_open {text, from_clip, at}.")
    text = str(cold.get("text") or "").strip()
    if not text:
        raise ValueError("cold_open.text trống — tập bắt buộc có một dòng chữ cold open.")
    words = text.split()
    if len(words) > COLD_OPEN_MAX_WORDS:
        raise ValueError(f"cold_open.text tối đa {COLD_OPEN_MAX_WORDS} từ; got {len(words)}.")
    from_clip = str(cold.get("from_clip") or "").strip()
    if from_clip not in seen:
        raise ValueError(f"cold_open.from_clip {from_clip!r} không có trong clips.")
    cold_at = _as_float(cold.get("at"), "cold_open.at")
    clip_duration = next(c["duration"] for c in clips if c["id"] == from_clip)
    if not 0 <= cold_at < clip_duration:
        raise ValueError(f"cold_open.at phải trong [0, {clip_duration}) giây; got {cold_at}.")

    music_raw = data.get("music_plan") or []
    if not isinstance(music_raw, list):
        raise ValueError("music_plan phải là một mảng.")
    music_plan = []
    for i, item in enumerate(music_raw):
        if not isinstance(item, dict):
            raise ValueError(f"music_plan[{i}] phải là object {{at, cue, action}}.")
        action = str(item.get("action") or "").strip().lower()
        if action not in ("in", "cut", "swap"):
            raise ValueError(f"music_plan[{i}].action phải là in/cut/swap; got {action!r}.")
        at = _as_float(item.get("at"), f"music_plan[{i}].at")
        if at < 0:
            raise ValueError(f"music_plan[{i}].at không được âm; got {at}.")
        cue = item.get("cue")
        music_plan.append({"at": round(at, 2), "cue": None if cue in (None, "") else str(cue), "action": action})

    return {
        "clips": clips,
        "cold_open": {"text": text, "from_clip": from_clip, "at": round(cold_at, 2)},
        "music_plan": music_plan,
        "caption_hint": str(data.get("caption_hint") or "").strip()[:500],
    }


# ---------------------------------------------------------------------------
# canonical artifacts
# ---------------------------------------------------------------------------

def _research_brief(studio: dict[str, Any]) -> dict[str, Any]:
    """Schema-valid research_brief — the formula's own research, reused per episode."""
    ref = "https://www.facebook.com/watch/?v=2286612768853006"
    return {
        "version": "1.0",
        "topic": f"Wordless 3D-cartoon reel — {studio['title']}",
        "research_date": datetime.now(timezone.utc).date().isoformat(),
        "landscape": {
            "existing_content": [
                {"title": "Reference wordless heartbreak reel (驢略略)", "source": "facebook", "url": ref,
                 "angle": "wordless animal heartbreak, exaggerated crying, music + SFX only",
                 "what_it_covers": "74 s, 27 shots, 2.7 s per shot, no dialogue",
                 "engagement_signal": "9.2M views, 279K reactions in ~2 days"},
                {"title": "Our own wordless reels (EP.1, EP.2)", "source": "own channel",
                 "url": "https://www.facebook.com/",
                 "angle": "same formula with an original cast and cue-mapped music",
                 "what_it_covers": "proven pipeline: Seedance reference_to_video + music cut on beats",
                 "engagement_signal": "EP.1 average view time 10 s of 73 s — cold open was wrong"},
                {"title": "Formula seasonal variants (Ế Tết, Valentine, hết tiền...)",
                 "source": "internal", "url": "https://www.facebook.com/",
                 "angle": "seasonal repeats of the WOO→DUMP→…→TWIST frame",
                 "what_it_covers": "posting calendar and per-variant beat swaps"},
            ],
            "saturated_angles": [
                "re-uploaded Chinese AI dramas with dialogue and blurred watermarks",
                "16:9 reels — Facebook downranks them in Reels distribution",
            ],
            "underserved_gaps": [
                "an original wordless 3D cast a series can reuse across episodes",
                "25–45 s cuts tuned for completion rate instead of the full 70–85 s frame",
            ],
        },
        "data_points": [
            {"claim": "Wordless format removes the language barrier — the reference reel reached 9.2M views across countries",
             "source_url": ref, "credibility": "primary_source", "surprise_factor": "notable",
             "usable_as": "hook"},
            {"claim": "Opening with a calm scene keeps only 38% of viewers past 3 seconds — the cold open must be the strongest moment",
             "source_url": ref, "credibility": "primary_source", "surprise_factor": "surprising",
             "usable_as": "script_anchor"},
            {"claim": "Music that runs start-to-finish flattens every beat; contrast between silence and music creates the laugh",
             "source_url": ref, "credibility": "anecdotal", "surprise_factor": "expected",
             "usable_as": "closing_punch"},
        ],
        "audience_insights": {
            "common_questions": [
                "Làm sao giữ người xem ở lại quá 3 giây?",
                "Reel không lời có cần phụ đề không?",
                "Bao nhiêu clip thì đủ cho một tập ngắn?",
            ],
            "misconceptions": [
                {"myth": "Nhạc chạy suốt video sẽ hay hơn", "reality": "Nhạc phải rót đúng điểm và cắt phụt trên gag"},
            ],
            "knowledge_level": "casual Facebook Reels viewers, 18-45, watch on mute first",
        },
        "angles_discovered": [
            {"name": studio["title"], "hook": studio["idea"], "type": "narrative",
             "why_now": "monthly recurring slot on the formula's posting calendar"},
            {"name": "Cold-open curiosity hook", "hook": "Giây đầu tiên là khoảnh khắc gây tò mò nhất của tập",
             "type": "trending", "why_now": "EP.1 lost 62% of viewers before 3s with a calm open"},
            {"name": "Twist ending replay value", "hook": "Vừa khóc xong đã gặp đối tượng mới",
             "type": "evergreen", "why_now": "the twist is what makes viewers rewatch and tag friends"},
        ],
        "sources": [
            {"url": ref, "title": "Reference wordless heartbreak reel", "used_for": "structure, pacing, gag style",
             "reliability": "primary"},
            {"url": "https://www.facebook.com/", "title": "Our EP.1 \"Hai ống hút\" results", "used_for": "cold-open lesson",
             "reliability": "primary"},
            {"url": "https://www.facebook.com/", "title": "Our EP.2 \"Hết tiền cuối tháng\"", "used_for": "short-cut precedent",
             "reliability": "primary"},
            {"url": "https://piapi.ai/docs/seedance-api/seedance-2", "title": "Seedance 2 API + pricing",
             "used_for": "clip duration limits and price table", "reliability": "primary"},
            {"url": "https://piapi.ai/docs/kling-api/create-task", "title": "Kling API + pricing",
             "used_for": "alternative model row in the price table", "reliability": "primary"},
        ],
        "research_summary": (
            "The wordless heartbreak formula is already validated by the reference reel and our own episodes; "
            "this studio reuses that research instead of re-running it. The two levers that matter for this "
            "episode are a strong 1.5–2 s cold open and music that enters and cuts on beats."
        ),
    }


def _proposal_packet(studio: dict[str, Any], *, approved: bool) -> dict[str, Any]:
    """Schema-valid proposal_packet for the episode (concept options + plan + cost)."""
    from tools import piapi_client

    title, idea, length = studio["title"], studio["idea"], studio["length"]
    lo, hi = (25, 45) if length == "short" else (70, 85)
    other = "long" if length == "short" else "short"
    olo, ohi = (70, 85) if other == "long" else (25, 45)

    def concept(n: int, suffix: str, dur: float, hook: str, approach: str) -> dict[str, Any]:
        return {
            "id": f"c{n}",
            "title": f"{title} — {suffix}",
            "hook": hook[:190],
            "narrative_structure": "story",
            "visual_approach": approach,
            "target_duration_seconds": dur,
            "target_audience": "Facebook viewers 18-45, casual comedy, watch on mute",
            "target_platform": "generic",
            "suggested_playbook": "custom",
            "core_message": idea,
            "key_points": ["Cold open: strongest or most curious moment", "Twist ending with instant recovery"],
            "tone": "silly, exaggerated, warm payoff",
            "grounded_in": ["wordless-heartbreak-formula", "reference reel 9.2M views"],
            "why_this_works": "Proven wordless structure with no language barrier and a replayable twist.",
        }

    concept_options = [
        concept(1, LENGTH_LABELS[length], round((lo + hi) / 2, 1), idea,
                f"Wordless 3D-cartoon reel, {LENGTH_LABELS[length]}, 9:16, "
                f"{LENGTHS[length][0]}–{LENGTHS[length][1]} clips generated with character references."),
        concept(2, LENGTH_LABELS[other], round((olo + ohi) / 2, 1), idea,
                f"The other cut length of the same episode ({LENGTH_LABELS[other]}) if the first one "
                "runs long or short in retention."),
        concept(3, "cold open khác", round((lo + hi) / 2, 1),
                "Mở bằng khoảnh khắc tò mò nhất thay vì cao trào",
                "Same beats, but the cold open is taken from a different moment (evidence/detail shot) "
                "to A/B the first two seconds."),
    ]

    has_key = bool(piapi_client.get_api_key())
    return {
        "version": "1.0",
        "concept_options": concept_options,
        "selected_concept": {
            "concept_id": "c1",
            "rationale": f"Người dùng chọn {LENGTH_LABELS[length]} khi tạo tập.",
        },
        "production_plan": {
            "pipeline": PIPELINE_TYPE,
            "playbook": "custom",
            "stages": [
                {
                    "stage": "assets",
                    "tools": [
                        {"tool_name": "seedance_piapi", "provider": "piapi", "available": has_key,
                         "role": "reference_to_video clips from the cast's primary images (chosen in the price table)",
                         "estimated_cost_usd": 0.0,
                         "why_this_provider": "multi-image character references keep HERO identical across clips"},
                    ],
                    "approach": "generate one clip per prompt, 9:16, model picked by the user from price_table",
                },
                {
                    "stage": "compose",
                    "tools": [
                        {"tool_name": "video_compose", "available": True, "estimated_cost_usd": 0.0,
                         "role": "cut clips, burn the cold-open hook text, place music on the cue map, write .srt"},
                    ],
                    "approach": "ffmpeg concat/trim to 1080x1920 — free and local (locked here; revising it "
                               "requires a logged render_runtime decision)",
                },
            ],
            "render_runtime": "ffmpeg",
            "renderer_family": "cinematic-trailer",
            "delivery_promise": {
                "promise_type": "motion_led",
                "motion_required": True,
                "tone_mode": "comedy",
                "quality_floor": "presentable",
                "approved_fallback": None,
            },
            "music_source": {
                "source_type": "none",
                "mood_direction": "cue map from the formula §6 — music enters and cuts on beats, never a constant bed",
                "estimated_cost_usd": 0.0,
            },
            "quality_tradeoffs": [
                {"tradeoff": "Seedance 2 fast 720p (default) vs Seedance 2 Pro 720p",
                 "recommendation": "start with fast; upgrade a clip only if a take looks soft",
                 "quality_impact": "fast is ~2x cheaper per second with slightly less camera nuance"},
            ],
        },
        "cost_estimate": {
            "total_estimated_usd": 0.01,
            "line_items": [
                {"tool": "piapi_chat", "operation": "Viết prompt clip bằng AI (bước 2)",
                 "quantity": 1, "estimated_usd": 0.01, "notes": "Claude Sonnet qua PiAPI, pay-per-use"},
                {"tool": "seedance_piapi", "operation": "Tạo clip video (bước 4) — giá chốt ở bảng giá",
                 "quantity": 0, "estimated_usd": 0.0,
                 "notes": "mặc định Seedance 2 fast 720p; price_table tính lại theo độ dài clip"},
            ],
            "budget_verdict": "no_budget_set",
        },
        "approval": {
            "status": "approved" if approved else "pending",
            **({"user_notes": "User clicked 'Viết bằng AI' — prompts are editable afterwards."} if approved else {}),
        },
    }


def _script_artifact(studio: dict[str, Any]) -> dict[str, Any]:
    clips = studio.get("clips") or []
    sections, t = [], 0.0
    for clip in clips:
        dur = float(clip["duration"])
        sections.append({
            "id": f"clip{clip['id']}",
            "label": " + ".join(clip["beats"]),
            "text": (f"{' / '.join(clip['beats'])} ({clip['duration']}s): "
                     f"{clip['prompt'][:160]}{'…' if len(clip['prompt']) > 160 else ''} "
                     f"Prompt: artifacts/clip{clip['id']}.txt"),
            "start_seconds": t,
            "end_seconds": t + dur,
        })
        t += dur
    return {
        "version": "1.0",
        "title": f"{studio['title']} — {len(clips)} clip ({int(t)}s)",
        "total_duration_seconds": t,
        "sections": sections,
        "metadata": {"length": studio.get("length"), "cold_open": studio.get("cold_open"),
                     "caption_hint": studio.get("caption_hint")},
    }


def _scene_plan_artifact(studio: dict[str, Any]) -> dict[str, Any]:
    clips = studio.get("clips") or []
    scenes, t = [], 0.0
    for clip in clips:
        dur = float(clip["duration"])
        scenes.append({
            "id": f"sc_clip{clip['id']}",
            "type": "generated",
            "description": f"{' / '.join(clip['beats'])}: {clip['prompt'][:200]}",
            "start_seconds": t,
            "end_seconds": t + dur,
            "script_section_id": f"clip{clip['id']}",
            "framing": "9:16",
            "movement": "one action + one exaggerated expression per shot",
            "required_assets": [
                {"type": "video",
                 "description": f"{clip['duration']}s reference_to_video, model pending in price_table, 9:16",
                 "source": "generate"},
            ],
        })
        t += dur
    return {
        "version": "1.0",
        "scenes": scenes,
        "metadata": {"total_duration_seconds": t, "music_plan": studio.get("music_plan"),
                     "cold_open": studio.get("cold_open")},
    }


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def list_episodes() -> dict[str, Any]:
    """Every studio-managed episode (a heartbreak-* project with studio.json)."""
    root = PROJECTS_DIR
    out = []
    if root.is_dir():
        for entry in sorted(root.iterdir()):
            if not entry.is_dir() or not entry.name.startswith("heartbreak-"):
                continue
            studio = _read_json(entry / "studio.json", None)
            if not isinstance(studio, dict):
                continue
            clips = studio.get("clips") or []
            out.append({
                "slug": entry.name,
                "title": studio.get("title", entry.name),
                "idea": studio.get("idea", ""),
                "length": studio.get("length", "short"),
                "stage": studio.get("stage", "proposal"),
                "spent_usd": float(studio.get("spent_usd") or 0.0),
                "clip_count": len(clips),
                "approved_clips": sum(1 for c in clips if c.get("status") == "approved"),
                "created_at": studio.get("created_at"),
                "updated_at": studio.get("updated_at"),
            })
    out.sort(key=lambda e: e.get("updated_at") or 0, reverse=True)
    return {"episodes": out}


def get_episode(slug: str) -> dict[str, Any]:
    return {**_load_studio(slug), "slug": slug}


def create_episode(title: str, idea: str, slots: Any, length: str = "short") -> dict[str, Any]:
    """Create ``projects/heartbreak-<slug>/`` + studio.json and open the pipeline.

    Writes the ``research`` checkpoint (completed — the formula is the research)
    and the ``proposal`` checkpoint as ``awaiting_human``; the user's first
    paid action (``write_prompts``) approves it.
    """
    title = str(title or "").strip()
    if not title:
        raise ValueError("Thiếu tiêu đề tập.")
    if len(title) > 200:
        raise ValueError("Tiêu đề tối đa 200 ký tự.")
    idea = str(idea or "").strip()
    if not idea:
        raise ValueError("Thiếu ý tưởng — cần một dòng mô tả tập này.")
    if len(idea) > 500:
        raise ValueError("Ý tưởng tối đa 500 ký tự.")
    if length not in LENGTHS:
        raise ValueError(f"length phải là 'short' hoặc 'long'; got {length!r}.")
    clean_slots = _validate_slots(slots)

    with _lock:
        base = "heartbreak-" + _slugify(title)
        slug, n = base, 2
        while (PROJECTS_DIR / slug).exists():
            slug, n = f"{base}-{n}", n + 1

        init_project(slug, title=title, pipeline_type=PIPELINE_TYPE, pipeline_dir=PROJECTS_DIR)
        now = time.time()
        studio: dict[str, Any] = {
            "title": title,
            "idea": idea,
            "length": length,
            "slots": clean_slots,
            "model": dict(DEFAULT_MODEL),
            "cold_open": None,
            "clips": [],
            "music_plan": [],
            "caption_hint": "",
            "spent_usd": 0.0,
            "stage": "proposal",
            "created_at": now,
            "updated_at": now,
        }
        _save_studio(slug, studio)

        brief = _research_brief(studio)
        _save_artifact(slug, "research_brief", brief)
        _write_ckpt(slug, "research", "completed", {"research_brief": brief})

        packet = _proposal_packet(studio, approved=False)
        _save_artifact(slug, "proposal_packet", packet)
        _write_ckpt(slug, "proposal", "awaiting_human", {"proposal_packet": packet})

    return get_episode(slug)


def write_prompts(slug: str, notes: str = "") -> dict[str, Any]:
    """Write the clip prompts with PiAPI chat (~$0.01) and advance the pipeline.

    The user's click is the human approval for ``proposal``/``script``/
    ``scene_plan`` (the real money gate stays on ``assets``); every prompt
    remains editable afterwards through :func:`save_prompt`.
    """
    studio = _load_studio(slug)
    mapping = _reference_mapping(studio)

    from backlot import social
    from tools import piapi_client

    api_key = piapi_client.get_api_key()
    if not api_key:
        raise RuntimeError("PIAPI_API_KEY / PIAPI_KEY chưa được đặt — prompt được viết qua PiAPI chat.")
    model = os.environ.get("BACKLOT_COPY_MODEL") or social.DEFAULT_MODEL
    messages = [
        {"role": "system", "content": _system_prompt()},
        {"role": "user", "content": _user_message(studio, mapping, str(notes or ""))},
    ]
    reply, usage = social._chat(messages, model, api_key)
    plan = _validate_plan(reply, studio, len(mapping))

    with _lock:
        studio = _load_studio(slug)
        previous = {c["id"]: c for c in studio.get("clips") or []}
        clips = []
        for clip in plan["clips"]:
            old = previous.get(clip["id"])
            if old and old.get("prompt") == clip["prompt"]:
                # Untouched prompt: keep its takes instead of orphaning them.
                clip = {**clip, "versions": old.get("versions") or [],
                        "chosen": old.get("chosen"), "status": old.get("status") or "draft"}
            else:
                clip = {**clip, "versions": [], "chosen": None, "status": "draft"}
            clips.append(clip)

        studio.update(clips=clips, cold_open=plan["cold_open"], music_plan=plan["music_plan"],
                      caption_hint=plan["caption_hint"], stage="scene_plan")
        _save_studio(slug, studio)
        for clip in clips:
            _write_clip_file(slug, clip)

        approval = {"approval": "user clicked 'Viết bằng AI' (write_prompts); prompts stay editable via save_prompt"}
        packet = _proposal_packet(studio, approved=True)
        _save_artifact(slug, "proposal_packet", packet)
        _write_ckpt(slug, "proposal", "completed", {"proposal_packet": packet},
                    human_approved=True, metadata=approval)

        script = _script_artifact(studio)
        _save_artifact(slug, "script", script)
        _write_ckpt(slug, "script", "completed", {"script": script},
                    human_approved=True, metadata=approval)

        scene_plan = _scene_plan_artifact(studio)
        _save_artifact(slug, "scene_plan", scene_plan)
        _write_ckpt(slug, "scene_plan", "completed", {"scene_plan": scene_plan},
                    human_approved=True, metadata=approval)

    return {
        "slug": slug,
        "clips": studio["clips"],
        "cold_open": studio["cold_open"],
        "music_plan": studio["music_plan"],
        "caption_hint": studio["caption_hint"],
        "model": model,
        "usage": {k: usage.get(k) for k in ("prompt_tokens", "completion_tokens", "total_tokens") if k in usage},
    }


def _user_message(studio: dict[str, Any], mapping: list[dict[str, str]], notes: str) -> str:
    length = studio.get("length", "short")
    lo, hi = LENGTHS[length]
    lines = [
        f"Tập: {studio['title']}",
        f"Ý tưởng: {studio['idea']}",
        f"Độ dài: {length} — {LENGTH_LABELS[length]}",
        "Tỉ lệ: 9:16 (Facebook Reels). Phim không lời.",
        "",
        "Bộ nhân vật — dùng đúng câu identity này trong prompt, không bịa tạo hình:",
    ]
    for i, m in enumerate(mapping, 1):
        lines.append(f"@image{i} = {m['slot']} ({m['name']}): {m['identity']}")
    lines += [
        "",
        "Mapping ảnh tham chiếu khi tạo video: "
        + ", ".join(f"@image{i} = {m['slot']}" for i, m in enumerate(mapping, 1))
        + f". Chỉ dùng @image1–@image{len(mapping)} trong prompt.",
        "",
        "Quy tắc cold open: giây đầu tiên phải là khoảnh khắc mạnh nhất hoặc tò mò nhất của tập; "
        "kèm một dòng chữ ngắn tối đa 8 từ do người dựng chèn lúc ghép video — không đưa dòng chữ vào prompt.",
        "",
        "Trả về JSON đúng mẫu sau, không thêm văn bản:",
        '{"clips": [{"id": "A", "beats": ["WOO", "DUMP"], "duration": 12, "prompt": "..."}], '
        '"cold_open": {"text": "...", "from_clip": "A", "at": 3.2}, '
        '"music_plan": [{"at": 0, "cue": "happy", "action": "in"}, {"at": 8.9, "cue": null, "action": "cut"}], '
        '"caption_hint": "..."}',
        "",
        f"- clips: {lo}–{hi} clip, id lần lượt A, B, C ...; duration mỗi clip {DURATION_RANGE[0]}–{DURATION_RANGE[1]} giây.",
        f"- beats: một trong {', '.join(BEATS)}.",
        "- music_plan: nhạc rót đúng điểm, không phủ suốt — action là in, cut hoặc swap.",
        "- caption_hint: một câu caption tiếng Việt theo mục 9 của công thức.",
    ]
    if notes.strip():
        lines += ["", f"Ghi chú của người dùng: {notes.strip()}"]
    return "\n".join(lines)


def save_prompt(slug: str, clip_id: str, prompt: Any) -> dict[str, Any]:
    """Manually edit one clip's prompt (studio.json + artifacts/clip<ID>.txt)."""
    studio = _load_studio(slug)
    clip = next((c for c in studio.get("clips") or [] if c.get("id") == clip_id), None)
    if clip is None:
        raise KeyError(f"clip {clip_id} không có trong tập {slug}")
    text = str(prompt or "").strip()
    if not text:
        raise ValueError("Prompt trống.")
    if len(text) > MAX_PROMPT_CHARS:
        raise ValueError(f"Prompt tối đa {MAX_PROMPT_CHARS} ký tự; got {len(text)}.")
    _check_image_refs(text, len(_reference_mapping(studio)), f"clip {clip_id}")

    with _lock:
        studio = _load_studio(slug)
        clip = next((c for c in studio.get("clips") or [] if c.get("id") == clip_id), None)
        if clip is None:
            raise KeyError(f"clip {clip_id} không có trong tập {slug}")
        clip["prompt"] = text
        _save_studio(slug, studio)
        _write_clip_file(slug, clip)
    return clip


def price_table(slug: str) -> dict[str, Any]:
    """Every candidate model priced for THIS episode's clip durations (local math, no API)."""
    studio = _load_studio(slug)
    clips = studio.get("clips") or []
    durations = [c["duration"] for c in clips]
    if not durations:
        raise ValueError("Chưa có prompt clip — hãy viết prompt (bước 2) trước khi xem bảng giá.")

    from tools.video.kling_piapi import KlingPiAPI, _PER_SECOND_PRICING
    from tools.video.seedance_piapi import SeedancePiAPI, _PRICING, _TASK_TYPES

    seed, kling = SeedancePiAPI(), KlingPiAPI()
    clip_length = ", ".join(f"{d}s" for d in durations)
    rows = []
    for variant, label in (("fast", "Seedance 2 fast"), ("standard", "Seedance 2 Pro"),
                           ("mini", "Seedance 2 mini")):
        for resolution in ("480p", "720p"):
            rate = _PRICING[_TASK_TYPES[variant]][resolution]
            total = round(sum(
                seed.estimate_cost({"model_variant": variant, "resolution": resolution, "duration": d})
                for d in durations
            ), 2)
            rows.append({
                "id": f"seedance-{variant}-{resolution}",
                "tool": "seedance_piapi",
                "model": label,
                "model_variant": variant,
                "resolution": resolution,
                "price_per_second": rate,
                "clip_length": clip_length,
                "durations": durations,
                "total_usd": total,
                "default": variant == "fast" and resolution == "720p",
            })
    for mode, resolution, label in (("std", "720p", "Kling 3.0 std"), ("pro", "1080p", "Kling 3.0 pro")):
        rate = _PER_SECOND_PRICING["3.0"][mode]
        total = round(sum(
            kling.estimate_cost({"version": "3.0", "mode": mode, "duration": d}) for d in durations
        ), 2)
        rows.append({
            "id": f"kling-30-{mode}",
            "tool": "kling_piapi",
            "model": label,
            "version": "3.0",
            "mode": mode,
            "resolution": resolution,
            "price_per_second": rate,
            "clip_length": clip_length,
            "durations": durations,
            "total_usd": total,
            "default": False,
        })
    return {
        "slug": slug,
        "length": studio.get("length"),
        "clips": [{"id": c["id"], "duration": c["duration"]} for c in clips],
        "total_seconds": sum(durations),
        "rows": rows,
        "spent_usd": float(studio.get("spent_usd") or 0.0),
        "model": studio.get("model"),
    }


def set_model(slug: str, model_id: str) -> dict[str, Any]:
    """Persist the user's model pick from the price table (M2 — local, no API)."""
    table = price_table(slug)                     # also validates the episode + clips
    row = next((r for r in table["rows"] if r["id"] == model_id), None)
    if row is None:
        raise ValueError(f"model_id không có trong bảng giá: {model_id}")
    with _lock:
        studio = _load_studio(slug)
        if row["tool"] == "seedance_piapi":
            model = {"tool": "seedance_piapi", "model_variant": row["model_variant"],
                     "resolution": row["resolution"]}
        else:
            model = {"tool": "kling_piapi", "version": row["version"], "mode": row["mode"],
                     "resolution": row["resolution"]}
        studio["model"] = model
        studio["model_id"] = row["id"]
        _save_studio(slug, studio)
    return {**studio, "slug": slug}
