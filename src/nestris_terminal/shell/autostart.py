"""Start the kiosk when the kiosk user signs in.

- Windows: the per-user ``Run`` registry key.
- Linux: an XDG autostart entry
  (``~/.config/autostart/retroverse-terminal.desktop``), which XFCE, GNOME,
  KDE and LXQt all honour.

In a PyInstaller build the kiosk executable (``RetroverseTerminal(.exe)``,
also when called from the console CLI ``nestris-terminal(.exe)`` next to it)
is registered; in development ``pythonw -m nestris_terminal`` (Windows) or
``python -m nestris_terminal`` is used.
"""

from __future__ import annotations

import contextlib
import os
import shlex
import subprocess
import sys
from pathlib import Path

KIOSK_EXE = "RetroverseTerminal.exe"
KIOSK_BIN = "RetroverseTerminal"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "NestrisTerminal"
DESKTOP_FILE = "retroverse-terminal.desktop"


def is_supported() -> bool:
    return sys.platform == "win32" or sys.platform.startswith("linux")


def _launch_args(config: Path | None = None) -> list[str]:
    windows = sys.platform == "win32"
    if getattr(sys, "frozen", False):
        kiosk = Path(sys.executable).with_name(KIOSK_EXE if windows else KIOSK_BIN)
        args = [str(kiosk if kiosk.exists() else sys.executable)]
    else:
        python = Path(sys.executable)
        pythonw = python.with_name("pythonw.exe")
        args = [str(pythonw if windows and pythonw.exists() else python), "-m", "nestris_terminal"]
    if config is not None:
        args += ["--config", str(config)]
    return args


def launch_command(config: Path | None = None) -> str:
    args = _launch_args(config)
    if sys.platform == "win32":
        return subprocess.list2cmdline(args)
    return shlex.join(args)


def desktop_entry_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "autostart" / DESKTOP_FILE


def desktop_entry(config: Path | None = None) -> str:
    # Desktop Entry Spec: Exec takes shell-like quoting; "%" must be doubled.
    exec_line = launch_command(config).replace("%", "%%")
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Retroverse Terminal\n"
        "Comment=Retroverse player terminal (kiosk)\n"
        f"Exec={exec_line}\n"
        "Icon=retroverse-terminal\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
        # Give the desktop a moment to finish (panel, compositor) first.
        "X-GNOME-Autostart-Delay=3\n"
    )


def is_enabled() -> bool:
    if sys.platform.startswith("linux"):
        return desktop_entry_path().is_file()
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
    except FileNotFoundError:
        return False
    return True


def set_enabled(enabled: bool, config: Path | None = None) -> None:
    if sys.platform.startswith("linux"):
        path = desktop_entry_path()
        if enabled:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(desktop_entry(config), encoding="utf-8")
        else:
            path.unlink(missing_ok=True)
        return
    if sys.platform != "win32":
        raise RuntimeError("autostart is only supported on Windows and Linux")
    import winreg

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, launch_command(config))
        else:
            with contextlib.suppress(FileNotFoundError):
                winreg.DeleteValue(key, VALUE_NAME)
