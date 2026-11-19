"""Võng Giới Tu Tiên control room for Backlot's /tutien page.

Data:  projects/vong-gioi-tu-tien/plan.json — follower counts per platform and the
       12-episode cultivation plan (lesson, goals, styles, render script, status).
Jobs:  renders run the episode's render script (HyperFrames, local, free) and
       commands run a headless Claude Code session (`claude -p`) in the repo.
       Each job writes a log under projects/vong-gioi-tu-tien/.jobs/ and its
       state into jobs.json, so the page can poll progress.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from backlot.state import PROJECTS_DIR, REPO_ROOT

SERIES_ID = "vong-gioi-tu-tien"
PLATFORMS = ("facebook", "tiktok", "youtube")
EP_STATUSES = {
    "planned": "Kế hoạch",
    "scripted": "Có kịch bản",
    "rendering": "Đang render",
    "rendered": "Đã render",
    "posted": "Đã đăng",
}
EP_EDITABLE = ("title", "lesson", "cliffhanger", "status", "post_date", "kpi", "gate", "notes")
# tools a UI command may use: files + the series' own check/render commands
COMMAND_TOOLS = [
    "Read", "Edit", "Write", "Glob", "Grep",
    "Bash(npm run check:*)", "Bash(npx --yes hyperframes@0.9.69:*)", "Bash(npx hyperframes:*)",
    "Bash(./render_versions.sh:*)", "Bash(./render_all.sh:*)", "Bash(./sync_common.sh:*)",
    "Bash(ffmpeg:*)", "Bash(ffprobe:*)", "Bash(ls:*)",
]

_lock = threading.Lock()
_procs: dict[str, subprocess.Popen] = {}


def root() -> Path:
    return PROJECTS_DIR / SERIES_ID


def _plan_path() -> Path:
    return root() / "plan.json"


def _jobs_path() -> Path:
    return root() / ".jobs" / "jobs.json"


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def realm_of(n: int) -> str:
    if n <= 0:
        return "Phàm Nhân"
    if n < 1000:
        return f"Luyện Khí tầng {min(9, -(-n // 111))}"
    for limit, name in ((10_000, "Trúc Cơ"), (100_000, "Kim Đan"), (1_000_000, "Nguyên Anh"), (10_000_000, "Hóa Thần")):
        if n < limit:
            return name
    return "Luyện Hư"


def next_milestone(n: int) -> int:
    for m in (1, 1000, 10_000, 100_000, 1_000_000, 10_000_000):
        if n < m:
            return m
    return 50_000_000


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------

def _videos(ep_n: int) -> dict[str, dict[str, Any]]:
    """Latest rendered file per platform: tap{n}-{platform}-{count}.mp4 (+ -nhe light copy)."""
    out: dict[str, dict[str, Any]] = {}
    pat = re.compile(rf"^tap{ep_n}-({'|'.join(PLATFORMS)})-(\d+)\.mp4$")
    for f in root().glob(f"tap{ep_n}-*.mp4"):
        m = pat.match(f.name)
        if not m:
            continue
        plat = m.group(1)
        st = f.stat()
        if plat in out and out[plat]["mtime"] >= st.st_mtime:
            continue
        light = f.with_name(f.stem + "-nhe.mp4")
        out[plat] = {
            "file": f.name, "count": int(m.group(2)), "mtime": st.st_mtime, "size": st.st_size,
            "light": light.name if light.is_file() else None,
        }
    return out


def get_plan() -> dict[str, Any]:
    plan = _read_json(_plan_path(), None)
    if plan is None:
        raise KeyError("plan.json not found")
    counts = plan.get("counts", {})
    plan["realms"] = {p: {"count": counts.get(p, 0), "realm": realm_of(int(counts.get(p, 0))),
                          "next": next_milestone(int(counts.get(p, 0)))} for p in PLATFORMS}
    running = {(j.get("episode"), j.get("kind")) for j in list_jobs() if j.get("status") == "running"}
    for ep in plan.get("episodes", []):
        ep["videos"] = _videos(ep["n"])
        ep["status_label"] = EP_STATUSES.get(ep.get("status"), ep.get("status"))
        ep["can_render"] = bool(ep.get("render")) and (root() / ep["render"]).is_file()
        ep["rendering_now"] = (ep["n"], "render") in running
    plan["statuses"] = [{"id": k, "label": v} for k, v in EP_STATUSES.items()]
    return plan


def set_counts(counts: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        plan = _read_json(_plan_path(), None)
        if plan is None:
            raise KeyError("plan.json not found")
        for p in PLATFORMS:
            if p in counts:
                v = int(counts[p])
                if v < 0 or v > 1_000_000_000:
                    raise ValueError(f"invalid count for {p}")
                plan["counts"][p] = v
        _write_json(_plan_path(), plan)
    return get_plan()


def update_episode(n: int, fields: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        plan = _read_json(_plan_path(), None)
        if plan is None:
            raise KeyError("plan.json not found")
        ep = next((e for e in plan["episodes"] if e["n"] == n), None)
        if ep is None:
            raise KeyError(f"episode {n}")
        for k, v in fields.items():
            if k in EP_EDITABLE:
                if k == "status" and v not in EP_STATUSES:
                    raise ValueError("invalid status")
                ep[k] = str(v)[:2000]
            elif k == "goals" and isinstance(v, dict):
                for p in PLATFORMS:
                    if p in v:
                        ep.setdefault("goals", {})[p] = int(v[p])
            elif k == "styles" and isinstance(v, dict):
                for p in PLATFORMS:
                    if p in v:
                        ep.setdefault("versions", {}).setdefault(p, {})["style"] = str(v[p])[:120]
        _write_json(_plan_path(), plan)
    return get_plan()


def _set_status(n: int, status: str) -> None:
    with _lock:
        plan = _read_json(_plan_path(), None)
        if not plan:
            return
        for ep in plan["episodes"]:
            if ep["n"] == n and ep.get("status") != "posted":
                ep["status"] = status
        _write_json(_plan_path(), plan)


# ---------------------------------------------------------------------------
# jobs
# ---------------------------------------------------------------------------

def _load_jobs() -> list[dict[str, Any]]:
    return _read_json(_jobs_path(), [])


def _save_job(job: dict[str, Any]) -> None:
    with _lock:
        jobs = [j for j in _load_jobs() if j["id"] != job["id"]]
        jobs.insert(0, job)
        _write_json(_jobs_path(), jobs[:60])


def _tail(path: Path, n: int = 40) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    # drop progress-bar noise
    lines = [ln for ln in lines if ln.strip() and "\r" not in ln[-2:]]
    return "\n".join(lines[-n:])


def list_jobs() -> list[dict[str, Any]]:
    jobs = _load_jobs()
    for j in jobs:
        if j.get("status") == "running" and j["id"] not in _procs:
            j["status"] = "interrupted"   # the server restarted while it ran
        j["log_tail"] = _tail(root() / ".jobs" / f"{j['id']}.log", 30 if j.get("kind") == "command" else 12)
        if j.get("kind") == "command" and "Credit balance is too low" in j["log_tail"]:
            j["hint"] = ("Claude Code CLI trên máy đang đăng nhập bằng API key hết credit. Mở Terminal, chạy `claude`, "
                         "gõ /logout rồi /login và chọn tài khoản Claude (gói Pro/Max) — sau đó gửi lại lệnh.")
    return jobs


def _run(job: dict[str, Any], cmd: list[str], cwd: Path, env: dict[str, str], on_done=None) -> None:
    log_path = root() / ".jobs" / f"{job['id']}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as log:
        log.write("$ " + " ".join(cmd)[:600] + "\n\n")
        log.flush()
        try:
            proc = subprocess.Popen(cmd, cwd=str(cwd), env=env, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        except OSError as e:
            log.write(f"\nKhông chạy được lệnh: {e}\n")
            job.update(status="failed", ended=time.time())
            _save_job(job)
            return
        _procs[job["id"]] = proc
        code = proc.wait()
    _procs.pop(job["id"], None)
    job.update(status="done" if code == 0 else "failed", code=code, ended=time.time())
    _save_job(job)
    if on_done:
        on_done(code)


def _env(plan: dict[str, Any]) -> dict[str, str]:
    env = dict(os.environ)
    for p, meta in plan["platforms"].items():
        env[meta["env"]] = str(int(plan["counts"].get(p, 0)))
    return env


def start_render(n: int, platform: str = "all") -> dict[str, Any]:
    if platform != "all" and platform not in PLATFORMS:
        raise ValueError("invalid platform")
    plan = _read_json(_plan_path(), None)
    if plan is None:
        raise KeyError("plan.json not found")
    ep = next((e for e in plan["episodes"] if e["n"] == n), None)
    if ep is None:
        raise KeyError(f"episode {n}")
    script = (root() / ep.get("render", "")).resolve() if ep.get("render") else None
    if not script or not script.is_file() or root().resolve() not in script.parents:
        raise ValueError(f"Tập {n} chưa có script render — cần dựng tập này trước (ra lệnh cho Claude).")
    if any(j.get("status") == "running" and j.get("kind") == "render" and j.get("episode") == n for j in list_jobs()):
        raise ValueError(f"Tập {n} đang render.")
    job = {"id": "r-" + uuid.uuid4().hex[:8], "kind": "render", "episode": n, "platform": platform,
           "title": f"Render tập {n} — {'tất cả' if platform == 'all' else plan['platforms'][platform]['label']}",
           "status": "running", "started": time.time(), "counts": plan["counts"]}
    _save_job(job)
    _set_status(n, "rendering")

    def done(code: int) -> None:
        _set_status(n, "rendered" if code == 0 else ep.get("status", "planned"))

    threading.Thread(target=_run, args=(job, ["bash", str(script), platform], script.parent, _env(plan), done),
                     daemon=True, name=f"tutien-{job['id']}").start()
    return job


# ---------------------------------------------------------------------------
# captions + hashtags per platform
# ---------------------------------------------------------------------------

SOCIAL_PLATFORM = {"facebook": "facebook_reels", "tiktok": "tiktok", "youtube": "youtube_shorts"}


def _episode_script(ep: dict[str, Any]) -> str:
    rel = ep.get("script") or ""
    if not rel:
        return ""
    path = (root() / rel).resolve()
    if root().resolve() not in path.parents or not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    if rel.endswith("series-bible.md"):   # tập 1 lives inside the bible
        m = re.search(r"## 10\..*?(?=\n## \d+\.|\Z)", text, re.S)
        text = m.group(0) if m else text
    return text[:6000]


def build_post_messages(plan: dict[str, Any], ep: dict[str, Any], platform: str, notes: str = "") -> list[dict[str, Any]]:
    from backlot import social
    rules = social.PLATFORMS[SOCIAL_PLATFORM[platform]]
    meta = plan["platforms"][platform]
    count = int(plan["counts"].get(platform, 0))
    style = (ep.get("versions", {}).get(platform) or {}).get("style") or ""
    system = ("You are a senior short-form social copywriter for a Vietnamese xianxia (tu tiên) animated series. "
              "You write titles, captions and hashtags that stop the scroll without lying. Return ONLY a JSON object.")
    user = f"""Write social copy for episode {ep['n']} of the series “{plan['series']}”.

Series premise: social networks are the cultivation world — follow/subscribe is “tín ngưỡng lực”, the algorithm is “Thiên Đạo”.
The hero Phạm Vô Danh is a nobody creator guided by Lão Tổ (an AI spirit living in his cracked phone). Each episode teaches one real
content-creation lesson disguised as a cultivation technique.

Platform: {rules['label']} (channel: {meta['channel']}, currently {count} {meta['unit']}, realm {realm_of(count)})
Platform rules: {rules['rules']}
Visual style of this version: {style or 'animated'}
Episode title: {ep['title']}
Real lesson (công pháp): {ep['lesson']}
Cliffhanger: {ep['cliffhanger']}
Episode script:
<script>
{_episode_script(ep) or '(no script file)'}
</script>
{('Creator notes: ' + notes.strip()) if notes.strip() else ''}

Requirements:
- Write titles and caption in Vietnamese. Hashtags may mix Vietnamese (no diacritics) and English, no spaces inside a hashtag.
- First line is a hook. Mention it is episode {ep['n']} (“Tập {ep['n']}”) of {plan['series']}.
- End the caption with a call to action to {meta['unit']} “để truyền tín ngưỡng lực” (use the word “{meta['unit']}”).
- The voices are AI-generated: add a short natural note (e.g. “Lồng tiếng AI”) — platforms require disclosure.
- Describe only what the script contains; do not invent plot.
- Always include #tutien and #vonggioitutien; on YouTube always include #Shorts.

JSON shape:
{{"titles": ["option 1", "option 2", "option 3"], "caption": "...", "hashtags": ["#...", "..."]}}"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _store_post(n: int, platform: str, post: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        plan = _read_json(_plan_path(), None)
        if plan is None:
            raise KeyError("plan.json not found")
        ep = next((e for e in plan["episodes"] if e["n"] == n), None)
        if ep is None:
            raise KeyError(f"episode {n}")
        posts = ep.setdefault("posts", {})
        old = posts.get(platform)
        if old and old.get("caption"):
            post.setdefault("history", ((old.get("history") or []) + [{k: old.get(k) for k in ("titles", "caption", "hashtags", "created_at")}])[-5:])
        posts[platform] = post
        _write_json(_plan_path(), plan)
    return post


def generate_posts(n: int, platform: str = "all", notes: str = "") -> dict[str, Any]:
    """Write titles + caption + hashtags with PiAPI's chat API (same path as the Gallery's social copy)."""
    from backlot import social
    from tools import piapi_client
    plats = list(PLATFORMS) if platform == "all" else [platform]
    if any(p not in PLATFORMS for p in plats):
        raise ValueError("invalid platform")
    plan = _read_json(_plan_path(), None)
    if plan is None:
        raise KeyError("plan.json not found")
    ep = next((e for e in plan["episodes"] if e["n"] == n), None)
    if ep is None:
        raise KeyError(f"episode {n}")
    api_key = piapi_client.get_api_key()
    if not api_key:
        raise RuntimeError("PIAPI_API_KEY / PIAPI_KEY chưa được đặt — caption được viết qua PiAPI chat.")
    model = os.environ.get("BACKLOT_COPY_MODEL") or social.DEFAULT_MODEL
    out = {}
    for p in plats:
        reply, usage = social._chat(build_post_messages(plan, ep, p, notes), model, api_key)
        copy = social.parse_copy(reply)
        out[p] = _store_post(n, p, {**copy, "source": "ai", "model": model, "notes": notes, "created_at": time.time(),
                                    "usage": {k: usage.get(k) for k in ("prompt_tokens", "completion_tokens", "total_tokens") if k in usage}})
    return {"episode": n, "posts": out}


def save_post(n: int, platform: str, fields: dict[str, Any]) -> dict[str, Any]:
    if platform not in PLATFORMS:
        raise ValueError("invalid platform")
    titles = [str(t).strip()[:200] for t in (fields.get("titles") or []) if str(t).strip()][:5]
    caption = str(fields.get("caption") or "").strip()[:5000]
    tags: list[str] = []
    for raw in fields.get("hashtags") or []:
        tag = "#" + re.sub(r"\s+", "", str(raw)).lstrip("#")
        if len(tag) > 1 and tag.lower() not in {t.lower() for t in tags}:
            tags.append(tag[:80])
    if not caption:
        raise ValueError("Caption trống.")
    return _store_post(n, platform, {"titles": titles, "caption": caption, "hashtags": tags[:30],
                                     "source": "manual", "created_at": time.time()})


def _clean_env() -> dict[str, str]:
    """A fresh CLI session must use the user's own `claude` login, not the env of whatever
    Claude session happened to launch Backlot (its base URL / auth vars would leak in)."""
    return {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "ANTHROPIC"))}


_auth_cache: dict[str, Any] = {"t": 0.0, "ok": False}


def _cli_logged_in(claude: str, env: dict[str, str]) -> bool:
    if _auth_cache["ok"] and time.time() - _auth_cache["t"] < 300:
        return True
    try:
        out = subprocess.run([claude, "auth", "status"], env=env, capture_output=True, text=True, timeout=30).stdout
        ok = bool(json.loads(out or "{}").get("loggedIn"))
    except (OSError, ValueError, subprocess.SubprocessError):
        ok = False
    _auth_cache.update(t=time.time(), ok=ok)
    return ok


def start_command(text: str, n: Optional[int] = None) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise ValueError("Lệnh trống.")
    claude = shutil.which("claude") or str(Path.home() / ".local/bin/claude")
    if not Path(claude).exists():
        raise ValueError("Không tìm thấy Claude Code CLI (lệnh `claude`).")
    env = _clean_env()
    if not _cli_logged_in(claude, env):
        raise ValueError("Claude Code CLI trên máy chưa đăng nhập. Mở Terminal, chạy `claude` rồi gõ /login "
                         "(hoặc `claude setup-token`), sau đó gửi lại lệnh.")
    plan = _read_json(_plan_path(), {})
    ep = next((e for e in plan.get("episodes", []) if e["n"] == n), None) if n else None
    ctx = [
        "Bạn đang làm series hoạt hình tu tiên “Võng Giới Tu Tiên” trong OpenMontage.",
        f"Thư mục series: projects/{SERIES_ID}/ (series-bible.md, plan.json, tap1/, tap2/ …).",
        "Dựng bằng HyperFrames (HTML/SVG/GSAP) — KHÔNG dùng Seedance/PiAPI. Sau khi sửa composition phải chạy `npm run check` trong thư mục project đó và sửa hết lỗi.",
        "Số follow hiện tại: " + ", ".join(f"{plan['platforms'][p]['label']} {plan['counts'][p]}" for p in PLATFORMS) + "." if plan else "",
        "Không tạo giọng/hình trả phí (ElevenLabs…) trong phiên này; nếu cần thì ghi rõ trong câu trả lời để người dùng duyệt.",
        "Trả lời ngắn gọn bằng tiếng Việt: đã làm gì, file nào đổi, còn gì chưa xong.",
    ]
    if ep:
        ctx.append(f"Tập đang nói tới: tập {ep['n']} “{ep['title']}” — bài học: {ep['lesson']}. Thư mục: projects/{SERIES_ID}/{ep.get('dir') or '(chưa có)'}; script render: {ep.get('render') or '(chưa có)'}.")
    prompt = "\n".join(c for c in ctx if c) + "\n\nYÊU CẦU CỦA NGƯỜI DÙNG:\n" + text[:4000]
    job = {"id": "c-" + uuid.uuid4().hex[:8], "kind": "command", "episode": n, "title": text[:120],
           "status": "running", "started": time.time()}
    _save_job(job)
    cmd = [claude, "-p", prompt, "--permission-mode", "acceptEdits", "--allowedTools", ",".join(COMMAND_TOOLS), "--output-format", "text"]
    threading.Thread(target=_run, args=(job, cmd, REPO_ROOT, env), daemon=True, name=f"tutien-{job['id']}").start()
    return job


def cancel(job_id: str) -> dict[str, Any]:
    proc = _procs.get(job_id)
    if not proc:
        raise KeyError(job_id)
    proc.terminate()
    return {"ok": True}
