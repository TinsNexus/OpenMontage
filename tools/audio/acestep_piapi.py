"""Ace-Step music/audio generation via PiAPI.

Cheap, keyless-beyond-PIAPI_KEY instrumental (or lyriced) music generation.
Good default for background music when no dedicated music_generation
provider (ElevenLabs, Suno, Google) is configured and pixabay_music's
scraper is blocked.

Docs: https://piapi.ai/docs/ace-step-api/text-to-audio
      https://piapi.ai/docs/ace-step-api/get-task
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

_RATE_PER_SECOND = 0.0005  # PiAPI published pricing for Qubico/ace-step


class AceStepPiAPI(BaseTool):
    name = "acestep_piapi"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "music_generation"
    provider = "piapi"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = []
    install_instructions = (
        "Set PIAPI_API_KEY (or PIAPI_KEY) to your PiAPI API key.\n"
        "  Get one from your PiAPI workspace at https://piapi.ai"
    )
    agent_skills = ["music", "acestep"]

    capabilities = ["generate_background_music", "generate_instrumental", "generate_song"]
    supports = {
        "instrumental": True,
        "lyrics": True,
        "duration_control": True,
        "no_api_key_beyond_piapi": True,
    }
    best_for = [
        "cheap instrumental background music (~$0.0005/s — a 30s track is ~$0.015)",
        "when no dedicated music_generation provider is configured",
        "fallback when pixabay_music's scraper is blocked (HTTP 403 etc.)",
    ]
    not_good_for = ["complex multi-section scored music", "precise tempo/beat-matching to picture"]
    fallback_tools = ["music_gen", "suno_music", "google_music", "pixabay_music"]

    input_schema = {
        "type": "object",
        "required": ["style_prompt"],
        "properties": {
            "style_prompt": {
                "type": "string",
                "description": "Style/mood/genre/instrumentation description, e.g. "
                               "'upbeat playful adventure, light percussion, strings, no vocals'.",
            },
            "negative_style_prompt": {
                "type": "string",
                "description": "Styles/qualities to avoid, e.g. 'slow, sad, distorted'.",
            },
            "lyrics": {
                "type": "string",
                "default": "[inst]",
                "description": "Full lyrics. Leave as '[inst]' (the default) for instrumental-only output — "
                               "the right choice for video background music, which should not collide with "
                               "narration or dialogue.",
            },
            "duration": {
                "type": "integer",
                "default": 30,
                "minimum": 10,
                "maximum": 240,
                "description": "Seconds of audio to generate. Match the target video/section duration.",
            },
            "poll_timeout_seconds": {"type": "integer", "default": 600},
            "output_path": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=256, vram_mb=0, disk_mb=50, network_required=True
    )
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=["rate_limit", "timeout"])
    idempotency_key_fields = ["style_prompt", "lyrics", "duration"]
    side_effects = ["writes audio file to output_path", "calls PiAPI API"]
    user_visible_verification = ["Listen for style match, instrumental cleanliness, and loudness"]

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE if piapi_client.get_api_key() else ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        duration = int(inputs.get("duration", 30) or 30)
        return round(_RATE_PER_SECOND * duration, 4)

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return 60.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        api_key = piapi_client.get_api_key()
        if not api_key:
            return ToolResult(success=False, error="PIAPI_API_KEY not set. " + self.install_instructions)

        style_prompt = (inputs.get("style_prompt") or "").strip()
        if not style_prompt:
            return ToolResult(success=False, error="Invalid Ace-Step (PiAPI) request: style_prompt must be non-empty")
        duration = int(inputs.get("duration", 30) or 30)
        if not 10 <= duration <= 240:
            return ToolResult(success=False, error=f"Invalid Ace-Step (PiAPI) request: duration must be 10-240s; got {duration}")

        payload: dict[str, Any] = {
            "model": "Qubico/ace-step",
            "task_type": "txt2audio",
            "input": {
                "style_prompt": style_prompt,
                "lyrics": inputs.get("lyrics") or "[inst]",
                "duration": duration,
            },
        }
        if inputs.get("negative_style_prompt"):
            payload["input"]["negative_style_prompt"] = inputs["negative_style_prompt"]

        import requests

        start = time.time()
        task_id = None

        def _remember(tid: str) -> None:
            nonlocal task_id
            task_id = tid

        try:
            task = piapi_client.run_task(
                payload, api_key, label="Ace-Step", timeout_s=int(inputs.get("poll_timeout_seconds", 600)),
                on_task_id=_remember,
            )
        except Exception as e:
            suffix = f" (task_id={task_id})" if task_id and task_id not in str(e) else ""
            return ToolResult(success=False, error=f"Ace-Step (PiAPI) music generation failed{suffix}: {e}")

        task_id = task.get("task_id", task_id)
        audio_url = (task.get("output") or {}).get("audio_url")
        if not audio_url:
            return ToolResult(success=False, error=f"PiAPI task {task_id} completed without an audio_url: {task.get('output')}")

        try:
            resp = requests.get(audio_url, timeout=120)
            resp.raise_for_status()
            output_path = Path(inputs.get("output_path", "acestep_output.mp3"))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(resp.content)
        except Exception as e:
            return ToolResult(success=False, error=f"Ace-Step (PiAPI) download failed (task_id={task_id}): {e}")

        return ToolResult(
            success=True,
            data={
                "provider": "piapi",
                "model": "Qubico/ace-step",
                "task_id": task_id,
                "style_prompt": style_prompt,
                "duration_requested": duration,
                "output": str(output_path),
                "output_path": str(output_path),
                "format": output_path.suffix.lstrip("."),
            },
            artifacts=[str(output_path)],
            cost_usd=self.estimate_cost(inputs),
            duration_seconds=round(time.time() - start, 2),
            model="Qubico/ace-step",
        )
