"""Frame-by-frame face swap via PiAPI image face swap (model "Qubico/image-toolkit").

Splits a clip into frames, swaps the face on every frame with PiAPI's image
face swap ($0.01 per frame), and reassembles the clip at the source frame rate
with the original audio. Use it while PiAPI's video face swap
(``face_swap_piapi``) is failing, or for clips it rejects.

    POST https://api.piapi.ai/api/v1/task
    {"model": "Qubico/image-toolkit", "task_type": "face-swap",
     "input": {"target_image": <frame url>, "swap_image": <face url>}}

The largest face in each frame is replaced, and only the face changes.
Every frame is swapped on its own, so the face can flicker slightly on fast
motion. Run a 1 s test before paying for a whole clip.

Modes:
    preview  swap one frame (``preview_time``) -> JPEG, $0.01
    video    swap every frame -> MP4

``work_dir`` caches extracted and swapped frames, so a run that is
interrupted picks up where it stopped and does not pay twice for a frame.

Docs: https://piapi.ai/docs/faceswap-api/create-task
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

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
from tools.video.face_swap_piapi import probe_video

PRICE_PER_FRAME = 0.01
DEFAULT_MAX_FRAMES = 600
MAX_FPS = 30.0
MAX_SHORT_SIDE = 720
MAX_LONG_SIDE = 1280
DEFAULT_WORKERS = 6
FRAME_ATTEMPTS = 3


def plan_frames(info: dict[str, Any], *, start: float = 0.0, end: float | None = None,
                max_frames: int = DEFAULT_MAX_FRAMES) -> dict[str, Any]:
    """Output size, fps and frame count for a (trimmed) clip. Raises ValueError over ``max_frames``."""
    dur_total = float(info["duration"])
    start = max(0.0, float(start or 0))
    end = dur_total if end is None else min(float(end), dur_total)
    if end - start <= 1e-3:
        raise ValueError(f"empty range: start {start:.2f}s, end {end:.2f}s (clip is {dur_total:.2f}s)")
    fps = info["fps"] or 24.0
    out_fps = min(fps, MAX_FPS)
    duration = end - start
    frames = max(1, int(math.ceil(duration * out_fps - 1e-6)))
    if frames > max_frames:
        raise ValueError(
            f"{duration:.1f}s at {out_fps:.0f} fps = {frames} frames; the limit is {max_frames} "
            f"(${max_frames * PRICE_PER_FRAME:.2f}). Shorten the range to <= {max_frames / out_fps:.1f}s."
        )
    w, h = info["width"], info["height"]
    scale = min(1.0, MAX_LONG_SIDE / max(w, h), MAX_SHORT_SIDE / min(w, h)) if w and h else 1.0
    return {
        "start": round(start, 3),
        "end": round(end, 3),
        "duration": round(duration, 3),
        "fps": out_fps,
        "frames": frames,
        "width": int(w * scale) // 2 * 2,
        "height": int(h * scale) // 2 * 2,
        "cost_usd": round(frames * PRICE_PER_FRAME, 2),
    }


def _ffmpeg(args: list[str], what: str, timeout: int = 900) -> None:
    proc = subprocess.run(["ffmpeg", "-y", "-v", "error", *args], capture_output=True, text=True,
                          timeout=timeout, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed {what}: {proc.stderr[-400:]}")


def extract_frames(src: str, plan: dict[str, Any], out_dir: Path) -> list[Path]:
    """Write frames as out_dir/00001.jpg ... at the plan's fps and size (reuses existing ones)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(out_dir.glob("*.jpg"))
    if len(existing) == plan["frames"]:
        return existing
    for old in existing:
        old.unlink()
    _ffmpeg(["-ss", f"{plan['start']:.3f}", "-t", f"{plan['duration']:.3f}", "-i", src,
             "-vf", f"scale={plan['width']}:{plan['height']},fps={plan['fps']:.5f}",
             "-q:v", "2", "-frames:v", str(plan["frames"]), str(out_dir / "%05d.jpg")], "extracting frames")
    frames = sorted(out_dir.glob("*.jpg"))
    if not frames:
        raise RuntimeError("no frames extracted from the clip")
    return frames


def assemble(frames_dir: Path, plan: dict[str, Any], audio_src: str | None, out: Path) -> None:
    """Frames -> H.264 MP4 at the plan fps, with the source audio for the same range when it has one."""
    out.parent.mkdir(parents=True, exist_ok=True)
    args = ["-framerate", f"{plan['fps']:.5f}", "-i", str(frames_dir / "%05d.jpg")]
    if audio_src:
        args += ["-ss", f"{plan['start']:.3f}", "-t", f"{plan['duration']:.3f}", "-i", audio_src,
                 "-map", "0:v:0", "-map", "1:a:0?", "-c:a", "aac", "-b:a", "128k"]
    args += ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
             "-movflags", "+faststart", "-shortest", str(out)]
    _ffmpeg(args, "assembling the swapped clip")


class FaceSwapFramesPiAPI(BaseTool):
    name = "face_swap_frames_piapi"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "video_post"
    provider = "piapi"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = ["cmd:ffmpeg", "cmd:ffprobe"]
    install_instructions = (
        "Set PIAPI_API_KEY to your PiAPI API key (https://piapi.ai). Uploading local frames needs a\n"
        "  PiAPI Creator plan or higher. ffmpeg/ffprobe must be installed."
    )
    agent_skills = ["face-swap-piapi"]

    capabilities = ["face_swap"]
    supports = {
        "face_swap": True,
        "full_body_character_replace": False,
        "preview_single_frame": True,
        "resume": True,
        "keeps_original_motion": True,
    }
    best_for = [
        "face swap while PiAPI video face-swap is down (works per frame, $0.01/frame)",
        "a $0.01 single-frame preview to approve the look before paying for a clip",
    ]
    not_good_for = [
        "long clips: cost is per frame (5 s at 24 fps = $1.20)",
        "fast motion where per-frame swaps flicker",
        "changing body, clothes or hairstyle (face only)",
    ]
    fallback_tools = []
    quality_score = 0.65

    input_schema = {
        "type": "object",
        "required": ["target_video_path"],
        "properties": {
            "face_image_url": {"type": "string"},
            "face_image_path": {"type": "string", "description": "Clear, front-facing face (a tight crop works best)."},
            "target_video_path": {"type": "string"},
            "mode": {"type": "string", "enum": ["video", "preview"], "default": "video"},
            "start": {"type": "number", "default": 0, "description": "Range start in seconds."},
            "end": {"type": "number", "description": "Range end in seconds (default: clip end)."},
            "preview_time": {"type": "number", "default": 0, "description": "Preview mode: second to grab."},
            "max_frames": {"type": "integer", "default": DEFAULT_MAX_FRAMES},
            "workers": {"type": "integer", "default": DEFAULT_WORKERS, "minimum": 1, "maximum": 12},
            "work_dir": {"type": "string", "description": "Frame cache; reuse it to resume without paying twice."},
            "dry_run": {"type": "boolean", "default": False},
            "output_path": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(cpu_cores=2, ram_mb=1024, vram_mb=0, disk_mb=2000, network_required=True)
    retry_policy = RetryPolicy(max_retries=0, retryable_errors=[])
    idempotency_key_fields = ["face_image_path", "face_image_url", "target_video_path", "mode", "start", "end",
                              "preview_time"]
    side_effects = ["uploads frames and the face image to PiAPI (24h)", "calls PiAPI API (billed per frame)",
                    "writes output_path and frame cache"]
    user_visible_verification = ["Watch for face flicker between frames and skin-tone seams at the jaw"]

    def _get_api_key(self) -> str | None:
        return piapi_client.get_api_key()

    def get_status(self) -> ToolStatus:
        if not self._get_api_key():
            return ToolStatus.UNAVAILABLE
        if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
            return ToolStatus.DEGRADED
        return ToolStatus.AVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        if inputs.get("mode") == "preview":
            return PRICE_PER_FRAME
        try:
            info = probe_video(inputs["target_video_path"])
            return plan_frames(info, start=inputs.get("start", 0), end=inputs.get("end"),
                               max_frames=int(inputs.get("max_frames", DEFAULT_MAX_FRAMES)))["cost_usd"]
        except Exception:
            return 0.0

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return 120.0 if inputs.get("mode") == "preview" else 600.0

    @staticmethod
    def build_payload(target_url: str, face_url: str) -> dict[str, Any]:
        return {"model": "Qubico/image-toolkit", "task_type": "face-swap",
                "input": {"target_image": target_url, "swap_image": face_url}}

    def swap_image(self, target_path: Path, face_url: str, out_path: Path, api_key: str) -> str:
        """Swap one image with retries. Returns the PiAPI task id of the successful attempt."""
        import requests

        last: Exception | None = None
        for attempt in range(FRAME_ATTEMPTS):
            try:
                target_url = piapi_client.upload(str(target_path), api_key)
                task = piapi_client.run_task(self.build_payload(target_url, face_url), api_key,
                                             label="image face-swap", timeout_s=600, poll_every_s=3)
                output = task.get("output") or {}
                url = output.get("image_url")
                if url:
                    resp = requests.get(url, timeout=120)
                    resp.raise_for_status()
                    data = resp.content
                elif output.get("image_base64"):
                    import base64
                    data = base64.b64decode(output["image_base64"])
                else:
                    raise RuntimeError(f"task {task.get('task_id')} returned no image")
                tmp = out_path.with_suffix(".part")
                tmp.write_bytes(data)
                tmp.replace(out_path)
                return str(task.get("task_id") or "")
            except Exception as e:  # transient upload/download timeouts are common; retry
                last = e
                time.sleep(2 * (attempt + 1))
        raise RuntimeError(str(last) if last else "face swap failed")

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        start_t = time.time()
        progress: Callable[[dict[str, Any]], None] | None = inputs.get("progress_callback")
        cancel: threading.Event | None = inputs.get("cancel_event")
        mode = inputs.get("mode", "video")
        dry_run = bool(inputs.get("dry_run", False))
        api_key = self._get_api_key()
        if not api_key and not dry_run:
            return ToolResult(success=False, error="PIAPI_API_KEY not set. " + self.install_instructions)
        src = inputs.get("target_video_path")
        if not src or not Path(src).exists():
            return ToolResult(success=False, error=f"target video not found: {src}")
        face_path = inputs.get("face_image_path")
        if not (inputs.get("face_image_url") or face_path):
            return ToolResult(success=False, error="face_image_path or face_image_url is required")
        if face_path and not Path(face_path).exists():
            return ToolResult(success=False, error=f"face image not found: {face_path}")
        if mode not in ("video", "preview"):
            return ToolResult(success=False, error="mode must be 'video' or 'preview'")

        try:
            info = probe_video(src)
            if mode == "preview":
                t = min(max(0.0, float(inputs.get("preview_time", 0))), max(0.0, info["duration"] - 0.05))
                plan = plan_frames(info, start=t, end=min(info["duration"], t + 1.0 / (info["fps"] or 24)),
                                   max_frames=1)
            else:
                plan = plan_frames(info, start=inputs.get("start", 0), end=inputs.get("end"),
                                   max_frames=int(inputs.get("max_frames", DEFAULT_MAX_FRAMES)))
        except (ValueError, RuntimeError) as e:
            return ToolResult(success=False, error=f"Invalid face swap request: {e}")
        if dry_run:
            return ToolResult(success=True, data={"dry_run": True, "plan": plan, "source_info": info})

        own_tmp = None
        if inputs.get("work_dir"):
            work = Path(inputs["work_dir"])
        else:
            own_tmp = tempfile.mkdtemp(prefix="face_swap_frames_")
            work = Path(own_tmp)
        try:
            frames_in = work / "frames_in"
            frames_out = work / "frames_out"
            # A cache from a different range/size must not be reused.
            sig = {k: plan[k] for k in ("start", "end", "fps", "frames", "width", "height")}
            sig["source"] = str(Path(src).resolve())
            sig["face"] = inputs.get("face_image_url") or str(Path(face_path).resolve())
            sig_path = work / "plan.json"
            if sig_path.exists() and json.loads(sig_path.read_text() or "{}") != sig:
                shutil.rmtree(frames_in, ignore_errors=True)
                shutil.rmtree(frames_out, ignore_errors=True)
            work.mkdir(parents=True, exist_ok=True)
            sig_path.write_text(json.dumps(sig))
            frames_out.mkdir(parents=True, exist_ok=True)
            frames = extract_frames(src, plan, frames_in)
            todo = [f for f in frames if not (frames_out / f.name).exists()]
            cached = len(frames) - len(todo)

            face_url = inputs.get("face_image_url") or piapi_client.upload(face_path, api_key)
            done, failed, task_ids, errors = cached, [], [], []
            lock = threading.Lock()

            def report() -> None:
                if progress:
                    try:
                        progress({"total": len(frames), "done": done, "failed": len(failed),
                                  "cost_usd": round((done - cached) * PRICE_PER_FRAME, 2)})
                    except Exception:
                        pass

            report()
            workers = max(1, min(12, int(inputs.get("workers", DEFAULT_WORKERS))))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {}
                for f in todo:
                    if cancel and cancel.is_set():
                        break
                    futures[pool.submit(self.swap_image, f, face_url, frames_out / f.name, api_key)] = f
                for fut in as_completed(futures):
                    f = futures[fut]
                    with lock:
                        try:
                            task_ids.append(fut.result())
                            done += 1
                        except Exception as e:
                            failed.append(f.name)
                            errors.append(f"{f.name}: {e}")
                    report()
                    if cancel and cancel.is_set():
                        for other in futures:
                            other.cancel()

            # Second pass: PiAPI's "image download timed out" is usually transient.
            if failed and not (cancel and cancel.is_set()):
                retry, failed, errors = failed, [], []
                for name in retry:
                    try:
                        task_ids.append(self.swap_image(frames_in / name, face_url, frames_out / name, api_key))
                        done += 1
                    except Exception as e:
                        failed.append(name)
                        errors.append(f"{name}: {e}")
                    report()

            paid = done - cached
            cost = round(paid * PRICE_PER_FRAME, 2)
            if cancel and cancel.is_set():
                return ToolResult(success=False, error=f"cancelled after {done}/{len(frames)} frames",
                                  cost_usd=cost, data={"done": done, "total": len(frames), "cost_usd": cost})
            if done == 0:
                return ToolResult(success=False, cost_usd=0.0,
                                  error="no frame could be swapped: " + (errors[0] if errors else "unknown error"))

            if mode == "preview":
                out = Path(inputs.get("output_path") or work / "preview.jpg")
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(frames_out / frames[0].name, out)
                before = out.with_name(f"{out.stem}_before.jpg")
                shutil.copyfile(frames[0], before)
                return ToolResult(
                    success=True,
                    data={"mode": "preview", "output_path": str(out), "before_path": str(before),
                          "time": plan["start"], "task_ids": task_ids, "cost_usd": cost},
                    artifacts=[str(out)], cost_usd=cost, duration_seconds=round(time.time() - start_t, 2),
                    model="Qubico/image-toolkit:face-swap",
                )

            # A frame that never swapped is filled with the nearest swapped frame: a one-frame
            # hold is far less visible than the original face flashing back for 1/fps s.
            names = [f.name for f in frames]
            bad = set(failed)
            for name in failed:
                i = names.index(name)
                near = next((names[j] for d in range(1, len(names)) for j in (i - d, i + d)
                             if 0 <= j < len(names) and names[j] not in bad), None)
                shutil.copyfile(frames_out / near if near else frames_in / name, frames_out / name)
            out = Path(inputs.get("output_path") or "face_swap_frames_output.mp4")
            assemble(frames_out, plan, src if info.get("has_audio") else None, out)
            # Failed frames were copies of the original; drop them so a rerun retries them.
            for name in failed:
                (frames_out / name).unlink(missing_ok=True)
            return ToolResult(
                success=True,
                data={"mode": "video", "output_path": str(out), "plan": plan, "frames": len(frames),
                      "swapped": done, "failed_frames": failed, "errors": errors[:5], "cached_frames": cached,
                      "cost_usd": cost},
                artifacts=[str(out)], cost_usd=cost, duration_seconds=round(time.time() - start_t, 2),
                model="Qubico/image-toolkit:face-swap",
            )
        except Exception as e:
            return ToolResult(success=False, error=f"frame face swap failed: {e}")
        finally:
            if own_tmp:
                shutil.rmtree(own_tmp, ignore_errors=True)
