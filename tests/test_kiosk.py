"""The kiosk window refuses Alt+F4 but must let a deliberate quit through."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWebEngineWidgets")

from PySide6.QtWidgets import QApplication

from nestris_terminal.shell.kiosk import KioskWindow


def test_close_is_refused_until_allowed() -> None:
    app = QApplication.instance() or QApplication([])
    window = KioskWindow("http://127.0.0.1:1/", allow_close=False)
    window.show()
    assert window.close() is False  # Alt+F4 / app.quit() without permission
    window.allow_close()
    assert window.close() is True
    app.processEvents()
