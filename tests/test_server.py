from __future__ import annotations

from starlette.testclient import TestClient

import server
from music_state import MusicStateStore, issue_event_token


def test_health_and_signed_widget_event(tmp_path, monkeypatch):
    store = MusicStateStore(tmp_path / "state.db")
    monkeypatch.setattr(server, "state_store", store)
    token = issue_event_token(
        {
            "song_id": 88,
            "name": "A Real Song",
            "artist": "A Real Artist",
            "album": "Album",
            "selected_by": "user",
        },
        server.EVENT_SIGNING_SECRET,
    )

    with TestClient(server.mcp.streamable_http_app()) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["ok"] is True

        response = client.post(
            server.EVENT_PATH,
            content=(
                f'{{"token":"{token}","event_type":"play",'
                '"actor":"user","position":2.5}'
            ),
            headers={"Content-Type": "text/plain;charset=UTF-8"},
        )
        assert response.status_code == 200
        assert response.json() == {"ok": True, "event_type": "play"}

    context = store.compact_context()
    assert context["status"] == "listening"
    assert context["current"]["song_id"] == 88


def test_invalid_widget_event_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "state_store", MusicStateStore(tmp_path / "state.db"))
    client = TestClient(server.mcp.streamable_http_app())
    response = client.post(
        server.EVENT_PATH,
        content='{"token":"bad","event_type":"play"}',
        headers={"Content-Type": "text/plain"},
    )
    assert response.status_code == 400
