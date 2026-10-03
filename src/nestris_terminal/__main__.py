"""Command line entry point.

nestris-terminal                 kiosk (full screen)
nestris-terminal --windowed      kiosk UI in a normal window (development)
nestris-terminal --headless      bridge only; open http://127.0.0.1:7991
nestris-terminal set-pin         set the admin PIN of the hidden menu
nestris-terminal configure ...   set host URL / token / reader (used by the installer)
nestris-terminal autostart on|off|status
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
    conf = sub.add_parser("configure", help="set connection settings without the touch menu")
    conf.add_argument("--host", help="NestrisLTM base URL, e.g. http://192.168.1.10:7990")
    conf.add_argument("--token", help="API token with the 'terminal' scope")
    conf.add_argument("--reader-port", help="serial port of the reader, '' = automatic")
    conf.add_argument("--driver", choices=["serial", "fake"], help="card reader driver")
    conf.add_argument("--lang", choices=["de", "en"], help="UI language")
    auto = sub.add_parser("autostart", help="start the kiosk when this Windows user signs in")
    auto.add_argument("state", choices=["on", "off", "status"])
    return parser


def _configure(args: argparse.Namespace) -> int:
    from nestris_terminal.config import Settings

    settings = load_settings(args.config)
    data = settings.model_dump(mode="python")
    data["host"]["token"] = settings.host.token.get_secret_value()
    if args.host:
        data["host"]["url"] = args.host.strip().rstrip("/")
    if args.token:
        data["host"]["token"] = args.token.strip()
    if args.reader_port is not None:
        data["rfid"]["port"] = args.reader_port.strip()
    if args.driver:
        data["rfid"]["driver"] = args.driver
    if args.lang:
        data["kiosk"]["lang"] = args.lang
    print(f"Saved to {save_settings(Settings.model_validate(data), args.config)}")
    return 0


def _autostart(args: argparse.Namespace) -> int:
    from nestris_terminal.shell import autostart

    if not autostart.is_supported():
        print("Autostart is only supported on Windows.", file=sys.stderr)
        return 2
    if args.state != "status":
        autostart.set_enabled(args.state == "on")
    print("on" if autostart.is_enabled() else "off")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "config-path":
        print(args.config)
        return 0

    if args.command == "configure":
        return _configure(args)
    if args.command == "autostart":
        return _autostart(args)

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
