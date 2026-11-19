"""Tests for the Heartbreak studio (backlot.heartbreak) — M1: episodes, prompt
writing/editing, and the price table.

No test here may reach the network: ``social._chat`` and
``piapi_client.get_api_key`` are always monkeypatched (see the ``fake_chat``
fixture), so the suite makes zero paid PiAPI calls.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backlot import heartbreak, social
from backlot import server as server_mod
from backlot import state as state_mod
from lib import characters as charlib
from schemas.artifacts import validate_artifact
from tools import piapi_client


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def studio_root(tmp_path, monkeypatch):
    """Isolated PROJECTS_DIR + a two-character library for slot validation."""
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setattr(heartbreak, "PROJECTS_DIR", root)
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", root)
    monkeypatch.setattr(server_mod, "PROJECTS_DIR", root)

    chars = tmp_path / "characters"
    for cid, name, identity in (
        ("hero", "Hero", "a skinny guy in a yellow hoodie with a tiny mustache"),
        ("crush", "Crush", "a round-faced girl with twin buns and a red backpack"),
    ):
        folder = chars / cid
        folder.mkdir(parents=True)
        (folder / "character.json").write_text(
            json.dumps({"name": name, "identity": identity, "images": []}),
            encoding="utf-8",
        )
    monkeypatch.setattr(charlib, "CHARACTERS_DIR", chars)
    return root


@pytest.fixture()
def client(studio_root, monkeypatch):
    async def no_watch():
        return None

    monkeypatch.setattr(server_mod, "_watch_projects", no_watch)
    monkeypatch.setattr(server_mod, "_summary_cache", {})
    monkeypatch.setattr(server_mod, "_PROJECTS_ROOT_STR",
                        __import__("os").path.normcase(str(studio_root.resolve())))
    monkeypatch.setattr(server_mod, "THUMB_CACHE_DIR", studio_root.parent / "thumbs")
    with TestClient(server_mod.create_app()) as c:
        yield c


@pytest.fixture()
def fake_chat(monkeypatch):
    """Install a fake PiAPI chat + API key; returns the list of call records."""
    calls: list[dict] = []

    def install(reply):
        def _chat(messages, model, key):
            calls.append({"messages": messages, "model": model, "key": key})
            if isinstance(reply, tuple):
                return reply
            return reply, {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}

        monkeypatch.setattr(social, "_chat", _chat)
        monkeypatch.setattr(piapi_client, "get_api_key", lambda: "test-key")
        return calls

    return install


def _plan(**over) -> dict:
    plan = {
        "clips": [
            {"id": "A", "beats": ["WOO", "DUMP"], "duration": 12,
             "prompt": "@image1 walks in holding a flower, sees @image2 with a rival. "
                       "One action, one exaggerated face. No text, no speech."},
            {"id": "B", "beats": ["PEAK", "TWIST"], "duration": 13,
             "prompt": "@image1 cries into a bowl of noodles then looks up startled at "
                       "@image2 passing by. No text, no speech."},
        ],
        "cold_open": {"text": "Hoa chưa trao đã nát", "from_clip": "B", "at": 3.2},
        "music_plan": [{"at": 0, "cue": "happy", "action": "in"},
                       {"at": 12, "cue": None, "action": "cut"}],
        "caption_hint": "Kẻ si tình tập mới: tình đã nát, mì còn nóng.",
    }
    plan.update(over)
    return plan


def _create(studio_root, **kw) -> str:
    ep = heartbreak.create_episode(
        kw.pop("title", "Hái hoa cho cô ấy"),
        kw.pop("idea", "kẻ si tình hái hoa tặng crush thì bị bỏ rơi"),
        kw.pop("slots", {"HERO": "hero", "CRUSH": "crush"}),
        kw.pop("length", "short"),
        **kw,
    )
    return ep["slug"]


# ---------------------------------------------------------------------------
# create_episode / list_episodes
# ---------------------------------------------------------------------------

def test_create_episode_layout_and_checkpoints(studio_root):
    slug = _create(studio_root)
    assert slug == "heartbreak-hai-hoa-cho-co-ay"
    d = studio_root / slug
    assert (d / "project.json").is_file()
    assert (d / "studio.json").is_file()

    studio = json.loads((d / "studio.json").read_text(encoding="utf-8"))
    assert studio["title"] == "Hái hoa cho cô ấy"
    assert studio["length"] == "short"
    assert studio["slots"]["HERO"] == "hero" and studio["slots"]["CRUSH"] == "crush"
    assert studio["clips"] == [] and studio["spent_usd"] == 0.0
    assert studio["stage"] == "proposal"
    assert studio["model"] == {"tool": "seedance_piapi", "model_variant": "fast", "resolution": "720p"}

    project = json.loads((d / "project.json").read_text(encoding="utf-8"))
    assert project["pipeline_type"] == "cinematic"

    research = json.loads((d / "checkpoint_research.json").read_text(encoding="utf-8"))
    assert research["status"] == "completed"
    assert "research_brief" in research["artifacts"]

    proposal = json.loads((d / "checkpoint_proposal.json").read_text(encoding="utf-8"))
    assert proposal["status"] == "awaiting_human"
    assert proposal["human_approval_required"] is True
    assert proposal["human_approved"] is False

    # the proposal must be readable as a canonical artifact on disk
    packet = json.loads((d / "artifacts" / "proposal_packet.json").read_text(encoding="utf-8"))
    validate_artifact("proposal_packet", packet)
    brief = json.loads((d / "artifacts" / "research_brief.json").read_text(encoding="utf-8"))
    validate_artifact("research_brief", brief)


def test_create_episode_rejects_bad_input(studio_root):
    with pytest.raises(ValueError):
        heartbreak.create_episode("", "idea", {"HERO": "hero"})
    with pytest.raises(ValueError):
        heartbreak.create_episode("Tiêu đề", "", {"HERO": "hero"})
    with pytest.raises(ValueError):
        heartbreak.create_episode("Tiêu đề", "idea", {"HERO": "hero"}, length="huge")
    with pytest.raises(ValueError):
        heartbreak.create_episode("Tiêu đề", "idea", {})               # HERO missing
    with pytest.raises(ValueError):
        heartbreak.create_episode("Tiêu đề", "idea", {"HERO": "hero", "JOKER": "hero"})  # bad slot
    with pytest.raises(ValueError):
        heartbreak.create_episode("Tiêu đề", "idea", {"HERO": "ghost"})  # unknown character
    assert list(studio_root.iterdir()) == []


def test_duplicate_titles_get_unique_slugs(studio_root):
    a = _create(studio_root, title="Tập trùng")
    b = _create(studio_root, title="Tập trùng")
    assert a == "heartbreak-tap-trung" and b == "heartbreak-tap-trung-2"


def test_list_episodes(studio_root):
    assert heartbreak.list_episodes() == {"episodes": []}
    slug = _create(studio_root)
    eps = heartbreak.list_episodes()["episodes"]
    assert len(eps) == 1
    assert eps[0]["slug"] == slug and eps[0]["stage"] == "proposal"
    assert eps[0]["clip_count"] == 0 and eps[0]["spent_usd"] == 0.0


# ---------------------------------------------------------------------------
# write_prompts (the only paid call — always faked here)
# ---------------------------------------------------------------------------

def test_write_prompts_advances_pipeline(studio_root, fake_chat):
    calls = fake_chat(json.dumps(_plan(), ensure_ascii=False))
    slug = _create(studio_root)

    out = heartbreak.write_prompts(slug, notes="nhạc vui hơn")
    assert len(calls) == 1
    messages = calls[0]["messages"]
    system, user = messages[0]["content"], messages[1]["content"]

    # system prompt = formula sections 2–9 only (§1 why-it-works, §10 metrics dropped)
    assert "THẤT TÌNH KHÔNG LỜI" in system
    assert "## 2. Bộ nhân vật" in system and "## 9. Caption" in system
    assert "## 1. Vì sao hiệu quả" not in system
    assert "## 10. Đo kết quả" not in system

    # user prompt = slot identities + @imageN map + idea + length + notes
    assert "Tập: Hái hoa cho cô ấy" in user
    assert "@image1 = HERO (Hero): a skinny guy in a yellow hoodie" in user
    assert "@image2 = CRUSH (Crush): a round-faced girl" in user
    assert "@image1 = HERO, @image2 = CRUSH" in user
    assert "2–4 clip" in user and "4–15 giây" in user
    assert "Ghi chú của người dùng: nhạc vui hơn" in user

    assert out["model"] == social.DEFAULT_MODEL
    assert out["usage"]["total_tokens"] == 30
    assert [(c["id"], c["duration"], c["status"]) for c in out["clips"]] == [
        ("A", 12, "draft"), ("B", 13, "draft")]
    # regression: the cold-open timestamp must survive the music-plan loop
    assert out["cold_open"] == {"text": "Hoa chưa trao đã nát", "from_clip": "B", "at": 3.2}
    assert out["music_plan"][1] == {"at": 12.0, "cue": None, "action": "cut"}
    assert out["caption_hint"].startswith("Kẻ si tình")

    d = studio_root / slug
    studio = json.loads((d / "studio.json").read_text(encoding="utf-8"))
    assert studio["stage"] == "scene_plan"
    assert len(studio["clips"]) == 2
    assert (d / "artifacts" / "clipA.txt").read_text(encoding="utf-8").startswith("@image1 walks in")
    assert (d / "artifacts" / "clipB.txt").read_text(encoding="utf-8").startswith("@image1 cries")

    for stage in ("proposal", "script", "scene_plan"):
        cp = json.loads((d / f"checkpoint_{stage}.json").read_text(encoding="utf-8"))
        assert cp["status"] == "completed", stage
        assert cp["human_approved"] is True, stage

    script = json.loads((d / "artifacts" / "script.json").read_text(encoding="utf-8"))
    validate_artifact("script", script)
    assert script["total_duration_seconds"] == 25
    assert [s["id"] for s in script["sections"]] == ["clipA", "clipB"]

    scene_plan = json.loads((d / "artifacts" / "scene_plan.json").read_text(encoding="utf-8"))
    validate_artifact("scene_plan", scene_plan)
    assert len(scene_plan["scenes"]) == 2
    assert scene_plan["scenes"][0]["required_assets"][0]["source"] == "generate"


def test_write_prompts_requires_api_key(studio_root, monkeypatch):
    slug = _create(studio_root)
    monkeypatch.setattr(piapi_client, "get_api_key", lambda: None)

    def _boom(*a, **k):                       # no chat call may happen without a key
        raise AssertionError("paid chat called without an API key")

    monkeypatch.setattr(social, "_chat", _boom)
    with pytest.raises(RuntimeError):
        heartbreak.write_prompts(slug)
    studio = json.loads((studio_root / slug / "studio.json").read_text(encoding="utf-8"))
    assert studio["clips"] == [] and studio["stage"] == "proposal"


@pytest.mark.parametrize("case", [
    "not_json",
    "too_few_clips",
    "bad_beat",
    "bad_duration",
    "bad_duration_type",
    "image_out_of_range",
    "long_cold_open",
    "duplicate_ids",
    "bad_from_clip",
    "bad_music_action",
    "missing_cold_open",
    "oversized_prompt",
    "bad_clip_id",
])
def test_write_prompts_rejects_invalid_plans(studio_root, fake_chat, case):
    if case == "not_json":
        reply = "xin chào, không có JSON ở đây"
    else:
        over: dict = {}
        if case == "too_few_clips":
            over["clips"] = _plan()["clips"][:1]
        elif case == "bad_beat":
            over["clips"] = [dict(c, beats=["DANCING"]) for c in _plan()["clips"]]
        elif case == "bad_duration":
            over["clips"] = [dict(c, duration=99) for c in _plan()["clips"]]
        elif case == "bad_duration_type":
            over["clips"] = [dict(c, duration="nhiều") for c in _plan()["clips"]]
        elif case == "image_out_of_range":
            over["clips"] = [dict(c, prompt=c["prompt"] + " @image9 appears.") for c in _plan()["clips"]]
        elif case == "long_cold_open":
            over["cold_open"] = dict(_plan()["cold_open"],
                                     text="một hai ba bốn năm sáu bảy tám chín")
        elif case == "duplicate_ids":
            over["clips"] = [dict(c, id="A") for c in _plan()["clips"]]
        elif case == "bad_from_clip":
            over["cold_open"] = dict(_plan()["cold_open"], from_clip="Z")
        elif case == "bad_music_action":
            over["music_plan"] = [{"at": 0, "cue": None, "action": "fade"}]
        elif case == "missing_cold_open":
            over["cold_open"] = None
        elif case == "oversized_prompt":
            over["clips"] = [dict(c, prompt="x" * 4001) for c in _plan()["clips"]]
        elif case == "bad_clip_id":
            over["clips"] = [dict(c, id="clip1") for c in _plan()["clips"]]
        reply = json.dumps(_plan(**over), ensure_ascii=False)

    fake_chat(reply)
    slug = _create(studio_root)
    with pytest.raises(ValueError):
        heartbreak.write_prompts(slug)

    # nothing may be written before validation passes
    d = studio_root / slug
    studio = json.loads((d / "studio.json").read_text(encoding="utf-8"))
    assert studio["clips"] == [] and studio["stage"] == "proposal"
    assert not (d / "artifacts" / "clipA.txt").exists()
    proposal = json.loads((d / "checkpoint_proposal.json").read_text(encoding="utf-8"))
    assert proposal["status"] == "awaiting_human"


# ---------------------------------------------------------------------------
# save_prompt / price_table
# ---------------------------------------------------------------------------

def test_save_prompt_edits_one_clip(studio_root, fake_chat):
    fake_chat(json.dumps(_plan(), ensure_ascii=False))
    slug = _create(studio_root)
    heartbreak.write_prompts(slug)

    clip = heartbreak.save_prompt(slug, "A", "@image1 holds out a wilted flower. No text, no speech.")
    assert clip["prompt"].startswith("@image1 holds out")
    d = studio_root / slug
    assert "@image1 holds out" in (d / "artifacts" / "clipA.txt").read_text(encoding="utf-8")
    studio = json.loads((d / "studio.json").read_text(encoding="utf-8"))
    assert studio["clips"][0]["prompt"].startswith("@image1 holds out")
    # untouched clip keeps its prompt
    assert studio["clips"][1]["prompt"].startswith("@image1 cries")

    with pytest.raises(KeyError):
        heartbreak.save_prompt(slug, "ZZ", "prompt")
    with pytest.raises(ValueError):
        heartbreak.save_prompt(slug, "A", "   ")
    with pytest.raises(ValueError):
        heartbreak.save_prompt(slug, "A", "@image9 too far. No text, no speech.")


def test_price_table(studio_root, fake_chat):
    slug = _create(studio_root)
    with pytest.raises(ValueError):
        heartbreak.price_table(slug)          # no clips yet

    fake_chat(json.dumps(_plan(), ensure_ascii=False))
    heartbreak.write_prompts(slug)
    table = heartbreak.price_table(slug)

    assert table["total_seconds"] == 25
    assert table["clips"] == [{"id": "A", "duration": 12}, {"id": "B", "duration": 13}]
    assert table["spent_usd"] == 0.0
    assert len(table["rows"]) == 8            # 3 Seedance variants x 2 res + 2 Kling rows

    by_id = {r["id"]: r for r in table["rows"]}
    assert set(by_id) == {
        "seedance-fast-480p", "seedance-fast-720p",
        "seedance-standard-480p", "seedance-standard-720p",
        "seedance-mini-480p", "seedance-mini-720p",
        "kling-30-std", "kling-30-pro",
    }
    # totals = per-second rate x the episode's clip durations
    assert by_id["seedance-fast-720p"]["total_usd"] == round(0.096 * 25, 2)
    assert by_id["seedance-standard-480p"]["total_usd"] == round(0.10 * 25, 2)
    assert by_id["kling-30-pro"]["total_usd"] == round(0.15 * 25, 2)
    defaults = [r for r in table["rows"] if r["default"]]
    assert len(defaults) == 1 and defaults[0]["id"] == "seedance-fast-720p"
    assert all(r["clip_length"] == "12s, 13s" for r in table["rows"])


# ---------------------------------------------------------------------------
# HTTP API
# ---------------------------------------------------------------------------

def _hdr(action: str) -> dict:
    return {"X-Backlot-Action": action}


def test_api_create_list_get(client, studio_root):
    assert client.get("/api/heartbreak").json() == {"episodes": []}

    # writes require the anti-CSRF action header
    payload = {"title": "Hái hoa cho cô ấy", "idea": "kẻ si tình bị bỏ rơi",
               "slots": {"HERO": "hero", "CRUSH": "crush"}, "length": "short"}
    assert client.post("/api/heartbreak/episodes", json=payload).status_code == 403

    r = client.post("/api/heartbreak/episodes", json=payload, headers=_hdr("heartbreak"))
    assert r.status_code == 200, r.text
    slug = r.json()["slug"]
    assert slug == "heartbreak-hai-hoa-cho-co-ay"

    eps = client.get("/api/heartbreak").json()["episodes"]
    assert [e["slug"] for e in eps] == [slug]

    ep = client.get(f"/api/heartbreak/{slug}").json()
    assert ep["title"] == "Hái hoa cho cô ấy" and ep["stage"] == "proposal"
    assert client.get("/api/heartbreak/nope").status_code == 404

    bad = dict(payload, slots={})
    r = client.post("/api/heartbreak/episodes", json=bad, headers=_hdr("heartbreak"))
    assert r.status_code == 422


def test_api_write_and_edit_prompts(client, studio_root, fake_chat, monkeypatch):
    r = client.post("/api/heartbreak/episodes",
                    json={"title": "Tập API", "idea": "ý tưởng",
                          "slots": {"HERO": "hero", "CRUSH": "crush"}},
                    headers=_hdr("heartbreak"))
    slug = r.json()["slug"]

    # paid route demands the paid action header
    assert client.post(f"/api/heartbreak/{slug}/prompts", json={}).status_code == 403

    # missing API key -> 502, not a stack trace
    monkeypatch.setattr(piapi_client, "get_api_key", lambda: None)
    r = client.post(f"/api/heartbreak/{slug}/prompts", json={}, headers=_hdr("heartbreak-paid"))
    assert r.status_code == 502 and "PIAPI" in r.json()["detail"]

    calls = fake_chat(json.dumps(_plan(), ensure_ascii=False))
    r = client.post(f"/api/heartbreak/{slug}/prompts", json={"notes": "hài hơn"},
                    headers=_hdr("heartbreak-paid"))
    assert r.status_code == 200, r.text
    assert len(calls) == 1 and "hài hơn" in calls[0]["messages"][1]["content"]
    body = r.json()
    assert [c["id"] for c in body["clips"]] == ["A", "B"]
    assert body["cold_open"]["at"] == 3.2

    # editable afterwards
    r = client.post(f"/api/heartbreak/{slug}/prompts/A",
                    json={"prompt": "@image1 kneels in the rain. No text, no speech."},
                    headers=_hdr("heartbreak"))
    assert r.status_code == 200, r.text
    assert r.json()["prompt"].startswith("@image1 kneels")
    assert client.post(f"/api/heartbreak/{slug}/prompts/A",
                       json={"prompt": "@image9 nope"}, headers=_hdr("heartbreak")).status_code == 422

    # local price table
    prices = client.get(f"/api/heartbreak/{slug}/prices").json()
    assert len(prices["rows"]) == 8 and prices["total_seconds"] == 25
    assert client.get("/api/heartbreak/nope/prices").status_code == 404
