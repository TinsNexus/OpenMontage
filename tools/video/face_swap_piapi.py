"""Video face swap via PiAPI (model "Qubico/video-toolkit", task_type "face-swap").

Puts the face from one image onto a person in an existing video. Only the face
changes: body, clothes, hair outside the face, background, motion and camera
stay exactly as in the source clip. This is the cheapest way to "re-cast" a
clip you already like with your own recurring character.

    POST https://api.piapi.ai/api/v1/task
    {"model": "Qubico/video-toolkit", "task_type": "face-swap",
     "input": {"swap_image": <url>, "target_video": <url>,
               "swap_faces_index": "0", "target_faces_index": "0"}}

PiAPI limits: MP4 only, <= 10 MB, <= 720p, <= 600 frames; face image <= 2048 px.
Price: $0.004 per processed frame (10 s at 30 fps = 300 frames = $1.20).

A local target video is prepared automatically before upload: scaled down to
720p, frame rate capped at 30 fps, re-encoded to fit 10 MB. A clip that is
still over 600 frames is refused before any paid call — trim it first.

Full-body character replacement (new clothes / body / silhouette while keeping
the scene, e.g. Wan 2.2 Animate "replace" mode) is NOT on PiAPI; this tool
does not do it.

Docs: https://piapi.ai/docs/faceswap-api/video-faceswap
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from tools import piapi_client
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
from tools.video.piapi_video_common import find_video_url, write_sidecar

PRICE_PER_FRAME = 0.004
MAX_FRAMES = 600
MAX_BYTES = 10 * 1024 * 1024
# Leave headroom under the 10 MB cap for container overhead and base64 upload.
TARGET_BYTES = int(9.0 * 1024 * 1024)
MAX_LONG_SIDE = 1280
MAX_SHORT_SIDE = 720
MAX_FPS = 30.0
AUDIO_KBPS = 96


def _parse_rate(rate: str | None) -> float:
    if not rate or rate in ("0/0", "0"):
        return 0.0
    if "/" in rate:
        num, den = rate.split("/", 1)
        try:
            return float(num) / float(den) if float(den) else 0.0
        except ValueError:
            return 0.0
    try:
        return float(rate)
    except ValueError:
        return 0.0


def probe_video(source: str) -> dict[str, Any]:
    """ffprobe a local path or URL: duration, fps, width, height, frames, size, has_audio."""
    if not shutil.which("ffprobe"):
        raise RuntimeError("ffprobe not found; install ffmpeg to use face_swap_piapi")
    proc = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", source],
        capture_output=True, text=True, timeout=60, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe could not read {source}")
    probe = json.loads(proc.stdout or "{}")
    fmt = probe.get("format") or {}
    video = next((s for s in probe.get("streams", []) if s.get("codec_type") == "video"), None)
    if not video:
        raise ValueError(f"{source} has no video stream")
    duration = float(fmt.get("duration") or video.get("duration") or 0)
    fps = _parse_rate(video.get("avg_frame_rate")) or _parse_rate(video.get("r_frame_rate"))
    nb = video.get("nb_frames")
    frames = int(nb) if nb and str(nb).isdigit() else int(round(duration * fps))
    return {
        "duration": duration,
        "fps": fps,
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "frames": frames,
        "size_bytes": int(fmt.get("size") or 0),
        "format_name": fmt.get("format_name", ""),
        "codec": video.get("codec_name", ""),
        "has_audio": any(s.get("codec_type") == "audio" for s in probe.get("streams", [])),
    }


def plan_prepare(info: dict[str, Any]) -> dict[str, Any]:
    """Decide what re-encode (if any) brings a clip inside PiAPI's limits.

    Returns {"needs_encode", "width", "height", "fps", "frames", "video_kbps", "reasons"}.
    Raises ValueError when the clip would still exceed MAX_FRAMES at <= 30 fps.
    """
    w, h, fps, dur = info["width"], info["height"], info["fps"], info["duration"]
    reasons: list[str] = []
    out_fps = fps
    if fps > MAX_FPS + 0.01:
        out_fps = MAX_FPS
        reasons.append(f"fps {fps:.2f} -> {MAX_FPS:g}")
    frames = int(math.ceil(dur * out_fps)) if out_fps else info["frames"]
    if frames > MAX_FRAMES:
        max_secs = MAX_FRAMES / out_fps if out_fps else 0
        raise ValueError(
            f"clip is {dur:.1f}s at {out_fps:.0f} fps = ~{frames} frames; PiAPI face-swap allows "
            f"{MAX_FRAMES}. Trim it to <= {max_secs:.1f}s (or split it and swap each part)."
        )

    scale = min(1.0, MAX_LONG_SIDE / max(w, h), MAX_SHORT_SIDE / min(w, h)) if w and h else 1.0
    out_w, out_h = w, h
    if scale < 1.0:
        out_w = int(w * scale) // 2 * 2
        out_h = int(h * scale) // 2 * 2
        reasons.append(f"{w}x{h} -> {out_w}x{out_h}")

    is_mp4 = "mp4" in info.get("format_name", "") and info.get("codec") in ("h264", "hevc")
    if not is_mp4:
        reasons.append("re-mux to H.264 MP4")
    if info["size_bytes"] > MAX_BYTES:
        reasons.append(f"{info['size_bytes'] / 1e6:.1f} MB > 10 MB")

    audio_kbps = AUDIO_KBPS if info.get("has_audio") else 0
    total_kbps = TARGET_BYTES * 8 / 1000 / max(dur, 0.1)
    video_kbps = int(max(300, min(4000, total_kbps - audio_kbps)))
    return {
        "needs_encode": bool(reasons),
        "width": out_w,
        "height": out_h,
        "fps": out_fps,
        "frames": frames,
        "video_kbps": video_kbps,
        "reasons": reasons,
    }


def prepare_video(src: str, plan: dict[str, Any], workdir: Path) -> Path:
    """Re-encode ``src`` per ``plan`` into an H.264 MP4 under 10 MB."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found; install ffmpeg to use face_swap_piapi")
    out = workdir / "face_swap_target.mp4"
    kbps = plan["video_kbps"]
    for _ in range(3):
        cmd = [
            "ffmpeg", "-y", "-v", "error", "-i", src,
            "-vf", f"scale={plan['width']}:{plan['height']},fps={plan['fps']:.3f}",
            "-c:v", "libx264", "-preset", "medium", "-pix_fmt", "yuv420p",
            "-b:v", f"{kbps}k", "-maxrate", f"{int(kbps * 1.2)}k", "-bufsize", f"{kbps * 2}k",
            "-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k",
            "-movflags", "+faststart", str(out),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=False)
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg failed preparing target video: {proc.stderr[-400:]}")
        if out.stat().st_size <= MAX_BYTES:
            return out
        kbps = int(kbps * 0.7)
    raise RuntimeError("could not fit the target video under 10 MB; trim it shorter")


def restore_audio(swapped: Path, audio_source: str) -> bool:
    """Copy the source clip's audio onto the swapped video when PiAPI dropped it."""
    if not shutil.which("ffmpeg"):
        return False
    tmp = swapped.with_name(f"{swapped.stem}.audio_tmp.mp4")
    proc = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(swapped), "-i", audio_source,
         "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
         "-shortest", str(tmp)],
        capture_output=True, text=True, timeout=300, check=False,
    )
    if proc.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        return False
    tmp.replace(swapped)
    return True


class FaceSwapPiAPI(BaseTool):
    name = "face_swap_piapi"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "video_post"
    provider = "piapi"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = ["cmd:ffmpeg", "cmd:ffprobe"]
    install_instructions = (
        "Set PIAPI_API_KEY to your PiAPI API key (https://piapi.ai).\n"
        "  Uploading local files needs a PiAPI Creator plan or higher;\n"
        "  public URLs work on any plan. ffmpeg/ffprobe must be installed."
    )
    agent_skills = ["face-swap-piapi"]

    capabilities = ["face_swap"]
    supports = {
        "face_swap": True,
        "full_body_character_replace": False,
        "multiple_faces": True,
        "keeps_original_motion": True,
        "auto_prepare_local_video": True,
    }
    best_for = [
        "re-casting an existing clip with your recurring character's face (scene, motion, body unchanged)",
        "swapping several faces at once via swap_faces_index / target_faces_index",
        "cheap edits: $0.004/frame, ~$1.20 for 10 s at 30 fps",
    ]
    not_good_for = [
        "changing body, clothes, hairstyle or species (face only)",
        "full-body character replacement (Wan 2.2 Animate 'replace' lives on DashScope/fal, not PiAPI)",
        "clips longer than 600 frames (~20 s at 30 fps) without trimming",
        "stylized/cartoon faces that the face detector cannot find",
    ]
    fallback_tools = []  # seedance_piapi reference_to_video is a different operation (new clip), not a retry
    quality_score = 0.75

    input_schema = {
        "type": "object",
        "required": [],
        "properties": {
            "face_image_url": {"type": "string", "description": "Image with the new face (<= 2048 px)."},
            "face_image_path": {"type": "string", "description": "Local face image (auto-uploaded, auto-shrunk)."},
            "target_video_url": {"type": "string", "description": "Public MP4 (<= 10 MB, <= 720p, <= 600 frames)."},
            "target_video_path": {
                "type": "string",
                "description": "Local video; auto-scaled to 720p, capped at 30 fps, re-encoded under 10 MB.",
            },
            "swap_faces_index": {
                "type": "string", "default": "0",
                "description": "Which face(s) in the face image to use, e.g. '0' or '1,0'.",
            },
            "target_faces_index": {
                "type": "string", "default": "0",
                "description": "Which face(s) in the video to replace, e.g. '0' or '0,1' (pairs with swap_faces_index).",
            },
            "keep_audio": {
                "type": "boolean", "default": True,
                "description": "Put the source clip's audio back if the swapped video comes back silent.",
            },
            "dry_run": {
                "type": "boolean", "default": False,
                "description": "Prepare + price the clip without uploading or paying.",
            },
            "poll_timeout_seconds": {"type": "integer", "default": 3600},
            "output_path": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(cpu_cores=2, ram_mb=1024, vram_mb=0, disk_mb=500, network_required=True)
    retry_policy = RetryPolicy(max_retries=0, retryable_errors=["rate_limit"])
    idempotency_key_fields = [
        "face_image_url", "face_image_path", "target_video_url", "target_video_path",
        "swap_faces_index", "target_faces_index",
    ]
    side_effects = [
        "writes video file to output_path",
        "uploads face image and target video to PiAPI ephemeral storage (24h)",
        "calls PiAPI API (billed per frame)",
    ]
    user_visible_verification = [
        "Watch the swapped clip: face identity, skin-tone match at the neck, flicker on fast head turns",
    ]

    # ------------------------------------------------------------------ helpers

    def _get_api_key(self) -> str | None:
        return piapi_client.get_api_key()

    def get_status(self) -> ToolStatus:
        if not self._get_api_key():
            return ToolStatus.UNAVAILABLE
        if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
            return ToolStatus.DEGRADED
        return ToolStatus.AVAILABLE

    @staticmethod
    def _target_source(inputs: dict[str, Any]) -> str:
        src = inputs.get("target_video_path") or inputs.get("target_video_url")
        if not src:
            raise ValueError("target_video_path or target_video_url is required")
        if inputs.get("target_video_path") and not Path(src).expanduser().exists():
            raise FileNotFoundError(f"target video not found: {src}")
        return str(Path(src).expanduser()) if inputs.get("target_video_path") else src

    @staticmethod
    def _index(value: Any, field: str) -> str:
        text = str(value if value is not None else "0").replace(" ", "")
        if not text or not all(part.isdigit() for part in text.split(",")):
            raise ValueError(f"{field} must be comma-separated face indexes like '0' or '0,1'; got {value!r}")
        return text

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        try:
            info = probe_video(self._target_source(inputs))
            return round(plan_prepare(info)["frames"] * PRICE_PER_FRAME, 2)
        except Exception:
            return 0.0

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return 300.0

    def build_payload(self, face_url: str, video_url: str, inputs: dict[str, Any]) -> dict[str, Any]:
        return {
            "model": "Qubico/video-toolkit",
            "task_type": "face-swap",
            "input": {
                "swap_image": face_url,
                "target_video": video_url,
                "swap_faces_index": self._index(inputs.get("swap_faces_index", "0"), "swap_faces_index"),
                "target_faces_index": self._index(inputs.get("target_faces_index", "0"), "target_faces_index"),
            },
        }

    # ------------------------------------------------------------------ execute

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        start = time.time()
        dry_run = bool(inputs.get("dry_run", False))
        api_key = self._get_api_key()
        if not api_key and not dry_run:
            return ToolResult(success=False, error="PIAPI_API_KEY not set. " + self.install_instructions)

        if not (inputs.get("face_image_url") or inputs.get("face_image_path")):
            return ToolResult(success=False, error="face_image_path or face_image_url is required")
        if inputs.get("face_image_path") and not Path(inputs["face_image_path"]).expanduser().exists():
            return ToolResult(success=False, error=f"face image not found: {inputs['face_image_path']}")

        workdir = Path(tempfile.mkdtemp(prefix="face_swap_"))
        try:
            try:
                source = self._target_source(inputs)
                self._index(inputs.get("swap_faces_index", "0"), "swap_faces_index")
                self._index(inputs.get("target_faces_index", "0"), "target_faces_index")
                info = probe_video(source)
                plan = plan_prepare(info)
            except (ValueError, FileNotFoundError) as e:
                return ToolResult(success=False, error=f"Invalid face swap request: {e}")
            except RuntimeError as e:
                return ToolResult(success=False, error=str(e))

            is_local = bool(inputs.get("target_video_path"))
            if not is_local and plan["needs_encode"]:
                return ToolResult(
                    success=False,
                    error="target_video_url is outside PiAPI limits (" + "; ".join(plan["reasons"])
                    + "). Download it and pass target_video_path so it can be prepared automatically.",
                )

            cost = round(plan["frames"] * PRICE_PER_FRAME, 2)
            prepared = source
            if is_local and plan["needs_encode"]:
                try:
                    prepared = str(prepare_video(source, plan, workdir))
                except RuntimeError as e:
                    return ToolResult(success=False, error=str(e))

            summary = {
                "source": source,
                "source_info": info,
                "prepared_video": prepared,
                "prepare_steps": plan["reasons"],
                "frames": plan["frames"],
                "estimated_cost_usd": cost,
            }
            if dry_run:
                keep = Path(inputs.get("output_path", "face_swap_piapi_output.mp4"))
                if prepared != source:
                    keep = keep.with_name(f"{keep.stem}.prepared.mp4")
                    keep.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(prepared, keep)
                    summary["prepared_video"] = str(keep)
                return ToolResult(success=True, data={"dry_run": True, **summary}, cost_usd=0.0)

            import requests

            task_id = None

            def _remember(tid: str) -> None:
                nonlocal task_id
                task_id = tid

            try:
                face_url = inputs.get("face_image_url") or piapi_client.upload(inputs["face_image_path"], api_key)
                video_url = piapi_client.upload(prepared, api_key) if is_local else source
                payload = self.build_payload(face_url, video_url, inputs)
                task = piapi_client.run_task(
                    payload, api_key, label="face-swap",
                    timeout_s=int(inputs.get("poll_timeout_seconds", 3600)), on_task_id=_remember,
                )
                result_url = find_video_url(task.get("output") or {})
                if not result_url:
                    return ToolResult(
                        success=False,
                        error=f"PiAPI face-swap task {task_id} completed without a video URL: {task.get('output')}",
                    )
                video = requests.get(result_url, timeout=300)
                video.raise_for_status()
                output_path = Path(inputs.get("output_path", "face_swap_piapi_output.mp4"))
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(video.content)
            except Exception as e:
                suffix = f" (task_id={task_id})" if task_id and task_id not in str(e) else ""
                return ToolResult(success=False, error=f"PiAPI face swap failed{suffix}: {e}")
        finally:
            # Only the prepared copy lives here; audio restore reads the original source.
            shutil.rmtree(workdir, ignore_errors=True)

        audio_restored = False
        if inputs.get("keep_audio", True) and info.get("has_audio") and is_local:
            try:
                if not probe_video(str(output_path)).get("has_audio"):
                    audio_restored = restore_audio(output_path, source)
            except Exception:
                audio_restored = False

        from tools.video._shared import probe_output

        probed = probe_output(output_path)
        write_sidecar(output_path, {
            "provider": "piapi",
            "gateway": "piapi",
            "model": "Qubico/video-toolkit:face-swap",
            "task_id": task_id,
            "face_image": payload["input"]["swap_image"],
            "target_video": source,
            "swap_faces_index": payload["input"]["swap_faces_index"],
            "target_faces_index": payload["input"]["target_faces_index"],
            "frames": plan["frames"],
            "cost_usd": cost,
            "created_at": time.time(),
        })
        return ToolResult(
            success=True,
            data={
                "provider": "piapi",
                "model": "Qubico/video-toolkit:face-swap",
                "task_id": task_id,
                "output": str(output_path),
                "output_path": str(output_path),
                "audio_restored": audio_restored,
                "piapi_usage": (task.get("meta") or {}).get("usage") or {},
                "format": "mp4",
                **summary,
                **probed,
            },
            artifacts=[str(output_path)],
            cost_usd=cost,
            duration_seconds=round(time.time() - start, 2),
            model="Qubico/video-toolkit:face-swap",
        )
