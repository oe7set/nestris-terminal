from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from nestris_terminal.rfid.card import CardTracker, CardWriteError
from nestris_terminal.rfid.driver import FakeDriver


def login(uid: str | None, name: str = "Unbekannt") -> str:
    data: dict[str, Any] = {"type": "login", "username": name, "source": "rfid"}
    if uid:
        data["uid"] = uid
    return json.dumps(data)


def tracker() -> tuple[CardTracker, list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    t = CardTracker(FakeDriver(), removed_after_s=2.0)
    t.add_listener(events.append)
    return t, events


def test_presence_and_removal() -> None:
    t, events = tracker()
    t.feed(login("AA11", "Erv"), now=0.0)
    t.feed(login("AA11", "Erv"), now=0.75)  # repeated report: no new event
    t.feed(login(None), now=1.0)  # "no card" lines are ignored
    t.check_removed(now=2.0)
    assert t.card is not None
    t.check_removed(now=3.0)
    assert t.card is None
    assert events == [
        {"type": "card", "state": "present", "uid": "AA11", "name": "Erv"},
        {"type": "card", "state": "removed"},
    ]
    assert t.last_card is not None and t.last_card.uid == "AA11"


def test_card_swap_and_name_change() -> None:
    t, events = tracker()
    t.feed(login("AA11"), now=0.0)
    t.feed(login("BB22", "Max"), now=0.5)
    t.feed(login("BB22", "Maxi"), now=1.0)
    assert [(e.get("uid"), e.get("name")) for e in events] == [
        ("AA11", None),
        ("BB22", "Max"),
        ("BB22", "Maxi"),
    ]


async def test_write_with_readback() -> None:
    driver = FakeDriver(interval_s=0.05)
    t = CardTracker(driver)
    t.start()
    try:
        driver.place("cafe01", None)
        card = await t.write_name("Erv", timeout_s=2)
        assert card.uid == "CAFE01" and card.name == "Erv"
        assert json.loads(driver.sent[-1]) == {"type": "setname", "value": "Erv"}
    finally:
        await t.stop()


async def test_write_failure_and_timeout() -> None:
    driver = FakeDriver(interval_s=0.05, fail_writes=True)
    t = CardTracker(driver)
    t.start()
    try:
        driver.place("cafe01", None)
        with pytest.raises(CardWriteError, match="Write failed"):
            await t.write_name("Erv", timeout_s=2)
        driver.fail_writes = False
        driver.remove()  # no card: the write waits ...
        with pytest.raises(CardWriteError, match="timeout"):
            await t.write_name("Erv", timeout_s=0.3)
    finally:
        await t.stop()


async def test_one_write_at_a_time() -> None:
    driver = FakeDriver(interval_s=0.05)
    t = CardTracker(driver)
    t.start()
    try:
        first = asyncio.create_task(t.write_name("A", timeout_s=1))
        await asyncio.sleep(0.01)
        with pytest.raises(CardWriteError, match="in progress"):
            await t.write_name("B", timeout_s=1)
        driver.place("cafe01", None)
        assert (await first).name == "A"
    finally:
        await t.stop()
