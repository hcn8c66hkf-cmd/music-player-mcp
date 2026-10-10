from __future__ import annotations

import asyncio

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


def test_ncm_get_retries_cold_start_and_keeps_cookie_out_of_url(monkeypatch):
    class FakeResponse:
        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self._payload = payload or {"ok": True}

        async def aclose(self):
            return None

        def raise_for_status(self):
            raise AssertionError(f"unexpected status {self.status_code}")

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self):
            self.calls = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, headers=None):
            self.calls.append((url, headers))
            if len(self.calls) < 3:
                return FakeResponse(502)
            return FakeResponse(200, {"result": {"songs": []}})

    fake_client = FakeClient()
    monkeypatch.setattr(server.httpx, "AsyncClient", lambda **kwargs: fake_client)
    monkeypatch.setattr(server, "NCM_API_BASE_URL", "https://ncm.test")
    monkeypatch.setattr(server, "NCM_COOKIE", "MUSIC_U=secret")
    monkeypatch.setattr(server, "NCM_RETRY_DELAYS_SECONDS", (0.0, 0.0, 0.0))

    result = asyncio.run(server.ncm_get("/search?keywords=test"))
    assert result == {"result": {"songs": []}}
    assert len(fake_client.calls) == 3
    assert "MUSIC_U" not in fake_client.calls[0][0]
    assert fake_client.calls[0][1]["Cookie"] == "MUSIC_U=secret"

def test_warm_ncm_source_retries_until_ready(monkeypatch):
    calls = []

    class FakeResponse:
        def __init__(self, status_code):
            self.status_code = status_code

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(502 if len(calls) < 3 else 200)

    monkeypatch.setattr(server.httpx, "get", fake_get)
    monkeypatch.setattr(server.time, "sleep", lambda _: None)
    monkeypatch.setattr(server, "NCM_API_BASE_URL", "https://ncm.test")
    monkeypatch.setattr(server, "NCM_WARMUP_DELAYS_SECONDS", (0.0, 0.0, 0.0))

    server.warm_ncm_source()

    assert len(calls) == 3
    assert calls[0][0] == "https://ncm.test/search?keywords=warmup&limit=1"
    assert calls[0][1]["follow_redirects"] is False

def test_bundled_ncm_process_lifecycle(tmp_path, monkeypatch):
    (tmp_path / "app.js").write_text("// test", encoding="utf-8")
    monkeypatch.setattr(server, "BUNDLED_NCM_DIR", tmp_path)
    monkeypatch.setattr(server, "BUNDLED_NCM_PORT", 3456)
    captured = {}

    class FakeProcess:
        def __init__(self):
            self.terminated = False
            self.waited = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout):
            self.waited = timeout

    fake_process = FakeProcess()

    def fake_popen(command, cwd, env):
        captured.update(command=command, cwd=cwd, env=env)
        return fake_process

    monkeypatch.setattr(server.subprocess, "Popen", fake_popen)

    process = server.start_bundled_ncm()
    assert process is fake_process
    assert captured["command"] == ["node", "app.js"]
    assert captured["cwd"] == tmp_path
    assert captured["env"]["PORT"] == "3456"

    server.stop_bundled_ncm(process)
    assert fake_process.terminated is True
    assert fake_process.waited == 10

