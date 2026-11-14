"""Command line entry point.

nestris-terminal                 kiosk (full screen)
nestris-terminal --windowed      kiosk UI in a normal window (development)
nestris-terminal --headless      bridge only; open http://127.0.0.1:7991
nestris-terminal set-pin         set the admin PIN of the hidden menu
nestris-terminal configure ...   set host URL / token / reader (used by the installer)
nestris-terminal autostart on|off|status
nestris-terminal config-path     print the config file location
nestris-terminal verify-update DIR FILE   check FILE against DIR/SHA256SUMS.txt(.sig)
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
    auto = sub.add_parser("autostart", help="start the kiosk when this user signs in")
    auto.add_argument("state", choices=["on", "off", "status"])
    verify = sub.add_parser(
        "verify-update",
        help="check a release file against the signed SHA256SUMS.txt next to it "
        "(used by the Debian update helper)",
    )
    verify.add_argument("dir", type=Path, help="folder with SHA256SUMS.txt and SHA256SUMS.txt.sig")
    verify.add_argument("file", help="file name inside that folder")
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
        print("Autostart is only supported on Windows and Linux.", file=sys.stderr)
        return 2
    if args.state != "status":
        autostart.set_enabled(args.state == "on")
    print("on" if autostart.is_enabled() else "off")
    return 0


def _verify_update(args: argparse.Namespace) -> int:
    """Exit 0 only if the signature and the file's checksum are good."""
    from nestris_terminal.updates.releases import parse_sums, verify_signature
    from nestris_terminal.updates.service import file_sha256

    folder: Path = args.dir
    name: str = args.file
    if "/" in name or "\\" in name or name.startswith("."):
        print(f"bad file name {name!r}", file=sys.stderr)
        return 2
    try:
        sums = (folder / "SHA256SUMS.txt").read_bytes()
        signature = (folder / "SHA256SUMS.txt.sig").read_text(encoding="ascii", errors="replace")
    except OSError as exc:
        print(f"cannot read the checksums: {exc}", file=sys.stderr)
        return 1
    if not verify_signature(sums, signature):
        print("SHA256SUMS.txt is not signed by the release key", file=sys.stderr)
        return 1
    expected = parse_sums(sums.decode("utf-8", "replace")).get(name)
    if expected is None:
        print(f"{name} is not in SHA256SUMS.txt", file=sys.stderr)
        return 1
    try:
        digest = file_sha256(folder / name)
    except OSError as exc:
        print(f"cannot read {name}: {exc}", file=sys.stderr)
        return 1
    if digest != expected:
        print(f"{name}: checksum mismatch", file=sys.stderr)
        return 1
    print(f"{name}: OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "config-path":
        print(args.config)
        return 0
    if args.command == "verify-update":
        return _verify_update(args)

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

        runtime = Runtime(settings)
        asyncio.run(runtime.serve())
        if runtime.restart_requested:
            from nestris_terminal.restart import restart_process

            restart_process()
        return 0

    from nestris_terminal.shell.kiosk import run_kiosk

    return run_kiosk(settings, windowed=args.windowed)


if __name__ == "__main__":
    sys.exit(main())
