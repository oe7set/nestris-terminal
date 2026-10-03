"""CardTracker against the v2 fake reader and hand-written reader lines."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from nestris_terminal.rfid.card import Card, CardTracker, CardWriteError
from nestris_terminal.rfid.driver import FakeDriver


class SilentDriver:
    """A port that delivers nothing by itself; tests feed lines directly."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.connected = True
        self.port = "test"

    def start(self, on_line: Any) -> None:
        pass

    def stop(self) -> None:
        pass

    def send(self, line: str) -> bool:
        self.sent.append(json.loads(line))
        return True


def hello(proto: int = 2, card: dict[str, Any] | None = None) -> str:
    return json.dumps(
        {
            "type": "hello",
            "proto": proto,
            "fw": "1.0.0",
            "board": "esp32dev",
            "serial": "S",
            "display": "128x32",
            "reader": "ok",
            "chip": "0x92",
            "card": card,
        }
    )


def tracker() -> tuple[CardTracker, SilentDriver, list[dict[str, Any]]]:
    driver = SilentDriver()
    t = CardTracker(driver)
    events: list[dict[str, Any]] = []
    t.add_listener(events.append)
    return t, driver, events


def test_events_follow_the_reader() -> None:
    t, _, events = tracker()
    t.feed(hello())
    events.clear()
    t.feed('{"type":"card","state":"present","uid":"04A1B2C3","name":"Erv","format":"legacy"}')
    t.feed('{"type":"card","state":"present","uid":"0B0B0B0B","name":null,"format":"blank"}')
    t.feed('{"type":"card","state":"removed","uid":"0B0B0B0B"}')
    assert events == [
        {"type": "card", "state": "present", "uid": "04A1B2C3", "name": "Erv", "format": "legacy"},
        {"type": "card", "state": "removed", "uid": "04A1B2C3"},
        {"type": "card", "state": "present", "uid": "0B0B0B0B", "name": None, "format": "blank"},
        {"type": "card", "state": "removed", "uid": "0B0B0B0B"},
    ]
    assert t.card is None and t.last_card == Card("0B0B0B0B", None, "blank")


def test_hello_and_status_resynchronise() -> None:
    t, _, events = tracker()
    t.feed(hello(card={"uid": "04A1B2C3", "name": "Erv", "format": "retroverse"}))
    assert t.ready and t.card == Card("04A1B2C3", "Erv", "retroverse")
    assert events[0]["type"] == "reader_info" and events[0]["fw"] == "1.0.0"
    # A missed "removed" line: the heartbeat corrects it.
    t.feed('{"type":"status","card":null,"reader":"ok","uptime_s":5,"host":true}')
    assert t.card is None and events[-1]["state"] == "removed"


def test_old_firmware_is_refused() -> None:
    t, _, events = tracker()
    t.feed('{"type":"login","username":"Erv","uid":"04A1B2C3","source":"rfid"}')
    assert not t.ready and t.card is None and events == []
    t.feed(hello(proto=3))
    assert not t.ready and "protocol 3" in (t.protocol_error or "")


def test_link_upkeep_hello_and_ping() -> None:
    t, driver, _ = tracker()
    t.tick(now=100.0)  # connected now; the reader may still be booting
    assert driver.sent == [{"type": "ping", "id": 1}]
    t.tick(now=102.5)  # no hello after 2 s: ask for it
    assert driver.sent[-1]["type"] == "hello"
    t.feed(hello())
    t.tick(now=103.5)
    assert sum(1 for m in driver.sent if m["type"] == "ping") == 2
    driver.connected = False
    t.tick(now=104.0)
    assert not t.ready


async def test_write_against_the_fake_reader() -> None:
    driver = FakeDriver(interval_s=0.05)
    t = CardTracker(driver)
    t.start()
    try:
        await asyncio.sleep(0.05)
        assert t.ready
        driver.place("04A1B2C3", None)
        card = await t.write_name("Erv", timeout_s=2, uid="04A1B2C3")
        assert card == Card("04A1B2C3", "Erv", "retroverse")
        await asyncio.sleep(0.05)
        assert t.card == card  # the reader's card event arrived too

        driver.remove()
        with pytest.raises(CardWriteError) as err:
            await t.write_name("Erv", timeout_s=1)
        assert err.value.code == "timeout"

        driver.place("0B0B0B0B", "Max")
        with pytest.raises(CardWriteError) as err:
            await t.write_name("Erv", timeout_s=1, uid="04A1B2C3")
        assert err.value.code == "wrong_card"

        driver.fail_writes = True
        with pytest.raises(CardWriteError) as err:
            await t.write_name("Erv", timeout_s=1)
        assert err.value.code == "write"
    finally:
        await t.stop()


async def test_one_write_at_a_time_and_show() -> None:
    driver = FakeDriver(interval_s=0.05)
    t = CardTracker(driver)
    t.start()
    try:
        await asyncio.sleep(0.05)
        first = asyncio.create_task(t.write_name("A", timeout_s=2))
        await asyncio.sleep(0.01)
        with pytest.raises(CardWriteError) as err:
            await t.write_name("B", timeout_s=1)
        assert err.value.code == "busy"
        driver.place("04A1B2C3", None)
        assert (await first).name == "A"
        assert await t.show(["A", "Bestwert 1"])
        assert driver.shown == ["A", "Bestwert 1"]
        assert not await t.show(["x"], uid="0B0B0B0B")
    finally:
        await t.stop()
