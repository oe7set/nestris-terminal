"""Card presence, reader identity and card writing on top of a reader driver.

The reader (protocol v2) reports changes itself; ``CardTracker`` keeps the
current state and turns it into events for the UI:

- ``{"type": "card", "state": "present", "uid", "name", "format"}``
- ``{"type": "card", "state": "removed", "uid"}``
- ``{"type": "reader_info", ...}`` when the reader introduced itself.

It also keeps the link alive (``ping`` every 3 s, ``hello`` after a
reconnect), refuses readers with another protocol version, and correlates
commands (``write``, ``show``, ``config``) with their ``result`` by id.
"""

from __future__ import annotations

import asyncio
import itertools
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import structlog

from nestris_terminal.rfid import protocol
from nestris_terminal.rfid.driver import ReaderDriver

log = structlog.get_logger(__name__)

Listener = Callable[[dict[str, Any]], None]

PING_INTERVAL_S = 3.0
HELLO_WAIT_S = 2.0
WRITE_GRACE_S = 3.0
COMMAND_TIMEOUT_S = 3.0


class CardWriteError(RuntimeError):
    """A write failed; ``code`` is the reader's error (``timeout``, ``verify`` ...)."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


class ReaderCommandError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Card:
    uid: str
    name: str | None
    format: str = "unreadable"

    @classmethod
    def from_data(cls, data: protocol.CardData) -> Card:
        return cls(data.uid, data.name, data.format)

    def as_dict(self) -> dict[str, Any]:
        return {"uid": self.uid, "name": self.name, "format": self.format}


class CardTracker:
    def __init__(self, driver: ReaderDriver) -> None:
        self.driver = driver
        self.card: Card | None = None
        self.last_card: Card | None = None
        self.hello: protocol.Hello | None = None
        self.protocol_error: str | None = None
        self.reader_ok: bool | None = None
        self.lines_seen = 0
        self._listeners: list[Listener] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[None] | None = None
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future[protocol.Result]] = {}
        self._writing = False
        self._was_connected = False
        self._connected_at = 0.0
        self._hello_sent = False
        self._last_ping = 0.0

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
        self._fail_pending("reader stopped")

    def _from_thread(self, line: str) -> None:
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self.feed, line)

    @property
    def ready(self) -> bool:
        """Connected to a reader that speaks protocol v2."""
        return self.driver.connected and self.hello is not None and self.protocol_error is None

    # ------------------------------------------------------------ input

    def feed(self, line: str) -> None:
        """Process one line from the reader (event loop thread)."""
        self.lines_seen += 1
        msg = protocol.parse_line(line)
        if msg is None:
            return
        if isinstance(msg, protocol.Hello):
            self._on_hello(msg)
        elif self.hello is None and not isinstance(msg, protocol.Log):
            # A reader that never said hello: the v1 firmware (or garbage).
            return
        elif isinstance(msg, protocol.CardPresent):
            self._set_card(Card.from_data(msg.card))
        elif isinstance(msg, protocol.CardRemoved):
            if self.card is not None:
                self._set_card(None)
        elif isinstance(msg, protocol.Status):
            self.reader_ok = msg.reader_ok
            # The heartbeat is the truth after missed lines.
            current = Card.from_data(msg.card) if msg.card else None
            if current != self.card:
                self._set_card(current)
        elif isinstance(msg, protocol.Result):
            future = self._pending.pop(msg.id, None) if msg.id is not None else None
            if future is not None and not future.done():
                future.set_result(msg)
        elif isinstance(msg, protocol.Log):
            emit = {"debug": log.debug, "info": log.info, "error": log.error}.get(
                msg.level, log.warning
            )
            emit("reader", msg=msg.msg)

    def _on_hello(self, msg: protocol.Hello) -> None:
        if msg.proto != protocol.PROTOCOL:
            self.hello = None
            self.protocol_error = (
                f"reader speaks protocol {msg.proto or '1 (old firmware)'}, "
                f"the terminal needs {protocol.PROTOCOL}: update the reader firmware"
            )
            log.error("reader protocol mismatch", proto=msg.proto, fw=msg.fw)
            return
        self.hello = msg
        self.protocol_error = None
        self.reader_ok = msg.reader_ok
        log.info("reader", fw=msg.fw, serial=msg.serial, display=msg.display, chip=msg.chip)
        self._emit({"type": "reader_info", **self.reader_info()})
        current = Card.from_data(msg.card) if msg.card else None
        if current != self.card:
            self._set_card(current)

    def _set_card(self, card: Card | None) -> None:
        previous = self.card
        self.card = card
        if previous is not None and (card is None or card.uid != previous.uid):
            self._emit({"type": "card", "state": "removed", "uid": previous.uid})
        if card is not None:
            self.last_card = card
            self._emit({"type": "card", "state": "present", **card.as_dict()})

    def _emit(self, event: dict[str, Any]) -> None:
        for listener in self._listeners:
            try:
                listener(event)
            except Exception:
                log.exception("card listener failed")

    # ------------------------------------------------------------ link upkeep

    def tick(self, now: float | None = None) -> None:
        """Connection bookkeeping; called every 250 ms by the watch task."""
        now = time.monotonic() if now is None else now
        connected = self.driver.connected
        if connected and not self._was_connected:
            # Do not reset `hello` here: the reader's boot hello may already
            # have arrived before this tick noticed the connection.
            self._connected_at = now
            self._hello_sent = False
        elif not connected and self._was_connected:
            self.hello = None
            self.protocol_error = None
            self.reader_ok = None
            if self.card is not None:
                self._set_card(None)
            self._fail_pending("reader disconnected")
        self._was_connected = connected
        if not connected:
            return
        # Opening the port usually resets the ESP32 (it then says hello by
        # itself); if not, ask.
        if self.hello is None and not self._hello_sent and now - self._connected_at >= HELLO_WAIT_S:
            self._hello_sent = True
            self.driver.send(protocol.hello(next(self._ids)))
        if now - self._last_ping >= PING_INTERVAL_S:
            self._last_ping = now
            self.driver.send(protocol.ping(next(self._ids)))

    async def _watch(self) -> None:
        while True:
            await asyncio.sleep(0.25)
            self.tick()

    def _fail_pending(self, reason: str) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_result(
                    protocol.Result(id=None, ok=False, error="disconnected", detail=reason)
                )
        self._pending.clear()

    # ------------------------------------------------------------ commands

    async def _command(self, build: Callable[[int], str], timeout_s: float) -> protocol.Result:
        if not self.ready:
            raise ReaderCommandError(self.protocol_error or "reader not connected")
        cid = next(self._ids)
        future: asyncio.Future[protocol.Result] = asyncio.get_running_loop().create_future()
        self._pending[cid] = future
        if not self.driver.send(build(cid)):
            self._pending.pop(cid, None)
            raise ReaderCommandError("could not send to the reader")
        try:
            return await asyncio.wait_for(future, timeout_s)
        except TimeoutError as exc:
            raise ReaderCommandError("the reader did not answer") from exc
        finally:
            self._pending.pop(cid, None)

    async def write_name(self, name: str, timeout_s: float, *, uid: str | None = None) -> Card:
        """Write ``name`` onto the card on (or next placed on) the reader.

        With ``uid`` only that card is written. The reader verifies the write
        by reading it back.
        """
        if self._writing:
            raise CardWriteError("busy", "another write is in progress")
        timeout_ms = int(min(max(timeout_s, 1.0), 60.0) * 1000)
        self._writing = True
        try:
            result = await self._command(
                lambda cid: protocol.write(
                    cid, name[: protocol.MAX_NAME], uid=uid, timeout_ms=timeout_ms
                ),
                timeout_ms / 1000 + WRITE_GRACE_S,
            )
        except ReaderCommandError as exc:
            raise CardWriteError("reader", str(exc)) from exc
        finally:
            self._writing = False
        if not result.ok:
            raise CardWriteError(result.error or "failed", result.detail or "")
        card = Card(result.uid or (uid or ""), result.name or name, "retroverse")
        return self.card if self.card is not None and self.card.uid == card.uid else card

    async def show(self, lines: list[str], *, uid: str | None = None, ttl_ms: int = 0) -> bool:
        """Text on the reader's display while the card lies on it."""
        try:
            result = await self._command(
                lambda cid: protocol.show(cid, lines, uid=uid, ttl_ms=ttl_ms), COMMAND_TIMEOUT_S
            )
        except ReaderCommandError:
            return False
        return result.ok

    async def configure(self, **settings: Any) -> None:
        result = await self._command(
            lambda cid: protocol.config(cid, **settings), COMMAND_TIMEOUT_S
        )
        if not result.ok:
            raise ReaderCommandError(f"{result.error}: {result.detail or ''}".rstrip(": "))

    # ------------------------------------------------------------ state

    def reader_info(self) -> dict[str, Any]:
        h = self.hello
        return {
            "fw": h.fw if h else None,
            "serial": h.serial if h else None,
            "board": h.board if h else None,
            "display": h.display if h else None,
            "chip": h.chip if h else None,
            "lang": h.raw.get("lang") if h else None,
            "reader_ok": self.reader_ok,
            "protocol_error": self.protocol_error,
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "connected": self.driver.connected,
            "ready": self.ready,
            "port": self.driver.port,
            "card": self.card.as_dict() if self.card else None,
            "last_card": self.last_card.as_dict() if self.last_card else None,
            "lines_seen": self.lines_seen,
            "writing": self._writing,
            "info": self.reader_info(),
        }
