"""Durable shared-listening state for the music player.

The state deliberately stores compact song metadata and playback events only.
Temporary audio URLs, lyrics, cookies, and account data never enter SQLite.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

TERMINAL_STATES = {"close", "finish"}
ACTIVE_STATES = {"play", "resume"}
ALLOWED_EVENTS = ACTIVE_STATES | {"pause"} | TERMINAL_STATES


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue_event_token(song: dict[str, Any], secret: str, ttl_seconds: int = 86_400) -> str:
    """Issue a short-lived signed token that lets a widget report this song only."""
    now = int(time.time())
    claims = {
        "provider": "netease",
        "song_id": int(song["song_id"]),
        "name": str(song["name"]),
        "artist": str(song["artist"]),
        "album": str(song.get("album", "")),
        "selected_by": str(song.get("selected_by", "companion")),
        "iat": now,
        "exp": now + ttl_seconds,
    }
    encoded = _b64encode(json.dumps(claims, ensure_ascii=False, separators=(",", ":")).encode())
    signature = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest()
    return f"{encoded}.{_b64encode(signature)}"


def verify_event_token(token: str, secret: str, now: int | None = None) -> dict[str, Any]:
    """Validate an event token and return its trusted song metadata."""
    try:
        encoded, supplied_signature = token.split(".", 1)
        expected = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64decode(supplied_signature), expected):
            raise ValueError("invalid signature")
        claims = json.loads(_b64decode(encoded))
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("invalid event token") from error

    current_time = int(time.time()) if now is None else now
    if int(claims.get("exp", 0)) < current_time:
        raise ValueError("expired event token")
    required = {"provider", "song_id", "name", "artist", "selected_by"}
    if not required.issubset(claims):
        raise ValueError("incomplete event token")
    return claims


class MusicStateStore:
    """Small SQLite ledger for one private shared-listening installation."""

    def __init__(self, path: str | Path, max_events: int = 500, active_lease_seconds: int = 7200):
        self.path = Path(path)
        self.max_events = max_events
        self.active_lease_seconds = active_lease_seconds
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS music_session (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    state TEXT NOT NULL,
                    provider TEXT,
                    song_id INTEGER,
                    name TEXT,
                    artist TEXT,
                    album TEXT,
                    selected_by TEXT,
                    actor TEXT,
                    position REAL NOT NULL DEFAULT 0,
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS music_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    song_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    artist TEXT NOT NULL,
                    album TEXT NOT NULL DEFAULT '',
                    selected_by TEXT NOT NULL,
                    position REAL NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_music_events_created_at
                ON music_events(created_at DESC);
                """
            )

    def record_event(
        self,
        event_type: str,
        actor: str,
        song: dict[str, Any],
        position: float = 0,
        created_at: int | None = None,
    ) -> dict[str, Any]:
        if event_type not in ALLOWED_EVENTS:
            raise ValueError(f"unsupported event type: {event_type}")
        if actor not in {"user", "companion"}:
            raise ValueError(f"unsupported actor: {actor}")

        timestamp = int(time.time()) if created_at is None else int(created_at)
        position = max(0.0, float(position or 0))
        values = {
            "event_type": event_type,
            "actor": actor,
            "provider": str(song.get("provider", "netease")),
            "song_id": int(song["song_id"]),
            "name": str(song["name"]),
            "artist": str(song["artist"]),
            "album": str(song.get("album", "")),
            "selected_by": str(song.get("selected_by", "companion")),
            "position": position,
            "created_at": timestamp,
        }

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO music_events (
                    event_type, actor, provider, song_id, name, artist, album,
                    selected_by, position, created_at
                ) VALUES (
                    :event_type, :actor, :provider, :song_id, :name, :artist, :album,
                    :selected_by, :position, :created_at
                )
                """,
                values,
            )
            connection.execute(
                """
                INSERT INTO music_session (
                    singleton, state, provider, song_id, name, artist, album,
                    selected_by, actor, position, updated_at
                ) VALUES (
                    1, :event_type, :provider, :song_id, :name, :artist, :album,
                    :selected_by, :actor, :position, :created_at
                )
                ON CONFLICT(singleton) DO UPDATE SET
                    state=excluded.state,
                    provider=excluded.provider,
                    song_id=excluded.song_id,
                    name=excluded.name,
                    artist=excluded.artist,
                    album=excluded.album,
                    selected_by=excluded.selected_by,
                    actor=excluded.actor,
                    position=excluded.position,
                    updated_at=excluded.updated_at
                """,
                values,
            )
            connection.execute(
                """
                DELETE FROM music_events WHERE id NOT IN (
                    SELECT id FROM music_events ORDER BY id DESC LIMIT ?
                )
                """,
                (self.max_events,),
            )
        return values

    def compact_context(self, now: int | None = None, event_limit: int = 5) -> dict[str, Any]:
        timestamp = int(time.time()) if now is None else int(now)
        with self._connect() as connection:
            session_row = connection.execute(
                "SELECT * FROM music_session WHERE singleton = 1"
            ).fetchone()
            event_rows = connection.execute(
                """
                SELECT event_type, actor, provider, song_id, name, artist, album,
                       selected_by, position, created_at
                FROM music_events ORDER BY id DESC LIMIT ?
                """,
                (event_limit,),
            ).fetchall()

        recent_events = [dict(row) for row in event_rows]
        if not session_row:
            return {"status": "idle", "current": None, "recent_events": recent_events}

        session = dict(session_row)
        age = max(0, timestamp - int(session["updated_at"]))
        state = session["state"]
        if state in ACTIVE_STATES and age <= self.active_lease_seconds:
            status = "listening"
        elif state == "pause":
            status = "paused"
        else:
            status = "idle"

        current = None
        if status in {"listening", "paused"}:
            current = {
                "provider": session["provider"],
                "song_id": session["song_id"],
                "name": session["name"],
                "artist": session["artist"],
                "album": session["album"],
                "selected_by": session["selected_by"],
                "last_actor": session["actor"],
                "position": session["position"],
                "updated_at": session["updated_at"],
            }

        return {
            "status": status,
            "current": current,
            "last_state": state,
            "last_updated_at": session["updated_at"],
            "recent_events": recent_events,
        }
