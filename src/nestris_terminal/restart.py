"""Start the terminal again in place of this process (after an app update).

On Debian the update helper replaces the files under ``/opt/nestris-terminal``
while the kiosk keeps running on the old ones; once the core and the window
are shut down, :func:`restart_process` ``exec``s the new binary with the same
arguments. Nothing supervises the kiosk in a desktop session, so it has to
start itself again.
"""

from __future__ import annotations

import logging
import os
import sys

import structlog

log = structlog.get_logger(__name__)


def restart_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, *sys.argv[1:]]
    return [sys.executable, "-m", "nestris_terminal", *sys.argv[1:]]


def restart_process() -> None:
    """Replace this process; only returns if ``exec`` failed."""
    command = restart_command()
    log.info("restarting", command=command)
    logging.shutdown()
    try:
        os.execv(command[0], command)
    except OSError as exc:  # pragma: no cover - exec failure
        print(f"restart failed: {exc}", file=sys.stderr)
