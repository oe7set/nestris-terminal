#!/usr/bin/env bash
# Builds the Retroverse Terminal Debian package:
#   1. the touch UI (frontend/ -> src/nestris_terminal/web)
#   2. the PyInstaller folder dist/RetroverseTerminal (packaging/nestris-terminal.spec)
#   3. dist/nestris-terminal_<version>_<arch>.deb
#
# Run from the repository root on Debian 12 or newer (the release builds on
# Debian 12, so the package also runs on Debian 13). Needs uv, pnpm + Node 22
# (unless --skip-ui), binutils and dpkg-deb. The UI needs the NestrisLTM
# repository next to this one (../nestris-ltm, see .github/workflows/ci.yml).
#
#   packaging/linux/build-deb.sh [--skip-ui]
#
# The file name keeps the PEP 440 version (nestris-terminal_0.3.0b1_amd64.deb,
# what the updater looks for); the package version inside uses "~" so that
# dpkg sorts pre-releases before the release (0.3.0~b1 < 0.3.0).
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
cd "$ROOT"
HERE=packaging/linux
SKIP_UI=0
[ "${1:-}" = "--skip-ui" ] && SKIP_UI=1

VERSION=$(sed -n 's/^version *= *"\([^"]*\)".*/\1/p' pyproject.toml | head -n 1)
[ -n "$VERSION" ] || { echo "no version in pyproject.toml" >&2; exit 1; }
DEBVERSION=$(sh "$HERE/debversion.sh" "$VERSION")
ARCH=$(dpkg --print-architecture)
DEB="dist/nestris-terminal_${VERSION}_${ARCH}.deb"
echo "Retroverse Terminal $VERSION (Debian $DEBVERSION, $ARCH)"

if [ "$SKIP_UI" = 0 ]; then
    (cd frontend && pnpm install --frozen-lockfile && pnpm build)
fi

uv sync --locked --group packaging
uv run --group packaging pyinstaller --noconfirm --clean --distpath dist --workpath build \
    packaging/nestris-terminal.spec

APP=dist/RetroverseTerminal
# Apache-2.0: LICENSE and NOTICE travel with every distribution.
cp LICENSE NOTICE "$APP/"
# Smoke test: the CLI must start and find its bundled files.
"$APP/nestris-terminal" --version

# ------------------------------------------------------------ package tree
PKG=build/deb/nestris-terminal
rm -rf "$PKG"
install -d "$PKG/DEBIAN" "$PKG/opt" "$PKG/usr/bin" "$PKG/usr/lib/nestris-terminal" \
    "$PKG/lib/systemd/system" "$PKG/usr/share/applications" \
    "$PKG/usr/share/icons/hicolor/256x256/apps" "$PKG/usr/share/doc/nestris-terminal"

cp -a "$APP" "$PKG/opt/nestris-terminal"
ln -s /opt/nestris-terminal/nestris-terminal "$PKG/usr/bin/nestris-terminal"
install -m 0755 "$HERE/update-helper" "$PKG/usr/lib/nestris-terminal/update-helper"
install -m 0644 "$HERE/nestris-terminal-update.path" "$HERE/nestris-terminal-update.service" \
    "$PKG/lib/systemd/system/"
install -m 0644 "$HERE/retroverse-terminal.desktop" "$PKG/usr/share/applications/"
install -m 0644 "$HERE/retroverse-terminal.png" "$PKG/usr/share/icons/hicolor/256x256/apps/"
{
    echo "Retroverse Terminal - https://github.com/oe7set/nestris-terminal"
    echo "License: Apache-2.0 (below), third-party material: NOTICE (below)."
    echo "Bundled programs keep their own licenses under /opt/nestris-terminal/_internal/licenses/"
    echo "(esptool: GPL-2.0-or-later)."
    echo
    cat LICENSE
    echo
    cat NOTICE
} > "$PKG/usr/share/doc/nestris-terminal/copyright"
chmod 0644 "$PKG/usr/share/doc/nestris-terminal/copyright"

for script in postinst prerm postrm; do
    install -m 0755 "$HERE/debian/$script" "$PKG/DEBIAN/$script"
done
SIZE=$(du -sk --exclude=DEBIAN "$PKG" | cut -f1)
sed -e "s/@VERSION@/$DEBVERSION/" -e "s/@ARCH@/$ARCH/" -e "s/@SIZE@/$SIZE/" \
    "$HERE/debian/control.in" > "$PKG/DEBIAN/control"

# Files are owned by root in the package whoever builds it.
dpkg-deb --root-owner-group -Zxz --build "$PKG" "$DEB"
dpkg-deb --info "$DEB" | sed -n '1,20p'
echo "Package: $DEB"
