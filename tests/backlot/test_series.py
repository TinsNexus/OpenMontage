"""Series wiki: storage (lib.series) and Backlot /api/series routes."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backlot import insights as insightslib
from backlot import server as server_mod
from backlot import state as state_mod
from lib import backlog as backlog_mod
from lib import series as ser

H = {"X-Backlot-Action": "series"}


@pytest.fixture
def series_root(tmp_path, monkeypatch):
    root = tmp_path / "series"
    monkeypatch.setenv("OPENMONTAGE_SERIES_DIR", str(root))
    monkeypatch.setattr(backlog_mod, "BACKLOG_FILE", tmp_path / "backlog" / "backlog.json")
    return root


def test_create_series_seeds_wiki_pages(series_root):
    sr = ser.create_series("Sasa — Đêm không ngủ", logline="Một đêm, năm trận", characters="sasa, sasa, mia")

    assert sr["id"] == "sasa-dem-khong-ngu"
    assert sr["characters"] == ["sasa", "mia"]
    assert [p["slug"] for p in sr["pages"]][0] == "tong-quan"
    assert {p["title"] for p in sr["pages"]} == {"Tổng quan", "Thế giới", "Nhân vật", "Bối cảnh"}
    assert "Một đêm, năm trận" in ser.read_page(sr["id"], "tong-quan")["text"]
    assert ser.create_series("Sasa — Đêm không ngủ")["id"] == "sasa-dem-khong-ngu-2"
    assert [s["id"] for s in ser.list_series()] == ["sasa-dem-khong-ngu-2", "sasa-dem-khong-ngu"]


def test_pages_create_update_delete(series_root):
    sid = ser.create_series("Sasa")["id"]

    page = ser.save_page(sid, "# Kẻ đứng sau\n\nAi ra lệnh?")
    assert page["slug"] == "ke-dung-sau" and page["title"] == "Kẻ đứng sau"
    assert ser.save_page(sid, "# Kẻ đứng sau\n\nbản 2")["slug"] == "ke-dung-sau-2"

    ser.save_page(sid, "# Kẻ đứng sau\n\nĐã sửa", slug="ke-dung-sau")
    assert ser.read_page(sid, "ke-dung-sau")["text"].endswith("Đã sửa")

    ser.delete_page(sid, "ke-dung-sau")
    with pytest.raises(KeyError):
        ser.read_page(sid, "ke-dung-sau")
    assert list((series_root / "_trash" / sid).glob("ke-dung-sau-*.md"))
    with pytest.raises(ValueError):
        ser.delete_page(sid, "tong-quan")
    with pytest.raises(ValueError):
        ser.save_page(sid, "no title here")
    with pytest.raises(ValueError):
        ser.read_page(sid, "../../etc/passwd")


def test_episodes_and_backlog_link(series_root):
    sid = ser.create_series("Sasa")["id"]
    e1 = ser.add_episode(sid, "Bar VIP", project_id="sasa-bar-fight")
    e2 = ser.add_episode(sid, "Sân trực thăng", summary="Hook: trực thăng đáp")
    assert (e1["number"], e2["number"]) == (1, 2)

    item = backlog_mod.create("Sasa — Tập 2")
    ser.update_episode(sid, e2["id"], backlog_id=item["id"], status="scripted", number=5)
    eps = ser.get_series(sid)["episodes"]
    assert [e["number"] for e in eps] == [1, 5]
    assert eps[1]["backlog"]["title"] == "Sasa — Tập 2" and eps[1]["status_label"] == "Đã có kịch bản"

    with pytest.raises(ValueError):
        ser.update_episode(sid, e1["id"], status="nope")
    with pytest.raises(ValueError):
        ser.update_episode(sid, e1["id"], project_id="../x")
    ser.delete_episode(sid, e1["id"])
    assert [e["title"] for e in ser.get_series(sid)["episodes"]] == ["Sân trực thăng"]


def test_delete_series_moves_to_trash(series_root):
    sid = ser.create_series("Sasa")["id"]
    moved = ser.delete_series(sid)
    assert "_trash" in moved and ser.list_series() == []
    with pytest.raises(KeyError):
        ser.get_series(sid)


@pytest.fixture
def client(series_root, tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", projects)
    monkeypatch.setattr(server_mod, "PROJECTS_DIR", projects)
    monkeypatch.setattr(server_mod, "_summary_cache", {})
    monkeypatch.setattr(insightslib, "stats_by_project",
                        lambda: {"sasa-bar-fight": {"plays": 3990.0, "retention": 0.6, "permalink_url": "https://x"}})

    async def no_watch():
        return None

    monkeypatch.setattr(server_mod, "_watch_projects", no_watch)
    with TestClient(server_mod.create_app()) as c:
        yield c


def test_api_routes(client):
    assert "series.js" in client.get("/series").text
    assert client.post("/api/series", json={"title": "x"}).status_code == 403

    sr = client.post("/api/series", headers=H, json={"title": "Sasa", "characters": ["sasa"]}).json()
    sid = sr["id"]
    ep = client.post(f"/api/series/{sid}/episodes", headers=H,
                     json={"title": "Bar VIP", "project_id": "sasa-bar-fight"}).json()

    data = client.get(f"/api/series/{sid}").json()
    assert data["episodes"][0]["stats"]["plays"] == 3990.0
    assert client.get("/api/series").json()["series"][0]["episode_count"] == 1

    page = client.post(f"/api/series/{sid}/pages", headers=H, json={"text": "# Luật\n\nKhông súng."}).json()
    assert client.get(f"/api/series/{sid}/pages/{page['slug']}").json()["text"].endswith("Không súng.")
    assert client.post(f"/api/series/{sid}/pages/tong-quan/delete", headers=H).status_code == 422
    assert client.get(f"/api/series/{sid}/pages/missing").status_code == 404
    assert client.get("/api/series/nope").status_code == 404

    r = client.post(f"/api/series/{sid}/episodes/{ep['id']}", headers=H, json={"status": "done"})
    assert r.json()["status"] == "done"
    assert client.post(f"/api/series/{sid}/episodes/{ep['id']}/delete", headers=H).status_code == 200
    assert client.post(f"/api/series/{sid}/delete", headers=H).status_code == 200
    assert client.get("/api/series").json()["series"] == []


def test_stats_by_project_picks_top_reel(tmp_path, monkeypatch):
    root = tmp_path / "insights"
    projects = tmp_path / "projects"
    social = projects / "sasa-bar-fight" / "artifacts" / "social"
    social.mkdir(parents=True)
    (social / "a.json").write_text(json.dumps({"caption": "Sasa clears a VIP bar room — five fighters"}))
    snap = root / "111" / "2026-11-15_120000"
    snap.mkdir(parents=True)
    reel = lambda rid, plays: {"id": rid, "description": "Sasa clears a VIP bar room — five fighters",
                               "length_s": 10, "plays": plays, "insights": {"post_video_avg_time_watched": 6000}}
    (snap / "insights.json").write_text(json.dumps({"page": {"name": "Tisorr"}, "reels": [reel("a", 50), reel("b", 3990)]}))
    monkeypatch.setattr(insightslib, "_characters", lambda: [])

    stats = insightslib.stats_by_project(root, projects)

    assert stats["sasa-bar-fight"]["plays"] == 3990 and stats["sasa-bar-fight"]["retention"] == 0.6
    assert stats["sasa-bar-fight"]["page_name"] == "Tisorr"
