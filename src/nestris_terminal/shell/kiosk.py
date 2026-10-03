"""Kiosk window: the terminal UI full screen on the touch PC.

- frameless full screen (``--windowed`` for development), no context menu,
  no pinch zoom, no overscroll navigation, optional hidden cursor;
- keeps the display awake (Windows ``SetThreadExecutionState``);
- reloads the page if it failed to load (e.g. while the bridge starts);
- quits when the core stops (the config menu's *App beenden*).
"""

from __future__ import annotations

import os
import sys

import structlog
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QCloseEvent, QColor
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QStackedWidget

from nestris_terminal import __version__
from nestris_terminal.config import Settings
from nestris_terminal.runtime import Runtime
from nestris_terminal.shell.core_thread import CoreThread
from nestris_terminal.shell.single_instance import InstanceServer, send_to_running, server_name

log = structlog.get_logger(__name__)

# Chromium flags for a touch kiosk (set before QApplication exists).
CHROMIUM_FLAGS = "--disable-pinch --overscroll-history-navigation=0 --touch-events=enabled"


def keep_display_awake() -> None:
    if sys.platform == "win32":
        import ctypes

        es_continuous, es_system_required, es_display_required = 0x80000000, 0x1, 0x2
        ctypes.windll.kernel32.SetThreadExecutionState(
            es_continuous | es_system_required | es_display_required
        )


class KioskWindow(QMainWindow):
    def __init__(self, url: str, *, allow_close: bool) -> None:
        super().__init__()
        self.setWindowTitle("Retroverse Terminal")
        self._allow_close = allow_close
        self._url = QUrl(url)
        self._view = QWebEngineView(self)
        self._view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self._view.page().setBackgroundColor(QColor("#0b1020"))
        settings = self._view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.ShowScrollBars, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.FocusOnNavigationEnabled, True)
        self._view.loadFinished.connect(self._loaded)
        self._placeholder = QLabel("Retroverse Terminal startet …")
        self._placeholder.setStyleSheet(
            "background:#0b1020;color:#cbd5e1;font-size:28px;qproperty-alignment:AlignCenter;"
        )
        self._stack = QStackedWidget(self)
        self._stack.addWidget(self._placeholder)
        self._stack.addWidget(self._view)
        self.setCentralWidget(self._stack)
        self._retry = QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.timeout.connect(self.load)

    def load(self) -> None:
        self._view.setUrl(self._url)

    def _loaded(self, ok: bool) -> None:
        if ok:
            self._stack.setCurrentWidget(self._view)
        else:
            self._retry.start(2000)

    def show_message(self, text: str) -> None:
        self._placeholder.setText(text)
        self._stack.setCurrentWidget(self._placeholder)

    def closeEvent(self, event: QCloseEvent) -> None:
        # Alt+F4 on a kiosk must not end the session; quitting goes through
        # the config menu (or --windowed during development).
        if self._allow_close:
            event.accept()
        else:
            event.ignore()


def run_kiosk(settings: Settings, *, windowed: bool = False) -> int:
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", CHROMIUM_FLAGS)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Retroverse Terminal")
    app.setApplicationVersion(__version__)

    instance = server_name(settings.http.port)
    if send_to_running("show", instance):
        log.info("terminal already running")
        return 0
    server = InstanceServer(instance)
    server.listen()

    runtime = Runtime(settings)
    core = CoreThread(runtime)
    window = KioskWindow(runtime.local_url, allow_close=windowed)

    def on_command(command: str) -> None:
        if command == "quit":
            app.quit()
        else:  # a second start: bring the kiosk to the front
            window.raise_()
            window.activateWindow()

    server.command_received.connect(on_command)
    if settings.kiosk.hide_cursor and not windowed:
        app.setOverrideCursor(Qt.CursorShape.BlankCursor)

    def check_core() -> None:
        if core.finished.is_set():
            if runtime.quit_requested or windowed:
                app.quit()
            else:
                window.show_message(f"Terminal-Kern beendet:\n{core.error or 'unbekannter Fehler'}")
        elif runtime.http_started and not window.property("loaded"):
            window.setProperty("loaded", True)
            window.load()

    timer = QTimer(app)
    timer.timeout.connect(check_core)
    timer.start(300)
    keep_display_awake()
    awake = QTimer(app)
    awake.timeout.connect(keep_display_awake)
    awake.start(60_000)

    core.start()
    if windowed:
        window.resize(1280, 800)
        window.show()
    else:
        window.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        window.showFullScreen()
    code = app.exec()
    core.stop(timeout_s=10.0)
    server.close()
    return code


__all__ = ["QWebEnginePage", "run_kiosk"]
