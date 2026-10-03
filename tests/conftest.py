from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from nestris_terminal.config import Settings


@pytest.fixture(autouse=True)
def _isolated_config(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Never pick up a real config file or env overrides."""
    for key in list(os.environ):
        if key.startswith("NESTRIS_TERMINAL__"):
            monkeypatch.delenv(key)
    Settings.config_file = None
    yield
    Settings.config_file = None
