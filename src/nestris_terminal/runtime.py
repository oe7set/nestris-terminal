"""The terminal core: reader, host client, monitors and the local HTTP server.

``Runtime.serve()`` runs everything on one asyncio loop; the Qt kiosk shell
runs it on a background thread, ``--headless`` on the main thread.
"""

from __future__ import annotations

import asyncio
import contextlib
import platform
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from typing import Any

import structlog
import uvicorn

from nestris_terminal import __version__
from nestris_terminal.broadcast import Broadcaster
from nestris_terminal.config import Settings
from nestris_terminal.host.client import HostClient, HostError
from nestris_terminal.rfid.card import CardTracker
from nestris_terminal.rfid.driver import FakeDriver, ReaderDriver, SerialDriver

log = structlog.get_logger(__name__)

HOST_PING_INTERVAL_S = 10.0


def make_driver(settings: Settings) -> ReaderDriver:
    if settings.rfid.driver == "fake":
        return FakeDriver()
    return SerialDriver(settings.rfid.port, settings.rfid.baud)


class Runtime:
    def __init__(self, settings: Settings, *, host_transport: Any = None) -> None:
        self.settings = settings
        self.started_at = datetime.now(UTC)
        self.events = Broadcaster()
        self.host = HostClient(settings.host, transport=host_transport)
        self.cards = CardTracker(make_driver(settings))
        self.cards.add_listener(self.events.publish)
        self.loop: asyncio.AbstractEventLoop | None = None
        self._tasks: set[asyncio.Task[Any]] = set()
        self._server: uvicorn.Server | None = None
        self._reader_connected: bool | None = None
        self._host_reachable: bool | None = None
        self.quit_requested = False

    # ------------------------------------------------------------ lifecycle

    def spawn(self, coro: Any, *, name: str) -> None:
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def start(self) -> None:
        self.cards.start()
        self.spawn(self._monitor_reader(), name="reader-monitor")
        self.spawn(self._monitor_host(), name="host-monitor")

    async def stop(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        for task in list(self._tasks):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        await self.cards.stop()
        await self.host.close()

    async def reconfigure(self, settings: Settings) -> None:
        """Apply saved settings: new host client and reader driver."""
        await self.cards.stop()
        await self.host.close()
        self.settings = settings
        self.host = HostClient(settings.host)
        self.cards = CardTracker(make_driver(settings))
        self.cards.add_listener(self.events.publish)
        self.cards.start()
        self._reader_connected = None
        self._host_reachable = None
        self.events.publish({"type": "config", "kiosk": settings.kiosk.model_dump()})
        log.info("configuration applied", host=settings.host.url, rfid=settings.rfid.driver)

    async def serve(self) -> None:
        from nestris_terminal.bridge.app import create_app

        self.loop = asyncio.get_running_loop()
        config = uvicorn.Config(
            create_app(self),
            host=self.settings.http.host,
            port=self.settings.http.port,
            log_config=None,
            access_log=False,
        )
        self._server = uvicorn.Server(config)
        log.info("terminal bridge starting", url=self.local_url)
        await self._server.serve()

    @property
    def local_url(self) -> str:
        return f"http://127.0.0.1:{self.settings.http.port}"

    @property
    def http_started(self) -> bool:
        return self._server is not None and self._server.started

    def request_shutdown(self, *, quit_app: bool = False) -> None:
        """Thread-safe. ``quit_app`` also closes the kiosk window."""
        self.quit_requested = self.quit_requested or quit_app

        def stop() -> None:
            if self._server is not None:
                self._server.should_exit = True

        if self.loop is not None and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(stop)
        else:
            stop()

    # ------------------------------------------------------------ monitors

    async def _monitor_reader(self) -> None:
        last: tuple[bool, str | None] | None = None
        while True:
            # "connected" for the UI = a v2 reader introduced itself.
            state = (self.cards.ready, self.cards.protocol_error)
            if state != last:
                last = state
                self._reader_connected = state[0]
                self.events.publish(
                    {
                        "type": "reader",
                        "connected": state[0],
                        "port": self.cards.driver.port,
                        "error": state[1],
                        "info": self.cards.reader_info(),
                    }
                )
            await asyncio.sleep(0.5)

    async def _monitor_host(self) -> None:
        while True:
            with contextlib.suppress(HostError):
                await self.host.ping()
            reachable = bool(self.host.reachable) and self.host.last_error is None
            if reachable != self._host_reachable:
                self._host_reachable = reachable
                self.events.publish(
                    {"type": "host", "reachable": reachable, "error": self.host.last_error}
                )
            await asyncio.sleep(HOST_PING_INTERVAL_S)

    # ------------------------------------------------------------ status

    def state(self) -> dict[str, Any]:
        return {
            "version": __version__,
            "kiosk": self.settings.kiosk.model_dump(),
            "reader": self.cards.snapshot(),
            "host": {
                "url": self.settings.host.url,
                "reachable": self._host_reachable,
                "error": self.host.last_error,
                "event": (self.host.server or {}).get("event"),
            },
        }

    async def debug(self) -> dict[str, Any]:
        return {
            **self.state(),
            "uptime_s": int((datetime.now(UTC) - self.started_at).total_seconds()),
            "host_detail": {
                "server": self.host.server,
                "last_ok": self.host.last_ok.isoformat() if self.host.last_ok else None,
                "has_token": bool(self.settings.host.token.get_secret_value()),
            },
            "network": await asyncio.to_thread(network_info),
            "system": {
                "python": sys.version.split()[0],
                "platform": platform.platform(),
                "hostname": socket.gethostname(),
            },
            "ws_clients": self.events.count,
        }


def network_info() -> dict[str, Any]:
    """Addresses of this PC and, on Windows, the Wi-Fi connection."""
    info: dict[str, Any] = {"addresses": [], "wifi": None}
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
        info["addresses"] = sorted({str(i[4][0]) for i in infos})
    except OSError:
        pass
    if sys.platform == "win32":
        try:
            started = time.monotonic()
            out = subprocess.run(
                ["netsh", "wlan", "show", "interfaces"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).stdout
            fields: dict[str, str] = {}
            for line in out.splitlines():
                key, sep, value = line.partition(":")
                if sep:
                    fields[key.strip().lower()] = value.strip()
            ssid = fields.get("ssid")
            if ssid:
                info["wifi"] = {
                    "ssid": ssid,
                    "signal": fields.get("signal"),
                    "state": fields.get("state") or fields.get("status"),
                }
            info["wifi_query_ms"] = int((time.monotonic() - started) * 1000)
        except (OSError, subprocess.SubprocessError):
            pass
    return info
