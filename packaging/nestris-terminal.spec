# PyInstaller spec: one folder, two executables sharing the same files.
#
#   RetroverseTerminal.exe  the kiosk (no console window); what autostart runs
#   nestris-terminal.exe    console CLI: configure, autostart, set-pin, --headless
#   esptool.exe             Espressif's esptool (GPL-2.0-or-later), a separate program
#                           the updater runs to flash the reader; never imported
#
# On Linux the same three programs, without ".exe".
# Build with packaging/build.ps1 (Windows) or packaging/linux/build-deb.sh
# (Debian); both build the UI first.
# ruff: noqa

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
SRC = ROOT / "src"
WEB = SRC / "nestris_terminal" / "web"
if not (WEB / "index.html").is_file():
    raise SystemExit("UI not built: run 'pnpm build' in frontend/ (or packaging/build.ps1)")

# Dev tools in the venv that the analysis would otherwise drag in (pydantic
# ships a mypy plugin).
DEV_TOOLS = ["mypy", "mypyc", "librt", "ast_serialize", "pytest", "_pytest", "ruff", "pyinstaller"]

a = Analysis(
    [str(SRC / "nestris_terminal" / "__main__.py")],
    pathex=[str(SRC)],
    datas=[(str(WEB), "nestris_terminal/web")],
    # uvicorn picks its loop/protocol implementations by name at runtime.
    hiddenimports=collect_submodules("uvicorn") + ["nestris_terminal.bridge.app"],
    excludes=["tkinter", "esptool", *DEV_TOOLS, "PySide6.Qt3DCore", "PySide6.QtQuick3D", "PySide6.QtCharts",
              "PySide6.QtDataVisualization", "PySide6.QtMultimedia", "PySide6.QtPdf",
              "PySide6.QtBluetooth", "PySide6.QtSensors"],
    noarchive=False,
)


# PySide6 hooks collect far more of Qt than a QWebEngineView needs. Drop the
# 3D/Charts/QML-controls libraries, QML modules and all but de/en locales.
DROP = ("Qt63D", "Qt6Quick3D", "Qt6Charts", "Qt6Graphs", "Qt6DataVisualization",
        "Qt6QuickControls2", "Qt6QuickDialogs2", "Qt6QuickTemplates2", "Qt6ShaderTools",
        "Qt6Multimedia", "Qt6SpatialAudio", "Qt6Pdf", "Qt6VirtualKeyboard", "Qt6Sensors",
        "Qt6Bluetooth", "Qt6Nfc", "Qt6SerialBus", "Qt6Scxml", "Qt6StateMachine",
        "Qt6RemoteObjects", "Qt6Designer", "Qt6Help", "Qt6Sql", "Qt6Test", "Qt6TextToSpeech",
        "Qt6Location", "Qt6HttpServer", "Qt6WebSockets", "Qt6Svg", "Qt6Xml")
KEEP_LOCALES = ("de.pak", "en-US.pak", "en-GB.pak")


def keep(entry):
    dest = entry[0].replace("\\", "/")
    name = dest.rsplit("/", 1)[-1]
    if name.startswith("libQt6"):  # Linux: libQt6Charts.so.6 = Qt6Charts.dll
        name = name[3:]
    if "PySide6/qml/" in dest:
        return False
    # Linux: the GTK3 platform theme would pull in all of GTK; Qt falls back
    # to its own style without it.
    if "platformthemes/libqgtk3" in dest:
        return False
    if name.startswith(DROP):
        return False
    if "qtwebengine_locales/" in dest and not name.endswith(KEEP_LOCALES):
        return False
    if "PySide6/translations/" in dest and name.endswith(".qm") and not ("_de" in name or "_en" in name):
        return False
    return True


# esptool: its own analysis and executable. It loads its stub flashers (JSON)
# and chip targets at runtime; its license file ships next to it.
import esptool as _esptool

SITE = Path(_esptool.__file__).parent.parent
ESPTOOL_LICENSE = next(SITE.glob("esptool-*.dist-info/licenses/LICENSE"))
e = Analysis(
    [str(ROOT / "packaging" / "esptool_main.py")],
    datas=[*collect_data_files("esptool"), (str(ESPTOOL_LICENSE), "licenses/esptool")],
    hiddenimports=collect_submodules("esptool"),
    excludes=["tkinter", "PySide6", *DEV_TOOLS],
    noarchive=False,
)

def basename(dest):
    return dest.replace("\\", "/").rsplit("/", 1)[-1]


# Names of the Qt files dropped on purpose (for drop_dependents below).
dropped_by_keep = {basename(e[0]) for e in a.binaries if not keep(e)}
a.binaries = [e for e in a.binaries if keep(e)]
a.datas = [e for e in a.datas if keep(e)]


def drop_dependents(binaries, dropped):
    """Linux: also drop every bundled library or plugin (e.g. PySide6/Qt3DCore.abi3.so,
    a QML or multimedia plugin) that links a library dropped above; it could
    never load. Windows keeps such files too, but nothing checks them there."""
    import subprocess

    dropped = set(dropped)
    needs = {}
    for dest, src, _kind in binaries:
        out = subprocess.run(["objdump", "-p", src], capture_output=True, text=True).stdout
        needs[dest] = {ln.split()[1] for ln in out.splitlines() if ln.strip().startswith("NEEDED")}
    while True:
        gone = {e[0] for e in binaries if needs.get(e[0], set()) & dropped}
        if not gone:
            return binaries
        dropped |= {basename(d) for d in gone}
        binaries = [e for e in binaries if e[0] not in gone]


def from_system(entry):
    """A library PyInstaller copied from the build machine's /lib or /usr/lib
    (libX11, libxcb-*, libstdc++, libnss3 ...). Bundled, Debian 12 copies
    clash with Debian 13's Mesa (GLX fails); the package depends on them
    instead (debian/control.in), so every PC uses its own matching versions."""
    src = str(entry[1])
    return src.startswith(("/lib/", "/lib64/", "/usr/lib/", "/usr/lib64/"))


if sys.platform.startswith("linux"):
    a.binaries = drop_dependents([e for e in a.binaries if not from_system(e)], dropped_by_keep)
pyz = PYZ(a.pure)

# The .ico is a Windows resource; Linux uses the PNG from the .desktop file.
icon = str(ROOT / "packaging" / "icon.ico") if sys.platform == "win32" else None
kiosk = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="RetroverseTerminal",
    console=False,
    icon=icon,
)
cli = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="nestris-terminal",
    console=True,
    icon=icon,
)
esptool_exe = EXE(
    PYZ(e.pure), e.scripts, [],
    exclude_binaries=True,
    name="esptool",
    console=True,
)
COLLECT(kiosk, cli, esptool_exe, a.binaries, a.datas, e.binaries, e.datas, name="RetroverseTerminal")
