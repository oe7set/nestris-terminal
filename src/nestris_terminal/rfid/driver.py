"""Reader drivers: the transport between the terminal and the RFID reader.

A driver delivers raw text lines from the reader to ``on_line`` (from its
own thread) and sends lines to it. The protocol (v2, ``protocol.py``) is
handled by ``card.py``; a new transport only needs a new driver here.
"""

from __future__ import annotations

import contextlib
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import structlog

from nestris_terminal.rfid import protocol

log = structlog.get_logger(__name__)

LineCallback = Callable[[str], None]

SILENCE_LIMIT_S = 6.0

# USB-UART chips used on ESP32 dev boards (Silicon Labs CP210x, WCH CH340/CH9102, FTDI).
ESP32_USB_VIDS = {0x10C4, 0x1A86, 0x0403}


class ReaderDriver(Protocol):
    def start(self, on_line: LineCallback) -> None: ...
    def send(self, line: str) -> bool: ...
    def stop(self) -> None: ...
    @property
    def connected(self) -> bool: ...
    @property
    def port(self) -> str | None: ...


def list_ports() -> list[dict[str, str | int | None]]:
    """Serial ports for the config menu (most likely reader first)."""
    from serial.tools import list_ports as lp

    ports = []
    for p in lp.comports():
        ports.append(
            {
                "device": p.device,
                "description": p.description,
                "vid": p.vid,
                "likely_reader": p.vid in ESP32_USB_VIDS,
            }
        )
    return sorted(ports, key=lambda p: (not p["likely_reader"], str(p["device"])))


def autodetect_port() -> str | None:
    ports = list_ports()
    for p in ports:
        if p["likely_reader"]:
            return str(p["device"])
    return None


class SerialDriver:
    """USB serial (pyserial) with endless reconnect, as the station does."""

    def __init__(self, port: str, baud: int) -> None:
        self._configured_port = port
        self._baud = baud
        self._serial: object | None = None
        self._port: str | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def port(self) -> str | None:
        return self._port

    def start(self, on_line: LineCallback) -> None:
        self._thread = threading.Thread(
            target=self._run, args=(on_line,), name="rfid-serial", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def send(self, line: str) -> bool:
        with self._lock:
            ser = self._serial
            if ser is None:
                return False
            try:
                ser.write((line + "\n").encode("utf-8"))  # type: ignore[attr-defined]
                ser.flush()  # type: ignore[attr-defined]
            except OSError as exc:
                log.warning("rfid write failed", error=str(exc))
                return False
        return True

    def _run(self, on_line: LineCallback) -> None:
        import serial

        delay = 1.0
        while not self._stop.is_set():
            port = self._configured_port or autodetect_port()
            if not port:
                self._stop.wait(delay)
                delay = min(delay * 2, 10.0)
                continue
            try:
                ser = serial.Serial(port, self._baud, timeout=0.5)
            except (OSError, serial.SerialException) as exc:
                log.info("rfid reader not available", port=port, error=str(exc))
                self._stop.wait(delay)
                delay = min(delay * 2, 10.0)
                continue
            with self._lock:
                self._serial = ser
            self._port = port
            self._connected = True
            delay = 1.0
            log.info("rfid reader connected", port=port)
            last_data = time.monotonic()
            try:
                while not self._stop.is_set():
                    raw = ser.readline()
                    if raw:
                        last_data = time.monotonic()
                        on_line(raw.decode("utf-8", "replace")[:1024])
                    elif time.monotonic() - last_data > SILENCE_LIMIT_S:
                        # v2 sends a status line every 2 s: three missed = hung or unplugged.
                        raise OSError(f"reader silent for {SILENCE_LIMIT_S:.0f} s")
            except (OSError, serial.SerialException) as exc:
                log.warning("rfid reader lost", port=port, error=str(exc))
            finally:
                self._connected = False
                with self._lock:
                    self._serial = None
                with contextlib.suppress(OSError):
                    ser.close()


@dataclass
class FakeDriver:
    """Simulated v2 reader for development and tests (debug menu: place/remove).

    Behaves like the firmware: ``hello`` on start, ``card`` events on changes,
    a ``status`` heartbeat, a ``result`` for every command, writes that wait
    for a (matching) card.
    """

    interval_s: float = 2.0
    card: protocol.CardData | None = None
    fail_writes: bool = False
    fw: str = "0.0.0-fake"
    proto: int = protocol.PROTOCOL
    sent: list[str] = field(default_factory=list)
    shown: list[str] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=lambda: {"display": "128x32", "lang": "de"})
    _pending: dict[str, Any] | None = None
    _stop: threading.Event = field(default_factory=threading.Event)
    _lock: threading.RLock = field(default_factory=threading.RLock)
    _thread: threading.Thread | None = None
    _on_line: LineCallback | None = None

    @property
    def connected(self) -> bool:
        return self._thread is not None

    @property
    def port(self) -> str | None:
        return "fake"

    def start(self, on_line: LineCallback) -> None:
        self._on_line = on_line
        self._thread = threading.Thread(target=self._run, name="rfid-fake", daemon=True)
        self._thread.start()
        self._hello(None)

    def stop(self) -> None:
        self._stop.set()

    # ---------------------------------------------------------------- reader side

    def _out(self, data: dict[str, Any]) -> None:
        if self._on_line is not None:
            self._on_line(json.dumps(data))

    def _hello(self, cid: int | None) -> None:
        data: dict[str, Any] = {
            "type": "hello", "proto": self.proto, "fw": self.fw, "build": "", "board": "fake",
            "serial": "FAKE00000001", "display": self.settings["display"],
            "lang": self.settings["lang"], "reader": "ok", "chip": "0x92",
            "card": self.card.as_dict() if self.card else None,
        }  # fmt: skip
        if cid is not None:
            data["id"] = cid
        self._out(data)

    def _result(self, cid: Any, ok: bool = True, **extra: Any) -> None:
        self._out({"type": "result", "id": cid, "ok": ok, **extra})

    def send(self, line: str) -> bool:
        self.sent.append(line)
        cmd = json.loads(line)
        cid = cmd.get("id")
        kind = cmd.get("type")
        with self._lock:
            if kind == "hello":
                self._hello(cid)
            elif kind in ("ping", "reboot"):
                self._result(cid)
            elif kind == "write":
                if self._pending is not None:
                    self._result(cid, False, error="busy")
                else:
                    deadline = time.monotonic() + int(cmd.get("timeout_ms", 15000)) / 1000
                    self._pending = {**cmd, "deadline": deadline, "wrong": False}
                    self._try_write()
            elif kind == "show":
                if self.card is None:
                    self._result(cid, False, error="no_card")
                elif cmd.get("uid") and cmd["uid"].upper() != self.card.uid:
                    self._result(cid, False, error="wrong_card")
                else:
                    self.shown = list(cmd.get("lines", []))
                    self._result(cid)
            elif kind == "cancel":
                if self._pending is not None:
                    self._result(self._pending.get("id"), False, error="cancelled")
                    self._pending = None
                self._result(cid)
            elif kind == "config":
                self.settings.update({k: v for k, v in cmd.items() if k not in ("type", "id")})
                self._result(cid)
                self._hello(None)
            else:
                self._result(cid, False, error="unknown_type", detail=str(kind))
        return True

    def _try_write(self) -> None:
        w = self._pending
        if w is None:
            return
        if time.monotonic() >= w["deadline"]:
            self._result(w.get("id"), False, error="wrong_card" if w["wrong"] else "timeout")
            self._pending = None
            return
        card = self.card
        if card is None:
            return
        if w.get("uid") and w["uid"].upper() != card.uid:
            w["wrong"] = True
            return
        self._pending = None
        if self.fail_writes:
            self._result(
                w.get("id"), False, error="write", detail="the card did not accept the write"
            )
            return
        self.card = protocol.CardData(card.uid, str(w["name"]), "retroverse")
        self._result(w.get("id"), True, uid=card.uid, name=w["name"])
        self._out({"type": "card", "state": "present", **self.card.as_dict()})

    # ---------------------------------------------------------------- bench controls

    def place(self, uid: str, name: str | None, fmt: str | None = None) -> None:
        with self._lock:
            uid = uid.upper()
            if self.card is not None and self.card.uid != uid:
                self._out({"type": "card", "state": "removed", "uid": self.card.uid})
            self.card = protocol.CardData(uid, name or None, fmt or ("legacy" if name else "blank"))
            self.shown = []
            self._out({"type": "card", "state": "present", **self.card.as_dict()})
            self._try_write()

    def remove(self) -> None:
        with self._lock:
            if self.card is not None:
                self._out({"type": "card", "state": "removed", "uid": self.card.uid})
            self.card = None
            self.shown = []

    def tick(self) -> None:
        """Heartbeat and write timeouts, like the firmware's loop."""
        with self._lock:
            self._try_write()
            self._out({
                "type": "status", "card": self.card.as_dict() if self.card else None,
                "reader": "ok", "uptime_s": 0, "host": True,
            })  # fmt: skip

    def _run(self) -> None:
        while not self._stop.wait(self.interval_s):
            self.tick()
