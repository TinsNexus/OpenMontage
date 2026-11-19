"""Tests for the Võng Giới Tu Tiên control room (backlot.tutien)."""
import json

import pytest

from backlot import tutien


@pytest.fixture()
def series(tmp_path, monkeypatch):
    root = tmp_path / "vong-gioi-tu-tien"
    root.mkdir()
    plan = {
        "series": "T", "project_id": "vong-gioi-tu-tien",
        "platforms": {p: {"label": p, "channel": p, "unit": "follow", "env": e}
                      for p, e in (("facebook", "FB_COUNT"), ("tiktok", "TT_COUNT"), ("youtube", "YT_COUNT"))},
        "counts": {"facebook": 750, "tiktok": 2, "youtube": 1},
        "episodes": [
            {"n": 1, "title": "A", "lesson": "x", "cliffhanger": "y", "status": "rendered", "goals": {"facebook": 800, "tiktok": 10, "youtube": 5},
             "dir": "tap1", "render": "tap1/render.sh", "versions": {"facebook": {"style": "s"}, "tiktok": {"style": ""}, "youtube": {"style": ""}}},
            {"n": 2, "title": "B", "lesson": "x", "cliffhanger": "y", "status": "planned", "goals": {}, "dir": "", "render": "", "versions": {}},
        ],
    }
    (root / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    (root / "tap1").mkdir()
    (root / "tap1" / "render.sh").write_text("echo hi\n")
    (root / "tap1-facebook-750.mp4").write_bytes(b"x")
    (root / "tap1-facebook-750-nhe.mp4").write_bytes(b"x")
    monkeypatch.setattr(tutien, "root", lambda: root)
    return root


def test_realm_ladder():
    assert tutien.realm_of(0) == "Phàm Nhân"
    assert tutien.realm_of(1) == "Luyện Khí tầng 1"
    assert tutien.realm_of(750) == "Luyện Khí tầng 7"
    assert tutien.realm_of(999) == "Luyện Khí tầng 9"
    assert tutien.realm_of(1000) == "Trúc Cơ"
    assert tutien.next_milestone(750) == 1000


def test_plan_lists_videos_and_render_ability(series):
    plan = tutien.get_plan()
    ep1, ep2 = plan["episodes"]
    assert ep1["videos"]["facebook"]["file"] == "tap1-facebook-750.mp4"
    assert ep1["videos"]["facebook"]["light"] == "tap1-facebook-750-nhe.mp4"
    assert ep1["can_render"] and not ep2["can_render"]
    assert plan["realms"]["facebook"]["realm"] == "Luyện Khí tầng 7"


def test_counts_and_episode_edits(series):
    tutien.set_counts({"tiktok": 40})
    tutien.update_episode(2, {"title": "Mới", "status": "scripted", "goals": {"youtube": 9}, "styles": {"tiktok": "Pixel"}, "evil": "x"})
    plan = json.loads((series / "plan.json").read_text(encoding="utf-8"))
    assert plan["counts"]["tiktok"] == 40
    ep2 = plan["episodes"][1]
    assert ep2["title"] == "Mới" and ep2["status"] == "scripted"
    assert ep2["goals"]["youtube"] == 9 and ep2["versions"]["tiktok"]["style"] == "Pixel"
    assert "evil" not in ep2
    with pytest.raises(ValueError):
        tutien.update_episode(2, {"status": "nope"})
    with pytest.raises(ValueError):
        tutien.set_counts({"facebook": -1})


def test_render_rejects_episode_without_script(series):
    with pytest.raises(ValueError):
        tutien.start_render(2)
    with pytest.raises(ValueError):
        tutien.start_render(1, "myspace")
    with pytest.raises(KeyError):
        tutien.start_render(9)


def test_command_env_drops_session_vars(monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://example.invalid")
    env = tutien._clean_env()
    assert "CLAUDECODE" not in env and "ANTHROPIC_BASE_URL" not in env
