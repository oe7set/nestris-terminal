# Changelog

The section of a version is the text of its GitHub release and what the
built-in updater shows before installing (`.github/scripts/release_notes.py`).

## 0.3.0b2

- **Portrait screens**: the UI also fits a screen turned by 90° (e.g.
  768×1366). The menu puts the highscore above the card prompt, the player
  page its statistics above the games list, the replay its controls below
  the (larger) playfield; the registration, score entry and the hidden menu
  wrap instead of running off the right edge. Landscape is unchanged.
- The status bar shortens a long event name instead of pushing the clock off
  the screen.

## 0.3.0b1

- **Debian**: the terminal also ships as `nestris-terminal_<v>_amd64.deb` for
  Debian 12/13 touch PCs with XFCE (set-up guide `docs/DEBIAN.md`).
  `nestris-terminal autostart on` writes an XDG autostart entry. Updates
  from the hidden menu install the package through a root helper, and the
  kiosk restarts by itself. Reader firmware is flashed with the bundled
  esptool, as on Windows.
- The Updates tab says why an installation cannot update itself.
- New command `nestris-terminal verify-update`.

## 0.2.0

First stable release of the Retroverse Terminal, the touch kiosk next to the
tournament (replaces RetroverseAnmledung). It works with NestrisLTM 0.2.0.

- **Players**: place the card, see the player page (best scores, games of the
  event, replays), sign up with the on-screen keyboard (the name is written
  onto the card and checked), enter scores, browse the highscore.
- **Card reader**: protocol v2 (nestris-rfid-reader 1.0.0): card placed and
  removed by the reader itself, greeting with nickname and best score on its
  display, display settings in the hidden menu.
- **Keyboard**: a plugged-in keyboard works next to the on-screen keyboard.
- **Hidden menu** (5 taps on the logo, PIN): settings, reader, updates, debug.
- **Updates**: the app and the reader firmware from signed GitHub releases;
  the kiosk restarts by itself after an app update, the reader is flashed
  over USB with the bundled esptool.
- Reports its version and the reader firmware to NestrisLTM (page *Geräte*).
