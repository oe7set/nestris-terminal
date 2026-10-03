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
| 5 taps on the logo + PIN | hidden **config** (host URL, token, reader port, PIN, language, timeouts), **reader** settings (display size, brightness, rotation) and **debug** menu (host REST/WebSocket, reader, network, logs, test card) |

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
  `card {state: present|removed, uid, name, format}`,
  `reader {connected, error, info}`, `reader_info`, `host {reachable}`,
  `config {kiosk}`.
- `--headless` runs only the bridge; open `http://127.0.0.1:7991` in a
  browser for development. A fake reader (`rfid.driver = "fake"`) lets the
  debug menu simulate cards.

## RFID reader (USB, protocol v2)

Firmware: `../nestris-rfid-reader` (ESP32 + RC522 + SSD1306); the contract
is its `docs/PROTOCOL.md`. JSON lines at 115200 baud:

- the reader says `hello` (firmware, serial, display, protocol version) on
  boot and on request; the terminal refuses any `proto` other than 2 and
  shows "Leser-Firmware veraltet" (the v1 sketch never says hello);
- `card` events `present` (uid, name, format: retroverse / legacy / blank /
  corrupt / unreadable / unsupported) and `removed` arrive immediately; the
  reader decides when a card is gone (≈ 300 ms);
- a `status` heartbeat every 2 s re-synchronises the card state; 6 s of
  silence makes the serial driver reopen the port;
- commands carry an `id` and get a `result`: `write` (name, optional `uid`
  = only that card, read back and verified by the reader), `show` (lines on
  the OLED, used for "nickname + Bestwert" when the player page opens),
  `config` (display size, language, brightness, rotation; stored in the
  reader), `ping` (every 3 s), `hello`.

Code: `rfid/protocol.py` (messages), `rfid/card.py` (`CardTracker`: state,
link upkeep, commands), `rfid/driver.py` (serial transport and the
`FakeDriver`, a simulated v2 reader for development and tests).

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
