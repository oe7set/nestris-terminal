"""Runs the terminal core (``Runtime.serve``) on a background thread."""

from __future__ import annotations

import asyncio
import threading

import structlog

from nestris_terminal.runtime import Runtime

log = structlog.get_logger(__name__)


class CoreThread(threading.Thread):
    def __init__(self, runtime: Runtime) -> None:
        super().__init__(name="terminal-core", daemon=True)
        self.runtime = runtime
        self.error: str | None = None
        self.finished = threading.Event()

    def run(self) -> None:
        try:
            asyncio.run(self.runtime.serve())
        except BaseException as exc:  # incl. SystemExit from uvicorn on bind errors
            self.error = f"{type(exc).__name__}: {exc}"
            log.error("terminal core stopped with an error", error=self.error)
        else:
            if not self.runtime.http_started and self.error is None:
                self.error = f"port {self.runtime.settings.http.port} already in use?"
        finally:
            self.finished.set()

    def stop(self, timeout_s: float = 10.0) -> bool:
        self.runtime.request_shutdown()
        return self.finished.wait(timeout_s)
