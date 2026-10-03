"""Card presence and card writing on top of a reader driver.

The reader reports the card on it every 750 ms. ``CardTracker`` turns those
reports into events for the UI:

- ``{"type": "card", "state": "present", "uid", "name"}`` when a card arrives
  (or another card replaces it, or its name changed after a write),
- ``{"type": "card", "state": "removed"}`` when no report carried the card's
  uid for ``removed_after_s``.

``write_name`` sends ``setname`` and waits until the card on the reader
reports the new name (read-back verification); a ``Write failed`` line or a
timeout is an error.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import structlog

from nestris_terminal.rfid import protocol
from nestris_terminal.rfid.driver import ReaderDriver

log = structlog.get_logger(__name__)

Listener = Callable[[dict[str, Any]], None]


class CardWriteError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Card:
    uid: str
    name: str | None

    def as_dict(self) -> dict[str, Any]:
        return {"uid": self.uid, "name": self.name}


class CardTracker:
    def __init__(self, driver: ReaderDriver, *, removed_after_s: float = 2.0) -> None:
        self.driver = driver
        self.removed_after_s = removed_after_s
        self.card: Card | None = None
        self.last_card: Card | None = None
        self._last_seen = 0.0
        self._listeners: list[Listener] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._write: tuple[str, asyncio.Future[Card]] | None = None
        self._task: asyncio.Task[None] | None = None
        self.lines_seen = 0

    # ------------------------------------------------------------ lifecycle

    def add_listener(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self.driver.start(self._from_thread)
        self._task = asyncio.create_task(self._watch(), name="card-watch")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
        self.driver.stop()

    def _from_thread(self, line: str) -> None:
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self.feed, line)

    # ------------------------------------------------------------ input

    def feed(self, line: str, now: float | None = None) -> None:
        """Process one line from the reader (event loop thread)."""
        self.lines_seen += 1
        message = protocol.parse_line(line)
        now = time.monotonic() if now is None else now
        if isinstance(message, protocol.WriteFailure):
            self._finish_write(error=message.detail)
        elif isinstance(message, protocol.Reading):
            if message.uid is None:
                return  # "no card" reports are ignored; removal is time based
            card = Card(message.uid, message.name)
            self._last_seen = now
            if card != self.card:
                self.card = card
                self.last_card = card
                self._emit({"type": "card", "state": "present", **card.as_dict()})
            write = self._write
            if write is not None and card.name == write[0]:
                self._finish_write(card=card)

    def check_removed(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        if self.card is not None and now - self._last_seen > self.removed_after_s:
            self.card = None
            self._emit({"type": "card", "state": "removed"})

    async def _watch(self) -> None:
        while True:
            await asyncio.sleep(0.25)
            self.check_removed()

    def _emit(self, event: dict[str, Any]) -> None:
        for listener in self._listeners:
            try:
                listener(event)
            except Exception:
                log.exception("card listener failed")

    # ------------------------------------------------------------ writing

    async def write_name(self, name: str, timeout_s: float) -> Card:
        """Write ``name`` to the card on (or next placed on) the reader."""
        name = name[: protocol.MAX_NAME]
        if self._write is not None:
            raise CardWriteError("another write is in progress")
        if not self.driver.connected:
            raise CardWriteError("reader not connected")
        future: asyncio.Future[Card] = asyncio.get_running_loop().create_future()
        self._write = (name, future)
        try:
            if not self.driver.send(protocol.setname(name)):
                raise CardWriteError("could not send to the reader")
            return await asyncio.wait_for(future, timeout_s)
        except TimeoutError as exc:
            raise CardWriteError("timeout: the card did not report the new name") from exc
        finally:
            self._write = None

    def _finish_write(self, *, card: Card | None = None, error: str | None = None) -> None:
        if self._write is None:
            return
        future = self._write[1]
        if future.done():
            return
        if error is not None:
            future.set_exception(CardWriteError(error))
        elif card is not None:
            future.set_result(card)

    def snapshot(self) -> dict[str, Any]:
        return {
            "connected": self.driver.connected,
            "port": self.driver.port,
            "card": self.card.as_dict() if self.card else None,
            "last_card": self.last_card.as_dict() if self.last_card else None,
            "lines_seen": self.lines_seen,
            "writing": self._write is not None,
        }
