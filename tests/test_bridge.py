"""Bridge: forwarding to a stub NestrisLTM, card writing, the admin menu."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from nestris_terminal.bridge.app import create_app
from nestris_terminal.config import load_settings
from nestris_terminal.rfid.driver import FakeDriver
from nestris_terminal.runtime import Runtime


class StubHost:
    """A tiny NestrisLTM terminal API."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, Any]] = []
        self.token_ok = True
        self.reader_fw: str | None = None
        self.cards: dict[str, dict[str, Any]] = {}  # uid -> player
        self.old_host = False  # NestrisLTM before 0.5.1: no search, no DELETE /card

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, request.url.path, body))
        if not self.token_ok:
            return httpx.Response(401, json={"detail": "invalid token"})
        assert request.headers["authorization"] == "Bearer nltm_test"
        assert request.headers["x-terminal-version"]
        self.reader_fw = request.headers.get("x-reader-firmware")
        path = request.url.path.removeprefix("/api/terminal/v1")
        if path == "/ping":
            return httpx.Response(
                200, json={"ok": True, "version": "x", "event": {"id": 1, "name": "2026"}}
            )
        if self.old_host and (
            request.method == "DELETE" or (path == "/players" and request.method == "GET")
        ):
            return httpx.Response(405, json={"detail": "Method Not Allowed"})
        if path.startswith("/card/") and path.endswith("/link"):
            uid = path.split("/")[2]
            self.cards[uid] = {"id": body["player_id"], "nickname": "Erv"}
            return httpx.Response(200, json={"ok": True, "player": self.cards[uid]})
        if path.startswith("/card/") and request.method == "DELETE":
            player = self.cards.pop(path.split("/")[2], None)
            return httpx.Response(200, json={"ok": True, "player": player})
        if path == "/players" and request.method == "GET":
            q = request.url.params.get("q", "")
            players = [{"id": 7, "nickname": "Erv", "cards": 1}] if q.lower() in "erv" else []
            return httpx.Response(200, json={"players": players})
        if path.startswith("/card/") and path.split("/")[2] in self.cards:
            uid = path.split("/")[2]
            return httpx.Response(
                200, json={"status": "known", "uid": uid, "player": self.cards[uid]}
            )
        if path.startswith("/card/"):
            return httpx.Response(
                200, json={"status": "unknown", "uid": path.split("/")[2], "name": None}
            )
        if path == "/players" and request.method == "POST":
            if body["nickname"] == "Taken":
                return httpx.Response(409, json={"detail": "nickname is already taken"})
            return httpx.Response(201, json={"player": {"id": 7, "nickname": body["nickname"]}})
        if path == "/players/7":
            return httpx.Response(
                200,
                json={
                    "player": {"id": 7, "nickname": "Erv"},
                    "all_time": {"best_score": 216560},
                    "current": {"standing": {"best_score": 159867}},
                    "events": [],
                    "games": [],
                },
            )
        if path == "/games/5/recording":
            return httpx.Response(
                200, content=b"\x1f\x8bngf", headers={"X-Recording-Source": "recording"}
            )
        return httpx.Response(404, json={"detail": "not found"})


@pytest.fixture
async def setup(tmp_path: Path) -> AsyncIterator[tuple[Runtime, httpx.AsyncClient, StubHost]]:
    stub = StubHost()
    settings = load_settings(
        tmp_path / "config.toml",
        data_dir=tmp_path,
        host={"url": "http://host.test:7990", "token": "nltm_test"},
        rfid={"driver": "fake"},
    )
    runtime = Runtime(settings, host_transport=httpx.MockTransport(stub))
    runtime.cards.driver.interval_s = 0.05  # type: ignore[attr-defined]
    runtime.cards.start()
    transport = httpx.ASGITransport(app=create_app(runtime))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        yield runtime, client, stub
    await runtime.cards.stop()
    await runtime.host.close()


async def test_forwarding_and_errors(setup: tuple[Runtime, httpx.AsyncClient, StubHost]) -> None:
    runtime, client, stub = setup
    r = await client.get("/api/card/04AA")
    assert r.json()["status"] == "unknown"
    r = await client.post("/api/players", json={"nickname": "Erv", "card_uid": "04AA"})
    assert r.json()["player"]["id"] == 7
    r = await client.post("/api/players", json={"nickname": "Taken"})
    assert r.status_code == 409 and r.json()["detail"] == "nickname is already taken"
    r = await client.get("/api/games/5/recording")
    assert r.content == b"\x1f\x8bngf" and r.headers["x-recording-source"] == "recording"
    stub.token_ok = False
    r = await client.get("/api/card/04AA")
    assert r.status_code == 401
    assert "check host.token" in (runtime.host.last_error or "")


async def until(check: Callable[[], object]) -> None:
    for _ in range(200):
        if check():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not reached")


async def test_card_write(setup: tuple[Runtime, httpx.AsyncClient, StubHost]) -> None:
    runtime, client, _ = setup
    await until(lambda: runtime.cards.ready)
    driver = runtime.cards.driver
    assert isinstance(driver, FakeDriver)
    driver.place("04AA0001", None)
    r = await client.post("/local/card/write", json={"name": "Erv", "uid": "04aa0001"})
    assert r.status_code == 200, r.text
    assert r.json()["card"] == {"uid": "04AA0001", "name": "Erv", "format": "retroverse"}
    assert '"uid":"04AA0001"' in driver.sent[-1]
    driver.fail_writes = True
    r = await client.post("/local/card/write", json={"name": "Erv2"})
    assert r.status_code == 409 and r.json()["detail"].startswith("write")
    r = await client.post("/local/card/write", json={"name": "Erv", "uid": "nothex!"})
    assert r.status_code == 422


async def test_admin_cards(setup: tuple[Runtime, httpx.AsyncClient, StubHost]) -> None:
    """Clear mode and a new card for a player (hidden menu, tab "Karten")."""
    runtime, client, stub = setup
    await until(lambda: runtime.cards.ready)
    driver = runtime.cards.driver
    assert isinstance(driver, FakeDriver)
    assert (await client.get("/local/admin/players", params={"q": "erv"})).status_code == 401
    token = (await client.post("/local/admin/unlock", json={"pin": "2580"})).json()["token"]
    h = {"x-admin-token": token}

    r = await client.get("/local/admin/players", params={"q": "er"}, headers=h)
    assert r.json()["players"] == [{"id": 7, "nickname": "Erv", "cards": 1}]

    # New card for Erv: written with the nickname, linked on the host.
    stub.cards["04BB0002"] = {"id": 9, "nickname": "Max"}
    driver.place("04BB0002", "Max", "retroverse")
    r = await client.post(
        "/local/admin/cards/issue", json={"player_id": 7, "nickname": "Erv"}, headers=h
    )
    assert r.status_code == 200, r.text
    assert r.json()["card"] == {"uid": "04BB0002", "name": "Erv", "format": "retroverse"}
    assert r.json()["player"]["id"] == 7
    assert r.json()["previous"] == {"id": 9, "nickname": "Max"}  # the card was Max's
    assert ("POST", "/api/terminal/v1/card/04BB0002/link", {"player_id": 7}) in stub.requests

    # Clear mode: the card becomes blank and is forgotten on the host.
    r = await client.post("/local/admin/cards/clear", json={"uid": "04bb0002"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json() == {
        "ok": True, "uid": "04BB0002", "name": "Erv", "erased": True,
        "player": {"id": 7, "nickname": "Erv"},
    }  # fmt: skip
    assert '"type": "erase"' in driver.sent[-1] or '"type":"erase"' in driver.sent[-1]
    await until(lambda: runtime.cards.card and runtime.cards.card.format == "blank")
    assert "04BB0002" not in stub.cards
    # Already blank: only forgotten on the host, no second write.
    sent = len(driver.sent)
    r = await client.post("/local/admin/cards/clear", json={"uid": "04BB0002"}, headers=h)
    assert r.json()["erased"] is False and r.json()["player"] is None
    assert not any("erase" in line for line in driver.sent[sent:])

    # Reader firmware 1.0.0 knows no erase; NestrisLTM before 0.5.1 no search.
    driver.can_erase = False
    driver.place("04CC0003", "Old", "legacy")
    r = await client.post("/local/admin/cards/clear", json={"uid": "04CC0003"}, headers=h)
    assert r.status_code == 409 and r.json()["detail"] == "reader_fw_old"
    stub.old_host = True
    r = await client.get("/local/admin/players", params={"q": "er"}, headers=h)
    assert r.status_code == 409 and r.json()["detail"] == "host_old"


async def test_profile_greets_on_the_reader(
    setup: tuple[Runtime, httpx.AsyncClient, StubHost],
) -> None:
    runtime, client, stub = setup
    await until(lambda: runtime.cards.ready)
    driver = runtime.cards.driver
    assert isinstance(driver, FakeDriver)
    driver.place("04AA0001", "Erv")
    await until(lambda: runtime.cards.card)
    assert (await client.get("/api/players/7")).status_code == 200
    assert stub.reader_fw == "0.0.0-fake"  # for NestrisLTM's device overview
    await until(lambda: driver.shown)
    assert driver.shown == ["Erv", "Bestwert 159.867"]


async def test_admin_menu(
    setup: tuple[Runtime, httpx.AsyncClient, StubHost], tmp_path: Path
) -> None:
    runtime, client, _ = setup
    assert (await client.get("/local/admin/config")).status_code == 401
    assert (await client.post("/local/admin/unlock", json={"pin": "1111"})).status_code == 401
    token = (await client.post("/local/admin/unlock", json={"pin": "2580"})).json()["token"]
    headers = {"X-Admin-Token": token}

    config = (await client.get("/local/admin/config", headers=headers)).json()
    assert config["has_token"] and config["default_pin"] and config["rfid_driver"] == "fake"

    r = await client.put(
        "/local/admin/config",
        headers=headers,
        json={"lang": "en", "idle_timeout_s": 90, "new_pin": "135790", "rfid_driver": "fake"},
    )
    assert r.status_code == 200, r.text
    assert (tmp_path / "config.toml").is_file()
    assert runtime.settings.kiosk.lang == "en"
    assert (await client.post("/local/admin/unlock", json={"pin": "2580"})).status_code == 401
    assert (await client.post("/local/admin/unlock", json={"pin": "135790"})).status_code == 200
    bad = await client.put("/local/admin/config", headers=headers, json={"host_url": "nope"})
    assert bad.status_code == 422

    r = await client.post(
        "/local/admin/fake-card",
        headers=headers,
        json={"action": "place", "uid": "0B0B", "name": "Max"},
    )
    assert r.status_code == 200
    debug = (await client.get("/local/admin/debug", headers=headers)).json()
    assert "network" in debug and debug["reader"]["port"] == "fake"

    await until(lambda: runtime.cards.ready)
    r = await client.put("/local/admin/reader", headers=headers, json={"display": "128x64"})
    assert r.status_code == 200, r.text
    await until(lambda: runtime.cards.reader_info()["display"] == "128x64")
    assert (await client.put("/local/admin/reader", headers=headers, json={})).status_code == 422
    bad = await client.put("/local/admin/reader", headers=headers, json={"display": "4k"})
    assert bad.status_code == 422
    state = (await client.get("/api/state")).json()
    assert state["kiosk"]["lang"] == "en"
