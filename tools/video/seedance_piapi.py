"""Seedance 2.0 / 2.5 (ByteDance) video generation via PiAPI.

PiAPI exposes Seedance through its unified task API:

    POST https://api.piapi.ai/api/v1/task      (create; header X-API-Key)
    GET  https://api.piapi.ai/api/v1/task/{id} (poll; data.status, data.output.video)

Local reference media is pushed through PiAPI's ephemeral upload endpoint
(see tools/piapi_client.py; 10 MB max, 24h retention,
Creator plan or higher).

Docs: https://piapi.ai/docs/seedance-api/seedance-2
      https://piapi.ai/blogs/seedance-2-5-api-specifications
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)
from tools import piapi_client


# model_variant -> PiAPI task_type (strict content policy).
_TASK_TYPES = {
    "2.5": "seedance-2.5",
    "standard": "seedance-2",
    "fast": "seedance-2-fast",
    "mini": "seedance-2-mini",
}

# USD per output second, by task_type and resolution (PiAPI published pricing).
_PRICING = {
    "seedance-2.5": {"480p": 0.30, "720p": 0.60},
    "seedance-2": {"480p": 0.10, "720p": 0.20, "1080p": 0.50},
    "seedance-2-fast": {"480p": 0.048, "720p": 0.096},
    "seedance-2-mini": {"480p": 0.042, "720p": 0.084},
    "seedance-2-less-restriction": {"480p": 0.11, "720p": 0.22, "1080p": 0.55},
    "seedance-2-fast-less-restriction": {"480p": 0.053, "720p": 0.106},
    "seedance-2-mini-less-restriction": {"480p": 0.046, "720p": 0.092},
}

# OpenMontage operation -> PiAPI input.mode
_MODES = {
    "text_to_video": "text_to_video",
    "image_to_video": "first_last_frames",
    "reference_to_video": "omni_reference",
}



class SeedancePiAPI(BaseTool):
    name = "seedance_piapi"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "video_generation"
    provider = "seedance"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = []
    install_instructions = (
        "Set PIAPI_API_KEY to your PiAPI API key.\n"
        "  Get one from your PiAPI workspace at https://piapi.ai\n"
        "  (Uploading local reference images needs a PiAPI Creator plan or higher;\n"
        "   public image URLs work on any plan.)"
    )
    agent_skills = ["seedance-2-0", "ai-video-gen"]

    capabilities = ["text_to_video", "image_to_video", "reference_to_video"]
    supports = {
        "text_to_video": True,
        "image_to_video": True,
        "reference_to_video": True,
        "multiple_reference_images": True,
        "reference_image": True,
        "native_audio": True,
        "cinematic_quality": True,
        "camera_direction": True,
        "lip_sync": True,
        "multi_shot": True,
        "aspect_ratio": True,
        "seed": False,
    }
    best_for = [
        "Seedance 2.0 / 2.5 when PIAPI_API_KEY is available",
        "Seedance 2.5 (longer clips up to 30s) — not offered by the fal.ai/Replicate wrappers",
        "cinematic clips with native synchronized audio and director-level camera control",
        "reference-conditioned generation (up to 9 images + 3 video clips + 3 audio clips, @image1 tags)",
        "consistent character identity from reference images",
    ]
    not_good_for = ["offline generation", "budget-constrained projects", "deterministic re-renders (no seed)"]
    fallback_tools = ["seedance_video", "seedance_replicate", "higgsfield_video", "kling_video"]
    quality_score = 0.95

    input_schema = {
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Max 4000 chars. Reference media with @image1, @video1, @audio1 (1-based).",
            },
            "operation": {
                "type": "string",
                "enum": ["text_to_video", "image_to_video", "reference_to_video"],
                "default": "text_to_video",
                "description": "image_to_video = first/last frame; reference_to_video = omni_reference.",
            },
            "model_variant": {
                "type": "string",
                "enum": ["2.5", "standard", "fast", "mini"],
                "default": "standard",
                "description": "2.5 = Seedance 2.5; standard = Seedance 2 Pro; fast / mini = cheaper Seedance 2 tiers.",
            },
            "less_restriction": {
                "type": "boolean",
                "default": False,
                "description": "Use the less-restrictive Seedance 2 task types (not available for 2.5).",
            },
            "duration": {
                "type": ["integer", "string"],
                "default": 5,
                "description": "Seconds. Seedance 2: 4-15. Seedance 2.5: 1-30.",
            },
            "aspect_ratio": {
                "type": "string",
                "enum": ["auto", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"],
                "default": "16:9",
                "description": "'auto' is only valid for image_to_video.",
            },
            "resolution": {
                "type": "string",
                "enum": ["480p", "720p", "1080p"],
                "default": "720p",
                "description": "1080p only on Seedance 2 standard tiers.",
            },
            "generate_audio": {
                "type": "boolean",
                "default": True,
                "description": "Generate synchronized audio (speech, SFX, ambient).",
            },
            "image_url": {"type": "string", "description": "First frame URL for image_to_video."},
            "image_path": {"type": "string", "description": "Local first frame for image_to_video (auto-uploaded)."},
            "end_image_url": {"type": "string", "description": "Optional last frame URL for image_to_video."},
            "end_image_path": {"type": "string", "description": "Optional local last frame (auto-uploaded)."},
            "reference_image_urls": {"type": "array", "items": {"type": "string"}, "description": "Up to 9."},
            "reference_image_paths": {"type": "array", "items": {"type": "string"}, "description": "Local, auto-uploaded."},
            "reference_video_urls": {"type": "array", "items": {"type": "string"}, "description": "Up to 3 (mp4/mov)."},
            "reference_video_paths": {"type": "array", "items": {"type": "string"}, "description": "Local mp4, auto-uploaded."},
            "reference_audio_urls": {"type": "array", "items": {"type": "string"}, "description": "Up to 3 (mp3/wav)."},
            "reference_audio_paths": {"type": "array", "items": {"type": "string"}, "description": "Local, auto-uploaded."},
            "characters": {
                "type": "array", "items": {"type": "string"},
                "description": "Character library ids (characters/<id>). Their primary reference images become "
                               "@image1..@imageN (before other reference images) and an [identity_lock] block is "
                               "prepended to the prompt. reference_to_video only.",
            },
            "character_refs": {
                "type": "string", "enum": ["set", "full", "primary"], "default": "set",
                "description": "'set' = primary + front face + back (3 images per character); 'full' = up to 6 "
                               "(+ three-quarter face, side, profile face); 'primary' = primary image only.",
            },
            "character_identity_block": {
                "type": "boolean", "default": True,
                "description": "Prepend the library's identity text. Turn off if the prompt already describes the characters.",
            },
            "poll_timeout_seconds": {
                "type": "integer",
                "default": 3600,
                "description": "Give up polling after this long. PiAPI queues can run long at peak hours.",
            },
            "output_path": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=500, network_required=True
    )
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=["rate_limit", "timeout"])
    idempotency_key_fields = ["prompt", "model_variant", "operation", "duration", "resolution"]
    side_effects = ["writes video file to output_path", "calls PiAPI API", "uploads local reference media to PiAPI"]
    user_visible_verification = [
        "Watch generated clip for motion coherence, audio sync, character consistency, and visual quality"
    ]

    # ------------------------------------------------------------------ helpers

    def _get_api_key(self) -> str | None:
        return piapi_client.get_api_key()

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE if self._get_api_key() else ToolStatus.UNAVAILABLE

    @staticmethod
    def _task_type(inputs: dict[str, Any]) -> str:
        variant = inputs.get("model_variant", "standard")
        if variant not in _TASK_TYPES:
            raise ValueError(f"Unknown model_variant {variant!r}; expected one of {sorted(_TASK_TYPES)}")
        task_type = _TASK_TYPES[variant]
        if inputs.get("less_restriction"):
            if variant == "2.5":
                raise ValueError("less_restriction is not available for Seedance 2.5")
            task_type = f"{task_type}-less-restriction"
        return task_type

    @staticmethod
    def _duration(inputs: dict[str, Any], task_type: str) -> int:
        raw = inputs.get("duration", 5)
        if raw in (None, "auto"):
            raw = 5
        secs = int(raw)
        lo, hi = (1, 30) if task_type == "seedance-2.5" else (4, 15)
        if not lo <= secs <= hi:
            raise ValueError(f"{task_type} duration must be {lo}-{hi}s; got {secs}")
        return secs

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        try:
            task_type = self._task_type(inputs)
            secs = self._duration(inputs, task_type)
        except ValueError:
            return 0.0
        resolution = inputs.get("resolution", "720p")
        rate = _PRICING.get(task_type, {}).get(resolution, 0.0)
        return round(rate * secs, 2)

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return 90.0 if inputs.get("model_variant") in ("fast", "mini") else 240.0

    def _upload(self, local_path: str, api_key: str) -> str:
        return piapi_client.upload(local_path, api_key)

    def _build_payload(self, inputs: dict[str, Any], api_key: str) -> dict[str, Any]:
        task_type = self._task_type(inputs)
        operation = inputs.get("operation", "text_to_video")
        if operation not in _MODES:
            raise ValueError(f"Unknown operation {operation!r}; expected one of {sorted(_MODES)}")
        mode = _MODES[operation]
        resolution = inputs.get("resolution", "720p")
        if resolution not in _PRICING[task_type]:
            raise ValueError(
                f"{task_type} does not support {resolution}; use one of {sorted(_PRICING[task_type])}"
            )
        prompt = inputs["prompt"]
        character_paths: list[str] = []
        if inputs.get("characters"):
            if mode != "omni_reference":
                raise ValueError("characters need operation 'reference_to_video'")
            from lib import characters as charlib

            slugs = list(inputs["characters"])
            ref_mode = inputs.get("character_refs", "set")
            try:
                character_paths = charlib.reference_paths(slugs, ref_mode)
            except KeyError as e:
                raise ValueError(str(e).strip("'\""))
            if inputs.get("character_identity_block", True):
                prompt = charlib.identity_block(slugs, mode=ref_mode) + "\n\n" + prompt
        if len(prompt) > 4000:
            raise ValueError(f"Prompt is {len(prompt)} chars; PiAPI Seedance max is 4000")

        data: dict[str, Any] = {
            "prompt": prompt,
            "mode": mode,
            "duration": self._duration(inputs, task_type),
            "resolution": resolution,
            "audio": bool(inputs.get("generate_audio", True)),
        }
        aspect = inputs.get("aspect_ratio", "16:9")
        if aspect == "auto":
            if mode != "first_last_frames":
                raise ValueError("aspect_ratio 'auto' is only valid for image_to_video")
        if aspect:
            data["aspect_ratio"] = aspect

        def collect(url_key: str, path_key: str) -> list[str]:
            urls = list(inputs.get(url_key) or [])
            for p in inputs.get(path_key) or []:
                urls.append(self._upload(p, api_key))
            return urls

        if mode == "first_last_frames":
            frames: list[str] = []
            first = inputs.get("image_url") or (
                self._upload(inputs["image_path"], api_key) if inputs.get("image_path") else None
            )
            if first:
                frames.append(first)
            last = inputs.get("end_image_url") or (
                self._upload(inputs["end_image_path"], api_key) if inputs.get("end_image_path") else None
            )
            if last:
                frames.append(last)
            if not frames:
                raise ValueError("image_to_video needs image_url or image_path")
            data["image_urls"] = frames

        elif mode == "omni_reference":
            # Library characters come first so they are @image1..@imageN.
            images = [self._upload(p, api_key) for p in character_paths]
            images += collect("reference_image_urls", "reference_image_paths")
            videos = collect("reference_video_urls", "reference_video_paths")
            audios = collect("reference_audio_urls", "reference_audio_paths")
            if len(images) > 9:
                raise ValueError(f"omni_reference accepts at most 9 images; got {len(images)}")
            if len(videos) > 3:
                raise ValueError(f"omni_reference accepts at most 3 videos; got {len(videos)}")
            if len(audios) > 3:
                raise ValueError(f"omni_reference accepts at most 3 audio clips; got {len(audios)}")
            total = len(images) + len(videos) + len(audios)
            max_total = 12 if task_type == "seedance-2.5" else 15
            if not 1 <= total <= max_total:
                raise ValueError(f"omni_reference needs 1-{max_total} references in total; got {total}")
            if audios and not (images or videos):
                raise ValueError("Audio-only references are rejected; add at least one image or video")
            if images:
                data["image_urls"] = images
            if videos:
                data["video_urls"] = videos
            if audios:
                data["audio_urls"] = audios

        return {"model": "seedance", "task_type": task_type, "input": data}

    # ------------------------------------------------------------------ execute

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        api_key = self._get_api_key()
        if not api_key:
            return ToolResult(success=False, error="PIAPI_API_KEY not set. " + self.install_instructions)

        import requests

        start = time.time()
        try:
            payload = self._build_payload(inputs, api_key)
        except (ValueError, FileNotFoundError) as e:
            return ToolResult(success=False, error=f"Invalid Seedance (PiAPI) request: {e}")
        except Exception as e:  # upload/network failures
            return ToolResult(success=False, error=f"Seedance (PiAPI) reference upload failed: {e}")

        task_type = payload["task_type"]
        timeout_s = int(inputs.get("poll_timeout_seconds", 3600))
        task_id = None

        def _remember(tid: str) -> None:
            nonlocal task_id
            task_id = tid

        try:
            task = piapi_client.run_task(
                payload, api_key, label="Seedance", timeout_s=timeout_s, on_task_id=_remember
            )
            output = task.get("output") or {}
            video_url = output.get("video") or output.get("video_url")
            if not video_url:
                return ToolResult(success=False, error=f"PiAPI task {task_id} completed without a video URL: {output}")

            video = requests.get(video_url, timeout=300)
            video.raise_for_status()
            output_path = Path(inputs.get("output_path", "seedance_piapi_output.mp4"))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(video.content)
        except Exception as e:
            suffix = f" (task_id={task_id})" if task_id and task_id not in str(e) else ""
            return ToolResult(success=False, error=f"Seedance (PiAPI) video generation failed{suffix}: {e}")

        from tools.video._shared import probe_output

        probed = probe_output(output_path)
        usage = (task.get("meta") or {}).get("usage") or {}
        _write_sidecar(output_path, {
            "prompt": payload["input"]["prompt"],
            "characters": list(inputs.get("characters") or []),
            "provider": "seedance",
            "gateway": "piapi",
            "model": task_type,
            "task_id": task_id,
            "operation": inputs.get("operation", "text_to_video"),
            "resolution": payload["input"]["resolution"],
            "aspect_ratio": payload["input"].get("aspect_ratio"),
            "duration_seconds": probed.get("duration_seconds", payload["input"]["duration"]),
            "reference_images": payload["input"].get("image_urls", []),
            "cost_usd": self.estimate_cost(inputs),
            "created_at": time.time(),
        })
        return ToolResult(
            success=True,
            data={
                "provider": "seedance",
                "gateway": "piapi",
                "model": task_type,
                "task_id": task_id,
                "prompt": inputs["prompt"],
                "operation": inputs.get("operation", "text_to_video"),
                "variant": inputs.get("model_variant", "standard"),
                "aspect_ratio": payload["input"].get("aspect_ratio"),
                "resolution": payload["input"]["resolution"],
                "duration_requested": payload["input"]["duration"],
                "generate_audio": payload["input"]["audio"],
                "piapi_usage": usage,
                "output": str(output_path),
                "output_path": str(output_path),
                "format": "mp4",
                **probed,
            },
            artifacts=[str(output_path)],
            cost_usd=self.estimate_cost(inputs),
            duration_seconds=round(time.time() - start, 2),
            model=task_type,
        )



def _write_sidecar(video_path: Path, meta: dict[str, Any]) -> None:
    """Write ``<stem>.meta.json`` next to the video (prompt provenance for Backlot's gallery).

    Best effort: a sidecar failure must never fail a paid, successful generation.
    """
    import json

    try:
        sidecar = video_path.with_name(f"{video_path.stem}.meta.json")
        sidecar.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
