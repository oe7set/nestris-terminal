# Operations guide: Retroverse Terminal

How to set up, run and troubleshoot the player terminal on the touch PC at
the event. For the design see [ARCHITECTURE.md](ARCHITECTURE.md).

## What you need

- A Windows 10/11 x64 touch PC (1920×1080 recommended; the UI also works on
  1280×800), network access to the tournament PC running **NestrisLTM**.
- The USB RFID reader (ESP32 + RC522, JSON over serial). Windows needs the
  USB-serial driver of the board: **CP210x** (Silicon Labs) or **CH340**
  (WCH). The reader then shows up as `COMx` in the Device Manager.
- An **API token** with the `terminal` scope from NestrisLTM:
  admin UI → *Einstellungen → API-Tokens* → name e.g. `terminal-1`, scope
  `terminal` → *Token erzeugen*. Copy it right away; it is shown only once.

## Install

1. Run `RetroverseTerminal-Setup-<version>.exe` **as the Windows user the
   kiosk runs under** (the setup installs per user and needs no admin rights).
2. On the page *Verbindung zu NestrisLTM* enter
   - the address of the tournament PC, e.g. `http://192.168.1.10:7990`,
   - the API token.

   Both are written to `%APPDATA%\NestrisTerminal\config.toml`. Leave them
   empty on an update to keep the current settings.
3. Keep *Terminal bei der Windows-Anmeldung automatisch starten* checked.
4. Finish; the terminal starts in full screen.

An update is the same setup run again: it stops the running kiosk, replaces
the files and keeps the configuration.

Without the installer (e.g. a copy of `dist\RetroverseTerminal`):

```powershell
nestris-terminal.exe configure --host http://192.168.1.10:7990 --token <token>
nestris-terminal.exe autostart on
RetroverseTerminal.exe
```

## First start checklist

1. The top bar shows the event name and no red warnings. A red pill means:
   *Keine Verbindung zum Turnier-Server* → address/token/firewall;
   *Kartenleser nicht verbunden* → USB cable/driver/port.
2. Open the hidden menu: **tap the RETROVERSE logo 5 times quickly**, enter
   the PIN (default **2580**).
3. *Einstellungen*:
   - **set a new PIN** (the menu warns while the default PIN is active),
   - card reader: *USB · automatisch* finds ESP32 boards by their USB IDs;
     if several serial devices are attached, pick the reader's `COMx`
     (★ marks likely readers),
   - check language, *Vollbild*, *Mauszeiger ausblenden* (recommended on
     the touch PC), timeouts.
4. *Debug* → *Verbindung testen* must answer `OK · … ms`.
5. Place a registered card: the player page must open; remove it: after
   3 s the main menu returns.
6. Sign up a test player with a blank card, then hide or delete that player
   in NestrisLTM.

## Windows set-up for a kiosk PC

The terminal is a normal Windows program in full screen; these settings make
the PC behave like an appliance:

- **Automatic sign-in** of the kiosk user (e.g. Sysinternals *Autologon*, or
  `netplwiz` → untick *Benutzer müssen Benutzernamen und Kennwort eingeben*).
  With autostart on, the terminal starts right after sign-in.
- **Power**: screen and sleep *Nie*; the terminal also keeps the display
  awake while it runs.
- **Notifications**: *Nicht stören* on; Windows Update active hours over the
  event days (or pause updates).
- **Touch edge swipes** (would open the action center over the kiosk):
  Group Policy *Computerkonfiguration → Administrative Vorlagen →
  Windows-Komponenten → Edgeswipe → Edgeswipe zulassen = Deaktiviert*, or
  the registry value `HKLM\SOFTWARE\Policies\Microsoft\Windows\EdgeUI`
  `AllowEdgeSwipe` = `0` (DWORD).
- The Windows touch keyboard never opens: all input uses the terminal's own
  keyboard and number pad.
- **Firewall**: the terminal only makes outgoing connections to NestrisLTM;
  its local bridge listens on `127.0.0.1:7991` only.

## Daily use

- The kiosk cannot be closed with Alt+F4. To leave it (Windows maintenance):
  hidden menu → *App beenden* (tap twice to confirm). Start it again from
  the start menu (*Retroverse Terminal*) or by signing in again.
- *Retroverse Terminal (Fenster)* in the start menu runs the UI in a normal
  window, useful with mouse and keyboard.
- Starting the program a second time only brings the running kiosk to the
  front.

## Hidden menu reference

| Tab | Purpose |
|---|---|
| Einstellungen | NestrisLTM address and token, reader port or simulated reader, language, full screen, cursor, idle timeout (back to the menu), card grace period, new PIN. *Speichern* applies immediately, no restart. |
| Leser-WLAN | Sends Wi-Fi name, password, device name and target IP/port to the reader's flash (for the reader firmware's Wi-Fi mode). Needs the reader connected over USB. |
| Debug | Version, uptime, reader (port, lines received, current and last card), host status and event, token present, IP addresses and Wi-Fi of this PC, live log, *Verbindung testen*, simulated test card (with the simulated reader). |

The menu locks itself again after 15 minutes without use or when it is closed.

## Files

| What | Where |
|---|---|
| Program | `%LOCALAPPDATA%\Programs\Retroverse Terminal` (per-user install) or `C:\Program Files\Retroverse Terminal` |
| Configuration | `%APPDATA%\NestrisTerminal\config.toml` (`nestris-terminal.exe config-path`) |
| Logs | `%APPDATA%\NestrisTerminal\logs\nestris-terminal.log` (rotating, JSON lines) |
| Autostart | `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` → `NestrisTerminal` |

All keys are documented in [config.example.toml](../config.example.toml).
The file contains the API token: do not share it.

## Command line (`nestris-terminal.exe`)

```text
nestris-terminal.exe configure --host URL --token TOKEN [--reader-port COM5] [--driver serial|fake] [--lang de|en]
nestris-terminal.exe autostart on|off|status
nestris-terminal.exe set-pin          # set the hidden-menu PIN (asks for it)
nestris-terminal.exe config-path
nestris-terminal.exe --headless       # bridge only, UI at http://127.0.0.1:7991 in a browser
RetroverseTerminal.exe [--windowed]   # kiosk
```

Forgot the PIN? `nestris-terminal.exe set-pin` (needs a keyboard), or delete
the `pin_hash` line in `config.toml` (the default PIN 2580 applies again).

## Troubleshooting

| Symptom | Check |
|---|---|
| "Keine Verbindung zum Turnier-Server" | NestrisLTM running? Address with port (`http://<ip>:7990`)? Windows firewall on the tournament PC allows the port? Debug → *Verbindung testen*: `401` = wrong token, `403` = token without `terminal` scope. |
| "Kartenleser nicht verbunden" | USB cable, driver (Device Manager → COM port present?), the right port in the settings. Debug → *lines* should grow every second while connected. |
| Card placed, nothing happens | Debug → *Card* must show the UID. If not: card too far from the reader, or a non-MIFARE card. |
| "Die Karte konnte nicht beschrieben werden" | The card was moved during writing; *Nochmal versuchen*. The card is linked to the player anyway, so *Ohne Beschreiben weiter* is fine. |
| Black screen / "Terminal-Kern beendet" | Look at the log file; usually port 7991 is used by another program (`http.port` in the config). |
| Wrong time in the top bar | Windows time/zone of the touch PC. |

## Building (developers)

```powershell
winget install JRSoftware.InnoSetup   # once, for the installer
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

Results: `dist\RetroverseTerminal\` (PyInstaller folder with
`RetroverseTerminal.exe` and `nestris-terminal.exe`) and
`dist\RetroverseTerminal-Setup-<version>.exe`. The version comes from
`pyproject.toml`. `packaging\icon.ico` is generated by
`packaging\make_icon.py`.
