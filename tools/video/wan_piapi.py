"""Alibaba Wan video generation via PiAPI (Wan 2.6, 2.2, 2.1).

Two PiAPI model families sit behind one tool:

    Wan 2.6   model "Wan",          task_type wan26-txt2video / wan26-img2video
              720P $0.08/s, 1080P $0.12/s; 5/10/15 s; native audio; optional multi-shot
    Wan 2.2   model "Qubico/wanx",  task_type wan22-txt2video-14b / wan22-img2video-14b
              720p, $0.28 per video
    Wan 2.1   model "Qubico/wanx",  task_type txt2video-14b / img2video-14b / img2video-14b-keyframe
              480p (85 frames), $0.28 per video; version "2.1-1.3b" = txt2video-1.3b, $0.12

Image-to-video takes ONE start image (plus an end image on 2.1 keyframe mode) —
there is no multi-image character-reference set. For multi-character identity
lock, use seedance_piapi reference_to_video.

Docs: https://piapi.ai/docs/wan-api/wan26-text-to-video,
      https://piapi.ai/docs/wan-api/wan26-image-to-video,
      https://piapi.ai/docs/wanx-api/create-task
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

_VERSIONS = ("2.6", "2.2", "2.1", "2.1-1.3b")
_WAN26_RATE = {"720p": 0.08, "1080p": 0.12}          # USD per output second
_WANX_PRICE = {"2.2": 0.28, "2.1": 0.28, "2.1-1.3b": 0.12}  # USD per video
_WANX_RESOLUTION = {"2.2": "720p", "2.1": "480p", "2.1-1.3b": "480p"}
_WAN26_ASPECTS = {"16:9", "9:16", "1:1", "4:3", "3:4"}


class WanPiAPI(BaseTool):
    name = "wan_piapi"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "video_generation"
    provider = "wan"
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
        "native_audio": True,      # 2.6 only
        "cinematic_quality": True,
        "multi_shot": True,        # 2.6 only, shot_type "multi"
        "aspect_ratio": True,
        "seed": True,              # 2.6 only
    }
    best_for = [
        "cheapest 1080p generation on PiAPI (Wan 2.6, $0.12/s) with native audio",
        "single-subject clips up to 15 s from text or one start image",
    ]
    not_good_for = [
        "multi-image character-reference consistency (use seedance_piapi reference_to_video)",
        "offline generation",
    ]
    fallback_tools = ["kling_piapi", "seedance_piapi"]
    quality_score = 0.85

    input_schema = {
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {"type": "string"},
            "negative_prompt": {"type": "string"},
            "version": {
                "type": "string", "enum": list(_VERSIONS), "default": "2.6",
                "description": "2.6 (720p/1080p, audio, 5-15s), 2.2 (720p), 2.1 (480p), 2.1-1.3b (480p, text only).",
            },
            "resolution": {
                "type": "string", "enum": ["720p", "1080p"], "default": "720p",
                "description": "Wan 2.6 only. 2.2 is fixed 720p, 2.1 fixed 480p.",
            },
            "duration": {
                "type": "integer", "enum": [5, 10, 15], "default": 5,
                "description": "Seconds, Wan 2.6 only. 2.1/2.2 always return ~5 s.",
            },
            "aspect_ratio": {
                "type": "string", "enum": sorted(_WAN26_ASPECTS), "default": "16:9",
                "description": "Text-to-video only. 2.1/2.2 accept 16:9 or 9:16. Image-to-video follows the image.",
            },
            "generate_audio": {"type": "boolean", "default": True, "description": "Wan 2.6 only."},
            "audio_url": {"type": "string", "description": "Wan 2.6: use this wav/mp3 as the soundtrack."},
            "shot_type": {
                "type": "string", "enum": ["single", "multi"], "default": "single",
                "description": "Wan 2.6; 'multi' needs prompt_extend true.",
            },
            "prompt_extend": {"type": "boolean", "default": True, "description": "Wan 2.6 prompt auto-expansion."},
            "seed": {"type": "integer", "minimum": 0, "maximum": 2147483647, "description": "Wan 2.6 only."},
            "image_url": {"type": "string", "description": "Start image URL (image-to-video)."},
            "image_path": {"type": "string", "description": "Local start image (auto-uploaded)."},
            "end_image_url": {"type": "string", "description": "End frame, Wan 2.1 keyframe mode only."},
            "end_image_path": {"type": "string", "description": "Local end frame, Wan 2.1 keyframe mode only."},
            "poll_timeout_seconds": {"type": "integer", "default": 3600},
            "output_path": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=500, network_required=True)
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=["rate_limit", "timeout"])
    idempotency_key_fields = ["prompt", "version", "resolution", "duration", "image_url"]
    side_effects = ["writes video file to output_path", "calls PiAPI API", "uploads local reference media to PiAPI"]
    user_visible_verification = ["Watch generated clip for motion coherence, audio sync, and visual quality"]

    # ------------------------------------------------------------------ helpers

    def _get_api_key(self) -> str | None:
        return piapi_client.get_api_key()

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE if self._get_api_key() else ToolStatus.UNAVAILABLE

    @staticmethod
    def _version(inputs: dict[str, Any]) -> str:
        version = str(inputs.get("version", "2.6"))
        if version not in _VERSIONS:
            raise ValueError(f"Unknown Wan version {version!r}; expected one of {list(_VERSIONS)}")
        return version

    @staticmethod
    def _resolution(inputs: dict[str, Any]) -> str:
        res = str(inputs.get("resolution", "720p")).lower()
        if res not in _WAN26_RATE:
            raise ValueError(f"Wan 2.6 resolution must be 720p or 1080p; got {inputs.get('resolution')!r}")
        return res

    @staticmethod
    def _duration(inputs: dict[str, Any]) -> int:
        secs = int(inputs.get("duration", 5))
        if secs not in (5, 10, 15):
            raise ValueError(f"Wan 2.6 duration must be 5, 10 or 15s; got {secs}")
        return secs

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        try:
            version = self._version(inputs)
            if version == "2.6":
                return round(_WAN26_RATE[self._resolution(inputs)] * self._duration(inputs), 2)
        except ValueError:
            return 0.0
        return _WANX_PRICE[version]

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return 240.0

    def _upload(self, local_path: str, api_key: str) -> str:
        return piapi_client.upload(local_path, api_key)

    def _image(self, inputs: dict[str, Any], url_key: str, path_key: str, api_key: str) -> str | None:
        if inputs.get(url_key):
            return inputs[url_key]
        if inputs.get(path_key):
            return self._upload(inputs[path_key], api_key)
        return None

    def _build_payload(self, inputs: dict[str, Any], api_key: str) -> dict[str, Any]:
        version = self._version(inputs)
        prompt = inputs.get("prompt", "")
        if not prompt:
            raise ValueError("prompt is required")
        image = self._image(inputs, "image_url", "image_path", api_key)
        end_image = self._image(inputs, "end_image_url", "end_image_path", api_key)
        aspect = inputs.get("aspect_ratio", "16:9")
        data: dict[str, Any] = {"prompt": prompt}
        if inputs.get("negative_prompt"):
            data["negative_prompt"] = inputs["negative_prompt"]

        if version == "2.6":
            if end_image:
                raise ValueError("end_image is only supported on Wan 2.1 keyframe mode")
            data["resolution"] = self._resolution(inputs).upper()
            data["duration"] = self._duration(inputs)
            data["prompt_extend"] = bool(inputs.get("prompt_extend", True))
            shot_type = inputs.get("shot_type", "single")
            if shot_type not in ("single", "multi"):
                raise ValueError("shot_type must be 'single' or 'multi'")
            if shot_type == "multi" and not data["prompt_extend"]:
                raise ValueError("shot_type 'multi' needs prompt_extend true")
            data["shot_type"] = shot_type
            if inputs.get("audio_url"):
                data["audio_url"] = inputs["audio_url"]
            else:
                data["audio"] = bool(inputs.get("generate_audio", True))
            if inputs.get("seed") is not None:
                data["seed"] = int(inputs["seed"])
            data["watermark"] = False
            if image:
                data["image"] = image
                task_type = "wan26-img2video"
            else:
                if aspect not in _WAN26_ASPECTS:
                    raise ValueError(f"Wan 2.6 aspect_ratio must be one of {sorted(_WAN26_ASPECTS)}")
                data["aspect_ratio"] = aspect
                task_type = "wan26-txt2video"
            return {"model": "Wan", "task_type": task_type, "input": data}

        # Wan 2.1 / 2.2 (Qubico/wanx): fixed resolution and length.
        if aspect not in ("16:9", "9:16") and not image:
            raise ValueError(f"Wan {version} aspect_ratio must be 16:9 or 9:16")
        if version == "2.1-1.3b":
            if image or end_image:
                raise ValueError("Wan 2.1-1.3b is text-to-video only; use version 2.1 for images")
            task_type = "txt2video-1.3b"
        elif end_image:
            if version != "2.1":
                raise ValueError("end_image (keyframe mode) is only supported on Wan 2.1")
            if not image:
                raise ValueError("end_image needs a start image (image_url/image_path)")
            data["start_image"], data["end_image"] = image, end_image
            image = None
            task_type = "img2video-14b-keyframe"
        elif version == "2.2":
            task_type = "wan22-img2video-14b" if image else "wan22-txt2video-14b"
        else:
            task_type = "img2video-14b" if image else "txt2video-14b"
        if image:
            data["image"] = image
        if task_type != "wan22-img2video-14b":
            data["aspect_ratio"] = aspect
        return {"model": "Qubico/wanx", "task_type": task_type, "input": data}

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
            return ToolResult(success=False, error=f"Invalid Wan (PiAPI) request: {e}")
        except Exception as e:  # upload/network failures
            return ToolResult(success=False, error=f"Wan (PiAPI) reference upload failed: {e}")

        version = self._version(inputs)
        model_id = f"wan-{version}"
        resolution = self._resolution(inputs) if version == "2.6" else _WANX_RESOLUTION[version]
        timeout_s = int(inputs.get("poll_timeout_seconds", 3600))
        task_id = None

        def _remember(tid: str) -> None:
            nonlocal task_id
            task_id = tid

        try:
            task = piapi_client.run_task(payload, api_key, label="Wan", timeout_s=timeout_s, on_task_id=_remember)
            output = task.get("output") or {}
            video_url = find_video_url(output)
            if not video_url:
                return ToolResult(success=False, error=f"PiAPI task {task_id} completed without a video URL: {output}")
            video = requests.get(video_url, timeout=300)
            video.raise_for_status()
            output_path = Path(inputs.get("output_path", "wan_piapi_output.mp4"))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(video.content)
        except Exception as e:
            suffix = f" (task_id={task_id})" if task_id and task_id not in str(e) else ""
            return ToolResult(success=False, error=f"Wan (PiAPI) video generation failed{suffix}: {e}")

        from tools.video._shared import probe_output

        probed = probe_output(output_path)
        cost = self.estimate_cost(inputs)
        image = payload["input"].get("image") or payload["input"].get("start_image")
        write_sidecar(output_path, {
            "prompt": payload["input"]["prompt"],
            "provider": "wan",
            "gateway": "piapi",
            "model": model_id,
            "task_id": task_id,
            "resolution": resolution,
            "aspect_ratio": payload["input"].get("aspect_ratio"),
            "duration_seconds": probed.get("duration_seconds", payload["input"].get("duration")),
            "reference_image": image,
            "cost_usd": cost,
            "created_at": time.time(),
        })
        return ToolResult(
            success=True,
            data={
                "provider": "wan",
                "gateway": "piapi",
                "model": model_id,
                "task_type": payload["task_type"],
                "task_id": task_id,
                "prompt": payload["input"]["prompt"],
                "resolution": resolution,
                "aspect_ratio": payload["input"].get("aspect_ratio"),
                "duration_requested": payload["input"].get("duration"),
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
