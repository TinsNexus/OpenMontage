"""Google Nano Banana / Gemini image generation and editing via PiAPI.

Uses PiAPI's unified task API (model ``gemini``) so a single PIAPI key unlocks
Google's image models without a Google account:

    nano-banana-2.1          $0.03 / $0.04 / $0.09  (1K / 2K / 4K)   default
    nano-banana-2            $0.06 / $0.08 / $0.12
    nano-banana-pro          $0.105 (1K, 2K) / $0.18 (4K)
    gemini-2.5-flash-image   $0.03 (fixed size)

Each PiAPI task returns one image; ``n`` > 1 runs that many tasks.

Docs: https://piapi.ai/docs/gemini-api/nano-banana-2
      https://piapi.ai/docs/gemini-api/nano-banana-pro
      https://piapi.ai/docs/gemini-api/gemini-25-flash-image
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

# task_type -> price per image by resolution ("*" = fixed size model).
_PRICING: dict[str, dict[str, float]] = {
    "nano-banana-2.1": {"1K": 0.03, "2K": 0.04, "4K": 0.09},
    "nano-banana-2": {"1K": 0.06, "2K": 0.08, "4K": 0.12},
    "nano-banana-pro": {"1K": 0.105, "2K": 0.105, "4K": 0.18},
    "gemini-2.5-flash-image": {"*": 0.03},
}
_MAX_INPUT_IMAGES = 14

_ASPECTS = {
    "nano-banana-2.1": {"1:1", "16:9", "9:16", "4:3", "3:4", "21:9", "3:2", "2:3", "5:4", "4:5",
                        "1:4", "1:8", "4:1", "8:1"},
    "nano-banana-2": {"1:1", "16:9", "9:16", "4:3", "3:4", "21:9", "3:2", "2:3", "5:4", "4:5",
                      "1:4", "1:8", "4:1", "8:1"},
    "nano-banana-pro": {"21:9", "1:1", "4:3", "3:2", "2:3", "5:4", "4:5", "3:4", "16:9", "9:16"},
    "gemini-2.5-flash-image": {"21:9", "1:1", "4:3", "3:2", "2:3", "5:4", "4:5", "3:4", "16:9", "9:16"},
}
# Accepted output_format values per model ("jpg" vs "jpeg" differs by family).
_FORMATS = {
    "nano-banana-2.1": {"jpg": "jpg", "jpeg": "jpg", "png": "png", "webp": "webp"},
    "nano-banana-2": {"jpg": "jpg", "jpeg": "jpg", "png": "png", "webp": "webp"},
    "nano-banana-pro": {"jpg": "jpeg", "jpeg": "jpeg", "png": "png"},
    "gemini-2.5-flash-image": {"jpg": "jpeg", "jpeg": "jpeg", "png": "png"},
}


class PiAPIImage(BaseTool):
    name = "piapi_image"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "image_generation"
    provider = "piapi"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = []
    install_instructions = (
        "Set PIAPI_API_KEY (or PIAPI_KEY) to your PiAPI API key.\n"
        "  Get one from your PiAPI workspace at https://piapi.ai\n"
        "  (Uploading local reference images needs a PiAPI Creator plan or higher;\n"
        "   public image URLs work on any plan.)"
    )
    agent_skills = []

    capabilities = ["generate_image", "edit_image", "text_to_image", "image_to_image", "style_transfer"]
    supports = {
        "image_edit": True,
        "multiple_outputs": True,
        "aspect_ratio": True,
        "resolution": True,
        "reference_image": True,
        "multiple_reference_images": True,
        "character_consistency": True,
    }
    best_for = [
        "Google Nano Banana image generation with only a PiAPI key",
        "character reference sheets and identity-consistent edits (up to 14 input images)",
        "photoreal portraits and keyframes to anchor image-to-video / reference-to-video",
        "cheap iteration ($0.03 per 1K image on nano-banana-2.1)",
    ]
    not_good_for = ["offline generation", "seeded reproducibility", "vector / SVG output"]
    fallback_tools = ["google_imagen", "flux_image", "openai_image", "grok_image"]

    input_schema = {
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {"type": "string"},
            "model": {
                "type": "string",
                "enum": sorted(_PRICING),
                "default": "nano-banana-2.1",
            },
            "aspect_ratio": {"type": "string", "description": "e.g. 1:1, 3:4, 16:9, 9:16. Omit when editing to keep the input ratio."},
            "resolution": {
                "type": "string",
                "enum": ["1K", "2K", "4K"],
                "default": "1K",
                "description": "Ignored by gemini-2.5-flash-image.",
            },
            "output_format": {"type": "string", "enum": ["png", "jpg", "jpeg", "webp"], "default": "png"},
            "safety_level": {
                "type": "string",
                "enum": ["low", "medium", "high"],
                "description": "nano-banana-pro only. low = strictest, high = most permissive (PiAPI default).",
            },
            "n": {
                "type": "integer",
                "minimum": 1,
                "maximum": 4,
                "default": 1,
                "description": "Number of images; each is a separate PiAPI task (billed per image).",
            },
            "image_url": {"type": "string", "description": "Single source / reference image URL."},
            "image_path": {"type": "string", "description": "Single local source / reference image (auto-uploaded)."},
            "image_urls": {"type": "array", "items": {"type": "string"}},
            "image_paths": {"type": "array", "items": {"type": "string"}},
            "characters": {
                "type": "array", "items": {"type": "string"},
                "description": "Character library ids (characters/<id>). Their primary images become reference "
                               "images 1..N and the prompt is prefixed with who each one is.",
            },
            "character_refs": {"type": "string", "enum": ["set", "full", "primary"], "default": "set"},
            "poll_timeout_seconds": {"type": "integer", "default": 900},
            "output_path": {
                "type": "string",
                "description": "File path. With n > 1, files are suffixed _1, _2, ...",
            },
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=256, vram_mb=0, disk_mb=100, network_required=True
    )
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=["rate_limit", "timeout"])
    idempotency_key_fields = ["prompt", "model", "aspect_ratio", "resolution", "n"]
    side_effects = ["writes image file(s) to output_path", "calls PiAPI API", "uploads local reference images to PiAPI"]
    user_visible_verification = ["Inspect generated image(s) for identity, anatomy, and prompt adherence"]

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE if piapi_client.get_api_key() else ToolStatus.UNAVAILABLE

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _model(inputs: dict[str, Any]) -> str:
        model = inputs.get("model") or "nano-banana-2.1"
        if model not in _PRICING:
            raise ValueError(f"Unknown model {model!r}; expected one of {sorted(_PRICING)}")
        return model

    @staticmethod
    def _n(inputs: dict[str, Any]) -> int:
        n = int(inputs.get("n", 1) or 1)
        if not 1 <= n <= 4:
            raise ValueError(f"n must be 1-4; got {n}")
        return n

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        try:
            model = self._model(inputs)
            n = self._n(inputs)
        except ValueError:
            return 0.0
        table = _PRICING[model]
        rate = table.get("*") or table.get(inputs.get("resolution", "1K"), 0.0)
        return round(rate * n, 3)

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return 30.0 * max(1, int(inputs.get("n", 1) or 1))

    def _build_payload(self, inputs: dict[str, Any], api_key: str) -> dict[str, Any]:
        model = self._model(inputs)
        prompt = (inputs.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("prompt must be non-empty")

        character_paths: list[str] = []
        if inputs.get("characters"):
            from lib import characters as charlib

            slugs = list(inputs["characters"])
            try:
                items = charlib.references(slugs, inputs.get("character_refs", "set"))
            except KeyError as e:
                raise ValueError(str(e).strip("'\""))
            sentences, n = [], 1
            for item in items:
                c, refs = item["char"], item["refs"]
                nums = list(range(n, n + len(refs)))
                n += len(refs)
                character_paths += [r["path"] for r in refs]
                which = ", ".join(f"{k} ({charlib.ROLES.get(r['role'], r['role'])})" for k, r in zip(nums, refs))
                label = f"Reference image {nums[0]}" if len(nums) == 1 else f"Reference images {which}"
                look = (c.get("identity") or c.get("description") or "").rstrip(".")
                sentences.append(f"{label} {'is' if len(nums) == 1 else 'all show'} {c['name']}: {look}. "
                                 f"Keep {c['name']}'s face, hair and outfit exactly as in those references.")
            prompt = " ".join(sentences) + "\n\n" + prompt

        data: dict[str, Any] = {"prompt": prompt}

        fmt = str(inputs.get("output_format") or "png").lower()
        if fmt not in _FORMATS[model]:
            raise ValueError(f"{model} output_format must be one of {sorted(_FORMATS[model])}; got {fmt}")
        data["output_format"] = _FORMATS[model][fmt]

        aspect = inputs.get("aspect_ratio")
        if aspect:
            if aspect not in _ASPECTS[model]:
                raise ValueError(f"{model} does not support aspect_ratio {aspect}; use one of {sorted(_ASPECTS[model])}")
            data["aspect_ratio"] = aspect

        if "*" not in _PRICING[model]:
            res = inputs.get("resolution") or "1K"
            if res not in _PRICING[model]:
                raise ValueError(f"{model} resolution must be 1K, 2K or 4K; got {res}")
            data["resolution"] = res

        if inputs.get("safety_level"):
            if model != "nano-banana-pro":
                raise ValueError("safety_level is only supported by nano-banana-pro")
            data["safety_level"] = inputs["safety_level"]

        given: list[str] = []
        if inputs.get("image_url"):
            given.append(inputs["image_url"])
        given += list(inputs.get("image_urls") or [])
        local = ([inputs["image_path"]] if inputs.get("image_path") else []) + list(inputs.get("image_paths") or [])
        count = len(character_paths) + len(given) + len(local)
        if count > _MAX_INPUT_IMAGES:
            raise ValueError(f"At most {_MAX_INPUT_IMAGES} input images; got {count}")
        # Library characters first: their position matches "Reference image N" in the prompt.
        urls = [piapi_client.upload(p, api_key) for p in character_paths] + given
        for p in local:
            urls.append(piapi_client.upload(p, api_key))
        if urls:
            data["image_urls"] = urls

        return {"model": "gemini", "task_type": model, "input": data}

    @staticmethod
    def _image_urls(task: dict[str, Any]) -> list[str]:
        out = task.get("output") or {}
        urls = list(out.get("image_urls") or [])
        if not urls and out.get("image_url"):
            urls = [out["image_url"]]
        if not urls:
            legacy = ((task.get("task_result") or {}).get("task_output") or {})
            if legacy.get("image_url"):
                urls = [legacy["image_url"]]
        return urls

    @staticmethod
    def _output_paths(output_path: str | None, count: int, ext: str) -> list[Path]:
        base = Path(output_path) if output_path else Path(f"piapi_image.{ext}")
        if base.suffix == "":
            base = base.with_suffix(f".{ext}")
        if count == 1:
            return [base]
        return [base.with_name(f"{base.stem}_{i + 1}{base.suffix}") for i in range(count)]

    # ------------------------------------------------------------------ execute

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        api_key = piapi_client.get_api_key()
        if not api_key:
            return ToolResult(success=False, error="PIAPI_API_KEY not set. " + self.install_instructions)

        import requests

        start = time.time()
        try:
            n = self._n(inputs)
            payload = self._build_payload(inputs, api_key)
        except (ValueError, FileNotFoundError) as e:
            return ToolResult(success=False, error=f"Invalid PiAPI image request: {e}")
        except Exception as e:
            return ToolResult(success=False, error=f"PiAPI reference upload failed: {e}")

        model = payload["task_type"]
        ext = payload["input"]["output_format"].replace("jpeg", "jpg")
        paths = self._output_paths(inputs.get("output_path"), n, ext)
        timeout_s = int(inputs.get("poll_timeout_seconds", 900))

        written: list[str] = []
        task_ids: list[str] = []
        try:
            for path in paths:
                task = piapi_client.run_task(
                    payload, api_key, label=f"image ({model})", timeout_s=timeout_s, poll_every_s=4,
                    on_task_id=task_ids.append,
                )
                urls = self._image_urls(task)
                if not urls:
                    raise RuntimeError(f"task {task.get('task_id')} completed without an image URL")
                img = requests.get(urls[0], timeout=120)
                img.raise_for_status()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(img.content)
                written.append(str(path))
        except Exception as e:
            partial = f" ({len(written)}/{n} images written: {written})" if written else ""
            return ToolResult(
                success=False,
                error=f"PiAPI image generation failed{partial}: {e}",
                artifacts=written,
                cost_usd=round(self.estimate_cost({**inputs, "n": max(len(written), 0)}) if written else 0.0, 3),
            )

        return ToolResult(
            success=True,
            data={
                "provider": "piapi",
                "model": model,
                "prompt": payload["input"]["prompt"],
                "aspect_ratio": payload["input"].get("aspect_ratio"),
                "resolution": payload["input"].get("resolution"),
                "reference_images": payload["input"].get("image_urls", []),
                "task_ids": task_ids,
                "output": written[0],
                "output_path": written[0],
                "outputs": written,
                "format": ext,
            },
            artifacts=written,
            cost_usd=self.estimate_cost(inputs),
            duration_seconds=round(time.time() - start, 2),
            model=model,
        )
