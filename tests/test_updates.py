"""Updates: GitHub releases, signed checksums, app installer, reader flashing."""

from __future__ import annotations

import base64
import hashlib
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from nestris_terminal.bridge.app import create_app
from nestris_terminal.config import load_settings
from nestris_terminal.runtime import Runtime
from nestris_terminal.updates import service as service_mod
from nestris_terminal.updates.github import GitHubReleases, UpdateError
from nestris_terminal.updates.releases import RELEASE_PUBLIC_KEYS, Version, verify_signature
from nestris_terminal.updates.service import (
    ReaderView,
    UpdateService,
    esptool_error,
    parse_manifest,
    run_esptool,
)

KEY = Ed25519PrivateKey.generate()
PUBLIC = base64.b64encode(
    KEY.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
).decode()
INSTALLER = b"MZ fake installer" * 50
APP_IMAGE = b"\xe9 fake esp32 app image" * 40
FACTORY_IMAGE = b"\xe9 fake factory image" * 80


def sign(data: bytes) -> str:
    return base64.b64encode(KEY.sign(data)).decode()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- fake GitHub


class FakeGitHub:
    """Releases API + downloads for oe7set/nestris-terminal and oe7set/nestris-rfid-reader."""

    def __init__(self) -> None:
        self.releases: dict[str, list[dict[str, Any]]] = {
            "nestris-terminal": [],
            "nestris-rfid-reader": [],
        }
        self.files: dict[str, bytes] = {}
        self.offline = False

    def _publish(self, repo: str, version: str, files: dict[str, bytes], *,
                 prerelease: bool = False, signature: str | None = None) -> None:  # fmt: skip
        sums = "".join(f"{sha(data)}  {name}\n" for name, data in files.items())
        files = {**files, "SHA256SUMS.txt": sums.encode(),
                 "SHA256SUMS.txt.sig": ((signature or sign(sums.encode())) + "\n").encode()}  # fmt: skip
        base = f"https://github.com/oe7set/{repo}/releases/download/v{version}"
        for name, data in files.items():
            self.files[f"{base}/{name}"] = data
        self.releases[repo].append({
            "tag_name": f"v{version}", "draft": False, "prerelease": prerelease,
            "body": f"Notes {version}", "published_at": "2026-10-04T10:00:00Z",
            "html_url": f"https://github.com/oe7set/{repo}/releases/tag/v{version}",
            "assets": [{"name": n, "browser_download_url": f"{base}/{n}", "size": len(d)}
                       for n, d in files.items()],
        })  # fmt: skip

    def add_app(self, version: str, **kw: Any) -> None:
        self._publish(
            "nestris-terminal",
            version,
            {f"RetroverseTerminal-Setup-{version}.exe": INSTALLER},
            **kw,
        )

    def add_reader(self, version: str, *, app_offset: str = "0x10000",
                   image: bytes = APP_IMAGE, **kw: Any) -> None:  # fmt: skip
        app_name = f"nestris-rfid-reader-{version}-esp32dev-app.bin"
        factory_name = f"nestris-rfid-reader-{version}-esp32dev.bin"
        manifest = {
            "name": "nestris-rfid-reader", "version": version, "board": "esp32dev",
            "chip": "esp32", "proto": 2,
            "files": [
                {"kind": "factory", "name": factory_name, "offset": "0x0", "sha256": sha(FACTORY_IMAGE)},
                {"kind": "app", "name": app_name, "offset": app_offset, "sha256": sha(image)},
            ],
        }  # fmt: skip
        self._publish("nestris-rfid-reader", version, {
            factory_name: FACTORY_IMAGE, app_name: image,
            f"nestris-rfid-reader-{version}-manifest.json": json.dumps(manifest).encode(),
        }, **kw)  # fmt: skip

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.offline:
            raise httpx.ConnectError("offline", request=request)
        url = str(request.url).split("?")[0]
        for repo, releases in self.releases.items():
            if url.endswith(f"/repos/oe7set/{repo}/releases"):
                return httpx.Response(200, json=releases)
        if url in self.files:
            return httpx.Response(200, content=self.files[url])
        return httpx.Response(404)


class FakeReader:
    """The reader as the updater sees it; flashing changes its firmware."""

    def __init__(self, fw: str | None = "1.0.0", port: str | None = "COM16") -> None:
        self.fw = fw
        self.port = port
        self.fake = False
        self.old_protocol = False
        self.calls: list[str] = []
        self.flashed_fw: str | None = None

    def view(self) -> ReaderView:
        return ReaderView(self.port, self.fw, self.fake, self.old_protocol)

    async def release(self) -> None:
        self.calls.append("release")

    async def reconnect(self) -> None:
        self.calls.append("reconnect")
        if self.flashed_fw:
            self.fw = self.flashed_fw

    async def wait_hello(self, timeout_s: float) -> str | None:
        return self.fw


@pytest.fixture
def gh() -> FakeGitHub:
    return FakeGitHub()


def make_service(
    tmp_path: Path, gh: FakeGitHub, reader: FakeReader | None = None, *,
    flash_result: Callable[[list[str]], int] | None = None, frozen: bool = True,
    current: str = "0.2.0", channel: str = "stable",
) -> tuple[UpdateService, dict[str, Any]]:  # fmt: skip
    settings = load_settings(
        tmp_path / "none.toml", data_dir=tmp_path, updates={"channel": channel}
    )
    calls: dict[str, Any] = {"launched": [], "flashed": [], "quit": 0}
    reader = reader or FakeReader()

    def flasher(args: list[str], progress: Callable[[float], None]) -> tuple[int, str]:
        assert "release" in reader.calls and "reconnect" not in reader.calls  # port is free
        calls["flashed"].append(args)
        progress(0.5)
        progress(1.0)
        code = flash_result(args) if flash_result else 0
        if code == 0:
            image = Path(args[-1]).name
            reader.flashed_fw = image.split("-")[3]  # nestris-rfid-reader-<v>-...
        return code, "Writing at 0x00010000 (100 %)\nHard resetting via RTS pin..."

    def quit_() -> None:
        calls["quit"] += 1

    transport = httpx.MockTransport(gh)
    service = UpdateService(
        settings,
        reader,
        request_quit=quit_,
        github_app=GitHubReleases("oe7set", "nestris-terminal", transport=transport),
        github_reader=GitHubReleases("oe7set", "nestris-rfid-reader", transport=transport),
        flasher=flasher,
        launcher=lambda path, args: calls["launched"].append((path, args)),
        frozen=frozen,
        current_version=current,
        public_keys=(PUBLIC,),
    )
    return service, calls


# ---------------------------------------------------------------- pure helpers


def test_shared_release_helpers() -> None:
    assert Version.parse("0.2.0b2") < Version.parse("0.2.0") < Version.parse("1.0.0")  # type: ignore[operator]
    assert Version.parse("0.2.0b2") == Version.parse("0.2.0-beta.2")
    data = b"x  file\n"
    assert verify_signature(data, sign(data), (PUBLIC,))
    assert not verify_signature(data, sign(data), RELEASE_PUBLIC_KEYS)


def test_parse_manifest() -> None:
    manifest = {"chip": "esp32", "files": [
        {"kind": "app", "name": "a.bin", "offset": "0x10000"},
        {"kind": "factory", "name": "f.bin", "offset": "0x0"},
    ]}  # fmt: skip
    text = json.dumps(manifest)
    assert parse_manifest(text, "app") == ("a.bin", 0x10000)
    assert parse_manifest(text, "factory") == ("f.bin", 0)
    for bad in (
        {**manifest, "chip": "esp32s3"},
        {"chip": "esp32", "files": [{"kind": "app", "name": "a.bin", "offset": "0x0"}]},
        {"chip": "esp32", "files": [{"kind": "app", "name": "../a.bin", "offset": "0x10000"}]},
        {"chip": "esp32", "files": []},
    ):
        with pytest.raises(UpdateError) as err:
            parse_manifest(json.dumps(bad), "app")
        assert err.value.code == "bad_manifest"
    with pytest.raises(UpdateError):
        parse_manifest("not json", "app")


def test_run_esptool_reports_progress(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    script = tmp_path / "fake_esptool.py"
    script.write_text(
        "import sys\n"
        "print('Connecting....')\n"
        "for p in (0, 37.5, 100):\n"
        "    sys.stdout.write(f'\\rWriting at 0x00010000 [====] {p:5.1f}% 1/2 bytes...')\n"
        "    sys.stdout.flush()\n"
        "print()\nprint('\\x1b[32mHard resetting via RTS pin...\\x1b[0m')\n"
        "sys.exit(int(sys.argv[-1]))\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(service_mod, "esptool_command", lambda: [sys.executable, str(script)])
    seen: list[float] = []
    code, output = run_esptool(["0"], seen.append)
    assert code == 0
    assert seen == [0.0, 0.375, 1.0]
    assert output.splitlines()[-1] == "Hard resetting via RTS pin..."
    assert run_esptool(["2"], seen.append)[0] == 2


# ---------------------------------------------------------------- checking


async def test_check_both_targets(tmp_path: Path, gh: FakeGitHub) -> None:
    gh.add_app("0.2.0")
    gh.add_app("0.3.0b1", prerelease=True)
    gh.add_reader("1.0.0")
    gh.add_reader("1.1.0")
    service, _ = make_service(tmp_path, gh)
    state = await service.check()
    assert state["app"]["latest"]["version"] == "0.2.0"
    assert not state["app"]["update_available"]
    assert state["reader"]["current"] == "1.0.0"
    assert state["reader"]["latest"]["version"] == "1.1.0"
    assert state["reader"]["update_available"]

    beta, _ = make_service(tmp_path, gh, channel="beta")
    state = await beta.check()
    assert state["app"]["latest"]["version"] == "0.3.0b1" and state["app"]["update_available"]
    releases = beta.release_list("reader")
    assert [(r["version"], r["is_current"], r["is_downgrade"]) for r in releases] == [
        ("1.1.0", False, False),
        ("1.0.0", True, False),
    ]


async def test_offline_check_is_quiet(tmp_path: Path, gh: FakeGitHub) -> None:
    gh.offline = True
    service, _ = make_service(tmp_path, gh)
    state = await service.check()
    assert "no connection" in state["app"]["check_error"]
    assert "no connection" in state["reader"]["check_error"]
    assert state["status"] == "idle" and state["last_check"]


async def test_reader_states(tmp_path: Path, gh: FakeGitHub) -> None:
    gh.add_reader("1.0.0")
    reader = FakeReader(fw=None)
    service, _ = make_service(tmp_path, gh, reader)
    await service.check()
    assert not service.reader_update_available()  # unknown firmware: no claim
    reader.old_protocol = True
    assert service.reader_update_available()  # v1 sketch: needs the factory image
    reader.port = None
    assert not service.reader_update_available()
    assert not service.state()["reader"]["can_install"]


# ---------------------------------------------------------------- installing the app


async def test_install_app(tmp_path: Path, gh: FakeGitHub) -> None:
    gh.add_app("0.3.0")
    service, calls = make_service(tmp_path, gh)
    await service.check()
    await service.install("app", "0.3.0")
    [(path, args)] = calls["launched"]
    assert path.read_bytes() == INSTALLER
    assert "/VERYSILENT" in args and "/update=1" in args
    assert service.status == "installing"


async def test_app_install_refused_from_source_and_when_forged(
    tmp_path: Path, gh: FakeGitHub
) -> None:
    gh.add_app("0.3.0")
    gh.add_app("0.4.0", signature=base64.b64encode(b"\0" * 64).decode())
    dev, _ = make_service(tmp_path, gh, frozen=False)
    with pytest.raises(UpdateError) as err:
        await dev.install("app", "0.3.0")
    assert err.value.code == "dev"

    service, calls = make_service(tmp_path, gh)
    with pytest.raises(UpdateError) as err:
        await service.install("app", "0.4.0")
    assert err.value.code == "bad_signature"
    assert calls["launched"] == [] and service.status == "error"
    with pytest.raises(UpdateError) as err:
        await service.install("app", "9.9.9")
    assert err.value.code == "unknown_version"


# ---------------------------------------------------------------- flashing the reader


async def test_flash_reader_app_image(tmp_path: Path, gh: FakeGitHub) -> None:
    gh.add_reader("1.1.0")
    reader = FakeReader("1.0.0")
    service, calls = make_service(tmp_path, gh, reader)
    await service.install("reader", "1.1.0")
    [args] = calls["flashed"]
    assert args[:4] == ["--chip", "esp32", "--port", "COM16"]
    assert args[-3:-1] == ["write-flash", "0x10000"]
    assert args[-1].endswith("nestris-rfid-reader-1.1.0-esp32dev-app.bin")
    assert reader.calls == ["release", "reconnect"]
    assert service.status == "done" and service.status_detail == "1.1.0"
    assert not Path(args[-1]).exists()  # image removed after a good flash
    assert not service.reader_update_available()


async def test_flash_factory_image_for_old_readers(tmp_path: Path, gh: FakeGitHub) -> None:
    gh.add_reader("1.1.0")
    reader = FakeReader(fw=None)
    reader.old_protocol = True
    service, calls = make_service(tmp_path, gh, reader)
    await service.install("reader", "1.1.0", mode="factory")
    assert calls["flashed"][0][-2:] == ["0x0", calls["flashed"][0][-1]]
    assert calls["flashed"][0][-1].endswith("nestris-rfid-reader-1.1.0-esp32dev.bin")


async def test_flash_failures(tmp_path: Path, gh: FakeGitHub) -> None:
    gh.add_reader("1.1.0")
    gh.add_reader("1.2.0", app_offset="0x1000")  # signed, but a bad layout
    reader = FakeReader("1.0.0")
    service, calls = make_service(tmp_path, gh, reader, flash_result=lambda _: 2)
    with pytest.raises(UpdateError) as err:
        await service.install("reader", "1.1.0")
    assert err.value.code == "flash_failed" and "Hard resetting" in err.value.message
    assert reader.calls == ["release", "reconnect"]  # the port is handed back anyway
    with pytest.raises(UpdateError) as err:
        await service.install("reader", "1.2.0")
    assert err.value.code == "bad_manifest"
    assert len(calls["flashed"]) == 1

    # Flashed, but the reader still reports the old firmware.
    service, _ = make_service(tmp_path, gh, StuckReader("1.0.0"))
    with pytest.raises(UpdateError) as err:
        await service.install("reader", "1.1.0")
    assert err.value.code == "verify_failed"

    no_reader, _ = make_service(tmp_path, gh, FakeReader(port=None))
    with pytest.raises(UpdateError) as err:
        await no_reader.install("reader", "1.1.0")
    assert err.value.code == "no_reader"


class StuckReader(FakeReader):
    """Flashing "works", but the reader comes back with its old firmware."""

    async def reconnect(self) -> None:
        self.calls.append("reconnect")


async def test_tampered_image_is_not_flashed(tmp_path: Path, gh: FakeGitHub) -> None:
    gh.add_reader("1.1.0")
    url = next(u for u in gh.files if u.endswith("-app.bin"))
    gh.files[url] = b"evil" + gh.files[url]
    service, calls = make_service(tmp_path, gh)
    with pytest.raises(UpdateError) as err:
        await service.install("reader", "1.1.0")
    assert err.value.code == "bad_checksum"
    assert calls["flashed"] == []


# ---------------------------------------------------------------- bridge


async def test_update_endpoints(tmp_path: Path, gh: FakeGitHub) -> None:
    gh.add_app("0.2.0")
    gh.add_reader("1.0.0")
    settings = load_settings(tmp_path / "config.toml", data_dir=tmp_path, rfid={"driver": "fake"})
    runtime = Runtime(settings)
    transport = httpx.MockTransport(gh)
    runtime.updates.targets["app"].github = GitHubReleases(
        "oe7set", "nestris-terminal", transport=transport
    )
    runtime.updates.targets["reader"].github = GitHubReleases(
        "oe7set", "nestris-rfid-reader", transport=transport
    )
    runtime.updates.public_keys = (PUBLIC,)
    asgi = httpx.ASGITransport(app=create_app(runtime))
    async with httpx.AsyncClient(transport=asgi, base_url="http://127.0.0.1") as client:
        assert (await client.get("/local/admin/updates")).status_code == 401
        token = (await client.post("/local/admin/unlock", json={"pin": "2580"})).json()["token"]
        h = {"X-Admin-Token": token}
        state = (await client.post("/local/admin/updates/check", headers=h)).json()
        assert state["app"]["latest"]["version"] == "0.2.0"
        assert state["reader"]["fake"] and not state["reader"]["can_install"]
        r = await client.post(
            "/local/admin/updates/install", headers=h, json={"target": "reader", "version": "1.0.0"}
        )
        assert r.status_code == 409 and r.json()["detail"]["code"] == "fake_reader"
        r = await client.get("/local/admin/updates/releases?target=reader", headers=h)
        assert [x["version"] for x in r.json()] == ["1.0.0"]
        r = await client.put("/local/admin/updates/settings", headers=h, json={"channel": "beta"})
        assert r.json()["channel"] == "beta"
    assert 'channel = "beta"' in (tmp_path / "config.toml").read_text(encoding="utf-8")
    await runtime.updates.close()
    await runtime.host.close()


def test_esptool_error_message() -> None:
    boxed = (
        "esptool v5.4.0\nConnecting......\n"
        "┌─ Error ──────────┐\n"
        "│ Failed to connect to ESP32: No serial data received. │\n"
        "└──────────────────┘\n"
    )
    assert esptool_error(boxed) == "Failed to connect to ESP32: No serial data received."
    assert esptool_error("a\nb\nc") == "b c"
