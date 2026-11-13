"""Kling (Kuaishou) video generation via PiAPI.

PiAPI exposes Kling through its unified task API:

    POST https://api.piapi.ai/api/v1/task      (create; header X-API-Key)
    GET  https://api.piapi.ai/api/v1/task/{id} (poll; data.status, data.output.video)

Kling image-to-video takes a single first-frame image (``image_url``), not a
multi-image character-reference set like Seedance's ``reference_to_video`` —
there is no @image1..N addressing here. For multi-reference character
consistency or multi-shot montages in one clip, use seedance_piapi instead.

Local reference media is pushed through PiAPI's ephemeral upload endpoint
(see tools/piapi_client.py; 10 MB max, 24h retention, Creator plan or higher).

Docs: https://piapi.ai/docs/kling-api/create-task
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

_VERSIONS = {"4.0", "4.0-flash", "3.0", "3.0-turbo", "2.6", "2.5", "2.1-master", "2.1", "1.6", "1.5"}

# USD per output second (4.0 / 3.0 family) or per video (2.6 and earlier).
_PER_SECOND_PRICING = {
    "4.0": {"std": 0.1667, "pro": 0.25},
    "4.0-flash": {"std": 0.10},
    "3.0": {"std": 0.10, "pro": 0.15},          # +0.05/0.05 if enable_audio
    "3.0-turbo": {"std": 0.13, "pro": 0.19},
}
_PER_VIDEO_PRICING = {
    "1.5": {"std": {5: 0.26, 10: 0.52}, "pro": {5: 0.46, 10: 0.92}},
    "1.6": {"std": {5: 0.26, 10: 0.52}, "pro": {5: 0.46, 10: 0.92}},
    "2.1": {"std": {5: 0.26, 10: 0.52}, "pro": {5: 0.46, 10: 0.92}},
    "2.1-master": {"pro": {5: 0.96, 10: 1.92}},
    "2.5": {"std": {5: 0.20, 10: 0.39}, "pro": {5: 0.33, 10: 0.66}},
    "2.6": {"std": {5: 0.20, 10: 0.39}, "pro": {5: 0.33, 10: 0.66}},
}


class KlingPiAPI(BaseTool):
    name = "kling_piapi"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "video_generation"
    provider = "kling"
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
    agent_skills = ["ai-video-gen"]

    capabilities = ["text_to_video", "image_to_video"]
    supports = {
        "text_to_video": True,
        "image_to_video": True,
        "multiple_reference_images": False,
        "reference_image": True,
        "native_audio": True,
        "cinematic_quality": True,
        "multi_shot": True,   # 3.0 only, via multi_shots
        "aspect_ratio": True,
        "seed": False,
    }
    best_for = [
        "Kling 4.0 / 3.0 when PIAPI_API_KEY is available",
        "fluid, cinematic single-shot motion from one starting frame",
        "first/last-frame image-to-video",
    ]
    not_good_for = [
        "multi-image character-reference consistency (use seedance_piapi reference_to_video)",
        "single-call multi-shot montages with hard cuts beyond 3.0's 6-shot/15s limit",
        "offline generation",
    ]
    fallback_tools = ["seedance_piapi", "kling_video", "kling_official_video"]
    quality_score = 0.9

    input_schema = {
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {"type": "string", "description": "Up to 2500 chars. Ignored when multi_shots is used."},
            "negative_prompt": {"type": "string", "description": "Up to 1000 chars. Not accepted by 4.0/4.0-flash."},
            "version": {
                "type": "string", "enum": sorted(_VERSIONS), "default": "2.6",
                "description": "Kling model version.",
            },
            "mode": {
                "type": "string", "enum": ["std", "pro"], "default": "std",
                "description": "std=720p, pro=1080p. 4.0-flash is std only; 2.1-master is pro only.",
            },
            "duration": {
                "type": "integer", "default": 5,
                "description": "Seconds. 4.0: 3-30. 4.0-flash: 3-20. 3.0/3.0-turbo: 3-15 (default 3). 2.6 and earlier: 5 or 10.",
            },
            "aspect_ratio": {
                "type": "string", "enum": ["16:9", "9:16", "1:1", "21:9"], "default": "16:9",
                "description": "21:9 is 4.0/4.0-flash only; other versions fall back to 16:9 for unsupported values.",
            },
            "image_url": {"type": "string", "description": "First frame URL. Setting it makes this image-to-video."},
            "image_path": {"type": "string", "description": "Local first frame (auto-uploaded)."},
            "image_tail_url": {"type": "string", "description": "Last frame URL. Requires image_url/image_path. Not on 4.0-flash."},
            "image_tail_path": {"type": "string", "description": "Local last frame (auto-uploaded)."},
            "enable_audio": {
                "type": "boolean", "default": False,
                "description": "Native audio. 3.0 (std/pro) or 2.6-and-earlier (pro only). Not on 3.0-turbo/4.0/4.0-flash.",
            },
            "multi_shots": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string"},
                        "duration": {"type": "integer", "default": 3, "description": "1-14s."},
                    },
                    "required": ["prompt"],
                },
                "description": "3.0 only. Up to 6 shots, 15s total. Ignores top-level prompt/duration.",
            },
            "poll_timeout_seconds": {"type": "integer", "default": 3600},
            "output_path": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=500, network_required=True)
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=["rate_limit", "timeout"])
    idempotency_key_fields = ["prompt", "version", "mode", "duration", "image_url"]
    side_effects = ["writes video file to output_path", "calls PiAPI API", "uploads local reference media to PiAPI"]
    user_visible_verification = [
        "Watch generated clip for motion coherence, audio sync (if enabled), and visual quality"
    ]

    # ------------------------------------------------------------------ helpers

    def _get_api_key(self) -> str | None:
        return piapi_client.get_api_key()

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE if self._get_api_key() else ToolStatus.UNAVAILABLE

    @staticmethod
    def _version(inputs: dict[str, Any]) -> str:
        version = inputs.get("version", "2.6")
        if version not in _VERSIONS:
            raise ValueError(f"Unknown version {version!r}; expected one of {sorted(_VERSIONS)}")
        return version

    @staticmethod
    def _duration(inputs: dict[str, Any], version: str) -> int:
        raw = inputs.get("duration", 5)
        secs = int(raw)
        if version in ("4.0",):
            lo, hi = 3, 30
        elif version == "4.0-flash":
            lo, hi = 3, 20
        elif version in ("3.0", "3.0-turbo"):
            lo, hi = 3, 15
        else:
            if secs not in (5, 10):
                raise ValueError(f"Kling {version} duration must be 5 or 10s; got {secs}")
            return secs
        if not lo <= secs <= hi:
            raise ValueError(f"Kling {version} duration must be {lo}-{hi}s; got {secs}")
        return secs

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        try:
            version = self._version(inputs)
            secs = self._duration(inputs, version)
        except ValueError:
            return 0.0
        mode = inputs.get("mode", "std")
        if version in _PER_SECOND_PRICING:
            rate = _PER_SECOND_PRICING[version].get(mode)
            if rate is None:
                return 0.0
            total = rate * secs
            if version == "3.0" and inputs.get("enable_audio"):
                total += 0.05 * secs
            return round(total, 2)
        table = _PER_VIDEO_PRICING.get(version, {}).get(mode, {})
        price = table.get(secs, 0.0)
        if version == "2.6" and inputs.get("enable_audio"):
            price *= 2
        return round(price, 2)

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return 180.0

    def _upload(self, local_path: str, api_key: str) -> str:
        return piapi_client.upload(local_path, api_key)

    def _build_payload(self, inputs: dict[str, Any], api_key: str) -> dict[str, Any]:
        version = self._version(inputs)
        mode = inputs.get("mode", "std")
        if mode == "pro" and version == "4.0-flash":
            raise ValueError("4.0-flash supports mode 'std' only")
        if mode == "std" and version == "2.1-master":
            raise ValueError("2.1-master supports mode 'pro' only")

        data: dict[str, Any] = {"version": version, "mode": mode}

        multi_shots = inputs.get("multi_shots")
        if multi_shots:
            if version != "3.0":
                raise ValueError("multi_shots is only available for version 3.0")
            if len(multi_shots) > 6:
                raise ValueError(f"multi_shots accepts at most 6 shots; got {len(multi_shots)}")
            total = sum(int(s.get("duration", 3)) for s in multi_shots)
            if total > 15:
                raise ValueError(f"multi_shots total duration must be <=15s; got {total}")
            data["multi_shots"] = [
                {"prompt": s["prompt"], "duration": int(s.get("duration", 3))} for s in multi_shots
            ]
        else:
            prompt = inputs.get("prompt", "")
            if len(prompt) > 2500:
                raise ValueError(f"Prompt is {len(prompt)} chars; PiAPI Kling max is 2500")
            data["prompt"] = prompt
            data["duration"] = self._duration(inputs, version)

        negative = inputs.get("negative_prompt")
        if negative:
            if version in ("4.0", "4.0-flash"):
                raise ValueError("negative_prompt is not accepted by 4.0 / 4.0-flash")
            if len(negative) > 1000:
                raise ValueError(f"negative_prompt is {len(negative)} chars; PiAPI Kling max is 1000")
            data["negative_prompt"] = negative

        aspect = inputs.get("aspect_ratio", "16:9")
        if aspect == "21:9" and version not in ("4.0", "4.0-flash"):
            raise ValueError("aspect_ratio 21:9 is only available on 4.0 / 4.0-flash")
        data["aspect_ratio"] = aspect

        image_url = inputs.get("image_url") or (
            self._upload(inputs["image_path"], api_key) if inputs.get("image_path") else None
        )
        if image_url:
            data["image_url"] = image_url

        tail_url = inputs.get("image_tail_url") or (
            self._upload(inputs["image_tail_path"], api_key) if inputs.get("image_tail_path") else None
        )
        if tail_url:
            if not image_url:
                raise ValueError("image_tail_url/image_tail_path requires image_url/image_path")
            if version == "4.0-flash":
                raise ValueError("image_tail_url is not supported on 4.0-flash")
            if version not in ("4.0",) and mode != "pro":
                raise ValueError(f"image_tail_url on Kling {version} requires mode 'pro'")
            data["image_tail_url"] = tail_url

        if inputs.get("enable_audio"):
            if version in ("3.0-turbo", "4.0", "4.0-flash"):
                raise ValueError(f"enable_audio is not accepted by Kling {version}")
            if version not in ("3.0",) and mode != "pro":
                raise ValueError(f"enable_audio on Kling {version} requires mode 'pro'")
            data["enable_audio"] = True

        task_type = "video_generation"
        return {"model": "kling", "task_type": task_type, "input": data}

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
            return ToolResult(success=False, error=f"Invalid Kling (PiAPI) request: {e}")
        except Exception as e:  # upload/network failures
            return ToolResult(success=False, error=f"Kling (PiAPI) reference upload failed: {e}")

        version = payload["input"]["version"]
        timeout_s = int(inputs.get("poll_timeout_seconds", 3600))
        task_id = None

        def _remember(tid: str) -> None:
            nonlocal task_id
            task_id = tid

        try:
            task = piapi_client.run_task(
                payload, api_key, label="Kling", timeout_s=timeout_s, on_task_id=_remember
            )
            output = task.get("output") or {}
            video_url = output.get("video") or output.get("video_url")
            if not video_url:
                return ToolResult(success=False, error=f"PiAPI task {task_id} completed without a video URL: {output}")

            video = requests.get(video_url, timeout=300)
            video.raise_for_status()
            output_path = Path(inputs.get("output_path", "kling_piapi_output.mp4"))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(video.content)
        except Exception as e:
            suffix = f" (task_id={task_id})" if task_id and task_id not in str(e) else ""
            return ToolResult(success=False, error=f"Kling (PiAPI) video generation failed{suffix}: {e}")

        from tools.video._shared import probe_output

        probed = probe_output(output_path)
        usage = (task.get("meta") or {}).get("usage") or {}
        _write_sidecar(output_path, {
            "prompt": payload["input"].get("prompt", ""),
            "provider": "kling",
            "gateway": "piapi",
            "model": f"kling-{version}",
            "task_id": task_id,
            "resolution": "1080p" if payload["input"]["mode"] == "pro" else "720p",
            "aspect_ratio": payload["input"].get("aspect_ratio"),
            "duration_seconds": probed.get("duration_seconds", payload["input"].get("duration")),
            "reference_image": payload["input"].get("image_url"),
            "cost_usd": self.estimate_cost(inputs),
            "created_at": time.time(),
        })
        return ToolResult(
            success=True,
            data={
                "provider": "kling",
                "gateway": "piapi",
                "model": f"kling-{version}",
                "task_id": task_id,
                "prompt": inputs.get("prompt", ""),
                "version": version,
                "mode": payload["input"]["mode"],
                "aspect_ratio": payload["input"].get("aspect_ratio"),
                "duration_requested": payload["input"].get("duration"),
                "piapi_usage": usage,
                "output": str(output_path),
                "output_path": str(output_path),
                "format": "mp4",
                **probed,
            },
            artifacts=[str(output_path)],
            cost_usd=self.estimate_cost(inputs),
            duration_seconds=round(time.time() - start, 2),
            model=f"kling-{version}",
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
