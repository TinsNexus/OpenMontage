"""Facebook Insights tab: snapshots, view model, rule findings, LLM advice (no network)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backlot import insights as ins
from backlot import server as server_mod
from backlot import state as state_mod

H = {"X-Backlot-Action": "insights"}
PAGE = "111"


def _reel(rid, plays, length, avg_ms, follows=0, desc="", comments=0):
    return {
        "id": rid, "created_time": "2026-11-14T14:15:18+0000", "permalink_url": f"https://www.facebook.com/reel/{rid}/",
        "description": desc, "length_s": length, "plays": plays,
        "insights": {"post_video_avg_time_watched": avg_ms, "post_video_followers": follows,
                     "post_video_social_actions": {"COMMENT": comments} if comments else {}},
    }


def _snapshot(root: Path, snap_id: str, followers: int, reels: list, posts=None, page_follows=None) -> Path:
    d = root / PAGE / snap_id
    d.mkdir(parents=True)
    data = {
        "page_id": PAGE, "fetched_at": "2026-11-15T03:57:01+00:00",
        "page": {"id": PAGE, "name": "Tisorr", "followers_count": followers},
        "page_insights": {"since": "2026-08-17", "until": "2026-11-15",
                          "totals": {"page_media_view": 5917, "page_post_engagements": 50},
                          "daily": {"page_follows": page_follows or [
                              {"date": "2026-11-13T08:00:00+0000", "value": 8},
                              {"date": "2026-11-14T08:00:00+0000", "value": followers}]}},
        "reels": reels, "posts": posts or [], "warnings": [], "rejected_metrics": {"page_fan_adds": "x"},
    }
    (d / "insights.json").write_text(json.dumps(data), encoding="utf-8")
    return d


@pytest.fixture
def roots(tmp_path, monkeypatch):
    insights_root = tmp_path / "insights"
    projects = tmp_path / "projects"
    social = projects / "sasa-bar-fight" / "artifacts" / "social"
    social.mkdir(parents=True)
    (projects / "sasa-bar-fight" / "project.json").write_text(json.dumps({"title": "Sasa — Bar Fight"}))
    (social / "renders__final.mp4.json").write_text(json.dumps(
        {"caption": "Sasa clears a VIP bar room — five fighters, no hesitation."}))
    monkeypatch.setattr(ins, "INSIGHTS_DIR", insights_root)
    monkeypatch.setattr(ins, "PROJECTS_DIR", projects)
    monkeypatch.setattr(ins, "_characters", lambda: [{"id": "sasa", "name": "Sasa"}, {"id": "mia", "name": "Mia"},
                                                     {"id": "vy", "name": "Vy"}])
    return insights_root, projects


REELS = [
    _reel("r1", 3990, 10, 6092, follows=9, desc="Sasa clears a VIP bar room — five fighters, no hesitation."),
    _reel("r2", 633, 20, 6000, desc="Mia's having a night out"),
    _reel("r3", 233, 30, 3700, desc="Vy just wants to make her drop-off", comments=2),
    _reel("r4", 214, 27, 2400, desc="zeigarnik"),
    _reel("r5", 217, 20, 5600, follows=1, desc="Mia's street BBQ date"),
]


def test_view_links_projects_characters_and_retention(roots):
    root, _ = roots
    _snapshot(root, "2026-11-15_120000", 24, REELS)
    v = ins.build_view(PAGE, "2026-11-15_120000")

    top = v["reels"][0]
    assert top["id"] == "r1" and top["project"]["project_id"] == "sasa-bar-fight"
    assert top["character"] == "Sasa" and top["retention"] == pytest.approx(0.609, abs=0.001)
    assert v["by_character"][0] == {"character": "Sasa", "plays": 3990.0, "reels": 1, "follows": 9.0, "avg_plays": 3990.0}
    assert {k["id"] for k in v["kpis"]} >= {"followers", "media_views", "reel_plays"}
    assert v["followers_daily"][-1] == {"date": "2026-11-14", "value": 24}


def test_findings_flag_short_wins_hit_driver_and_low_retention(roots):
    root, _ = roots
    _snapshot(root, "2026-11-15_120000", 24, REELS)
    ids = {f["id"]: f for f in ins.build_view(PAGE, "2026-11-15_120000")["findings"]}

    assert {"short_wins", "hit", "follow_driver", "low_retention", "low_conversation", "small_sample"} <= set(ids)
    assert "Sasa" in ids["follow_driver"]["title"]
    assert "zeigarnik" in ids["low_retention"]["detail"]


def test_kpi_delta_against_previous_snapshot(roots):
    root, _ = roots
    _snapshot(root, "2026-11-08_120000", 7, REELS[:2])
    _snapshot(root, "2026-11-15_120000", 24, REELS)
    v = ins.build_view(PAGE, "2026-11-15_120000")

    followers = next(k for k in v["kpis"] if k["id"] == "followers")
    assert followers["delta"] == 17 and v["previous_snapshot_id"] == "2026-11-08_120000"
    assert any(f["id"] == "follower_delta" for f in v["findings"])
    pages = ins.list_pages()
    assert [s["id"] for s in pages[0]["snapshots"]] == ["2026-11-15_120000", "2026-11-08_120000"]


def test_snapshot_ids_are_validated(roots):
    with pytest.raises(ValueError):
        ins.snapshot_dir(PAGE, "../../etc")
    with pytest.raises(ValueError):
        ins.snapshot_dir("../x", "2026-11-15_120000")


def test_parse_advice_normalises():
    reply = 'Sure!\n{"summary": "S", "recommendations": [{"title": "Short reels", "why": "60% vs 19%", ' \
            '"action": "Cut to 10s", "priority": "URGENT"}, {"title": ""}], ' \
            '"next_videos": [{"title": "Sasa ep 2", "character": "Sasa", "length_s": 10, "hook": "kick"}], "caveats": ["small"]}'
    a = ins.parse_advice(reply)
    assert [r["title"] for r in a["recommendations"]] == ["Short reels"]
    assert a["recommendations"][0]["priority"] == "medium"
    assert a["next_videos"][0]["length_s"] == 10 and a["caveats"] == ["small"]
    with pytest.raises(ValueError):
        ins.parse_advice('{"recommendations": []}')


def test_generate_advice_saves_with_history(roots, monkeypatch):
    root, _ = roots
    d = _snapshot(root, "2026-11-15_120000", 24, REELS)
    from backlot import social
    from tools import piapi_client

    seen = {}

    def fake_chat(messages, model, api_key):
        seen["prompt"] = messages[1]["content"]
        return json.dumps({"summary": "ok", "recommendations": [{"title": "Make Sasa series", "priority": "high"}]}), \
            {"total_tokens": 1234}

    monkeypatch.setattr(piapi_client, "get_api_key", lambda: "k")
    monkeypatch.setattr(social, "_chat", fake_chat)

    ins.generate_advice(PAGE, "2026-11-15_120000")
    rec = ins.generate_advice(PAGE, "2026-11-15_120000", language="en", notes="grow to 1k")

    assert "Vietnamese" not in seen["prompt"] and "grow to 1k" in seen["prompt"]
    assert "facebook.com" not in seen["prompt"]  # no URLs sent to the model
    assert rec["usage"]["total_tokens"] == 1234 and len(rec["history"]) == 1
    assert json.loads((d / "advice.json").read_text())["language"] == "en"
    assert ins.build_view(PAGE, "2026-11-15_120000")["advice"]["summary"] == "ok"


@pytest.fixture
def client(roots, tmp_path, monkeypatch):
    projects_root = tmp_path / "projects"
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", projects_root)
    monkeypatch.setattr(server_mod, "PROJECTS_DIR", projects_root)
    monkeypatch.setattr(server_mod, "_summary_cache", {})

    async def no_watch():
        return None

    monkeypatch.setattr(server_mod, "_watch_projects", no_watch)
    with TestClient(server_mod.create_app()) as c:
        yield c


def test_api_routes(client, roots, monkeypatch):
    root, _ = roots
    _snapshot(root, "2026-11-15_120000", 24, REELS)

    assert "insights.js" in client.get("/insights").text
    data = client.get("/api/insights").json()
    assert data["pages"][0]["page_id"] == PAGE
    view = client.get(f"/api/insights/{PAGE}/2026-11-15_120000").json()
    assert view["reels"][0]["id"] == "r1"
    assert client.get(f"/api/insights/{PAGE}/2026-01-01_000000").status_code == 404
    assert client.get(f"/api/insights/{PAGE}/bad").status_code == 422

    # Writes / paid calls need the action header.
    assert client.post("/api/insights/refresh", json={}).status_code == 403
    assert client.post(f"/api/insights/{PAGE}/2026-11-15_120000/advice", json={}).status_code == 403

    def boom(days):
        raise RuntimeError("FACEBOOK_PAGE_ACCESS_TOKEN is not set in .env")

    monkeypatch.setattr(ins, "refresh", boom)
    r = client.post("/api/insights/refresh", headers=H, json={"days": 28})
    assert r.status_code == 502 and "FACEBOOK" in r.json()["detail"]


def test_refresh_moves_snapshot_under_page_id(roots, monkeypatch):
    root, _ = roots
    from tools.analysis import facebook_page_insights as fpi
    from tools.base_tool import ToolResult, ToolStatus

    def fake_execute(self, inputs):
        out = Path(inputs["output_dir"])
        out.mkdir(parents=True)
        (out / "insights.json").write_text(json.dumps({"page": {"name": "Tisorr"}, "reels": []}))
        return ToolResult(success=True, data={"page_id": PAGE})

    monkeypatch.setattr(fpi.FacebookPageInsights, "execute", fake_execute)
    monkeypatch.setattr(fpi.FacebookPageInsights, "get_status", lambda self: ToolStatus.AVAILABLE)

    r = ins.refresh(days=28)

    assert r["page_id"] == PAGE
    assert (root / PAGE / r["snapshot_id"] / "insights.json").is_file()
    assert [p["page_id"] for p in ins.list_pages()] == [PAGE]  # _staging is not a page
