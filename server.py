"""Chat-native music player MCP with durable shared-listening state.

One ASGI service exposes the MCP endpoint, a signed audio stream, widget event
ingestion, and health checks. A separately configured Netease-compatible API
remains private behind this service.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Literal
from urllib.parse import quote, urljoin, urlparse

import httpx
import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from music_state import MusicStateStore, issue_event_token, verify_event_token

LOGGER = logging.getLogger("music-player")
BASE_DIR = Path(__file__).parent
WIDGET_JS_PATH = BASE_DIR / "dist" / "widget" / "music-player-widget.global.js"

NCM_API_BASE_URL = os.getenv("NCM_API_BASE_URL", "http://127.0.0.1:3939").rstrip("/")
NCM_COOKIE_FILE = os.getenv("NCM_COOKIE_FILE", "")
NCM_COOKIE = os.getenv("NCM_COOKIE", "").strip()
NCM_RETRYABLE_STATUS_CODES = frozenset({502, 503, 504})
NCM_RETRY_DELAYS_SECONDS = (0.0, 2.0, 5.0, 10.0, 15.0)
NCM_WARMUP_DELAYS_SECONDS = (0.0, 5.0, 10.0, 15.0, 20.0, 30.0)
APP_HOST = os.getenv("APP_HOST", os.getenv("MCP_HOST", "127.0.0.1"))
APP_PORT = int(os.getenv("PORT", os.getenv("APP_PORT", os.getenv("MCP_PORT", "3941"))))
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", f"http://127.0.0.1:{APP_PORT}").rstrip("/")
PUBLIC_URL_PARTS = urlparse(PUBLIC_BASE_URL)
MUSIC_STATE_PATH = os.getenv("MUSIC_STATE_PATH", str(BASE_DIR / "data" / "music_state.db"))
ACTIVE_LEASE_SECONDS = int(os.getenv("MUSIC_ACTIVE_LEASE_SECONDS", "7200"))
EVENT_TOKEN_TTL_SECONDS = int(os.getenv("MUSIC_EVENT_TOKEN_TTL_SECONDS", "86400"))
EVENT_SIGNING_SECRET = os.getenv("MUSIC_EVENT_SIGNING_SECRET") or secrets.token_urlsafe(32)
ALLOWED_AUDIO_HOST_SUFFIXES = tuple(
    item.strip().lower()
    for item in os.getenv("ALLOWED_AUDIO_HOST_SUFFIXES", ".music.126.net").split(",")
    if item.strip()
)

if not os.getenv("MUSIC_EVENT_SIGNING_SECRET"):
    LOGGER.warning("MUSIC_EVENT_SIGNING_SECRET is unset; widget tokens will reset on restart")

MUSIC_VIEW_URI = "ui://music-player/mcp-app-v2.html"
MUSIC_VIEW_MIME = "text/html;profile=mcp-app"
AUDIO_STREAM_PATH = "/music-audio/stream"
EVENT_PATH = "/music-state/event"

state_store = MusicStateStore(MUSIC_STATE_PATH, active_lease_seconds=ACTIVE_LEASE_SECONDS)
allowed_hosts = list(
    dict.fromkeys(
        [
            PUBLIC_URL_PARTS.netloc,
            PUBLIC_URL_PARTS.hostname or "",
            f"{PUBLIC_URL_PARTS.hostname}:*" if PUBLIC_URL_PARTS.hostname else "",
            "127.0.0.1:*",
            "localhost:*",
            "[::1]:*",
        ]
    )
)
allowed_origins = list(
    dict.fromkeys(
        [
            f"{PUBLIC_URL_PARTS.scheme}://{PUBLIC_URL_PARTS.netloc}",
            "https://chatgpt.com",
            "https://chat.openai.com",
            "http://127.0.0.1:*",
            "http://localhost:*",
        ]
    )
)
mcp = FastMCP(
    "music-player",
    host=APP_HOST,
    port=APP_PORT,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[value for value in allowed_hosts if value],
        allowed_origins=[value for value in allowed_origins if value],
    ),
)


def _public_origin() -> str:
    parsed = urlparse(PUBLIC_BASE_URL)
    return f"{parsed.scheme}://{parsed.netloc}"


def _public_url(path: str, **query: str) -> str:
    base = f"{PUBLIC_BASE_URL}{path}"
    if not query:
        return base
    return f"{base}?" + "&".join(f"{key}={quote(value, safe='')}" for key, value in query.items())


def _cors_headers() -> dict[str, str]:
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type,Range",
        "Access-Control-Expose-Headers": "Accept-Ranges,Content-Length,Content-Range,Content-Type",
    }


def widget_html() -> str:
    if not WIDGET_JS_PATH.exists():
        return "<!doctype html><html><body><p>Run <code>npm run build:widget</code> first.</p></body></html>"
    js = WIDGET_JS_PATH.read_text(encoding="utf-8")
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<style>:root{color-scheme:light dark}*{box-sizing:border-box}"
        "html,body{margin:0;padding:0;background:transparent;width:100%;height:fit-content;overflow:hidden}"
        "#root{display:block;width:100%}</style></head>"
        f"<body><div id='root'></div><script>{js}</script></body></html>"
    )


WIDGET_META = {
    "openai/outputTemplate": MUSIC_VIEW_URI,
    "ui": {
        "resourceUri": MUSIC_VIEW_URI,
        "csp": {
            "resourceDomains": ["https://*.music.126.net"],
            "connectDomains": [_public_origin()],
        },
    },
}


@mcp.resource(MUSIC_VIEW_URI, mime_type=MUSIC_VIEW_MIME, name="music-player", meta=WIDGET_META["ui"])
def music_view() -> str:
    return widget_html()


class MusicPayload(BaseModel):
    audioUrl: str
    eventUrl: str
    eventToken: str
    songId: int
    coverUrl: str = ""
    songName: str = "Unknown track"
    artistName: str = "Unknown artist"
    albumName: str = ""
    selectedBy: str = "companion"
    duration: int = 0
    lyrics: str = ""
    colorPrimary: str = "#6e7c87"
    colorSecondary: str = "#CAE0E8"
    colorBg: str = "#1a1d21"
    colorBgEnd: str = "#2a2d31"


def get_cookie() -> str:
    """Load the private login cookie without ever returning it to clients."""
    if NCM_COOKIE_FILE:
        try:
            value = Path(NCM_COOKIE_FILE).read_text(encoding="utf-8").strip()
            if value:
                return value
        except OSError:
            pass
    return NCM_COOKIE


async def ncm_get(path: str) -> dict:
    """Call the private Netease-compatible API and tolerate Render cold starts."""
    cookie = get_cookie()
    url = f"{NCM_API_BASE_URL}{path}"
    headers = {"Cookie": cookie, "User-Agent": "Mozilla/5.0"} if cookie else {"User-Agent": "Mozilla/5.0"}

    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        for attempt, delay in enumerate(NCM_RETRY_DELAYS_SECONDS):
            if delay:
                await asyncio.sleep(delay)
            try:
                response = await client.get(url, headers=headers)
            except (httpx.TimeoutException, httpx.NetworkError) as error:
                if attempt == len(NCM_RETRY_DELAYS_SECONDS) - 1:
                    raise RuntimeError("NCM upstream request failed after retries") from error
                LOGGER.warning(
                    "NCM upstream request failed; retrying cold-start request (%d/%d)",
                    attempt + 1,
                    len(NCM_RETRY_DELAYS_SECONDS),
                )
                continue

            if response.status_code in NCM_RETRYABLE_STATUS_CODES:
                if attempt < len(NCM_RETRY_DELAYS_SECONDS) - 1:
                    await response.aclose()
                    LOGGER.warning(
                        "NCM upstream returned HTTP %s; retrying cold-start request (%d/%d)",
                        response.status_code,
                        attempt + 1,
                        len(NCM_RETRY_DELAYS_SECONDS),
                    )
                    continue
                raise RuntimeError(
                    f"NCM upstream unavailable after retries (HTTP {response.status_code})"
                )

            response.raise_for_status()
            return response.json()

    raise RuntimeError("NCM upstream request failed after retries")


def warm_ncm_source() -> None:
    """Wake a sleeping Render music-source instance without blocking MCP startup."""
    url = f"{NCM_API_BASE_URL}/search?keywords=warmup&limit=1"
    headers = {"User-Agent": "Mozilla/5.0"}
    for attempt, delay in enumerate(NCM_WARMUP_DELAYS_SECONDS):
        if delay:
            time.sleep(delay)
        try:
            response = httpx.get(url, headers=headers, timeout=15, follow_redirects=False)
            if response.status_code not in NCM_RETRYABLE_STATUS_CODES:
                LOGGER.info("NCM upstream warmup ready (HTTP %s)", response.status_code)
                return
        except httpx.HTTPError:
            pass
        LOGGER.info(
            "NCM upstream still waking (%d/%d)",
            attempt + 1,
            len(NCM_WARMUP_DELAYS_SECONDS),
        )
    LOGGER.warning("NCM upstream did not become ready during background warmup")


def is_allowed_audio_url(value: str) -> bool:
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower()
    return parsed.scheme in {"http", "https"} and any(
        hostname == suffix.lstrip(".") or hostname.endswith(suffix)
        for suffix in ALLOWED_AUDIO_HOST_SUFFIXES
    )


async def get_song_url(song_id: int) -> str | None:
    data = await ncm_get(f"/song/url?id={song_id}&br=128000")
    items = data.get("data", [])
    value = items[0].get("url") if items else None
    if value and is_allowed_audio_url(value):
        return value
    return None


async def get_song_detail(song_id: int) -> dict:
    data = await ncm_get(f"/song/detail?ids={song_id}")
    songs = data.get("songs", [])
    if not songs:
        return {}
    song = songs[0]
    return {
        "name": song.get("name", "Unknown track"),
        "artist": ", ".join(a.get("name", "") for a in song.get("ar", [])) or "Unknown artist",
        "album": song.get("al", {}).get("name", ""),
        "cover": song.get("al", {}).get("picUrl", ""),
        "duration": song.get("dt", 0) // 1000,
    }


async def get_lyrics(song_id: int) -> str:
    try:
        return (await ncm_get(f"/lyric?id={song_id}")).get("lrc", {}).get("lyric", "")
    except (httpx.HTTPError, asyncio.TimeoutError):
        return ""


async def music_info(song_id: int, selected_by: str) -> dict:
    detail = await get_song_detail(song_id)
    if not detail:
        raise ValueError("Track not found.")
    if not await get_song_url(song_id):
        raise ValueError(f"{detail['name']} has no playable URL. It may be restricted.")
    return {
        "song_id": song_id,
        "lyrics": await get_lyrics(song_id),
        "selected_by": selected_by,
        **detail,
    }


async def search_and_play(keywords: str, selected_by: str) -> dict:
    data = await ncm_get(f"/search?keywords={quote(keywords)}&limit=5")
    songs = data.get("result", {}).get("songs", [])
    if not songs:
        raise ValueError(f"No track found for {keywords!r}.")
    for song in songs:
        try:
            return await music_info(int(song["id"]), selected_by)
        except ValueError:
            continue
    raise ValueError(f"No playable track found for {keywords!r}.")


def payload(info: dict, color_primary: str, color_secondary: str, color_bg: str) -> MusicPayload:
    event_token = issue_event_token(info, EVENT_SIGNING_SECRET, EVENT_TOKEN_TTL_SECONDS)
    return MusicPayload(
        audioUrl=_public_url(AUDIO_STREAM_PATH, token=event_token),
        eventUrl=_public_url(EVENT_PATH),
        eventToken=event_token,
        songId=info["song_id"],
        coverUrl=info["cover"],
        songName=info["name"],
        artistName=info["artist"],
        albumName=info["album"],
        selectedBy=info["selected_by"],
        duration=info["duration"],
        lyrics=info["lyrics"],
        colorPrimary=color_primary,
        colorSecondary=color_secondary,
        colorBg=color_bg,
        colorBgEnd=color_bg.replace("#1a", "#2a") if color_bg.startswith("#1a") else color_bg,
    )


@mcp.tool(
    name="play_music",
    description=(
        "Search for a real playable track and render a compact in-chat player. "
        "Set selected_by to user when directly fulfilling the user's exact choice, "
        "or companion when making your own selection or recommendation."
    ),
    meta=WIDGET_META,
)
async def play_music(
    keywords: str,
    selected_by: Literal["user", "companion"] = "user",
    color_primary: str = "#6e7c87",
    color_secondary: str = "#CAE0E8",
    color_bg: str = "#1a1d21",
) -> MusicPayload:
    return payload(await search_and_play(keywords, selected_by), color_primary, color_secondary, color_bg)


@mcp.tool(
    name="play_music_by_id",
    description=(
        "Render a compact in-chat player for a verified Netease track ID. "
        "Set selected_by to user or companion to preserve who chose it."
    ),
    meta=WIDGET_META,
)
async def play_music_by_id(
    song_id: int,
    selected_by: Literal["user", "companion"] = "user",
    color_primary: str = "#6e7c87",
    color_secondary: str = "#CAE0E8",
    color_bg: str = "#1a1d21",
) -> MusicPayload:
    return payload(await music_info(song_id, selected_by), color_primary, color_secondary, color_bg)


@mcp.tool(
    name="get_music_session",
    description=(
        "Read compact, factual shared-listening state. Use it before referring to "
        "what is currently playing; status=listening is the only active state."
    ),
)
def get_music_session() -> dict:
    return state_store.compact_context()


async def _open_upstream_stream(target_url: str, range_header: str | None):
    current_url = target_url
    client = httpx.AsyncClient(timeout=httpx.Timeout(60, connect=15), follow_redirects=False)
    headers = {"Referer": "https://music.163.com/", "User-Agent": "Mozilla/5.0"}
    if range_header:
        headers["Range"] = range_header
    try:
        for _ in range(4):
            if not is_allowed_audio_url(current_url):
                raise ValueError("Audio host is not allowed")
            request = client.build_request("GET", current_url, headers=headers)
            response = await client.send(request, stream=True)
            if response.status_code not in {301, 302, 303, 307, 308}:
                return client, response
            location = response.headers.get("location")
            await response.aclose()
            if not location:
                break
            current_url = urljoin(current_url, location)
        raise httpx.TooManyRedirects("Too many audio redirects")
    except Exception:
        await client.aclose()
        raise


@mcp.custom_route(AUDIO_STREAM_PATH, methods=["GET", "OPTIONS"])
async def audio_stream(request: Request) -> Response:
    if request.method == "OPTIONS":
        return Response(status_code=204, headers=_cors_headers())
    try:
        claims = verify_event_token(request.query_params.get("token", ""), EVENT_SIGNING_SECRET)
        target_url = await get_song_url(int(claims["song_id"]))
        if not target_url:
            return JSONResponse({"error": "track_unavailable"}, status_code=404, headers=_cors_headers())
        client, upstream = await _open_upstream_stream(target_url, request.headers.get("range"))
        if upstream.status_code not in {200, 206}:
            status = upstream.status_code
            await upstream.aclose()
            await client.aclose()
            return JSONResponse(
                {"error": "upstream_error", "status": status},
                status_code=502,
                headers=_cors_headers(),
            )

        async def chunks():
            try:
                async for chunk in upstream.aiter_bytes(64 * 1024):
                    yield chunk
            finally:
                await upstream.aclose()
                await client.aclose()

        headers = _cors_headers()
        for name in ("content-type", "content-length", "content-range", "accept-ranges"):
            if value := upstream.headers.get(name):
                headers[name] = value
        headers["Cache-Control"] = "private, max-age=600"
        return StreamingResponse(chunks(), status_code=upstream.status_code, headers=headers)
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=403, headers=_cors_headers())
    except (httpx.HTTPError, asyncio.TimeoutError) as error:
        LOGGER.warning("Audio stream failed: %s", type(error).__name__)
        return JSONResponse({"error": "audio_stream_failed"}, status_code=502, headers=_cors_headers())


@mcp.custom_route(EVENT_PATH, methods=["POST", "OPTIONS"])
async def record_music_event(request: Request) -> Response:
    if request.method == "OPTIONS":
        return Response(status_code=204, headers=_cors_headers())
    raw = await request.body()
    if len(raw) > 16_384:
        return JSONResponse({"error": "payload_too_large"}, status_code=413, headers=_cors_headers())
    try:
        body = json.loads(raw)
        song = verify_event_token(str(body.get("token", "")), EVENT_SIGNING_SECRET)
        event = state_store.record_event(
            event_type=str(body.get("event_type", "")),
            actor=str(body.get("actor", "user")),
            song=song,
            position=float(body.get("position", 0) or 0),
        )
        return JSONResponse({"ok": True, "event_type": event["event_type"]}, headers=_cors_headers())
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        return JSONResponse({"error": str(error)}, status_code=400, headers=_cors_headers())


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> Response:
    return JSONResponse({"ok": True, "service": "music-player-mcp"})


if __name__ == "__main__":
    threading.Thread(target=warm_ncm_source, name="ncm-warmup", daemon=True).start()
    uvicorn.run(mcp.streamable_http_app(), host=APP_HOST, port=APP_PORT)
