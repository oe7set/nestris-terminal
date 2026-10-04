# CLAUDE.md

Guidance for Claude Code (and other contributors) working in this repository.

## What this is

**nestris-terminal** ("Retroverse Terminal") is the player terminal of the
Retroverse Tetris tournament: a touch PC without keyboard plus a USB RFID
reader. Players register, see their statistics and replays, enter scores,
and browse the highscore. It is a client of **NestrisLTM**
(`../nestris-ltm`, the host app) and replaces `../RetroverseAnmledung`.

Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) first: screens, process
layout, RFID protocol, the NestrisLTM terminal API and the phase plan.

## Commands

```powershell
uv sync
uv run pytest                          # tests (fake reader, stub host; no hardware needed)
uv run ruff check . ; uv run ruff format . ; uv run mypy
uv run nestris-terminal                # kiosk window (fullscreen)
uv run nestris-terminal --windowed     # kiosk UI in a normal window
uv run nestris-terminal --headless     # bridge only; open http://127.0.0.1:7991
cd frontend; pnpm install; pnpm build  # UI -> src/nestris_terminal/web (git-ignored)
pnpm check; pnpm test; pnpm dev        # svelte-check, vitest, Vite dev server (proxies the bridge)
powershell -ExecutionPolicy Bypass -File packaging\build.ps1   # UI + PyInstaller (+ Inno Setup installer)
```

Packaging: `packaging/nestris-terminal.spec` builds one folder with two
executables, `RetroverseTerminal.exe` (kiosk, no console; autostart target)
and `nestris-terminal.exe` (console CLI: `configure`, `autostart`, `set-pin`,
`--headless`), plus `esptool.exe` (Espressif, GPL-2.0-or-later) as a separate
program for reader updates. Never import `esptool` in `src/`: the updater
(`updates/service.py`) only runs it as a child process. `packaging/installer.iss` asks for host URL + token and calls
`nestris-terminal.exe configure`. Operations guide: `docs/OPERATIONS.md`.

The NestrisLTM side lives in `../nestris-ltm` (`src/nestris_ltm/api/routes_terminal.py`);
run that app (or `uv run nestris-ltm --headless` there) to develop end to end.

## Conventions

- Code comments, docstrings and docs in **English**; the UI is German first,
  English switchable (strings in `frontend/src/lib/i18n.svelte.ts`).
- **Commit messages never mention Claude** (no Co-Authored-By trailer).
- License: Apache-2.0 (`LICENSE`), attribution and third-party material in `NOTICE`.
  New third-party assets (fonts, icons, copied code) get an entry there and keep
  their own license file next to them; LICENSE and NOTICE ship with every build.
- Touch only: no screen may need a physical keyboard. Text input uses the
  built-in on-screen keyboard; numbers use the on-screen number pad. Touch
  targets are at least 56 px.
- The browser never gets the NestrisLTM token: UI -> bridge (`/api/*`) ->
  NestrisLTM (`/api/terminal/v1/*`).
- Privacy on a public screen: only nicknames are shown, a player page closes
  when the card leaves (3 s grace) or after 2 minutes idle.
- The reader speaks protocol v2 (`../nestris-rfid-reader/docs/PROTOCOL.md`,
  the contract): `rfid/protocol.py` parses it, `rfid/card.py` keeps the state
  and sends commands, `rfid/driver.py` is the transport plus `FakeDriver`
  (a simulated v2 reader). Protocol changes start in the reader repository.
- Shared NES rendering, NGF decoding and the replay clock come from
  `../nestris-ltm/frontend/packages/nes` (`@nestris-ltm/nes`, file dependency).
