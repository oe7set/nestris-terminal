"""Local HTTP bridge between the kiosk UI and NestrisLTM / the RFID reader.

Bound to 127.0.0.1 only. Routes:

- ``/api/*``      player-facing calls, forwarded to NestrisLTM with the token
- ``/local/card/write``  write a nickname to the card on the reader
- ``/local/admin/*``     hidden config/debug menu (PIN -> short-lived token)
- ``/ws``         events: card, reader, host, config
- ``/``           the built Svelte UI
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
import time
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, Response, WebSocket
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.websockets import WebSocketDisconnect

from nestris_terminal.config import check_pin, hash_pin, save_settings
from nestris_terminal.host.client import HostError
from nestris_terminal.logging_setup import ring_buffer
from nestris_terminal.rfid import protocol
from nestris_terminal.rfid.card import CardWriteError, ReaderCommandError
from nestris_terminal.rfid.driver import FakeDriver, list_ports

if TYPE_CHECKING:
    from nestris_terminal.runtime import Runtime

ADMIN_TTL_S = 15 * 60
_admin_tokens: dict[str, float] = {}


def web_dir() -> Path:
    return Path(str(resources.files("nestris_terminal"))) / "web"


def rt(request: Request) -> Runtime:
    runtime: Runtime = request.app.state.runtime
    return runtime


# ---------------------------------------------------------------- models


class LinkIn(BaseModel):
    player_id: int


class RegisterIn(BaseModel):
    nickname: str = Field(min_length=1, max_length=64)
    first_name: str | None = Field(default=None, max_length=64)
    last_name: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=255)
    email_consent: bool = False
    card_uid: str | None = Field(default=None, max_length=32)


class ScoreIn(BaseModel):
    score: int = Field(ge=0, le=9_999_999)
    lines: int | None = Field(default=None, ge=0, le=9999)
    start_level: int | None = Field(default=None, ge=0, le=29)
    end_level: int | None = Field(default=None, ge=0, le=255)
    note: str | None = Field(default=None, max_length=500)


class WriteIn(BaseModel):
    name: str = Field(min_length=1, max_length=protocol.MAX_NAME)
    # Only write this card (the one the player just registered with).
    uid: str | None = Field(default=None, pattern=r"^[0-9A-Fa-f]{8}([0-9A-Fa-f]{6}){0,2}$")


class PinIn(BaseModel):
    pin: str = Field(min_length=4, max_length=12, pattern=r"^\d+$")


class ConfigIn(BaseModel):
    host_url: str | None = None
    host_token: str | None = None  # empty/None = keep
    rfid_driver: str | None = None
    rfid_port: str | None = None
    lang: str | None = None
    fullscreen: bool | None = None
    hide_cursor: bool | None = None
    idle_timeout_s: float | None = None
    card_grace_s: float | None = None
    new_pin: str | None = Field(default=None, pattern=r"^\d{4,12}$")


class ReaderConfigIn(BaseModel):
    display: str | None = Field(default=None, pattern=r"^(128x32|128x64|none)$")
    lang: str | None = Field(default=None, pattern=r"^(de|en)$")
    brightness: int | None = Field(default=None, ge=0, le=255)
    flip: bool | None = None


class FakeCardIn(BaseModel):
    action: str = Field(pattern=r"^(place|remove)$")
    uid: str = Field(default="04A1B2C3", max_length=32)
    name: str | None = None
    format: str | None = Field(
        default=None, pattern=r"^(retroverse|legacy|blank|corrupt|unreadable|unsupported)$"
    )


# ---------------------------------------------------------------- helpers


async def _host(call: Any) -> Any:
    try:
        return await call
    except HostError as exc:
        status = exc.status if exc.status >= 400 else 503
        raise HTTPException(status, exc.detail) from exc


def require_admin(x_admin_token: Annotated[str | None, Header()] = None) -> None:
    now = time.monotonic()
    for token, expires in list(_admin_tokens.items()):
        if expires < now:
            _admin_tokens.pop(token, None)
    if not x_admin_token or x_admin_token not in _admin_tokens:
        raise HTTPException(401, "admin PIN required")
    _admin_tokens[x_admin_token] = now + ADMIN_TTL_S  # sliding expiry


AdminDep = Annotated[None, Depends(require_admin)]


# ---------------------------------------------------------------- player API

api = APIRouter(prefix="/api")


@api.get("/state")
async def state(request: Request) -> dict[str, Any]:
    return rt(request).state()


@api.get("/card/{uid}")
async def card(uid: str, request: Request, name: str | None = None) -> Any:
    return await _host(rt(request).host.card(uid, name))


@api.post("/card/{uid}/link")
async def link_card(uid: str, body: LinkIn, request: Request) -> Any:
    return await _host(rt(request).host.link_card(uid, body.player_id))


@api.get("/nickname")
async def nickname(value: str, request: Request) -> Any:
    return await _host(rt(request).host.nickname(value))


@api.post("/players")
async def register(body: RegisterIn, request: Request) -> Any:
    return await _host(rt(request).host.register(body.model_dump()))


@api.get("/players/{player_id}")
async def profile(player_id: int, request: Request) -> Any:
    runtime = rt(request)
    data = await _host(runtime.host.profile(player_id))
    _show_on_reader(runtime, data)
    return data


def _show_on_reader(runtime: Runtime, profile: Any) -> None:
    """Greet the player on the reader's display: nickname + best score."""
    card = runtime.cards.card
    if card is None or not isinstance(profile, dict):
        return
    nickname = str((profile.get("player") or {}).get("nickname") or "")
    current = profile.get("current") or {}
    best = (current.get("standing") or {}).get("best_score") or (profile.get("all_time") or {}).get(
        "best_score"
    )
    en = runtime.settings.kiosk.lang == "en"
    lines = [nickname]
    if isinstance(best, int):
        sep = "," if en else "."
        lines.append(("Best " if en else "Bestwert ") + f"{best:,}".replace(",", sep))
    task = asyncio.get_running_loop().create_task(runtime.cards.show(lines, uid=card.uid))
    _background.add(task)
    task.add_done_callback(_background.discard)


_background: set[asyncio.Task[Any]] = set()


@api.post("/players/{player_id}/games")
async def self_report(player_id: int, body: ScoreIn, request: Request) -> Any:
    return await _host(rt(request).host.self_report(player_id, body.model_dump(exclude_none=True)))


@api.get("/highscore")
async def highscore(request: Request) -> Any:
    return await _host(rt(request).host.highscore())


@api.get("/games/{game_id}/recording")
async def recording(game_id: int, request: Request) -> Response:
    data, source = await _host(rt(request).host.recording(game_id))
    return Response(data, media_type="application/gzip", headers={"X-Recording-Source": source})


# ---------------------------------------------------------------- local: card + admin

local = APIRouter(prefix="/local")


@local.post("/card/write")
async def write_card(body: WriteIn, request: Request) -> dict[str, Any]:
    runtime = rt(request)
    try:
        card = await runtime.cards.write_name(
            body.name,
            runtime.settings.rfid.write_timeout_s,
            uid=body.uid.upper() if body.uid else None,
        )
    except CardWriteError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True, "card": card.as_dict()}


@local.post("/admin/unlock")
async def unlock(body: PinIn, request: Request) -> dict[str, Any]:
    # A wrong PIN costs a second: makes guessing on the touch screen pointless.
    if not check_pin(rt(request).settings, body.pin):
        await asyncio.sleep(1.0)
        raise HTTPException(401, "wrong PIN")
    token = secrets.token_urlsafe(24)
    _admin_tokens[token] = time.monotonic() + ADMIN_TTL_S
    return {"token": token, "ttl_s": ADMIN_TTL_S}


@local.get("/admin/config")
async def get_config(request: Request, _: AdminDep) -> dict[str, Any]:
    s = rt(request).settings
    return {
        "host_url": s.host.url,
        "has_token": bool(s.host.token.get_secret_value()),
        "rfid_driver": s.rfid.driver,
        "rfid_port": s.rfid.port,
        "lang": s.kiosk.lang,
        "fullscreen": s.kiosk.fullscreen,
        "hide_cursor": s.kiosk.hide_cursor,
        "idle_timeout_s": s.kiosk.idle_timeout_s,
        "card_grace_s": s.kiosk.card_grace_s,
        "default_pin": not s.admin.pin_hash,
        "config_file": str(type(s).config_file),
    }


@local.put("/admin/config")
async def put_config(body: ConfigIn, request: Request, _: AdminDep) -> dict[str, Any]:
    runtime = rt(request)
    data = runtime.settings.model_dump(mode="python")
    data["host"]["token"] = runtime.settings.host.token.get_secret_value()
    if body.host_url is not None:
        data["host"]["url"] = body.host_url
    if body.host_token:
        data["host"]["token"] = body.host_token.strip()
    if body.rfid_driver is not None:
        data["rfid"]["driver"] = body.rfid_driver
    if body.rfid_port is not None:
        data["rfid"]["port"] = body.rfid_port
    for key in ("lang", "fullscreen", "hide_cursor", "idle_timeout_s", "card_grace_s"):
        value = getattr(body, key)
        if value is not None:
            data["kiosk"][key] = value
    if body.new_pin:
        data["admin"]["pin_hash"] = hash_pin(body.new_pin)
    try:
        new = type(runtime.settings).model_validate(data)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    path = save_settings(new)
    await runtime.reconfigure(new)
    return {"ok": True, "saved_to": str(path)}


@local.get("/admin/ports")
async def ports(_: AdminDep) -> list[dict[str, Any]]:
    return await asyncio.to_thread(list_ports)


@local.get("/admin/reader")
async def reader_info(request: Request, _: AdminDep) -> dict[str, Any]:
    return rt(request).cards.snapshot()


@local.put("/admin/reader")
async def reader_config(body: ReaderConfigIn, request: Request, _: AdminDep) -> dict[str, Any]:
    """Settings stored in the reader itself (display size, language, brightness)."""
    settings = body.model_dump(exclude_none=True)
    if not settings:
        raise HTTPException(422, "nothing to change")
    try:
        await rt(request).cards.configure(**settings)
    except ReaderCommandError as exc:
        raise HTTPException(409, str(exc)) from exc
    return rt(request).cards.snapshot()


@local.post("/admin/test-host")
async def test_host(request: Request, _: AdminDep) -> dict[str, Any]:
    started = time.monotonic()
    try:
        result = await rt(request).host.ping()
    except HostError as exc:
        return {"ok": False, "status": exc.status, "detail": exc.detail}
    return {"ok": True, "ms": int((time.monotonic() - started) * 1000), "server": result}


@local.get("/admin/debug")
async def debug(request: Request, _: AdminDep) -> dict[str, Any]:
    return await rt(request).debug()


@local.get("/admin/logs")
async def logs(_: AdminDep, after_id: int = 0) -> dict[str, Any]:
    buffer = ring_buffer()
    entries = buffer.entries(after_id=after_id, min_level=logging.INFO) if buffer else []
    return {
        "entries": [
            {"id": e.id, "ts": e.ts.isoformat(), "level": e.level, "message": e.message}
            for e in entries[-300:]
        ]
    }


@local.post("/admin/fake-card")
async def fake_card(body: FakeCardIn, request: Request, _: AdminDep) -> dict[str, Any]:
    driver = rt(request).cards.driver
    if not isinstance(driver, FakeDriver):
        raise HTTPException(409, "only with rfid.driver = fake")
    if body.action == "place":
        driver.place(body.uid, body.name or None, body.format)
    else:
        driver.remove()
    return {"ok": True}


@local.post("/admin/quit")
async def quit_app(request: Request, _: AdminDep) -> dict[str, bool]:
    """Leave the kiosk (e.g. for Windows maintenance on the touch PC)."""
    rt(request).request_shutdown(quit_app=True)
    return {"ok": True}


# ---------------------------------------------------------------- app


def create_app(runtime: Runtime) -> FastAPI:
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> Any:
        await runtime.start()
        try:
            yield
        finally:
            await runtime.stop()

    app = FastAPI(title="Retroverse Terminal", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.runtime = runtime
    app.include_router(api)
    app.include_router(local)

    @app.websocket("/ws")
    async def events(websocket: WebSocket) -> None:
        await websocket.accept()
        sub = runtime.events.subscribe()
        receiver = asyncio.create_task(websocket.receive_text())
        try:
            await websocket.send_json({"type": "state", "data": runtime.state()})
            while True:
                getter = asyncio.create_task(sub.queue.get())
                done, _ = await asyncio.wait(
                    {getter, receiver}, return_when=asyncio.FIRST_COMPLETED
                )
                if receiver in done:
                    getter.cancel()
                    receiver.result()  # raises WebSocketDisconnect when the client left
                    receiver = asyncio.create_task(websocket.receive_text())
                    continue
                await websocket.send_json(getter.result())
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            receiver.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await receiver
            runtime.events.unsubscribe(sub)

    app.mount(
        "/assets", StaticFiles(directory=web_dir() / "assets", check_dir=False), name="assets"
    )

    @app.get("/{path:path}", include_in_schema=False, response_model=None)
    async def ui(path: str) -> FileResponse | HTMLResponse:
        candidate = web_dir() / path
        if path and candidate.is_file() and web_dir() in candidate.resolve().parents:
            return FileResponse(candidate)
        index = web_dir() / "index.html"
        if index.is_file():
            return FileResponse(index, headers={"Cache-Control": "no-store"})
        return HTMLResponse(
            "<p style='font:20px sans-serif'>UI not built: run <code>pnpm build</code> in "
            "<code>frontend/</code>.</p>",
            status_code=503,
        )

    @app.exception_handler(HostError)
    async def host_error(_: Request, exc: HostError) -> JSONResponse:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status or 503)

    return app
