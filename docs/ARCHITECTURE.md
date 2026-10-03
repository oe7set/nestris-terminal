# nestris-terminal: architecture and plan

**Retroverse Terminal** is the player terminal of the Retroverse Classic
Tetris tournament: a touch PC (no keyboard) with an RFID card reader on USB.
It replaces the old `RetroverseAnmledung` and talks to the host application
**NestrisLTM** (`../nestris-ltm`) over its REST API; it never touches the
database itself.

## What a player can do

| Situation | Screen |
|---|---|
| No card on the reader | **Main menu** (attract mode): highscore of the active event, replays of other players' games, button *Neu anmelden* |
| A known card is placed | **Player page**: own statistics over all games ever, history per event, current event (rank, best, gap to the next place), own recorded games with replay, *Score eintragen* |
| A blank card is placed (no name, unknown uid) | **Registration**, card already known to the flow |
| A card with a name but unknown uid (old card) | resolved by name: player page, uid gets linked |
| *Neu anmelden* without a card | guided registration: data → *Karte auflegen* → write → *Karte bitte entnehmen* → done |
| Card removed | player page closes after a 3 s grace period; also after 2 minutes without a touch |
| 5 taps on the logo + PIN | hidden **config** (host URL, token, reader port, reader Wi-Fi, PIN, language, timeouts) and **debug** menu (host REST/WebSocket, reader, network, logs, test card) |

Registration asks for nickname (required, unique), first and last name and
e-mail (optional) with a consent checkbox for the e-mail. Only the nickname
is ever shown publicly on the terminal.

Self-entered scores (forgot the card, or just because) count immediately
and are marked `self_reported` in NestrisLTM, so the crew sees and can hide
them.

## Process layout

```
┌──────────────────────── touch PC ────────────────────────┐
│ PySide6 kiosk window (fullscreen, QWebEngineView)        │
│      │ http://127.0.0.1:7991  (UI + /local/* + /ws)       │
│      ▼                                                    │
│ local bridge (FastAPI, asyncio)                           │
│   ├─ RFID driver ── USB serial ── ESP32 reader            │
│   ├─ host client ── REST ──────────► NestrisLTM :7990     │
│   ├─ config store (%APPDATA%\NestrisTerminal\config.toml) │
│   └─ static Svelte UI (frontend/, built into the package) │
└───────────────────────────────────────────────────────────┘
```

- The browser never sees the API token: the UI calls the bridge
  (`/api/...`), the bridge forwards to NestrisLTM's terminal API with the
  token (`/api/terminal/v1/...`).
- Card events reach the UI over the bridge WebSocket (`/ws`):
  `card_present {uid, name}`, `card_removed`, `reader {connected}`,
  `write_result {ok, detail}`, `host {reachable}`.
- `--headless` runs only the bridge; open `http://127.0.0.1:7991` in a
  browser for development. A fake reader (`rfid.driver = "fake"`) lets the
  debug menu simulate cards.

## RFID reader (USB, current firmware)

Firmware: `../RFID_ESP/ESP32_CARD_READER` (ESP32 + RC522 + SSD1306), 115200
baud, JSON lines. The reader prints
`{"type":"login","username":..,"uid":..}` every 750 ms; no card =
`username "Unbekannt"` without uid. Commands:

- `{"type":"setname","value":"Nick"}` writes the name to the **next** card
  read. Success is verified by reading the card back (the next login line
  carries the new name); a timeout or a `Write failed` line is an error.
- `{"type":"highscore","value":"159867"}` shows a score on the OLED.
- `{"type":"config","ip":..,"port":..,"device":..,"ssid":..,"password":..}`
  stores the reader's Wi-Fi settings (config menu).

Presence: a card counts as removed when no line with its uid arrived for
`rfid.removed_after_s` (default 2 s). The driver sits behind a small
interface (`rfid/driver.py`) so the planned new reader firmware only needs
a new driver.

## NestrisLTM terminal API (`/api/terminal/v1`, token scope `terminal`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/card/{uid}?name=` | who owns this card: `known`, `name_match` (old card) or `unknown` |
| POST | `/card/{uid}/link` | link a card uid to a player (old card with a name) |
| GET | `/nickname?value=` | availability check while typing |
| POST | `/players` | register: nickname, first/last name, e-mail, consent, card uid |
| GET | `/players/{id}` | profile: all-time stats, per-event history, current event standing, games |
| POST | `/players/{id}/games` | self-reported score (counts, flagged `self_reported`) |
| GET | `/highscore` | active event leaderboard incl. the best game id per player |
| GET | `/games/{id}/recording` | NGF for replays (also public in NestrisLTM) |
| GET | `/ping` | reachability + server version for the debug menu |

## Repository layout

```
pyproject.toml, uv.lock, README.md, CLAUDE.md, config.example.toml
src/nestris_terminal/
  __main__.py      CLI (kiosk | --headless | --windowed | set-pin)
  config.py        settings (TOML + env NESTRIS_TERMINAL__*), save from the config menu
  rfid/            driver interface, serial driver (ESP32 JSON), fake driver, card state machine
  host/client.py   NestrisLTM terminal API client (httpx, token)
  bridge/          FastAPI app: static UI, /api proxy, /local config/debug, /ws events
  shell/           PySide6 kiosk window (fullscreen, no context menu/zoom), single instance
  web/             built UI (git-ignored, `pnpm build` in frontend/)
frontend/          Svelte 5 + TypeScript (Vite); uses ../nestris-ltm/frontend/packages/nes
tests/
```

## Phases

1. Plan, repository, NestrisLTM terminal API (+ tests). **Done.**
2. Terminal core: config, RFID drivers + card state machine, host client,
   bridge, kiosk shell (+ tests with the fake reader and a stub host). **Done.**
3. UI: main menu with highscore and replays, player page, registration
   wizard with on-screen keyboard, score entry, hidden config/debug menus.
   **Done** (verified end to end against a dev NestrisLTM with the fake reader).
   UI layout: `frontend/src/lib/flow.svelte.ts` is the screen state machine
   (cards + idle timeout), `screens/` holds one component per screen,
   `components/Keyboard.svelte` + `TextField.svelte` replace the OS keyboard.
4. Packaging (PyInstaller, autostart) and the operations guide. **Done**
   (`packaging/`, `docs/OPERATIONS.md`).
