"""Luma Dream Machine (Ray2) video generation via PiAPI.

    POST https://api.piapi.ai/api/v1/task
    {"model": "luma", "task_type": "video_generation",
     "input": {"prompt", "model": "ray-v2", "duration": 5|9,
               "aspect_ratio": "9:16"|"3:4"|"1:1"|"4:3"|"16:9"|"21:9",
               "start_image"?, "end_image"?, "loop"},
     "config": {"service_mode": "public"}}

Result: ``data.output.video`` (MP4, no audio). Priced per video, charged on
success: 5 s $0.20, 9 s $0.40. Only Ray2 is served (Ray1 retired, Ray3 not yet).

Image-to-video takes a start frame and/or an end frame (keyframe interpolation);
there is no multi-image character-reference set.

Docs: https://piapi.ai/docs/dream-machine/create-task
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
from tools.video.piapi_video_common import find_video_url, write_sidecar

_PRICING = {5: 0.20, 9: 0.40}   # duration (s) -> USD per video
_MODELS = ("ray-v2",)
_ASPECT_RATIOS = ("9:16", "3:4", "1:1", "4:3", "16:9", "21:9")


class LumaPiAPI(BaseTool):
    name = "luma_piapi"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "video_generation"
    provider = "luma"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = []
    install_instructions = (
        "Set PIAPI_API_KEY to your PiAPI API key.\n"
        "  Get one from your PiAPI workspace at https://piapi.ai\n"
        "  (Uploading local images needs a PiAPI Creator plan or higher;\n"
        "   public image URLs work on any plan.)"
    )
    agent_skills = ["ai-video-gen"]

    capabilities = ["text_to_video", "image_to_video"]
    supports = {
        "text_to_video": True,
        "image_to_video": True,
        "end_frame": True,
        "loop": True,
        "multiple_reference_images": False,
        "reference_image": True,
        "native_audio": False,
        "cinematic_quality": True,
        "multi_shot": False,
        "aspect_ratio": True,
        "seed": False,
    }
    best_for = [
        "cheap flat-priced clips ($0.20 per 5 s, $0.40 per 9 s)",
        "start-frame to end-frame transitions and seamless loops",
        "any aspect ratio from 9:16 to 21:9 for text-to-video",
    ]
    not_good_for = [
        "clips that need native audio (Ray2 is silent)",
        "durations other than 5 or 9 s",
        "multi-image character-reference consistency (use seedance_piapi reference_to_video)",
    ]
    fallback_tools = ["hailuo_piapi", "kling_piapi", "wan_piapi"]
    quality_score = 0.8

    input_schema = {
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {"type": "string"},
            "model": {"type": "string", "enum": list(_MODELS), "default": "ray-v2"},
            "duration": {"type": "integer", "enum": sorted(_PRICING), "default": 5},
            "aspect_ratio": {"type": "string", "enum": list(_ASPECT_RATIOS), "default": "16:9"},
            "loop": {"type": "boolean", "default": False, "description": "Make the clip loop seamlessly."},
            "image_url": {"type": "string", "description": "Start frame URL (image-to-video)."},
            "image_path": {"type": "string", "description": "Local start frame (auto-uploaded)."},
            "end_image_url": {"type": "string", "description": "End frame URL."},
            "end_image_path": {"type": "string", "description": "Local end frame (auto-uploaded)."},
            "poll_timeout_seconds": {"type": "integer", "default": 3600},
            "output_path": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=500, network_required=True)
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=["rate_limit", "timeout"])
    idempotency_key_fields = ["prompt", "model", "duration", "aspect_ratio", "loop", "image_url", "end_image_url"]
    side_effects = ["writes video file to output_path", "calls PiAPI API", "uploads local reference media to PiAPI"]
    user_visible_verification = ["Watch generated clip for motion coherence and visual quality"]

    # ------------------------------------------------------------------ helpers

    def _get_api_key(self) -> str | None:
        return piapi_client.get_api_key()

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE if self._get_api_key() else ToolStatus.UNAVAILABLE

    @staticmethod
    def _spec(inputs: dict[str, Any]) -> tuple[str, int, str]:
        model = inputs.get("model", "ray-v2")
        if model not in _MODELS:
            raise ValueError(f"Luma model must be one of {list(_MODELS)}; got {model!r}")
        secs = int(inputs.get("duration", 5))
        if secs not in _PRICING:
            raise ValueError(f"Luma duration must be 5 or 9s; got {secs}")
        aspect = str(inputs.get("aspect_ratio", "16:9"))
        if aspect not in _ASPECT_RATIOS:
            raise ValueError(f"Luma aspect_ratio must be one of {list(_ASPECT_RATIOS)}; got {aspect!r}")
        return model, secs, aspect

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        try:
            return _PRICING[self._spec(inputs)[1]]
        except ValueError:
            return 0.0

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return 120.0

    def _image(self, inputs: dict[str, Any], url_key: str, path_key: str, api_key: str) -> str | None:
        if inputs.get(url_key):
            return inputs[url_key]
        if inputs.get(path_key):
            return piapi_client.upload(inputs[path_key], api_key)
        return None

    def _build_payload(self, inputs: dict[str, Any], api_key: str) -> dict[str, Any]:
        model, secs, aspect = self._spec(inputs)
        prompt = inputs.get("prompt", "")
        if not prompt:
            raise ValueError("prompt is required")
        data: dict[str, Any] = {
            "prompt": prompt,
            "model": model,
            "duration": secs,
            "aspect_ratio": aspect,
            "loop": bool(inputs.get("loop", False)),
        }
        start = self._image(inputs, "image_url", "image_path", api_key)
        if start:
            data["start_image"] = start
        end = self._image(inputs, "end_image_url", "end_image_path", api_key)
        if end:
            data["end_image"] = end
        return {
            "model": "luma",
            "task_type": "video_generation",
            "input": data,
            "config": {"service_mode": "public"},
        }

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
            return ToolResult(success=False, error=f"Invalid Luma (PiAPI) request: {e}")
        except Exception as e:  # upload/network failures
            return ToolResult(success=False, error=f"Luma (PiAPI) reference upload failed: {e}")

        model_id = f"luma-{payload['input']['model']}"
        timeout_s = int(inputs.get("poll_timeout_seconds", 3600))
        task_id = None

        def _remember(tid: str) -> None:
            nonlocal task_id
            task_id = tid

        try:
            task = piapi_client.run_task(payload, api_key, label="Luma", timeout_s=timeout_s, on_task_id=_remember)
            output = task.get("output") or {}
            video_url = find_video_url(output)
            if not video_url:
                return ToolResult(success=False, error=f"PiAPI task {task_id} completed without a video URL: {output}")
            video = requests.get(video_url, timeout=300)
            video.raise_for_status()
            output_path = Path(inputs.get("output_path", "luma_piapi_output.mp4"))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(video.content)
        except Exception as e:
            suffix = f" (task_id={task_id})" if task_id and task_id not in str(e) else ""
            return ToolResult(success=False, error=f"Luma (PiAPI) video generation failed{suffix}: {e}")

        from tools.video._shared import probe_output

        probed = probe_output(output_path)
        cost = self.estimate_cost(inputs)
        write_sidecar(output_path, {
            "prompt": payload["input"]["prompt"],
            "provider": "luma",
            "gateway": "piapi",
            "model": model_id,
            "task_id": task_id,
            "aspect_ratio": payload["input"]["aspect_ratio"],
            "duration_seconds": probed.get("duration_seconds", payload["input"]["duration"]),
            "reference_image": payload["input"].get("start_image"),
            "end_image": payload["input"].get("end_image"),
            "cost_usd": cost,
            "created_at": time.time(),
        })
        return ToolResult(
            success=True,
            data={
                "provider": "luma",
                "gateway": "piapi",
                "model": model_id,
                "task_id": task_id,
                "prompt": payload["input"]["prompt"],
                "aspect_ratio": payload["input"]["aspect_ratio"],
                "duration_requested": payload["input"]["duration"],
                "piapi_usage": (task.get("meta") or {}).get("usage") or {},
                "output": str(output_path),
                "output_path": str(output_path),
                "format": "mp4",
                **probed,
            },
            artifacts=[str(output_path)],
            cost_usd=cost,
            duration_seconds=round(time.time() - start, 2),
            model=model_id,
        )
