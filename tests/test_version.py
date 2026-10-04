"""The release workflow checks the tag against pyproject.toml; the app reports __version__."""

from __future__ import annotations

import tomllib
from pathlib import Path

from nestris_terminal import __version__


def test_version_matches_pyproject() -> None:
    pyproject = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text("utf-8"))
    assert pyproject["project"]["version"] == __version__
