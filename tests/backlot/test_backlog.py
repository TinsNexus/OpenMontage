"""Backlot Backlog page: CRUD over the backlog file and script preview."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backlot import server as server_mod
from backlot import state as state_mod
from lib import backlog as bl

H = {"X-Backlot-Action": "backlog"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", projects)
    monkeypatch.setattr(server_mod, "PROJECTS_DIR", projects)
    monkeypatch.setattr(server_mod, "_summary_cache", {})
    monkeypatch.setattr(bl, "BACKLOG_FILE", tmp_path / "backlog" / "backlog.json")
    monkeypatch.setattr(bl, "REPO_ROOT", tmp_path)

    async def no_watch():
        return None

    monkeypatch.setattr(server_mod, "_watch_projects", no_watch)
    with TestClient(server_mod.create_app()) as c:
        yield c, tmp_path


def test_page_and_empty_list(client):
    c, _ = client
    assert "backlog.js" in c.get("/backlog").text
    data = c.get("/api/backlog").json()
    assert data["items"] == []
    assert {s["id"] for s in data["statuses"]} >= {"idea", "scripted", "done"}


def test_create_update_script_delete(client):
    c, root = client
    (root / "projects" / "dog").mkdir()
    (root / "projects" / "dog" / "script.md").write_text("# Chó phố\nxin chào", encoding="utf-8")

    r = c.post("/api/backlog", headers=H, json={
        "title": "Chó Phố Gặp Chó Quê", "status": "scripted", "tags": "hài, chó",
        "project_id": "dog", "script_path": "projects/dog/script.md"})
    assert r.status_code == 200, r.text
    item = r.json()
    assert item["id"] == "cho-pho-gap-cho-que"
    assert item["tags"] == ["hài", "chó"]
    assert item["script_exists"] and item["project_exists"]

    assert c.get(f"/api/backlog/{item['id']}/script").json()["text"].startswith("# Chó phố")

    r = c.post(f"/api/backlog/{item['id']}", headers=H, json={"status": "in_production", "priority": 9})
    assert r.json()["status"] == "in_production" and r.json()["priority"] == 3

    # same title gets a unique id
    assert c.post("/api/backlog", headers=H, json={"title": "Chó Phố Gặp Chó Quê"}).json()["id"].endswith("-2")

    assert c.post(f"/api/backlog/{item['id']}/delete", headers=H).status_code == 200
    assert [i["id"] for i in c.get("/api/backlog").json()["items"]] == ["cho-pho-gap-cho-que-2"]


def test_writes_need_header_and_valid_input(client):
    c, _ = client
    assert c.post("/api/backlog", json={"title": "x"}).status_code == 403
    assert c.post("/api/backlog", headers=H, json={"title": ""}).status_code == 422
    assert c.post("/api/backlog", headers=H, json={"title": "x", "status": "nope"}).status_code == 422
    assert c.post("/api/backlog", headers=H, json={"title": "x", "script_path": "../etc/passwd.md"}).status_code == 422
    assert c.post("/api/backlog", headers=H, json={"title": "x", "script_path": "a.py"}).status_code == 422
    assert c.post("/api/backlog/missing", headers=H, json={"status": "done"}).status_code == 404
