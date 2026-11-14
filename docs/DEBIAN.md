# Debian set-up: Retroverse Terminal on a Debian touch PC

How to install and set up the player terminal on a **Debian 13 "trixie"**
x86-64 touch PC (Debian 12 works too) with an XFCE desktop that signs in
automatically and starts the kiosk. Everything after the first start (hidden
menu, checklist, troubleshooting of the reader and the connection) is the
same as on Windows: see [OPERATIONS.md](OPERATIONS.md).

## What you need

- An x86-64 touch PC (1920×1080 recommended; the UI also works on 1280×800),
  network access to the tournament PC running **NestrisLTM**.
- The USB RFID reader (nestris-rfid-reader, protocol v2). Linux has the
  drivers of both USB-serial chips (CP210x, CH340) built in; the reader shows
  up as `/dev/ttyUSB0` and under `/dev/serial/by-id/`.
- An **API token** with the `terminal` scope from NestrisLTM: admin UI →
  *Einstellungen → API-Tokens* → name e.g. `terminal-1`, scope `terminal`.
- A USB stick with the Debian 13 *netinst* image, and for the set-up a
  keyboard (afterwards the terminal needs none).

## 1. Install Debian

Install from the netinst image with these choices:

- **Root password: leave empty.** The first user then gets `sudo`. Name it
  e.g. `admin` (maintenance user).
- Software selection: **Debian desktop environment**, **Xfce** and
  **SSH server**; untick GNOME.
- After the first boot, sign in as `admin` and update:

  ```sh
  sudo apt update && sudo apt full-upgrade
  ```

## 2. Kiosk user with automatic sign-in

The kiosk runs as its own user without `sudo`:

```sh
sudo adduser terminal          # any password; nobody types it at the event
```

LightDM signs it in at boot:

```sh
sudo tee /etc/lightdm/lightdm.conf.d/50-autologin.conf <<'EOF'
[Seat:*]
autologin-user=terminal
autologin-session=xfce
autologin-user-timeout=0
EOF
```

## 3. Install the terminal

Download from the
[latest release](https://github.com/oe7set/nestris-terminal/releases/latest)
`nestris-terminal_<version>_amd64.deb` and `SHA256SUMS.txt`. Check the
download and install it:

```sh
sha256sum -c --ignore-missing SHA256SUMS.txt
sudo apt install ./nestris-terminal_<version>_amd64.deb
sudo usermod -aG dialout,nestris-terminal terminal
```

- `apt` also installs the Qt/Chromium libraries the kiosk needs.
- `dialout` gives the kiosk the card reader; `nestris-terminal` lets it hand
  updates to the root helper (section 8).
- The `SHA256SUMS.txt.sig` signature is what the built-in updater checks.
  For a manual download the checksum against the release page is enough.

## 4. Configure (as the kiosk user)

```sh
sudo -iu terminal
nestris-terminal configure --host http://192.168.1.10:7990 --token <token>
nestris-terminal set-pin            # the PIN of the hidden menu (default 2580)
nestris-terminal autostart on       # ~/.config/autostart/retroverse-terminal.desktop
nestris-terminal config-path        # ~/.local/share/NestrisTerminal/config.toml
exit
```

`configure` also takes `--reader-port`, `--driver serial|fake` and
`--lang de|en`. Everything else is in the hidden menu.

## 5. Make XFCE an appliance

Sign in as `terminal` once with a keyboard (or reboot: the autologin does
it). Then, still as `terminal`, set the following.

**Screen never goes off, nothing locks.** The terminal also asks the
desktop not to blank, but these settings are what counts:

```sh
xfconf-query -c xfce4-power-manager -p /xfce4-power-manager/dpms-enabled -n -t bool -s false
xfconf-query -c xfce4-power-manager -p /xfce4-power-manager/blank-on-ac -n -t int -s 0
xfconf-query -c xfce4-power-manager -p /xfce4-power-manager/inactivity-on-ac -n -t int -s 0
xfconf-query -c xfce4-session -p /general/LockCommand -n -t string -s ""
xfconf-query -c xfce4-screensaver -p /saver/enabled -n -t bool -s false 2>/dev/null || true
xfconf-query -c xfce4-screensaver -p /lock/enabled -n -t bool -s false 2>/dev/null || true
```

As `admin`, remove the lockers Debian may have installed:

```sh
sudo apt purge light-locker xscreensaver
```

**No notifications, no panels.**

- *Settings → Notifications* → *Do not disturb*.
- Right-click each panel → *Panel → Panel Preferences* → *Automatically
  hide the panel: Always*, or delete the panels. The kiosk is full screen and
  stays on top anyway.

**Touch.**

- One display: touch works out of the box.
- With a second screen (e.g. a projector), map the touchscreen to the
  terminal display. Put the command into a second autostart entry:

  ```sh
  xinput list                                # name of the touchscreen
  xrandr                                     # name of the output, e.g. HDMI-1
  xinput map-to-output "<touchscreen name>" HDMI-1
  ```

- Do not enable an on-screen keyboard (`onboard`): the terminal brings its
  own.

**Updates of Debian itself.** Keep `unattended-upgrades` to security updates
(the default). Over the event days you can stop it:

```sh
sudo systemctl disable --now unattended-upgrades
```

The terminal package is not touched by it; it updates through its own menu.

Reboot. The PC signs in as `terminal` and starts the kiosk in full screen.

## 6. Card reader

- Automatic detection (*USB · automatisch*) finds the ESP32 reader by its
  USB IDs.
- With several serial devices attached, pick it in the hidden menu or set
  it once:

  ```sh
  ls -l /dev/serial/by-id/
  sudo -iu terminal nestris-terminal configure --reader-port /dev/serial/by-id/usb-Silicon_Labs_CP2102_..._if00-port0
  ```

- The `/dev/serial/by-id/` name stays the same after re-plugging.
- Optional: a udev rule gives a fixed name and keeps USB autosuspend off.
  Use the template `nestris-core/crates/nestris-station/packaging/99-nestris-station.rules`
  (the `tty` lines). With it the port is `/dev/nestris-rfid`.

## 7. Network and maintenance

- The terminal only connects out to NestrisLTM. Its local bridge listens on
  `127.0.0.1:7991` only, so no firewall rule is needed on this PC.
- Maintenance over SSH as `admin`: `ssh admin@<terminal-ip>`.
- **Leave the kiosk**: hidden menu → *App beenden*. The XFCE desktop of
  `terminal` remains. Start the kiosk again from the menu (*Retroverse
  Terminal*), or sign out and in again.
- See what the kiosk does:

  ```sh
  sudo -iu terminal tail -f ~/.local/share/NestrisTerminal/logs/nestris-terminal.log
  ```

## 8. Updates

Hidden menu → *Updates*, as on Windows ([OPERATIONS.md](OPERATIONS.md#updates)).

**Terminal app.**

1. *Version X installieren* downloads `nestris-terminal_<v>_amd64.deb` and
   checks the Retroverse release signature.
2. The kiosk hands the package to the root helper: it writes into
   `/var/lib/nestris-terminal/updates/`, and the path unit
   `nestris-terminal-update.path` starts `nestris-terminal-update.service`.
3. The helper verifies the package again and installs it with `apt`.
4. The kiosk then restarts itself (about a minute). Settings are kept.

Follow it:

```sh
journalctl -u nestris-terminal-update.service -f
```

The tab tells you if the kiosk user is missing from the group
`nestris-terminal` (section 3; sign in again after `usermod`).

Manual alternative:

```sh
sudo apt install ./nestris-terminal_<version>_amd64.deb
```

Afterwards, restart the kiosk (menu *App beenden*, then start it again, or
reboot).

**Reader firmware**: flashed over USB with the bundled
`/opt/nestris-terminal/esptool`. This needs the group `dialout`.

## 9. Files

| What | Where |
|---|---|
| Program | `/opt/nestris-terminal/` (`RetroverseTerminal`, `nestris-terminal`, `esptool`); `/usr/bin/nestris-terminal` → CLI |
| Configuration | `~terminal/.local/share/NestrisTerminal/config.toml` |
| Logs | `~terminal/.local/share/NestrisTerminal/logs/nestris-terminal.log` |
| Update downloads | `~terminal/.local/share/NestrisTerminal/updates/` |
| Autostart | `~terminal/.config/autostart/retroverse-terminal.desktop` |
| Update hand-over | `/var/lib/nestris-terminal/updates/` (`root:nestris-terminal`, `2770`) |
| Update helper | `/usr/lib/nestris-terminal/update-helper`, units `nestris-terminal-update.{path,service}` |

The config file contains the API token: do not share it.

Remove the program:

- `sudo apt remove nestris-terminal` removes it.
- `sudo apt purge nestris-terminal` also removes `/var/lib/nestris-terminal`.

The kiosk user's settings stay in their home.

## 10. Troubleshooting

| Symptom | Check |
|---|---|
| Kiosk does not start after sign-in | `ls ~terminal/.config/autostart/`; start it by hand in a terminal of the `terminal` desktop: `/opt/nestris-terminal/RetroverseTerminal --windowed` and read the error. |
| `Could not load the Qt platform plugin "xcb"` | A library is missing: `QT_DEBUG_PLUGINS=1 /opt/nestris-terminal/RetroverseTerminal --windowed` names it; `sudo apt install -f`. Running under Wayland instead of XFCE/X11: `QT_QPA_PLATFORM=xcb`. |
| Black or white window, UI never appears | Graphics driver: try `QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu"` (for good: add `Exec=env QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu /opt/nestris-terminal/RetroverseTerminal` in the autostart file). |
| "Kartenleser nicht verbunden", log says `Permission denied` | `id terminal` must list `dialout`; sign in again after `usermod`. |
| Updates tab: "no write access to /var/lib/nestris-terminal/updates" | Group `nestris-terminal` missing for the kiosk user (section 3). |
| Updates tab: "no answer from the update helper" | `systemctl status nestris-terminal-update.path` must be *active (waiting)*: `sudo systemctl enable --now nestris-terminal-update.path`. |
| Update failed | `journalctl -u nestris-terminal-update.service`; the error is also shown in the tab. |
| Screen goes dark after a while | Section 5 (power manager, screensaver). `xset q` shows DPMS and screensaver state. |
| Touch hits the wrong place | Section 5, `xinput map-to-output`. |

## Building the package (developers)

The package is built on Debian 12 so that it runs on Debian 12 and 13.
Requirements:

- the NestrisLTM repository next to this one, for the UI's shared NES
  package (`../nestris-ltm/frontend`: `pnpm install`);
- uv, pnpm with Node 22, `binutils`, and the Qt runtime libraries from
  `packaging/linux/debian/build-libs.txt`.

```sh
bash packaging/linux/build-deb.sh            # -> dist/nestris-terminal_<version>_amd64.deb
bash packaging/linux/test-package.sh dist/nestris-terminal_<version>_amd64.deb   # as root, in a throwaway Debian 13 container
```

The CI does the same (`.github/workflows/deb.yml`: build in
`debian:bookworm`, test in `debian:trixie`). Every release tag publishes the
`.deb` next to the Windows setup, under the same signed `SHA256SUMS.txt`.
