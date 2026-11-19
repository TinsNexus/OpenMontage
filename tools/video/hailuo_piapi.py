"""MiniMax Hailuo 2.3 video generation via PiAPI.

    POST https://api.piapi.ai/api/v1/task
    {"model": "hailuo", "task_type": "video_generation",
     "input": {"prompt", "model": "v2.3"|"v2.3-fast", "image_url"?, "expand_prompt",
               "duration": 6|10, "resolution": 768|1080},
     "config": {"service_mode": "public"}}

Result: ``data.output.video`` (MP4 with audio). 1080p is 6 s only. Prices (USD,
charged on success): v2.3 768p 6s $0.23, 10s $0.45, 1080p 6s $0.40;
v2.3-fast 768p 6s $0.16, 10s $0.26, 1080p 6s $0.26.

Image-to-video takes ONE start image (jpg/png, 300-4096 px, aspect 2:5-5:2).

Docs: https://piapi.ai/docs/hailuo-api/generate-video
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
from tools.video.piapi_video_common import check_image_aspect, find_video_url, write_sidecar

# (model, resolution, duration) -> USD per video
_PRICING = {
    ("v2.3", 768, 6): 0.23,
    ("v2.3", 768, 10): 0.45,
    ("v2.3", 1080, 6): 0.40,
    ("v2.3-fast", 768, 6): 0.16,
    ("v2.3-fast", 768, 10): 0.26,
    ("v2.3-fast", 1080, 6): 0.26,
}
_MODELS = ("v2.3", "v2.3-fast")
_RESOLUTIONS = {"768p": 768, "1080p": 1080}
_IMAGE_ASPECT = (0.4, 2.5)   # 2:5 .. 5:2
_PROMPT_MAX = 2000


class HailuoPiAPI(BaseTool):
    name = "hailuo_piapi"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "video_generation"
    provider = "hailuo"
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
        "multiple_reference_images": False,
        "reference_image": True,
        "native_audio": True,
        "cinematic_quality": True,
        "multi_shot": False,
        "aspect_ratio": False,
        "seed": False,
    }
    best_for = [
        "cheap 1080p 6-second clips (v2.3-fast $0.26, v2.3 $0.40)",
        "expressive human motion and physics from one start frame",
    ]
    not_good_for = [
        "1080p clips longer than 6 s",
        "choosing an aspect ratio for text-to-video",
        "multi-image character-reference consistency (use seedance_piapi reference_to_video)",
    ]
    fallback_tools = ["kling_piapi", "wan_piapi", "seedance_piapi"]
    quality_score = 0.85

    input_schema = {
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {"type": "string", "description": f"Up to {_PROMPT_MAX} chars."},
            "model": {"type": "string", "enum": list(_MODELS), "default": "v2.3"},
            "resolution": {
                "type": "string", "enum": list(_RESOLUTIONS), "default": "768p",
                "description": "1080p is 6 s only.",
            },
            "duration": {"type": "integer", "enum": [6, 10], "default": 6},
            "expand_prompt": {"type": "boolean", "default": False},
            "image_url": {"type": "string", "description": "Start image URL (image-to-video)."},
            "image_path": {"type": "string", "description": "Local start image (auto-uploaded)."},
            "poll_timeout_seconds": {"type": "integer", "default": 3600},
            "output_path": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=500, network_required=True)
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=["rate_limit", "timeout"])
    idempotency_key_fields = ["prompt", "model", "resolution", "duration", "image_url"]
    side_effects = ["writes video file to output_path", "calls PiAPI API", "uploads local reference media to PiAPI"]
    user_visible_verification = ["Watch generated clip for motion coherence and visual quality"]

    # ------------------------------------------------------------------ helpers

    def _get_api_key(self) -> str | None:
        return piapi_client.get_api_key()

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE if self._get_api_key() else ToolStatus.UNAVAILABLE

    @staticmethod
    def _spec(inputs: dict[str, Any]) -> tuple[str, int, int]:
        model = inputs.get("model", "v2.3")
        if model not in _MODELS:
            raise ValueError(f"Hailuo model must be one of {list(_MODELS)}; got {model!r}")
        res_key = str(inputs.get("resolution", "768p")).lower()
        if res_key not in _RESOLUTIONS:
            raise ValueError(f"Hailuo resolution must be one of {list(_RESOLUTIONS)}; got {inputs.get('resolution')!r}")
        res = _RESOLUTIONS[res_key]
        secs = int(inputs.get("duration", 6))
        if secs not in (6, 10):
            raise ValueError(f"Hailuo duration must be 6 or 10s; got {secs}")
        if (model, res, secs) not in _PRICING:
            raise ValueError(f"Hailuo {model} does not support {res}p at {secs}s (1080p is 6 s only)")
        return model, res, secs

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        try:
            return _PRICING[self._spec(inputs)]
        except ValueError:
            return 0.0

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return 180.0

    def _upload(self, local_path: str, api_key: str) -> str:
        check_image_aspect(local_path, *_IMAGE_ASPECT, model="Hailuo")
        return piapi_client.upload(local_path, api_key)

    def _build_payload(self, inputs: dict[str, Any], api_key: str) -> dict[str, Any]:
        model, res, secs = self._spec(inputs)
        prompt = inputs.get("prompt", "")
        if not prompt:
            raise ValueError("prompt is required")
        if len(prompt) > _PROMPT_MAX:
            raise ValueError(f"Prompt is {len(prompt)} chars; Hailuo max is {_PROMPT_MAX}")
        data: dict[str, Any] = {
            "prompt": prompt,
            "model": model,
            "expand_prompt": bool(inputs.get("expand_prompt", False)),
            "duration": secs,
            "resolution": res,
        }
        image = inputs.get("image_url") or (
            self._upload(inputs["image_path"], api_key) if inputs.get("image_path") else None
        )
        if image:
            data["image_url"] = image
        return {
            "model": "hailuo",
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
            return ToolResult(success=False, error=f"Invalid Hailuo (PiAPI) request: {e}")
        except Exception as e:  # upload/network failures
            return ToolResult(success=False, error=f"Hailuo (PiAPI) reference upload failed: {e}")

        model = payload["input"]["model"]
        model_id = f"hailuo-{model}"
        resolution = f"{payload['input']['resolution']}p"
        timeout_s = int(inputs.get("poll_timeout_seconds", 3600))
        task_id = None

        def _remember(tid: str) -> None:
            nonlocal task_id
            task_id = tid

        try:
            task = piapi_client.run_task(payload, api_key, label="Hailuo", timeout_s=timeout_s, on_task_id=_remember)
            output = task.get("output") or {}
            video_url = find_video_url(output)
            if not video_url:
                return ToolResult(success=False, error=f"PiAPI task {task_id} completed without a video URL: {output}")
            video = requests.get(video_url, timeout=300)
            video.raise_for_status()
            output_path = Path(inputs.get("output_path", "hailuo_piapi_output.mp4"))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(video.content)
        except Exception as e:
            suffix = f" (task_id={task_id})" if task_id and task_id not in str(e) else ""
            return ToolResult(success=False, error=f"Hailuo (PiAPI) video generation failed{suffix}: {e}")

        from tools.video._shared import probe_output

        probed = probe_output(output_path)
        cost = self.estimate_cost(inputs)
        write_sidecar(output_path, {
            "prompt": payload["input"]["prompt"],
            "provider": "hailuo",
            "gateway": "piapi",
            "model": model_id,
            "task_id": task_id,
            "resolution": resolution,
            "duration_seconds": probed.get("duration_seconds", payload["input"]["duration"]),
            "reference_image": payload["input"].get("image_url"),
            "cost_usd": cost,
            "created_at": time.time(),
        })
        return ToolResult(
            success=True,
            data={
                "provider": "hailuo",
                "gateway": "piapi",
                "model": model_id,
                "task_id": task_id,
                "prompt": payload["input"]["prompt"],
                "resolution": resolution,
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
