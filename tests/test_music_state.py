from __future__ import annotations

import sqlite3

import pytest

from music_state import MusicStateStore, issue_event_token, verify_event_token

SONG = {
    "provider": "netease",
    "song_id": 123,
    "name": "Night Walk",
    "artist": "Willow",
    "album": "Shared",
    "selected_by": "companion",
}


def test_event_token_round_trip_and_tamper_detection(monkeypatch):
    monkeypatch.setattr("music_state.time.time", lambda: 1_000)
    token = issue_event_token(SONG, "test-secret", ttl_seconds=60)

    claims = verify_event_token(token, "test-secret", now=1_030)
    assert claims["song_id"] == 123
    assert claims["selected_by"] == "companion"

    with pytest.raises(ValueError, match="invalid event token"):
        verify_event_token(token + "x", "test-secret", now=1_030)
    with pytest.raises(ValueError, match="expired event token"):
        verify_event_token(token, "test-secret", now=1_061)


def test_only_real_playback_becomes_active(tmp_path):
    store = MusicStateStore(tmp_path / "state.db", active_lease_seconds=120)
    assert store.compact_context(now=1_000)["status"] == "idle"

    store.record_event("play", "user", SONG, position=3.5, created_at=1_000)
    active = store.compact_context(now=1_100)
    assert active["status"] == "listening"
    assert active["current"]["name"] == "Night Walk"
    assert active["current"]["selected_by"] == "companion"

    stale = store.compact_context(now=1_121)
    assert stale["status"] == "idle"
    assert stale["current"] is None


def test_pause_and_terminal_events_are_not_listening(tmp_path):
    store = MusicStateStore(tmp_path / "state.db")
    store.record_event("play", "user", SONG, created_at=100)
    store.record_event("pause", "user", SONG, position=42, created_at=110)
    paused = store.compact_context(now=120)
    assert paused["status"] == "paused"
    assert paused["current"]["position"] == 42

    store.record_event("close", "user", SONG, position=42, created_at=130)
    closed = store.compact_context(now=131)
    assert closed["status"] == "idle"
    assert closed["current"] is None
    assert closed["last_state"] == "close"


def test_event_history_is_bounded(tmp_path):
    store = MusicStateStore(tmp_path / "state.db", max_events=3)
    for index in range(5):
        store.record_event("play", "user", SONG, created_at=index + 1)

    with sqlite3.connect(tmp_path / "state.db") as connection:
        count = connection.execute("SELECT COUNT(*) FROM music_events").fetchone()[0]
    assert count == 3


def test_rejects_unknown_event_and_actor(tmp_path):
    store = MusicStateStore(tmp_path / "state.db")
    with pytest.raises(ValueError, match="unsupported event type"):
        store.record_event("prepare", "user", SONG)
    with pytest.raises(ValueError, match="unsupported actor"):
        store.record_event("play", "stranger", SONG)
