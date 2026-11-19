---
name: face-swap-piapi
description: |
  Swap a face from one image onto a person in an existing video with the OpenMontage tool
  `face_swap_piapi` (PiAPI "Qubico/video-toolkit" face-swap, $0.004/frame). Use when re-casting a
  clip you already have with a recurring character's face, keeping motion, body, clothes and
  background unchanged. Not for full-body character replacement.
metadata:
  openclaw:
    requires:
      env:
        - PIAPI_API_KEY
    primaryEnv: PIAPI_API_KEY
---

# Face swap on PiAPI (`face_swap_piapi`)

## What it changes — and what it does not

| Changes | Stays as in the source clip |
|---|---|
| Face identity (eyes, nose, mouth, face shape, skin on the face) | Body, clothes, hair outside the face, hands, background, lighting, camera, motion, timing |

So the source clip must already have the right body, outfit and action. If the user wants a
different outfit, body type, species or art style, this is the wrong tool:

- New outfit / whole character, same motion → generate a new clip with `seedance_piapi`
  `operation: reference_to_video` (character image + up to 3 reference videos for motion).
- True full-body replace keeping the scene (Wan 2.2 Animate `replace`) → not on PiAPI;
  needs a DashScope or fal key. Tell the user instead of improvising.

## Limits (enforced by the tool before paying)

- Output ≤ 600 frames: ~20 s at 30 fps, ~25 s at 24 fps. Longer clips are refused — trim or split.
- Local `target_video_path` is auto-prepared: scaled to ≤ 720p (long side ≤ 1280), fps capped at 30,
  re-encoded to H.264 MP4 under 10 MB. A `target_video_url` must already meet the limits.
- Face image ≤ 2048 px. Local images over 500 KB are auto-shrunk on upload; a small file with a
  long side over 2048 px is sent as-is and rejected — resize it first.
- Local uploads need a PiAPI Creator plan or higher.

## Known issue (2026-11-19)

PiAPI's *video* face-swap failed 3/3 times with "Internal error." — a 5 s 720p clip hit a 15-min
server timeout twice (`context deadline exceeded`), a 1 s 480p clip got a server 500. Failed tasks
are not billed (`usage.consume: 0`). The same faces swapped fine with PiAPI *image* face-swap
(`Qubico/image-toolkit`, $0.01), so the inputs were fine and the video service was the problem.
Before a paid batch, run one 1 s test clip; if it fails, report it to the user instead of retrying in a loop.

## Cost — always quote before running

`frames × $0.004`. Run `dry_run: true` first: it probes and prepares the clip, returns
`frames` and `estimated_cost_usd`, and makes no upload or paid call.

| Clip | Frames | Cost |
|---|---|---|
| 5 s @ 24 fps | 120 | $0.48 |
| 10 s @ 30 fps | 300 | $1.20 |
| 20 s @ 30 fps | 600 | $2.40 |

Show this to the user and wait for a yes before the paid run.

## Face image that works

- One clear, front-facing face, eyes open, neutral or matching expression, even light.
- Similar head angle and skin tone to the person in the video — the neck/jaw seam shows otherwise.
- Photoreal faces work best. Strongly stylized / 3D-cartoon / anime faces are often not detected;
  test a 3–5 s piece first.
- No sunglasses, hands or hair across the face.

## Picking faces when there are several

Indexes are comma-separated and pair up in order:

- `swap_faces_index: "0"`, `target_faces_index: "0"` — first face → first person (default).
- `swap_faces_index: "0,1"`, `target_faces_index: "1,0"` — swap two people at once.

Index order is the detector's, not left-to-right guaranteed. If the wrong person changes, swap the
target index and rerun a short test.

## Call

```python
from tools.tool_registry import registry
tool = registry.get("face_swap_piapi")
tool.execute({
    "face_image_path": "projects/<p>/assets/characters/nova_face.jpg",
    "target_video_path": "projects/<p>/assets/clips/shot03.mp4",
    "dry_run": True,            # first: price + prepare only
    "output_path": "projects/<p>/assets/clips/shot03_swapped.mp4",
})
```

Then the same call with `dry_run: False` after the user approves the price.
`keep_audio: true` (default) puts the source audio back if the result is silent.

## Review the result

Watch it full screen. Check: identity holds on head turns, no flicker on fast motion or
occlusion (hands, hair), neck/jaw skin tone matches, lips still sync with any dialogue.
If it fails on one fast section, cut that section out rather than paying for a full rerun.
