"""Command line entry point.

nestris-terminal                 kiosk (full screen)
nestris-terminal --windowed      kiosk UI in a normal window (development)
nestris-terminal --headless      bridge only; open http://127.0.0.1:7991
nestris-terminal set-pin         set the admin PIN of the hidden menu
nestris-terminal config-path     print the config file location
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from pathlib import Path

import structlog

from nestris_terminal import __version__
from nestris_terminal.config import default_config_path, hash_pin, load_settings, save_settings
from nestris_terminal.logging_setup import configure_logging

log = structlog.get_logger("nestris_terminal")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nestris-terminal", description="Retroverse player terminal"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--config", type=Path, default=default_config_path(),
                        help="config file (default: %(default)s)")  # fmt: skip
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--headless", action="store_true", help="run only the local bridge")
    mode.add_argument("--windowed", action="store_true", help="kiosk UI in a normal window")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("set-pin", help="set the admin PIN of the hidden config menu")
    sub.add_parser("config-path", help="print the config file location")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "config-path":
        print(args.config)
        return 0

    settings = load_settings(args.config)
    configure_logging(settings)

    if args.command == "set-pin":
        pin = getpass.getpass("New PIN (4-12 digits): ")
        if not pin.isdigit() or not 4 <= len(pin) <= 12:
            print("The PIN must have 4 to 12 digits.", file=sys.stderr)
            return 2
        settings.admin.pin_hash = hash_pin(pin)
        print(f"Saved to {save_settings(settings, args.config)}")
        return 0

    log.info("starting", version=__version__, config=str(args.config))
    if args.headless:
        from nestris_terminal.runtime import Runtime

        asyncio.run(Runtime(settings).serve())
        return 0

    from nestris_terminal.shell.kiosk import run_kiosk

    return run_kiosk(settings, windowed=args.windowed)


if __name__ == "__main__":
    sys.exit(main())
