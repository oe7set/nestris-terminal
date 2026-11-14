#!/bin/bash
# CI check of the Debian package in a clean Debian 13 container (no systemd
# there, so the update helper is run by hand):
#   docker run --rm -v "$PWD:/w" -w /w debian:trixie bash packaging/linux/test-package.sh dist/<deb>
set -euo pipefail
DEB="$1"
DATA=tests/data
UPD=/var/lib/nestris-terminal/updates
APP=/opt/nestris-terminal
CLI=$APP/nestris-terminal

fail() { echo "FAIL: $*"; exit 1; }
result_has() { grep -q "$1" "$UPD/result" || { cat "$UPD/result"; fail "result lacks $1"; }; }

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
# xvfb: a virtual X server, so the kiosk runs on the real xcb platform plugin
# (as under XFCE); mesa renders without a GPU.
apt-get install -y -qq "./$DEB" curl procps xvfb xauth libgl1-mesa-dri libglx-mesa0 libegl-mesa0 > /tmp/apt.log 2>&1 || { tail -n 30 /tmp/apt.log; fail "install"; }

echo "== files, units, group"
test -x $APP/RetroverseTerminal || fail "kiosk binary missing"
test -x $APP/esptool || fail "esptool missing"
test -f $APP/LICENSE && test -f $APP/NOTICE || fail "LICENSE/NOTICE missing"
test -x /usr/lib/nestris-terminal/update-helper || fail "helper not executable"
test -f /usr/share/applications/retroverse-terminal.desktop || fail "desktop file missing"
for unit in nestris-terminal-update.path nestris-terminal-update.service; do
    ls /lib/systemd/system/$unit /usr/lib/systemd/system/$unit 2>/dev/null | grep -q . || fail "$unit missing"
done
ls /etc/systemd/system/multi-user.target.wants/ | grep -q nestris-terminal-update.path \
    || fail "path unit not enabled"
getent group nestris-terminal > /dev/null || fail "group nestris-terminal missing"
test "$(stat -c '%a %U %G' $UPD)" = "2770 root nestris-terminal" || fail "bad $UPD: $(stat -c '%a %U %G' $UPD)"
nestris-terminal --version
"$APP/esptool" version > /dev/null || fail "esptool does not start"

echo "== shared libraries"
# A library that is neither on the system nor in the bundle; libraries that
# only resolve inside the bundle at run time (libpython, Qt) are fine.
missing=$(find $APP -type f \( -name '*.so' -o -name '*.so.*' -o -name QtWebEngineProcess \) \
    -exec ldd {} \; 2>/dev/null | awk '/not found/ {print $1}' | sort -u)
absent=""
for lib in $missing; do
    find $APP -name "$lib" | grep -q . || absent="$absent $lib"
done
[ -z "$absent" ] || fail "system libraries missing (add them to debian/control):$absent"

echo "== kiosk starts (virtual X display, simulated reader)"
useradd -m -G nestris-terminal,dialout kiosk
# The Chromium sandbox needs user namespaces, which containers usually lack.
runuser -u kiosk -- env HOME=/home/kiosk QTWEBENGINE_DISABLE_SANDBOX=1 \
    NESTRIS_TERMINAL__RFID__DRIVER=fake xvfb-run -a -s "-screen 0 1280x800x24" \
    $APP/RetroverseTerminal --windowed > /tmp/kiosk.log 2>&1 &
KIOSK=$!
ok=""
for _ in $(seq 1 40); do
    if curl -fsS http://127.0.0.1:7991/ 2>/dev/null | grep -qi '<html'; then ok=1; break; fi
    kill -0 $KIOSK 2>/dev/null || break
    sleep 0.5
done
sleep 5
kill -0 $KIOSK 2>/dev/null || { tail -n 40 /tmp/kiosk.log; fail "kiosk exited"; }
[ -n "$ok" ] || { tail -n 40 /tmp/kiosk.log; fail "bridge did not serve the UI"; }
pgrep -f QtWebEngineProcess > /dev/null || { tail -n 40 /tmp/kiosk.log; fail "no QtWebEngineProcess"; }
pkill -f "$APP/RetroverseTerminal" || true
wait $KIOSK 2>/dev/null || true
runuser -u kiosk -- env HOME=/home/kiosk $CLI autostart on
grep -q "Exec=$APP/RetroverseTerminal" /home/kiosk/.config/autostart/retroverse-terminal.desktop \
    || fail "autostart entry wrong"

echo "== verify-update with a real signed release"
mkdir -p /tmp/rel
cp "$DATA/reader-v1.0.0-SHA256SUMS.txt" /tmp/rel/SHA256SUMS.txt
cp "$DATA/reader-v1.0.0-SHA256SUMS.txt.sig" /tmp/rel/SHA256SUMS.txt.sig
cp "$DATA/nestris-rfid-reader-1.0.0-manifest.json" /tmp/rel/
$CLI verify-update /tmp/rel nestris-rfid-reader-1.0.0-manifest.json || fail "real file rejected"
echo tampered >> /tmp/rel/nestris-rfid-reader-1.0.0-manifest.json
if $CLI verify-update /tmp/rel nestris-rfid-reader-1.0.0-manifest.json; then fail "tampered file accepted"; fi

echo "== helper: bad request"
echo "deb=../../etc/passwd" > "$UPD/request"
/usr/lib/nestris-terminal/update-helper && fail "bad request accepted"
test ! -e "$UPD/request" || fail "request not removed"
result_has '"ok":false'
result_has 'bad request'

echo "== helper: package without a valid release signature"
DEBNAME=nestris-terminal_9.9.9_amd64.deb
cp "./$DEB" "$UPD/$DEBNAME"
sha256sum "$UPD/$DEBNAME" | sed "s#$UPD/##" > "$UPD/SHA256SUMS.txt"
# A well-formed release signature, but of other data (the reader v1.0.0 list).
cp "$DATA/reader-v1.0.0-SHA256SUMS.txt.sig" "$UPD/SHA256SUMS.txt.sig"
echo "deb=$DEBNAME" > "$UPD/request"
/usr/lib/nestris-terminal/update-helper && fail "unsigned package accepted"
result_has 'verification failed'
test ! -e "$UPD/$DEBNAME" || fail "package left in the kiosk's directory"
test "$(stat -c %G "$UPD/result")" = nestris-terminal || fail "result not in group nestris-terminal"
runuser -u kiosk -- rm "$UPD/result" || fail "kiosk cannot remove the result"

echo "== remove and purge"
apt-get remove -y -qq nestris-terminal > /dev/null
test ! -e $APP/RetroverseTerminal || fail "program left after remove"
apt-get purge -y -qq nestris-terminal > /dev/null
test ! -e /var/lib/nestris-terminal || fail "state left after purge"

echo "OK: package, kiosk start and update helper"
