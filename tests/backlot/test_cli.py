"""`python -m backlot` server management: reuse, start, and restart stale servers (no real processes)."""

from __future__ import annotations

import pytest

from backlot import __main__ as cli


@pytest.fixture
def fake(monkeypatch):
    state = {"health": [], "spawned": 0, "killed": []}

    def health(port):
        return state["health"].pop(0) if state["health"] else state.get("after")

    monkeypatch.setattr(cli, "_health", health)
    monkeypatch.setattr(cli, "_spawn_server", lambda port: state.__setitem__("spawned", state["spawned"] + 1))
    monkeypatch.setattr(cli.os, "kill", lambda pid, sig: state["killed"].append(pid))
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    return state


def test_fresh_server_is_reused(fake):
    fake["health"] = [{"app": "backlot", "pid": 42, "stale": False}]
    assert cli._ensure_server(4750) is True
    assert fake["spawned"] == 0 and fake["killed"] == []


def test_stale_server_is_restarted(fake):
    # stale -> (stop) health for pid -> gone (wait loop) -> gone (final check) -> spawn -> alive
    stale = {"app": "backlot", "pid": 42, "stale": True}
    fake["health"] = [stale, stale, None, None]
    fake["after"] = {"app": "backlot", "pid": 43, "stale": False}
    assert cli._ensure_server(4750) is True
    assert fake["killed"] == [42] and fake["spawned"] == 1


def test_missing_server_is_started(fake):
    fake["health"] = [None]
    fake["after"] = {"app": "backlot", "pid": 7, "stale": False}
    assert cli._ensure_server(4750) is True
    assert fake["spawned"] == 1 and fake["killed"] == []


def test_stop_refuses_without_pid(fake):
    fake["health"] = [{"app": "backlot"}]
    assert cli._stop_server(4750) is False
    assert fake["killed"] == []
