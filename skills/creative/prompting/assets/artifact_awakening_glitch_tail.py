"""Reference-style glitch ending: black → overexposed → smear → stutter → RGB/band tear → colour streaks.

usage: glitch_tail.py <clip.mp4> <start_s> <out.mp4> [WxH]
Writes <out.mp4> (default 720x1280, 24 fps) covering start_s..start_s+0.75.
"""
import subprocess
import sys

import numpy as np
from PIL import Image, ImageFilter

clip, start, out = sys.argv[1], float(sys.argv[2]), sys.argv[3]
W, H = (int(v) for v in (sys.argv[4] if len(sys.argv) > 4 else "720x1280").split("x"))
FPS, N = 24, 18
rng = np.random.default_rng(7)

# Grab N frames before start too, for the stutter repeat.
raw = subprocess.run(
    ["ffmpeg", "-v", "error", "-ss", f"{start - 0.25:.3f}", "-i", clip, "-frames:v", str(N + 6),
     "-vf", f"scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
    check=True, capture_output=True).stdout
frames = np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3)
src = list(frames[6:]) + [frames[-1]] * N   # frames from `start` on
early = frames[:6]                           # 0.25s earlier, for stutter


def smear(f, k=60):
    im = Image.fromarray(f).filter(ImageFilter.BoxBlur(2))
    a = np.asarray(im).astype(np.float32)
    acc = np.zeros_like(a)
    for s in range(0, k, 6):
        acc += np.roll(a, s, axis=1)
    return np.clip(acc / len(range(0, k, 6)) * 1.15, 0, 255).astype(np.uint8)


def rgb_split(f, d):
    o = f.copy()
    o[..., 0] = np.roll(f[..., 0], d, axis=1)
    o[..., 2] = np.roll(f[..., 2], -d, axis=1)
    return o


def tear(f, strength):
    o = f.copy()
    y = 0
    while y < H:
        h = int(rng.integers(8, 70))
        if rng.random() < 0.55:
            o[y:y + h] = np.roll(f[y:y + h], int(rng.integers(-1, 2) * rng.integers(20, 40 + 220 * strength)), axis=1)
        y += h
    return o


def streaks(f):
    # Each band takes one column's colours and stretches it across the row → colour streaks.
    o = np.empty_like(f)
    y = 0
    sat = np.clip((f.astype(np.int16) - 128) * 1.8 + 128, 0, 255).astype(np.uint8)
    while y < H:
        h = int(rng.integers(3, 18))
        col = int(rng.integers(0, W))
        band = sat[y:y + h, col:col + 1]
        o[y:y + h] = np.repeat(band, W, axis=1)
        if rng.random() < 0.35:   # keep some torn picture between streaks
            o[y:y + h] = np.roll(f[y:y + h], int(rng.integers(-200, 200)), axis=1)
        y += h
    noise = rng.integers(-40, 40, o.shape, dtype=np.int16)
    return np.clip(o.astype(np.int16) + noise, 0, 255).astype(np.uint8)


seq = []
for i in range(N):
    f = src[i]
    if i == 0:
        g = np.zeros_like(f)                                            # hard black
    elif i == 1:
        g = np.clip(f.astype(np.float32) * 1.9 + 60, 0, 255).astype(np.uint8)  # overexposed
    elif i in (2, 3):
        g = smear(f, 90)                                                # motion smear
    elif i in (4, 5):
        g = early[i]                                                    # stutter back
    elif i == 6:
        g = np.full_like(f, 255)                                        # white pop
    elif i < 11:
        s = (i - 6) / 5
        g = tear(rgb_split(f, int(8 + 30 * s)), s)
    elif i < 15:
        g = tear(rgb_split(smear(f, 40), 40), 1.0)
    else:
        g = streaks(f)
    seq.append(g)

enc = subprocess.Popen(
    ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
     "-i", "-", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", out],
    stdin=subprocess.PIPE)
enc.stdin.write(b"".join(np.ascontiguousarray(x).tobytes() for x in seq))
enc.stdin.close()
enc.wait()
