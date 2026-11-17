#!/usr/bin/env bash
# A headless Chromium in a sandbox that cannot download one.
#
# WHY THIS EXISTS. `npx playwright install` fetches browsers from
# cdn.playwright.dev, which a locked-down sandbox may not be allowed to reach --
# the download stalls and is eventually killed, so `playwright` is installed and
# useless. Debian's package archive IS usually reachable, and there is
# no root here to `apt-get install` with. So: download the package files and their whole
# dependency closure, unpack them into a directory, and point the dynamic linker
# at it. No root, no image change, ~2 minutes the first time.
#
#     source path/to/setup-browser.sh          # sets CHROME_BIN + LD_LIBRARY_PATH
#     "$CHROME_BIN" --headless --no-sandbox --screenshot=out.png URL
#
# Sourcing is deliberate: LD_LIBRARY_PATH has to survive into the caller, and a
# subshell would throw it away. Running it directly still builds the tree and
# prints what to export.
#
# DO NOT PIPE THE SOURCE CALL. `source setup-browser.sh | tail -3` puts it in a
# pipeline, which is a subshell, so the tree gets built and the exports vanish --
# and the failure surfaces later as `timeout: failed to run command ''`, which
# looks like a broken binary rather than a lost variable. Redirect instead:
# `source setup-browser.sh > /dev/null`.
#
# Idempotent -- re-sourcing an existing tree costs one `test -x`.
set -uo pipefail

CHROME_ROOT="${CHROME_ROOT:-${TMPDIR:-/tmp}/pr-qa-chrome}"
CHROME_BIN="$CHROME_ROOT/usr/lib/chromium/chromium-headless-shell"

if [ ! -x "$CHROME_BIN" ]; then
  echo "==> building a headless Chromium in $CHROME_ROOT (first run only)"
  mkdir -p "$CHROME_ROOT/debs"
  (
    cd "$CHROME_ROOT/debs" || exit 1
    # The recurse flags matter: without them apt resolves only the direct
    # depends and the binary dies on the FIRST missing .so, one at a time,
    # which is a very slow way to discover 142 packages.
    pkgs="$(apt-cache depends --recurse --no-recommends --no-suggests \
              --no-conflicts --no-breaks --no-replaces --no-enhances \
              chromium-headless-shell 2>/dev/null | grep '^\w' | sort -u)"
    # shellcheck disable=SC2086
    apt-get download $pkgs >/dev/null 2>&1
    for d in *.d[e]b; do dpkg -x "$d" "$CHROME_ROOT" 2>/dev/null; done
  )
fi

if [ ! -x "$CHROME_BIN" ]; then
  echo "pr-qa: could not build a headless Chromium at $CHROME_BIN" >&2
  echo "       check that Debian's package archive is reachable: apt-get download chromium-headless-shell" >&2
  return 1 2>/dev/null || exit 1
fi

# Every directory holding a .so, not a fixed list. chromium-headless-shell needs
# libraries from at least three trees (usr/lib/x86_64-linux-gnu, usr/lib, and
# usr/lib/x86_64-linux-gnu/pulseaudio) -- libpulsecommon lives one level deeper
# than the rest and is the one a hand-written list always forgets.
CHROME_LIBS="$(find "$CHROME_ROOT" -type d -name '*-linux-gnu' -o -type d -name lib -o -type d -name pulseaudio 2>/dev/null | tr '\n' ':')"
export LD_LIBRARY_PATH="${CHROME_LIBS}${LD_LIBRARY_PATH:-}"
export CHROME_BIN

echo "CHROME_BIN=$CHROME_BIN"
echo "LD_LIBRARY_PATH set (${CHROME_LIBS%%:*}:...)"
