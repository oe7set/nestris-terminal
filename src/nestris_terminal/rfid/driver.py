"""Reader drivers: the transport between the terminal and the RFID reader.

A driver delivers raw text lines from the reader to ``on_line`` (from its
own thread) and sends lines to it. A new reader firmware or transport only
needs a new driver here; the card logic in ``card.py`` stays the same.
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

import structlog

from nestris_terminal.rfid import protocol

log = structlog.get_logger(__name__)

LineCallback = Callable[[str], None]

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
                    elif time.monotonic() - last_data > 10:
                        raise OSError("reader silent for 10 s")
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
    """Simulated reader for development and tests (debug menu: place/remove card).

    Behaves like the firmware: reports the card every ``interval_s`` and writes
    a pending ``setname`` on the next report.
    """

    interval_s: float = 0.75
    card: protocol.Reading | None = None
    fail_writes: bool = False
    sent: list[str] = field(default_factory=list)
    _pending_name: str | None = None
    _stop: threading.Event = field(default_factory=threading.Event)
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

    def stop(self) -> None:
        self._stop.set()

    def send(self, line: str) -> bool:
        self.sent.append(line)
        import json

        data = json.loads(line)
        if data.get("type") == "setname":
            self._pending_name = str(data["value"])
        return True

    def place(self, uid: str, name: str | None) -> None:
        self.card = protocol.Reading(uid.upper(), name)
        self.tick()

    def remove(self) -> None:
        self.card = None

    def tick(self) -> None:
        """One report, like the firmware's read cycle."""
        if self._on_line is None:
            return
        import json

        card = self.card
        if card is not None and self._pending_name is not None:
            name, self._pending_name = self._pending_name, None
            if self.fail_writes:
                self._on_line("Write failed: STATUS_TIMEOUT")
            else:
                self.card = card = protocol.Reading(card.uid, name)
                self._on_line("Name erfolgreich auf Karte geschrieben.")
        if card is None:
            self._on_line(json.dumps({"type": "login", "username": "Unbekannt", "source": "rfid"}))
        else:
            self._on_line(
                json.dumps(
                    {
                        "type": "login",
                        "username": card.name or "Unbekannt",
                        "uid": card.uid,
                        "scoreloaded": "0",
                        "source": "rfid",
                    }
                )
            )

    def _run(self) -> None:
        while not self._stop.wait(self.interval_s):
            self.tick()
