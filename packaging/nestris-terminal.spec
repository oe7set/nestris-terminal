# PyInstaller spec: one folder, two executables sharing the same files.
#
#   RetroverseTerminal.exe  the kiosk (no console window); what autostart runs
#   nestris-terminal.exe    console CLI: configure, autostart, set-pin, --headless
#
# Build with packaging/build.ps1 (it builds the UI first).
# ruff: noqa

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
SRC = ROOT / "src"
WEB = SRC / "nestris_terminal" / "web"
if not (WEB / "index.html").is_file():
    raise SystemExit("UI not built: run 'pnpm build' in frontend/ (or packaging/build.ps1)")

a = Analysis(
    [str(SRC / "nestris_terminal" / "__main__.py")],
    pathex=[str(SRC)],
    datas=[(str(WEB), "nestris_terminal/web")],
    # uvicorn picks its loop/protocol implementations by name at runtime.
    hiddenimports=collect_submodules("uvicorn") + ["nestris_terminal.bridge.app"],
    excludes=["tkinter", "PySide6.Qt3DCore", "PySide6.QtQuick3D", "PySide6.QtCharts",
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
    if "PySide6/qml/" in dest:
        return False
    if name.startswith(DROP):
        return False
    if "qtwebengine_locales/" in dest and not name.endswith(KEEP_LOCALES):
        return False
    if "PySide6/translations/" in dest and name.endswith(".qm") and not ("_de" in name or "_en" in name):
        return False
    return True


a.binaries = [e for e in a.binaries if keep(e)]
a.datas = [e for e in a.datas if keep(e)]
pyz = PYZ(a.pure)

icon = str(ROOT / "packaging" / "icon.ico")
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
COLLECT(kiosk, cli, a.binaries, a.datas, name="RetroverseTerminal")
