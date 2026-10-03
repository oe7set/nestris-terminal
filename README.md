# Retroverse Terminal (nestris-terminal)

Touch kiosk for players at the Retroverse Classic Tetris tournament:

- **register** with an RFID card (guided: data → place card → card is
  written → remove card), on-screen keyboard, no physical keyboard needed;
- **player page** when a card is placed: statistics over all games, history
  per event, the current event (rank, best, gap to the next place), own
  games with replay, **enter a score** (counts, flagged for the crew);
- **main menu**: highscore of the running event and replays of other
  players' games;
- hidden **config and debug menu** (5 taps on the logo + PIN).

It is a client of [NestrisLTM](../nestris-ltm) (host app) and replaces
`RetroverseAnmledung`. Design and plan: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Setup on the touch PC

1. NestrisLTM: *Einstellungen → API-Tokens* → create a token with the
   `terminal` scope.
2. Install and start the terminal (`uv sync`, `cd frontend; pnpm install;
   pnpm build`, `uv run nestris-terminal`).
3. Open the hidden menu (tap the logo 5 times, default PIN **2580**), enter
   the host URL (`http://<host-ip>:7990`) and the token, pick the reader
   port, **change the PIN**.

Settings live in `%APPDATA%\NestrisTerminal\config.toml`
(`uv run nestris-terminal config-path`); see
[config.example.toml](config.example.toml).

## Development

```powershell
uv sync
uv run pytest ; uv run ruff check . ; uv run mypy
uv run nestris-terminal --headless      # bridge on http://127.0.0.1:7991, open it in a browser
uv run nestris-terminal --windowed      # kiosk UI in a normal window
cd frontend; pnpm install; pnpm dev     # UI with hot reload on :5175 (proxies the bridge)
```

Without hardware set `rfid.driver = "fake"`; the debug menu can then place
and remove simulated cards.
