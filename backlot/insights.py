"""Facebook Page analytics for Backlot: snapshots, rule findings, LLM advice.

Snapshots are written by the ``facebook_page_insights`` tool and live outside
``projects/`` (they are not video productions)::

    insights/facebook/<page_id>/<YYYY-MM-DD_HHMMSS>/insights.json
    insights/facebook/<page_id>/<YYYY-MM-DD_HHMMSS>/summary.md
    insights/facebook/<page_id>/<YYYY-MM-DD_HHMMSS>/advice.json   (LLM, optional)

Three jobs:

1. Read: list snapshots and build a view model for one (KPIs with deltas vs
   the previous snapshot, follower series, reels with retention, posts,
   plays per character, reels linked to the Backlot project that made them).
2. Rules: deterministic findings computed from the numbers (no network).
3. Write (explicit user action only): ``refresh`` pulls a new snapshot via
   the Graph API tool; ``generate_advice`` asks an LLM (PiAPI chat, same path
   as ``backlot.social``) for recommendations grounded in the view model.
"""

from __future__ import annotations

import json
import os
import re
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from backlot.state import PROJECTS_DIR, REPO_ROOT

INSIGHTS_DIR = REPO_ROOT / "insights" / "facebook"
SNAPSHOT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{6}$")
DEFAULT_MODEL = "claude-sonnet-4-6"
LANGUAGES = {"vi": "Vietnamese", "en": "English"}

SHORT_REEL_S = 15          # reels at or under this count as "short"
LOW_RETENTION = 0.15       # avg watch / length below this is "low"
HIT_FACTOR = 3.0           # a reel with plays >= HIT_FACTOR x median is a "hit"
MIN_REELS_FOR_TIMING = 15  # fewer reels than this: weekday/hour advice is noise


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _safe_id(value: str, pattern: str = r"^[0-9A-Za-z_-]+$") -> str:
    if not value or not re.match(pattern, value):
        raise ValueError(f"invalid id: {value!r}")
    return value


def snapshot_dir(page_id: str, snap_id: str, root: Optional[Path] = None) -> Path:
    root = root or INSIGHTS_DIR
    _safe_id(page_id)
    if not SNAPSHOT_RE.match(snap_id or ""):
        raise ValueError(f"invalid snapshot id: {snap_id!r}")
    return root / page_id / snap_id


def list_pages(root: Optional[Path] = None) -> list[dict[str, Any]]:
    """Pages with their snapshots, newest snapshot first."""
    root = root or INSIGHTS_DIR
    pages: list[dict[str, Any]] = []
    if not root.is_dir():
        return pages
    for page_dir in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))):
        snaps = []
        for snap in sorted((s for s in page_dir.iterdir() if s.is_dir() and SNAPSHOT_RE.match(s.name)), reverse=True):
            data = _read_json(snap / "insights.json")
            if not data:
                continue
            pi = data.get("page_insights") or {}
            snaps.append({
                "id": snap.name,
                "fetched_at": data.get("fetched_at"),
                "since": pi.get("since"),
                "until": pi.get("until"),
                "posts": len(data.get("posts") or []),
                "reels": len(data.get("reels") or []),
                "has_advice": (snap / "advice.json").is_file(),
            })
        if not snaps:
            continue
        latest = _read_json(page_dir / snaps[0]["id"] / "insights.json") or {}
        page = latest.get("page") or {}
        pages.append({
            "page_id": page_dir.name,
            "name": page.get("name") or page_dir.name,
            "followers": page.get("followers_count"),
            "snapshots": snaps,
        })
    return pages


# ---------------------------------------------------------------------------
# View model
# ---------------------------------------------------------------------------

def _project_captions(projects_dir: Path) -> list[dict[str, str]]:
    """Social captions saved by the Gallery, used to link reels to projects."""
    out: list[dict[str, str]] = []
    if not projects_dir.is_dir():
        return out
    for path in projects_dir.glob("*/artifacts/social/*.json"):
        data = _read_json(path) or {}
        project_dir = path.parents[2]
        title = (_read_json(project_dir / "project.json") or {}).get("title") or project_dir.name
        captions = [data.get("caption")] + [h.get("caption") for h in data.get("history") or []]
        for cap in captions:
            if cap:
                out.append({"project_id": project_dir.name, "project_title": title, "caption": cap})
    return out


def _norm(text: str) -> str:
    return re.sub(r"\W+", " ", (text or "").lower()).strip()


def _match_project(description: str, captions: list[dict[str, str]]) -> Optional[dict[str, str]]:
    desc = _norm(description)
    if len(desc) < 12:
        return None
    head = desc[:60]
    for c in captions:
        cap = _norm(c["caption"])
        if cap and (cap.startswith(head) or desc.startswith(cap[:60])):
            return {"project_id": c["project_id"], "project_title": c["project_title"]}
    return None


def _characters() -> list[dict[str, str]]:
    try:
        from lib import characters as charlib
        return [{"id": c["id"], "name": c["name"]} for c in charlib.list_characters()]
    except Exception:
        return []


def _character_of(text: str, project_id: Optional[str], chars: list[dict[str, str]]) -> Optional[str]:
    hay = f"{text or ''} {project_id or ''}".lower()
    for c in chars:
        first = c["name"].split()[0].lower()
        if re.search(rf"\b({re.escape(first)}|{re.escape(c['id'].lower())})\b", hay):
            return c["name"].split()[0]
    return None


def _num(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) else None


def _reel_rows(data: dict, captions: list, chars: list) -> list[dict[str, Any]]:
    rows = []
    for r in data.get("reels") or []:
        ins = r.get("insights") or {}
        length = _num(r.get("length_s"))
        avg_ms = _num(ins.get("post_video_avg_time_watched"))
        avg_s = avg_ms / 1000 if avg_ms is not None else None
        retention = min(avg_s / length, 1.0) if (avg_s is not None and length) else None
        social = ins.get("post_video_social_actions") or {}
        link = _match_project(r.get("description") or "", captions)
        rows.append({
            "id": r.get("id"),
            "created_time": r.get("created_time"),
            "permalink_url": r.get("permalink_url"),
            "description": r.get("description") or "",
            "length_s": length,
            "plays": _num(r.get("plays")),
            "unique_plays": _num(ins.get("blue_reels_play_count")),
            "avg_watch_s": round(avg_s, 1) if avg_s is not None else None,
            "retention": round(retention, 3) if retention is not None else None,
            "follows": _num(ins.get("post_video_followers")),
            "comments": _num(social.get("COMMENT")) or 0,
            "shares": _num(social.get("SHARE")) or 0,
            "project": link,
            "character": _character_of(r.get("description") or "", (link or {}).get("project_id"), chars),
        })
    # A reel whose caption doesn't name the character inherits it from
    # another reel of the same project.
    by_project = {(r["project"] or {}).get("project_id"): r["character"]
                  for r in rows if r["project"] and r["character"]}
    for r in rows:
        if not r["character"] and r["project"]:
            r["character"] = by_project.get(r["project"]["project_id"])
    rows.sort(key=lambda x: -(x["plays"] or 0))
    return rows


def _post_rows(data: dict, reel_ids: set[str]) -> list[dict[str, Any]]:
    rows = []
    for p in data.get("posts") or []:
        ins = p.get("insights") or {}
        url = p.get("permalink_url") or ""
        reel_id = (re.search(r"/reel/(\d+)", url) or [None, None])[1]
        rows.append({
            "id": p.get("id"),
            "created_time": p.get("created_time"),
            "permalink_url": url,
            "message": p.get("message") or "",
            "media_type": p.get("media_type"),
            "is_reel": bool(reel_id and reel_id in reel_ids) or "/reel/" in url,
            "views": _num(ins.get("post_media_view")),
            "clicks": _num(ins.get("post_clicks")),
            "engagement": p.get("engagement") or 0,
        })
    rows.sort(key=lambda x: -(x["views"] or 0))
    return rows


def _kpis(data: dict, prev: Optional[dict]) -> list[dict[str, Any]]:
    def totals(d: Optional[dict]) -> dict:
        return ((d or {}).get("page_insights") or {}).get("totals") or {}

    def reel_plays(d: Optional[dict]) -> Optional[float]:
        vals = [r.get("plays") for r in (d or {}).get("reels") or [] if isinstance(r.get("plays"), (int, float))]
        return float(sum(vals)) if vals else None

    page, prev_page = data.get("page") or {}, (prev or {}).get("page") or {}
    t, pt = totals(data), totals(prev)
    specs = [
        ("followers", "Follower", _num(page.get("followers_count")), _num(prev_page.get("followers_count"))),
        ("media_views", "Lượt xem nội dung", _num(t.get("page_media_view")), _num(pt.get("page_media_view"))),
        ("reel_plays", "Lượt phát reels", reel_plays(data), reel_plays(prev)),
        ("video_views", "Lượt xem video", _num(t.get("page_video_views")), _num(pt.get("page_video_views"))),
        ("engagements", "Tương tác", _num(t.get("page_post_engagements")), _num(pt.get("page_post_engagements"))),
        ("new_follows", "Follow mới", _num(t.get("page_daily_follows_unique")), _num(pt.get("page_daily_follows_unique"))),
    ]
    return [
        {"id": i, "label": label, "value": v,
         "delta": (v - p) if (prev is not None and v is not None and p is not None) else None}
        for i, label, v, p in specs if v is not None
    ]


def _by_character(reels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    agg: dict[str, dict[str, float]] = {}
    for r in reels:
        key = r["character"] or "Khác"
        a = agg.setdefault(key, {"plays": 0.0, "reels": 0, "follows": 0.0})
        a["plays"] += r["plays"] or 0
        a["reels"] += 1
        a["follows"] += r["follows"] or 0
    rows = [{"character": k, **v, "avg_plays": round(v["plays"] / v["reels"], 1)} for k, v in agg.items()]
    return sorted(rows, key=lambda x: -x["plays"])


def _previous_snapshot(page_id: str, snap_id: str, root: Path) -> Optional[dict]:
    page_dir = root / page_id
    older = sorted((s.name for s in page_dir.iterdir() if s.is_dir() and SNAPSHOT_RE.match(s.name) and s.name < snap_id),
                   reverse=True)
    for name in older:
        data = _read_json(page_dir / name / "insights.json")
        if data:
            return {**data, "_id": name}
    return None


def build_view(page_id: str, snap_id: str, root: Optional[Path] = None,
               projects_dir: Optional[Path] = None) -> dict[str, Any]:
    root = root or INSIGHTS_DIR
    d = snapshot_dir(page_id, snap_id, root)
    data = _read_json(d / "insights.json")
    if data is None:
        raise FileNotFoundError(f"{page_id}/{snap_id}")
    prev = _previous_snapshot(page_id, snap_id, root)
    captions = _project_captions(projects_dir or PROJECTS_DIR)
    chars = _characters()
    reels = _reel_rows(data, captions, chars)
    posts = _post_rows(data, {r["id"] for r in reels if r["id"]})
    daily = ((data.get("page_insights") or {}).get("daily") or {})
    view = {
        "page_id": page_id,
        "snapshot_id": snap_id,
        "previous_snapshot_id": (prev or {}).get("_id"),
        "fetched_at": data.get("fetched_at"),
        "page": data.get("page") or {},
        "period": {k: (data.get("page_insights") or {}).get(k) for k in ("since", "until")},
        "kpis": _kpis(data, prev),
        "followers_daily": [
            {"date": (p.get("date") or "")[:10], "value": p.get("value")}
            for p in daily.get("page_follows") or [] if isinstance(p.get("value"), (int, float))
        ],
        "reels": reels,
        "posts": posts,
        "by_character": _by_character(reels),
        "warnings": data.get("warnings") or [],
        "rejected_metrics": sorted(data.get("rejected_metrics") or {}),
        "advice": _read_json(d / "advice.json"),
    }
    view["findings"] = findings(view)
    return view


def stats_by_project(root: Optional[Path] = None, projects_dir: Optional[Path] = None) -> dict[str, dict[str, Any]]:
    """Reel stats per Backlot project from each Page's latest snapshot.

    A project with several reels gets the one with the most plays. Used by the
    series wiki to show how each episode performed.
    """
    root = root or INSIGHTS_DIR
    out: dict[str, dict[str, Any]] = {}
    pages = list_pages(root)
    if not pages:
        return out
    captions = _project_captions(projects_dir or PROJECTS_DIR)
    chars = _characters()
    for page in pages:
        snap = page["snapshots"][0]["id"]
        data = _read_json(root / page["page_id"] / snap / "insights.json") or {}
        for r in _reel_rows(data, captions, chars):
            if not r["project"]:
                continue
            pid = r["project"]["project_id"]
            if pid in out and (out[pid]["plays"] or 0) >= (r["plays"] or 0):
                continue
            out[pid] = {k: r[k] for k in ("plays", "retention", "avg_watch_s", "length_s", "follows",
                                          "comments", "permalink_url", "created_time")}
            out[pid].update({"page_id": page["page_id"], "page_name": page["name"], "snapshot_id": snap})
    return out


# ---------------------------------------------------------------------------
# Rule findings (deterministic)
# ---------------------------------------------------------------------------

def _pct(x: float) -> str:
    return f"{round(x * 100)}%"


def findings(view: dict[str, Any]) -> list[dict[str, Any]]:
    """Each finding: {id, level: good|warn|info, title, detail}. Vietnamese copy."""
    out: list[dict[str, Any]] = []
    reels = [r for r in view["reels"] if r["plays"] is not None]
    posts = view["posts"]

    # 1. Short vs long retention.
    short = [r["retention"] for r in reels if r["retention"] is not None and r["length_s"] and r["length_s"] <= SHORT_REEL_S]
    long_ = [r["retention"] for r in reels if r["retention"] is not None and r["length_s"] and r["length_s"] > SHORT_REEL_S]
    if short and long_:
        s, l = statistics.mean(short), statistics.mean(long_)
        if s >= 1.5 * l:
            out.append({"id": "short_wins", "level": "good",
                        "title": f"Reel ≤{SHORT_REEL_S}s giữ người xem tốt gấp {s / l:.1f} lần",
                        "detail": f"Tỉ lệ xem hết trung bình: reel ngắn {_pct(s)} ({len(short)} reel) so với reel dài "
                                  f"{_pct(l)} ({len(long_)} reel). Ưu tiên làm reel 8–{SHORT_REEL_S} giây."})
        elif l >= 1.5 * s:
            out.append({"id": "long_wins", "level": "info",
                        "title": "Reel dài đang giữ người xem tốt hơn reel ngắn",
                        "detail": f"Tỉ lệ xem hết: dài {_pct(l)} so với ngắn {_pct(s)}."})

    # 2. A hit reel.
    if len(reels) >= 3:
        med = statistics.median(r["plays"] for r in reels)
        top = reels[0]
        if med and top["plays"] >= HIT_FACTOR * med:
            total = sum(r["plays"] for r in reels)
            who = top["project"]["project_title"] if top["project"] else (top["character"] or "reel này")
            out.append({"id": "hit", "level": "good",
                        "title": f"Reel thắng lớn: {who}",
                        "detail": f"{int(top['plays'])} lượt phát, gấp {top['plays'] / med:.0f} lần trung vị và chiếm "
                                  f"{_pct(top['plays'] / total)} tổng lượt phát reels"
                                  + (f", dài {top['length_s']:.0f}s, xem hết {_pct(top['retention'])}" if top["retention"] is not None else "")
                                  + ". Làm tiếp các tập cùng công thức.",
                        "reel_id": top["id"]})

    # 3. Who brings followers.
    gained = [r for r in reels if (r["follows"] or 0) > 0]
    total_follows = sum(r["follows"] for r in gained)
    if gained:
        by_char: dict[str, float] = {}
        for r in gained:
            by_char[r["character"] or "Khác"] = by_char.get(r["character"] or "Khác", 0) + r["follows"]
        lead, n = max(by_char.items(), key=lambda kv: kv[1])
        if total_follows and n / total_follows >= 0.6 and lead != "Khác":
            out.append({"id": "follow_driver", "level": "good",
                        "title": f"{lead} kéo được {_pct(n / total_follows)} follower mới từ reels",
                        "detail": f"{int(n)}/{int(total_follows)} follow mới đến từ reel có {lead}. "
                                  f"Cân nhắc làm series xoay quanh {lead}."})

    # 4. Low-retention reels.
    weak = [r for r in reels if r["retention"] is not None and r["retention"] < LOW_RETENTION]
    if weak:
        names = ", ".join((r["project"] or {}).get("project_title") or r["description"][:30] or r["id"] for r in weak[:3])
        out.append({"id": "low_retention", "level": "warn",
                    "title": f"{len(weak)} reel bị bỏ xem sớm (xem hết < {_pct(LOW_RETENTION)})",
                    "detail": f"{names}. Cắt ngắn, đưa cảnh mạnh nhất lên giây đầu, hoặc tách thành nhiều phần."})

    # 5. Conversation.
    plays = sum(r["plays"] for r in reels)
    convo = sum((r["comments"] or 0) + (r["shares"] or 0) for r in reels)
    if plays >= 500 and convo / plays < 0.005:
        out.append({"id": "low_conversation", "level": "warn",
                    "title": "Có lượt xem nhưng gần như không ai bình luận hay chia sẻ",
                    "detail": f"{int(convo)} bình luận + chia sẻ trên {int(plays)} lượt phát "
                              f"({convo / plays * 100:.2f}%). Thêm câu hỏi ở caption hoặc cuối video."})

    # 6. Off-niche content: non-reel posts far below reel median views.
    reel_views = [p["views"] for p in posts if p["is_reel"] and p["views"]]
    others = [p for p in posts if not p["is_reel"] and p["views"] is not None]
    if reel_views and others:
        med = statistics.median(reel_views)
        low = [p for p in others if p["views"] < 0.3 * med]
        if low and len(low) >= len(others) / 2:
            out.append({"id": "off_niche", "level": "warn",
                        "title": f"{len(low)} bài không phải reel có lượt xem rất thấp",
                        "detail": f"Trung bình {statistics.mean(p['views'] for p in low):.0f} lượt xem, so với trung vị "
                                  f"reels {med:.0f}. Nếu là nội dung khác chủ đề (ví dụ bán hàng), tách sang Page khác."})

    # 7. Small sample.
    times = sorted(r["created_time"] for r in reels if r["created_time"])
    span_days = None
    if len(times) >= 2:
        try:
            a = datetime.fromisoformat(times[0].replace("+0000", "+00:00"))
            b = datetime.fromisoformat(times[-1].replace("+0000", "+00:00"))
            span_days = (b - a).days
        except ValueError:
            pass
    if len(reels) < MIN_REELS_FOR_TIMING:
        out.append({"id": "small_sample", "level": "info",
                    "title": "Dữ liệu còn ít, chưa nên kết luận về ngày/giờ đăng",
                    "detail": f"Mới có {len(reels)} reel"
                              + (f" trong {span_days} ngày" if span_days is not None else "")
                              + f". Cần khoảng {MIN_REELS_FOR_TIMING}+ reel. Reels mới đăng vẫn còn đang tăng lượt xem."})

    # 8. Follower growth vs previous snapshot.
    fk = next((k for k in view["kpis"] if k["id"] == "followers"), None)
    if fk and fk["delta"] is not None and fk["delta"] != 0:
        out.append({"id": "follower_delta", "level": "good" if fk["delta"] > 0 else "warn",
                    "title": f"Follower {'+' if fk['delta'] > 0 else ''}{int(fk['delta'])} so với lần trước",
                    "detail": f"Từ {int(fk['value'] - fk['delta'])} lên {int(fk['value'])}."})
    return out


# ---------------------------------------------------------------------------
# Refresh (Graph API) — explicit user action
# ---------------------------------------------------------------------------

def refresh(days: int = 90, root: Optional[Path] = None) -> dict[str, Any]:
    """Pull a new snapshot for FACEBOOK_PAGE_ID (or the token's Page)."""
    from tools.analysis.facebook_page_insights import FacebookPageInsights

    root = root or INSIGHTS_DIR
    days = max(1, min(int(days), 730))
    tool = FacebookPageInsights()
    if tool.get_status().value != "available":
        raise RuntimeError("FACEBOOK_PAGE_ACCESS_TOKEN is not set in .env")
    snap_id = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    staging = root / "_staging" / snap_id
    result = tool.execute({"operation": "report", "days": days, "max_items": 500, "output_dir": str(staging)})
    if not result.success:
        raise RuntimeError(result.error or "Graph API call failed")
    page_id = _safe_id(str(result.data.get("page_id") or ""))
    target = root / page_id / snap_id
    target.parent.mkdir(parents=True, exist_ok=True)
    staging.replace(target)
    return {"page_id": page_id, "snapshot_id": snap_id}


# ---------------------------------------------------------------------------
# LLM advice — explicit user action
# ---------------------------------------------------------------------------

def _compact(view: dict[str, Any]) -> dict[str, Any]:
    """The facts the model sees: small, numeric, no URLs."""
    return {
        "page": {k: view["page"].get(k) for k in ("name", "followers_count", "category")},
        "period": view["period"],
        "kpis": [{k: x[k] for k in ("label", "value", "delta")} for x in view["kpis"]],
        "reels": [
            {k: r[k] for k in ("created_time", "length_s", "plays", "avg_watch_s", "retention",
                               "follows", "comments", "shares", "character")}
            | {"project": (r["project"] or {}).get("project_title"), "caption": r["description"][:160]}
            for r in view["reels"][:30]
        ],
        "non_reel_posts": [
            {k: p[k] for k in ("created_time", "media_type", "views", "engagement")} | {"text": p["message"][:120]}
            for p in view["posts"] if not p["is_reel"]
        ][:15],
        "by_character": view["by_character"],
        "rule_findings": [{k: f[k] for k in ("title", "detail")} for f in view["findings"]],
        "data_warnings": view["warnings"],
    }


def build_messages(view: dict[str, Any], language: str = "vi", notes: str = "") -> list[dict[str, str]]:
    lang = LANGUAGES[language]
    chars = ", ".join(c["name"] for c in _characters()) or "(none)"
    system = (
        "You are a short-form video growth strategist for a Facebook Page that posts AI-generated "
        "cinematic reels. You give specific, testable recommendations grounded only in the data you "
        "are given. Never invent numbers. Say when the sample is too small. Return ONLY a JSON object, "
        "no markdown fences."
    )
    user = f"""Analyse this Facebook Page snapshot and recommend what to make next.

Write everything in {lang}.
Recurring characters available in the creator's library: {chars}.
{('Creator notes: ' + notes.strip()) if notes.strip() else ''}

Data (retention = average watch time / reel length; plays are lifetime plays so far):
<data>
{json.dumps(_compact(view), ensure_ascii=False, indent=1)}
</data>

Requirements:
- 3 to 6 recommendations, most impactful first. Each must cite the numbers it is based on.
- Each recommendation has a concrete action the creator can do this week.
- 2 to 4 next video ideas that reuse what worked (character, length, hook), each with a target length in seconds and the hook in the first 2 seconds.
- Note the main caveats (sample size, reels still accumulating plays, missing metrics).

JSON shape:
{{"summary": "2-3 sentences",
  "recommendations": [{{"title": "...", "why": "evidence with numbers", "action": "...", "priority": "high|medium|low"}}],
  "next_videos": [{{"title": "...", "character": "...", "length_s": 10, "hook": "...", "why": "..."}}],
  "caveats": ["..."]}}"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse_advice(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        raise ValueError("model reply contained no JSON object")
    data = json.loads(match.group(0))
    recs = []
    for r in data.get("recommendations") or []:
        if not isinstance(r, dict) or not str(r.get("title") or "").strip():
            continue
        prio = str(r.get("priority") or "medium").lower()
        recs.append({
            "title": str(r["title"]).strip(),
            "why": str(r.get("why") or "").strip(),
            "action": str(r.get("action") or "").strip(),
            "priority": prio if prio in {"high", "medium", "low"} else "medium",
        })
    vids = []
    for v in data.get("next_videos") or []:
        if not isinstance(v, dict) or not str(v.get("title") or "").strip():
            continue
        length = v.get("length_s")
        vids.append({
            "title": str(v["title"]).strip(),
            "character": str(v.get("character") or "").strip(),
            "length_s": length if isinstance(length, (int, float)) else None,
            "hook": str(v.get("hook") or "").strip(),
            "why": str(v.get("why") or "").strip(),
        })
    if not recs:
        raise ValueError("model reply had no recommendations")
    return {
        "summary": str(data.get("summary") or "").strip(),
        "recommendations": recs[:8],
        "next_videos": vids[:6],
        "caveats": [str(c).strip() for c in data.get("caveats") or [] if str(c).strip()][:6],
    }


def generate_advice(page_id: str, snap_id: str, *, language: str = "vi", notes: str = "",
                    model: Optional[str] = None, root: Optional[Path] = None,
                    projects_dir: Optional[Path] = None) -> dict[str, Any]:
    if language not in LANGUAGES:
        raise ValueError(f"unknown language {language!r}")
    from backlot import social
    from tools import piapi_client

    api_key = piapi_client.get_api_key()
    if not api_key:
        raise RuntimeError("PIAPI_API_KEY / PIAPI_KEY is not set; advice is written via PiAPI's chat API")
    root = root or INSIGHTS_DIR
    view = build_view(page_id, snap_id, root, projects_dir)
    model = model or os.environ.get("BACKLOT_INSIGHTS_MODEL") or os.environ.get("BACKLOT_COPY_MODEL") or DEFAULT_MODEL
    reply, usage = social._chat(build_messages(view, language, notes), model, api_key)
    advice = parse_advice(reply)

    path = snapshot_dir(page_id, snap_id, root) / "advice.json"
    existing = _read_json(path) or {}
    history = (existing.get("history") or [])[-4:]
    if existing.get("recommendations"):
        history.append({k: existing.get(k) for k in ("summary", "recommendations", "next_videos", "caveats",
                                                     "model", "language", "created_at")})
    record = {
        **advice, "language": language, "notes": notes, "model": model,
        "usage": {k: usage.get(k) for k in ("prompt_tokens", "completion_tokens", "total_tokens") if k in usage},
        "created_at": time.time(), "history": history,
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return record
