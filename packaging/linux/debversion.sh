#!/bin/sh
# PEP 440 / semver version -> Debian package version, so that dpkg sorts
# pre-releases before the release:
#   0.3.0 -> 0.3.0   0.3.0b1 -> 0.3.0~b1   0.3.0rc2 -> 0.3.0~rc2
#   0.3.0-rc.1 -> 0.3.0~rc1   0.3.0-beta.1 -> 0.3.0~beta1
set -eu
printf '%s\n' "$1" | sed -E \
    -e 's/-?(a|alpha|b|beta|c|rc|pre)\.?([0-9]+)$/~\1\2/' \
    -e 's/-/~/g'
