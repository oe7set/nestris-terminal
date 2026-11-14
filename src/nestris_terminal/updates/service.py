"""Updates of the terminal and its card reader from GitHub releases.

Plan: ``nestris-ltm/docs/UPDATES.md``. Two targets, checked by themselves
(1 minute after start, then every ``updates.check_interval_h``) and
installed only by a click in the hidden menu:

- ``app``: from ``oe7set/nestris-terminal``. Windows: ``RetroverseTerminal-Setup-<v>.exe``,
  started with ``/VERYSILENT /update=1``; the kiosk quits and the installer
  starts it again. Debian: ``nestris-terminal_<v>_<arch>.deb``, handed to the
  root helper of the package (``packaging/linux/update-helper``, started by
  the path unit ``nestris-terminal-update.path``): the terminal copies the
  package and the signed checksums into ``/var/lib/nestris-terminal/updates``
  and writes ``request``; the helper verifies again, runs ``apt-get install``
  and writes ``result``; on success the kiosk restarts itself.
- ``reader``: the firmware from ``oe7set/nestris-rfid-reader``. The signed
  release manifest names the image and its flash offset; esptool writes the
  ``app`` image (keeps the reader's settings). A reader still on the v1
  sketch needs the ``factory`` image once (offset 0x0, resets its settings).

Every file is checked against the release's ``SHA256SUMS.txt``, whose
Ed25519 signature must come from the release key (``releases.py``).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
import json
import os
import platform as platform_mod
import re
import shutil
import subprocess
import sys
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, cast

import httpx
import structlog

from nestris_terminal import __version__
from nestris_terminal.config import Settings
from nestris_terminal.updates.github import SUMS_FILE, GitHubReleases, Release, UpdateError
from nestris_terminal.updates.releases import (
    RELEASE_PUBLIC_KEYS,
    Version,
    parse_sums,
    verify_signature,
)

log = structlog.get_logger(__name__)

FIRST_CHECK_DELAY_S = 60.0
FLASH_TIMEOUT_S = 240.0
HELLO_AFTER_FLASH_S = 20.0
FLASH_BAUD = 460800

APP_PREFIX, APP_SUFFIX = "RetroverseTerminal-Setup-", ".exe"
DEB_PREFIX = "nestris-terminal_"
DEB_ARCH = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}
# Installed by the Debian package (packaging/linux/).
UPDATE_HELPER = Path("/usr/lib/nestris-terminal/update-helper")
DEB_UPDATE_DIR = Path("/var/lib/nestris-terminal/updates")
DEB_INSTALL_TIMEOUT_S = 600.0
READER_PREFIX, MANIFEST_SUFFIX = "nestris-rfid-reader-", "-manifest.json"
READER_CHIP = "esp32"
APP_OFFSET_MIN = 0x10000

Target = Literal["app", "reader"]
ReaderMode = Literal["app", "factory"]


# ---------------------------------------------------------------- reader access


@dataclass(frozen=True)
class ReaderView:
    """What the updater needs to know about the plugged-in reader."""

    port: str | None  # serial port, None = no reader found
    fw: str | None  # firmware version from its hello (None: no v2 hello)
    fake: bool = False  # the simulated reader (rfid.driver = fake)
    old_protocol: bool = False  # answers, but with protocol v1 (needs the factory image)


class ReaderControl(Protocol):
    def view(self) -> ReaderView: ...
    async def release(self) -> None: ...  # close the serial port
    async def reconnect(self) -> None: ...  # open it again
    async def wait_hello(self, timeout_s: float) -> str | None: ...  # fw after reconnect


# ---------------------------------------------------------------- esptool

Flasher = Callable[[list[str], Callable[[float], None]], tuple[int, str]]
Launcher = Callable[[Path, str], None]

_PERCENT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s?%")
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def app_asset(platform: str = sys.platform, machine: str | None = None) -> tuple[str, str]:
    """Prefix and suffix of the app update for this platform (the version sits between)."""
    if platform == "win32":
        return APP_PREFIX, APP_SUFFIX
    machine = (machine or platform_mod.machine()).lower()
    return DEB_PREFIX, f"_{DEB_ARCH.get(machine, machine)}.deb"


def esptool_command() -> list[str]:
    """esptool as a separate program (it is GPL-2.0-or-later; never imported):
    ``esptool(.exe)`` next to the app when installed, the venv's module in development."""
    if getattr(sys, "frozen", False):
        name = "esptool.exe" if sys.platform == "win32" else "esptool"
        return [str(Path(sys.executable).with_name(name))]
    return [sys.executable, "-m", "esptool"]


def run_esptool(args: list[str], progress: Callable[[float], None]) -> tuple[int, str]:
    """Run esptool, report write progress (0..1); returns (exit code, output tail)."""
    env = {**os.environ, "NO_COLOR": "1", "TERM": "dumb", "PYTHONUNBUFFERED": "1",
           "PYTHONIOENCODING": "utf-8"}  # fmt: skip
    proc = subprocess.Popen(
        [*esptool_command(), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    timer = threading.Timer(FLASH_TIMEOUT_S, proc.kill)
    timer.start()
    tail: deque[str] = deque(maxlen=40)
    pending = b""
    try:
        stdout = cast(io.BufferedReader, proc.stdout)
        while chunk := stdout.read1(512):
            pending += chunk
            # Progress bars redraw with \r: treat it as a line end too.
            *lines, pending = re.split(rb"[\r\n]", pending)
            for raw in lines:
                line = _ANSI.sub("", raw.decode("utf-8", "replace")).strip()
                if not line:
                    continue
                tail.append(line)
                m = _PERCENT.search(line)
                if m and "writing" in line.lower():
                    progress(min(float(m[1]) / 100, 1.0))
        code = proc.wait()
    finally:
        timer.cancel()
    if pending.strip():
        tail.append(_ANSI.sub("", pending.decode("utf-8", "replace")).strip())
    return code, "\n".join(tail)


def esptool_error(output: str) -> str:
    """The gist of a failed esptool run: its last message, without the box
    drawing that esptool puts around errors."""
    lines = [ln.strip(" │┌┐└┘─") for ln in output.splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith("Error")]
    for i in range(len(lines) - 1, -1, -1):
        if "error" in lines[i].lower() or "failed" in lines[i].lower():
            return " ".join(lines[i : i + 3])[:300]
    return " ".join(lines[-2:])[:300]


def start_installer(path: Path, args: str) -> None:
    """ShellExecute, so an all-users install can still ask for admin rights."""
    if sys.platform != "win32":
        raise UpdateError("unsupported", "installing updates is only supported on Windows")
    os.startfile(str(path), "open", args)


# ---------------------------------------------------------------- service


@dataclass(frozen=True)
class SignedSums:
    raw: bytes  # SHA256SUMS.txt as published
    signature: str  # SHA256SUMS.txt.sig (base64)
    entries: dict[str, str]  # file name -> sha256


@dataclass
class TargetInfo:
    name: Target
    github: GitHubReleases
    releases: list[Release] = field(default_factory=list)
    latest: Release | None = None
    check_error: str | None = None


class UpdateService:
    def __init__(
        self,
        settings: Settings,
        reader: ReaderControl,
        *,
        request_quit: Callable[[], None] = lambda: None,
        request_restart: Callable[[], None] = lambda: None,
        github_app: GitHubReleases | None = None,
        github_reader: GitHubReleases | None = None,
        flasher: Flasher = run_esptool,
        launcher: Launcher = start_installer,
        frozen: bool | None = None,
        current_version: str = __version__,
        public_keys: tuple[str, ...] = RELEASE_PUBLIC_KEYS,
        platform: str = sys.platform,
        machine: str | None = None,
        deb_dir: Path = DEB_UPDATE_DIR,
        update_helper: Path = UPDATE_HELPER,
        poll_interval_s: float = 1.0,
    ) -> None:
        cfg = settings.updates
        token = cfg.token.get_secret_value()
        self.settings = settings
        self.reader = reader
        self.request_quit = request_quit
        self.request_restart = request_restart
        self.platform = platform
        self.app_prefix, self.app_suffix = app_asset(platform, machine)
        self.deb_dir = deb_dir
        self.update_helper = update_helper
        self.poll_interval_s = poll_interval_s
        self.targets: dict[Target, TargetInfo] = {
            "app": TargetInfo("app", github_app or GitHubReleases(cfg.owner, cfg.app_repo, token)),
            "reader": TargetInfo(
                "reader", github_reader or GitHubReleases(cfg.owner, cfg.reader_repo, token)
            ),
        }
        self._flasher = flasher
        self._launcher = launcher
        self.frozen = getattr(sys, "frozen", False) if frozen is None else frozen
        self.current = Version.parse(current_version) or Version(0, 0, 0)
        self.public_keys = public_keys
        self.last_check: datetime | None = None
        # idle, checking, downloading, verifying, flashing, waiting, installing, done, error
        self.status = "idle"
        self.status_target: Target | None = None
        self.status_detail: str | None = None
        self.progress: float | None = None
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        for info in self.targets.values():
            await info.github.close()

    # ------------------------------------------------------------ checking

    def _candidates(self, info: TargetInfo) -> list[Release]:
        beta = self.settings.updates.channel == "beta"
        return [r for r in info.releases if beta or not r.prerelease]

    async def check(self) -> dict[str, Any]:
        if self.status in ("idle", "done", "error"):
            self._set("checking", None)
        for info in self.targets.values():
            try:
                info.releases = await info.github.list()
                candidates = self._candidates(info)
                info.latest = candidates[0] if candidates else None
                info.check_error = None
            except UpdateError as exc:
                info.check_error = exc.message
            except httpx.HTTPError as exc:
                # No internet at the venue is normal; say so quietly.
                info.check_error = f"no connection to GitHub ({type(exc).__name__})"
        self.last_check = datetime.now(UTC)
        if self.status == "checking":
            self._set("idle", None)
        return self.state()

    def apply_settings(self, settings: Settings) -> None:
        """New channel/enabled: the channel may pick another "latest"."""
        self.settings = settings
        for info in self.targets.values():
            candidates = self._candidates(info)
            info.latest = candidates[0] if candidates else None

    async def run(self) -> None:
        """Background checks while ``updates.enabled``."""
        await asyncio.sleep(FIRST_CHECK_DELAY_S)
        while True:
            if self.settings.updates.enabled:
                await self.check()
            await asyncio.sleep(self.settings.updates.check_interval_h * 3600)

    def _reader_version(self, view: ReaderView) -> Version | None:
        return Version.parse(view.fw) if view.fw else None

    def app_update_available(self) -> bool:
        latest = self.targets["app"].latest
        return latest is not None and latest.version > self.current

    def reader_update_available(self, view: ReaderView | None = None) -> bool:
        view = view or self.reader.view()
        latest = self.targets["reader"].latest
        if latest is None or view.port is None or view.fake:
            return False
        if view.old_protocol:
            return True
        current = self._reader_version(view)
        return current is not None and latest.version > current

    def state(self) -> dict[str, Any]:
        cfg = self.settings.updates
        view = self.reader.view()
        app, reader = self.targets["app"], self.targets["reader"]
        return {
            "app": {
                "current": str(self.current),
                "latest": app.latest.summary() if app.latest else None,
                "update_available": self.app_update_available(),
                "check_error": app.check_error,
                "source": f"github.com/{cfg.owner}/{cfg.app_repo}",
                "can_install": self.app_install_block() is None,
                "install_hint": self.app_install_block(),
            },
            "reader": {
                "current": view.fw,
                "port": view.port,
                "fake": view.fake,
                "old_protocol": view.old_protocol,
                "latest": reader.latest.summary() if reader.latest else None,
                "update_available": self.reader_update_available(view),
                "check_error": reader.check_error,
                "source": f"github.com/{cfg.owner}/{cfg.reader_repo}",
                "can_install": view.port is not None and not view.fake,
            },
            "last_check": self.last_check.isoformat() if self.last_check else None,
            "status": self.status,
            "status_target": self.status_target,
            "status_detail": self.status_detail,
            "progress": self.progress,
            "enabled": cfg.enabled,
            "channel": cfg.channel,
        }

    def release_list(self, target: Target) -> list[dict[str, Any]]:
        info = self.targets[target]
        current: Version | None = (
            self.current if target == "app" else self._reader_version(self.reader.view())
        )
        out = []
        for rel in self._candidates(info):
            item = rel.summary()
            item["is_current"] = current is not None and rel.version == current
            item["is_downgrade"] = current is not None and rel.version < current
            out.append(item)
        return out

    # ------------------------------------------------------------ installing

    def _set(self, status: str, target: Target | None, detail: str | None = None,
             progress: float | None = None) -> None:  # fmt: skip
        self.status = status
        self.status_target = target
        self.status_detail = detail
        self.progress = progress

    def _release(self, target: Target, version: str) -> Release:
        wanted = Version.parse(version)
        release = next((r for r in self.targets[target].releases if r.version == wanted), None)
        if release is None:
            raise UpdateError("unknown_version", f"release {version} not found")
        if not release.signed:
            raise UpdateError("not_installable", f"release {version} is not signed")
        return release

    async def install(
        self, target: Target, version: str, *, mode: ReaderMode = "app"
    ) -> dict[str, Any]:
        if self._lock.locked():
            raise UpdateError("busy", "an update is already in progress")
        async with self._lock:
            try:
                if not self.targets[target].releases:
                    await self.check()
                release = self._release(target, version)
                if target == "app":
                    await self._install_app(release)
                else:
                    await self._install_reader(release, mode)
            except UpdateError as exc:
                self._set("error", target, exc.message)
                raise
            except Exception as exc:
                self._set("error", target, f"{type(exc).__name__}: {exc}")
                raise UpdateError("failed", str(exc)) from exc
        return self.state()

    def app_install_block(self) -> str | None:
        """Why this installation cannot update itself (None: it can)."""
        if not self.frozen:
            return "app updates install only in the installed app (not a source checkout)"
        if self.platform == "win32":
            return None
        if not self.platform.startswith("linux"):
            return f"app updates are not supported on {self.platform}"
        if not self.update_helper.exists():
            return f"update helper {self.update_helper} missing (install the Debian package)"
        if not os.access(self.deb_dir, os.W_OK | os.X_OK):
            return (
                f"no write access to {self.deb_dir}: add this user to the group "
                "nestris-terminal and sign in again"
            )
        return None

    async def _install_app(self, release: Release) -> None:
        block = self.app_install_block()
        if block is not None:
            raise UpdateError("dev" if not self.frozen else "unsupported", block)
        name = release.find(self.app_prefix, self.app_suffix)
        if name is None:
            raise UpdateError(
                "not_installable", f"release {release.version} has no package for this PC"
            )
        sums = await self._signed_sums(release, "app")
        installer = await self._download_checked(release, name, sums.entries, "app")
        if self.platform != "win32":
            await self._install_deb(release, installer, sums)
            return
        self._set("installing", "app", str(release.version))
        logfile = self.settings.data_dir / "updates" / f"install-{release.version}.log"
        log.info("starting installer", version=str(release.version), installer=str(installer))
        args = f'/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /update=1 /LOG="{logfile}"'
        self._launcher(installer, args)
        # Let the API answer first, then leave so the installer can replace the files.
        asyncio.get_running_loop().call_later(1.5, self.request_quit)

    async def _install_deb(self, release: Release, package: Path, sums: SignedSums) -> None:
        """Hand a verified package to the root helper and wait for its result."""
        folder = self.deb_dir
        for stale in ("request", "result"):
            (folder / stale).unlink(missing_ok=True)
        self._set("installing", "app", str(release.version))
        await asyncio.to_thread(shutil.copyfile, package, folder / package.name)
        (folder / SUMS_FILE).write_bytes(sums.raw)
        (folder / (SUMS_FILE + ".sig")).write_bytes(f"{sums.signature}\n".encode("ascii"))
        # Atomic: the path unit fires as soon as "request" exists.
        tmp = folder / "request.tmp"
        tmp.write_bytes(f"deb={package.name}\n".encode("ascii"))
        tmp.replace(folder / "request")
        log.info("app update handed to the helper", version=str(release.version))

        result = await self._wait_deb_result()
        await asyncio.to_thread(package.unlink, missing_ok=True)
        if not result.get("ok"):
            detail = str(result.get("detail") or "installation failed")
            log.error("app update failed", detail=detail)
            raise UpdateError("install_failed", detail)
        log.info("app updated, restarting", version=result.get("version"))
        self._set("done", "app", str(release.version))
        asyncio.get_running_loop().call_later(1.5, self.request_restart)

    async def _wait_deb_result(self) -> dict[str, Any]:
        result = self.deb_dir / "result"
        loop = asyncio.get_running_loop()
        deadline = loop.time() + DEB_INSTALL_TIMEOUT_S
        while loop.time() < deadline:
            if result.is_file():
                try:
                    data = json.loads(result.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    data = {"ok": False, "detail": "unreadable result from the update helper"}
                with contextlib.suppress(OSError):
                    result.unlink()
                return data if isinstance(data, dict) else {"ok": False}
            await asyncio.sleep(self.poll_interval_s)
        (self.deb_dir / "request").unlink(missing_ok=True)
        raise UpdateError(
            "install_timeout",
            "no answer from the update helper (is nestris-terminal-update.path active?)",
        )

    async def _install_reader(self, release: Release, mode: ReaderMode) -> None:
        view = self.reader.view()
        if view.fake:
            raise UpdateError("fake_reader", "the simulated reader cannot be flashed")
        if view.port is None:
            raise UpdateError("no_reader", "no reader found (USB cable, COM port)")
        manifest_name = release.find(READER_PREFIX, MANIFEST_SUFFIX)
        if manifest_name is None:
            raise UpdateError("not_installable", f"release {release.version} has no manifest")
        sums = await self._signed_sums(release, "reader")
        manifest_path = await self._download_checked(release, manifest_name, sums.entries, "reader")
        image_name, offset = parse_manifest(manifest_path.read_text(encoding="utf-8"), mode)
        image = await self._download_checked(release, image_name, sums.entries, "reader")

        port = view.port
        args = ["--chip", READER_CHIP, "--port", port, "--baud", str(FLASH_BAUD),
                "--before", "default-reset", "--after", "hard-reset",
                "write-flash", hex(offset), str(image)]  # fmt: skip
        self._set("flashing", "reader", f"{image_name} → {port}", 0.0)
        log.info("flashing reader", port=port, image=image_name, offset=hex(offset))

        def progress(value: float) -> None:
            self.progress = round(value, 3)

        await self.reader.release()
        try:
            code, output = await asyncio.to_thread(self._flasher, args, progress)
        finally:
            await self.reader.reconnect()
        if code != 0:
            log.error("reader flash failed", code=code, output=output[-2000:])
            raise UpdateError("flash_failed", f"esptool exit {code}: {esptool_error(output)}")
        self._set("waiting", "reader", "hello", None)
        fw = await self.reader.wait_hello(HELLO_AFTER_FLASH_S)
        if fw is None or Version.parse(fw) != release.version:
            raise UpdateError(
                "verify_failed",
                f"reader reports {fw or 'nothing'} after flashing, expected {release.version}",
            )
        log.info("reader updated", fw=fw, port=port)
        self._set("done", "reader", fw)
        with contextlib.suppress(OSError):
            image.unlink()

    async def _signed_sums(self, release: Release, target: Target) -> SignedSums:
        github = self.targets[target].github
        self._set("downloading", target, SUMS_FILE, 0.0)
        sums_bytes = await github.fetch(release.assets[SUMS_FILE].url)
        signature = (await github.fetch(release.assets[SUMS_FILE + ".sig"].url)).decode(
            "ascii", "replace"
        )
        self._set("verifying", target, "signature")
        if not verify_signature(sums_bytes, signature, self.public_keys):
            raise UpdateError("bad_signature", "SHA256SUMS.txt is not signed by the release key")
        return SignedSums(
            sums_bytes, signature.strip(), parse_sums(sums_bytes.decode("utf-8", "replace"))
        )

    async def _download_checked(
        self, release: Release, name: str, sums: dict[str, str], target: Target
    ) -> Path:
        expected = sums.get(name)
        if expected is None:
            raise UpdateError("bad_checksum", f"{name} is not in SHA256SUMS.txt")
        if name not in release.assets:
            raise UpdateError("not_installable", f"{name} is missing in release {release.version}")
        folder = self.settings.data_dir / "updates" / target / str(release.version)
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / name

        def progress(done: int, total: int) -> None:
            self.progress = round(done / total, 3) if total else None

        self._set("downloading", target, name, 0.0)
        await self.targets[target].github.download(release.assets[name].url, dest, progress)
        self._set("verifying", target, "sha256")
        digest = await asyncio.to_thread(file_sha256, dest)
        if digest != expected:
            dest.unlink(missing_ok=True)
            raise UpdateError("bad_checksum", f"{name}: checksum mismatch")
        return dest


def parse_manifest(text: str, mode: ReaderMode) -> tuple[str, int]:
    """The image file and flash offset for ``mode`` from a reader release
    manifest (``nestris-rfid-reader/tools/make_release.py``)."""
    try:
        manifest = json.loads(text)
        entry = next(f for f in manifest["files"] if f.get("kind") == mode)
        name, offset = str(entry["name"]), int(str(entry["offset"]), 0)
    except (ValueError, KeyError, TypeError, StopIteration) as exc:
        raise UpdateError("bad_manifest", f"release manifest has no usable '{mode}' image") from exc
    if manifest.get("chip", READER_CHIP) != READER_CHIP:
        raise UpdateError("bad_manifest", f"firmware is for {manifest.get('chip')}, not esp32")
    # Only the two layouts the reader uses: app at its partition, factory at 0.
    if (mode == "factory" and offset != 0) or (mode == "app" and offset < APP_OFFSET_MIN):
        raise UpdateError("bad_manifest", f"unexpected offset {hex(offset)} for '{mode}'")
    if "/" in name or "\\" in name:
        raise UpdateError("bad_manifest", f"bad file name {name!r}")
    return name, offset


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
