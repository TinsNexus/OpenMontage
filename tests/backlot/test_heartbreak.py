"""Tests for the Heartbreak studio (backlot.heartbreak) — M1: episodes, prompt
writing/editing, and the price table.

No test here may reach the network: ``social._chat`` and
``piapi_client.get_api_key`` are always monkeypatched (see the ``fake_chat``
fixture), so the suite makes zero paid PiAPI calls.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backlot import heartbreak, social
from backlot import server as server_mod
from backlot import state as state_mod
from lib import characters as charlib
from schemas.artifacts import validate_artifact
from tools import piapi_client
from tools.base_tool import ToolResult
import tools.video.kling_piapi as kling_mod
import tools.video.seedance_piapi as seedance_mod


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
        ("noimg", "NoImg", "a shadowy figure with no reference art yet"),
    ):
        folder = chars / cid
        folder.mkdir(parents=True)
        images = []
        if cid != "noimg":
            (folder / "ref.png").write_bytes(
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
                b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01"
                b"\x00\x00\x00\x00IEND\xaeB`\x82")
            images = [{"file": "ref.png", "role": "full_body"}]
        (folder / "character.json").write_text(
            json.dumps({"name": name, "identity": identity, "images": images}),
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


# ---------------------------------------------------------------------------
# M2 — page /heartbreak, nav links, model pick
# ---------------------------------------------------------------------------

def test_heartbreak_page_serves_ui(client):
    r = client.get("/heartbreak")
    assert r.status_code == 200
    html = r.text
    assert "<title>Backlot — Xưởng Heartbreak</title>" in html
    assert "/ui/heartbreak.js" in html and "/ui/heartbreak.css" in html
    assert 'href="/heartbreak" aria-current="page"' in html          # self link in nav
    for label in ("+ Tập mới", "stepper", "epList", "panel"):
        assert label in html, label


def test_nav_has_heartbreak_after_tutien_on_every_page(client):
    pages = ("/", "/gallery", "/backlog", "/series", "/tutien", "/heartbreak",
             "/insights", "/images", "/characters", "/swap", "/products", "/formulas")
    for path in pages:
        html = client.get(path).text
        i = html.index('href="/tutien"')
        j = html.index('href="/heartbreak"')
        assert 0 < j - i < 240, f"{path}: Heartbreak not right after Tu Tiên"
        # no duplicate links
        assert html.count('href="/heartbreak"') == 1, path


def test_page_load_makes_no_paid_calls(client, studio_root, monkeypatch):
    """Opening /heartbreak (and its free GETs) must never reach PiAPI chat."""
    def boom(*a, **k):
        raise AssertionError("paid chat call triggered by page load")

    monkeypatch.setattr(social, "_chat", boom)
    monkeypatch.setattr(piapi_client, "get_api_key", lambda: "k")

    assert client.get("/heartbreak").status_code == 200
    assert client.get("/api/heartbreak").status_code == 200
    assert client.get("/api/characters").status_code == 200


def test_set_model_persists_choice(studio_root, fake_chat):
    fake_chat(json.dumps(_plan(), ensure_ascii=False))
    slug = _create(studio_root)
    with pytest.raises(ValueError):
        heartbreak.set_model(slug, "seedance-fast-720p")      # no clips -> no price table

    heartbreak.write_prompts(slug)
    table = heartbreak.price_table(slug)
    for row in table["rows"]:                                  # every row id is selectable
        heartbreak.set_model(slug, row["id"])

    ep = heartbreak.set_model(slug, "seedance-standard-720p")
    assert ep["model"] == {"tool": "seedance_piapi", "model_variant": "standard", "resolution": "720p"}
    assert ep["model_id"] == "seedance-standard-720p"

    ep = heartbreak.set_model(slug, "kling-30-pro")
    assert ep["model"] == {"tool": "kling_piapi", "version": "3.0", "mode": "pro", "resolution": "1080p"}

    saved = json.loads((studio_root / slug / "studio.json").read_text(encoding="utf-8"))
    assert saved["model_id"] == "kling-30-pro" and saved["model"]["tool"] == "kling_piapi"

    with pytest.raises(ValueError):
        heartbreak.set_model(slug, "no-such-row")


def test_api_set_model(client, studio_root, fake_chat):
    r = client.post("/api/heartbreak/episodes",
                    json={"title": "Tập giá", "idea": "ý tưởng",
                          "slots": {"HERO": "hero", "CRUSH": "crush"}},
                    headers=_hdr("heartbreak"))
    slug = r.json()["slug"]

    # cannot pick a model before prompts exist (no durations to price)
    r = client.post(f"/api/heartbreak/{slug}/model", json={"model_id": "seedance-fast-720p"},
                    headers=_hdr("heartbreak"))
    assert r.status_code == 422

    fake_chat(json.dumps(_plan(), ensure_ascii=False))
    assert client.post(f"/api/heartbreak/{slug}/prompts", json={},
                       headers=_hdr("heartbreak-paid")).status_code == 200

    # writes need the action header
    assert client.post(f"/api/heartbreak/{slug}/model",
                       json={"model_id": "seedance-fast-720p"}).status_code == 403

    r = client.post(f"/api/heartbreak/{slug}/model", json={"model_id": "seedance-fast-480p"},
                    headers=_hdr("heartbreak"))
    assert r.status_code == 200, r.text
    assert r.json()["model_id"] == "seedance-fast-480p"
    assert client.get(f"/api/heartbreak/{slug}").json()["model_id"] == "seedance-fast-480p"

    r = client.post(f"/api/heartbreak/{slug}/model", json={"model_id": "bogus"},
                    headers=_hdr("heartbreak"))
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# M3 — clip generation jobs (video tools are faked; zero network)
# ---------------------------------------------------------------------------

class _FakeVideo:
    """Stands in for SeedancePiAPI / KlingPiAPI: writes a stub mp4 locally."""
    calls: list = []
    error: str | None = None
    gate: threading.Event | None = None   # set -> execute() blocks (for "still running" tests)

    def __init__(self):
        pass

    def estimate_cost(self, inputs) -> float:
        raise NotImplementedError

    def execute(self, inputs):
        _FakeVideo.calls.append(dict(inputs))
        if _FakeVideo.gate is not None:
            _FakeVideo.gate.wait(5)
        if _FakeVideo.error:
            return ToolResult(success=False, error=_FakeVideo.error)
        out = Path(inputs["output_path"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\x00\x00\x00\x18ftypmp42")
        return ToolResult(success=True, cost_usd=self.estimate_cost(inputs),
                          data={"output_path": str(out), "task_id": "task-test",
                                "resolution": "480x854"})


class _FakeSeedance(_FakeVideo):
    def estimate_cost(self, inputs) -> float:
        rate = 0.11 if inputs.get("less_restriction") else 0.096     # fast @720p
        return round(rate * int(inputs.get("duration", 5)), 2)


class _FakeKling(_FakeVideo):
    def estimate_cost(self, inputs) -> float:
        return round(0.10 * int(inputs.get("duration", 5)), 2)        # 3.0 std


@pytest.fixture()
def fake_video(monkeypatch):
    _FakeVideo.calls = []
    _FakeVideo.error = None
    _FakeVideo.gate = None
    monkeypatch.setattr(seedance_mod, "SeedancePiAPI", _FakeSeedance)
    monkeypatch.setattr(kling_mod, "KlingPiAPI", _FakeKling)
    return _FakeVideo


def _ready(studio_root, fake_chat, fake_video=None) -> str:
    """Create an episode and write its prompts (mocked chat)."""
    fake_chat(json.dumps(_plan(), ensure_ascii=False))
    slug = _create(studio_root)
    heartbreak.write_prompts(slug)
    return slug


def _wait_jobs(slug, timeout=8.0) -> list[dict]:
    end = time.time() + timeout
    while time.time() < end:
        jobs = heartbreak.list_jobs(slug)["jobs"]
        if not any(j.get("status") == "running" for j in jobs):
            return jobs
        time.sleep(0.02)
    raise AssertionError("clip jobs never finished")


def test_generation_estimate_local(studio_root, fake_chat, fake_video):
    slug = _ready(studio_root, fake_chat, fake_video)
    est = heartbreak.generation_estimate(slug)
    assert est["pending_ids"] == ["A", "B"]
    assert [r["usd"] for r in est["clips"]] == [1.15, 1.25]     # 0.096 * 12/13, rounded per clip
    assert est["pending_usd"] == 2.40 and est["spent_usd"] == 0.0
    assert _FakeVideo.calls == []                                # estimate never runs the tool

    with pytest.raises(ValueError):
        heartbreak.generation_estimate(_create(studio_root, title="trước prompt"))


def test_generate_clip_records_take_and_charge(studio_root, fake_chat, fake_video):
    slug = _ready(studio_root, fake_chat, fake_video)
    job = heartbreak.generate_clip(slug, "A")
    assert job["status"] == "running" and job["file"] == "assets/video/clipA_v1.mp4"

    jobs = _wait_jobs(slug)
    assert jobs[0]["status"] == "done" and jobs[0]["cost_usd"] == 1.15

    ep = heartbreak.get_episode(slug)
    clipA = next(c for c in ep["clips"] if c["id"] == "A")
    assert len(clipA["versions"]) == 1 and clipA["status"] == "draft"   # needs "Chọn bản này"
    assert clipA["versions"][0]["file"] == "assets/video/clipA_v1.mp4"
    assert clipA["versions"][0]["resolution"] == "480x854"
    assert ep["spent_usd"] == 1.15
    assert (studio_root / slug / "assets" / "video" / "clipA_v1.mp4").is_file()
    # tool wrote the .meta.json sidecar in real runs; the fake does not, and we don't need it

    # the tool got the full reference-to-video payload from the brief
    call = _FakeVideo.calls[0]
    assert call["operation"] == "reference_to_video"
    assert call["aspect_ratio"] == "9:16" and call["duration"] == 12
    assert call["model_variant"] == "fast" and call["resolution"] == "720p"
    assert len(call["reference_image_paths"]) == 2                  # HERO + CRUSH primary images
    assert all(Path(p).is_file() for p in call["reference_image_paths"])
    assert call["output_path"].endswith("assets/video/clipA_v1.mp4")
    assert "@image1" in call["prompt"]

    # assets checkpoint: takes exist but nothing approved yet
    ckpt = json.loads((studio_root / slug / "checkpoint_assets.json").read_text(encoding="utf-8"))
    assert ckpt["status"] == "awaiting_human"
    manifest = json.loads((studio_root / slug / "artifacts" / "asset_manifest.json").read_text(encoding="utf-8"))
    validate_artifact("asset_manifest", manifest)
    assert manifest["assets"][0]["scene_id"] == "sc_clipA"
    assert manifest["total_cost_usd"] == 1.15


def test_generate_all_then_choose_completes_assets(studio_root, fake_chat, fake_video):
    slug = _ready(studio_root, fake_chat, fake_video)
    out = heartbreak.generate_all(slug)
    assert out["clips"] == 2 and out["estimate_usd"] == 2.40

    jobs = _wait_jobs(slug)
    assert len(jobs) == 2 and all(j["status"] == "done" for j in jobs)
    ep = heartbreak.get_episode(slug)
    assert all(len(c["versions"]) == 1 for c in ep["clips"]) and ep["spent_usd"] == 2.40

    heartbreak.choose_version(slug, "A", 0)
    ckpt = json.loads((studio_root / slug / "checkpoint_assets.json").read_text(encoding="utf-8"))
    assert ckpt["status"] == "awaiting_human"            # B still pending

    heartbreak.choose_version(slug, "B", 0)
    ckpt = json.loads((studio_root / slug / "checkpoint_assets.json").read_text(encoding="utf-8"))
    assert ckpt["status"] == "completed"
    assert ckpt.get("human_approved") is True
    manifest = json.loads((studio_root / slug / "artifacts" / "asset_manifest.json").read_text(encoding="utf-8"))
    validate_artifact("asset_manifest", manifest)
    assert len(manifest["assets"]) == 2

    assert heartbreak.list_episodes()["episodes"][0]["approved_clips"] == 2
    with pytest.raises(ValueError):
        heartbreak.generate_all(slug)                    # everything approved


def test_generate_validation_errors(studio_root, fake_chat, fake_video):
    fake_chat(json.dumps(_plan(), ensure_ascii=False))
    slug = _create(studio_root)

    with pytest.raises(ValueError):
        heartbreak.generate_clip(slug, "A")               # no prompts yet
    with pytest.raises(ValueError):
        heartbreak.generate_all(slug)

    heartbreak.write_prompts(slug)
    with pytest.raises(KeyError):
        heartbreak.generate_clip(slug, "ZZ")              # unknown clip
    with pytest.raises(ValueError):
        heartbreak.choose_version(slug, "A", 0)           # no takes yet
    with pytest.raises(ValueError):
        heartbreak.choose_version(slug, "A", 9)           # take out of range

    # a slot character without a reference image cannot go to reference_to_video
    bad = _create(studio_root, title="thieu anh", slots={"HERO": "hero", "CRUSH": "noimg"})
    fake_chat(json.dumps(_plan(), ensure_ascii=False))
    heartbreak.write_prompts(bad)
    with pytest.raises(ValueError, match="ảnh chính"):
        heartbreak.generate_clip(bad, "A")

    # kling has no less_restriction
    fake_chat(json.dumps(_plan(), ensure_ascii=False))
    kl = _create(studio_root, title="ban kling")
    heartbreak.write_prompts(kl)
    heartbreak.set_model(kl, "kling-30-std")
    with pytest.raises(ValueError, match="less_restriction"):
        heartbreak.generate_clip(kl, "A", less_restriction=True)


def test_generate_duplicate_running_job_blocked(studio_root, fake_chat, fake_video):
    slug = _ready(studio_root, fake_chat, fake_video)
    _FakeVideo.gate = threading.Event()               # keep the first job running
    try:
        heartbreak.generate_clip(slug, "A")
        with pytest.raises(ValueError, match="đang được tạo"):
            heartbreak.generate_clip(slug, "A")
        with pytest.raises(ValueError, match="Đang có"):
            heartbreak.generate_all(slug)
    finally:
        _FakeVideo.gate.set()
        _FakeVideo.gate = None
    jobs = _wait_jobs(slug)
    assert jobs[0]["status"] == "done"


def test_moderation_failure_offers_less_restriction(studio_root, fake_chat, fake_video):
    slug = _ready(studio_root, fake_chat, fake_video)
    _FakeVideo.error = ("Seedance (PiAPI) video generation failed (task_id=t1): "
                        "content rejections are refunded")
    try:
        heartbreak.generate_clip(slug, "A")
        jobs = _wait_jobs(slug)
    finally:
        _FakeVideo.error = None

    job = jobs[0]
    assert job["status"] == "failed" and "content rejections" in job["error"]
    advice = job["advice"]
    assert advice["kind"] == "less_restriction" and advice["retry"] is True
    assert advice["extra_usd"] > 0                      # 0.11 vs 0.096 per second
    ep = heartbreak.get_episode(slug)
    assert ep["spent_usd"] == 0.0                       # failed takes cost nothing
    assert not next(c for c in ep["clips"] if c["id"] == "A")["versions"]

    # the retry (user-confirmed) goes out with less_restriction=True and succeeds
    heartbreak.generate_clip(slug, "A", less_restriction=True)
    jobs = _wait_jobs(slug)
    assert jobs[0]["status"] == "done"
    assert _FakeVideo.calls[-1].get("less_restriction") is True
    assert heartbreak.get_episode(slug)["spent_usd"] > 0


def test_non_moderation_failure_has_no_advice(studio_root, fake_chat, fake_video):
    slug = _ready(studio_root, fake_chat, fake_video)
    _FakeVideo.error = "PiAPI API key missing"
    try:
        heartbreak.generate_clip(slug, "A")
        jobs = _wait_jobs(slug)
    finally:
        _FakeVideo.error = None
    assert jobs[0]["status"] == "failed"
    assert "advice" not in jobs[0]


def test_kling_generation_uses_first_frame(studio_root, fake_chat, fake_video):
    slug = _ready(studio_root, fake_chat, fake_video)
    heartbreak.set_model(slug, "kling-30-std")
    heartbreak.generate_clip(slug, "A")
    jobs = _wait_jobs(slug)
    assert jobs[0]["status"] == "done"

    call = _FakeVideo.calls[0]
    assert call["version"] == "3.0" and call["mode"] == "std"
    assert call["aspect_ratio"] == "9:16" and call["duration"] == 12
    assert Path(call["image_path"]).is_file()                 # HERO primary as first frame
    assert "@image" not in call["prompt"]                     # tags rewritten to names
    assert "Hero" in call["prompt"]


def test_orphan_jobs_marked_interrupted(studio_root, fake_chat, fake_video):
    slug = _ready(studio_root, fake_chat, fake_video)
    jobs_file = studio_root / slug / ".jobs" / "jobs.json"
    jobs_file.parent.mkdir(parents=True, exist_ok=True)
    jobs_file.write_text(json.dumps([{"id": "g-orphan00", "kind": "clip", "clip": "A", "version": 1,
                                      "status": "running", "started": time.time()}]),
                         encoding="utf-8")
    jobs = heartbreak.list_jobs(slug)["jobs"]
    assert jobs[0]["status"] == "interrupted"
    assert json.loads(jobs_file.read_text(encoding="utf-8"))[0]["status"] == "interrupted"


# ---- HTTP -----------------------------------------------------------------

def test_api_jobs_and_estimate_are_free_gets(client, studio_root, fake_chat, fake_video):
    fake_chat(json.dumps(_plan(), ensure_ascii=False))
    slug = _create(studio_root)
    r = client.get(f"/api/heartbreak/{slug}/jobs")
    assert r.status_code == 200 and r.json()["jobs"] == []

    assert client.get(f"/api/heartbreak/{slug}/estimate").status_code == 422   # no prompts yet
    assert client.get("/api/heartbreak/nope/jobs").status_code == 404

    assert client.post(f"/api/heartbreak/{slug}/clips/generate").status_code == 403   # no action header
    assert client.post(f"/api/heartbreak/{slug}/clips/A/generate").status_code == 403

    assert client.post(f"/api/heartbreak/{slug}/prompts", json={},
                       headers=_hdr("heartbreak-paid")).status_code == 200
    est = client.get(f"/api/heartbreak/{slug}/estimate").json()
    assert est["pending_ids"] == ["A", "B"]

    r = client.post(f"/api/heartbreak/{slug}/clips/A/generate", json={},
                    headers=_hdr("heartbreak-paid"))
    assert r.status_code == 200 and r.json()["status"] == "running"
    jobs = _wait_jobs(slug)
    assert jobs[0]["status"] == "done"

    # choose a take
    r = client.post(f"/api/heartbreak/{slug}/clips/A/choose", json={"index": 0},
                    headers=_hdr("heartbreak"))
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert client.post(f"/api/heartbreak/{slug}/clips/A/choose", json={"index": 0}).status_code == 403
    assert client.post(f"/api/heartbreak/{slug}/clips/A/choose", json={"index": 5},
                       headers=_hdr("heartbreak")).status_code == 422
    assert client.post(f"/api/heartbreak/{slug}/clips/ZZ/choose", json={"index": 0},
                       headers=_hdr("heartbreak")).status_code == 404

    # generate-all through the API
    r = client.post(f"/api/heartbreak/{slug}/clips/generate", json={},
                    headers=_hdr("heartbreak-paid"))
    assert r.status_code == 200 and r.json()["clips"] == 1      # only B left
    _wait_jobs(slug)
    assert len(client.get(f"/api/heartbreak/{slug}").json()["clips"][1]["versions"]) == 1
