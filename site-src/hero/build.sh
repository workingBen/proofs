#!/bin/bash
# Builds the README hero: assets/hero.gif (light) and assets/hero-dark.gif.
#
#   site-src/hero/build.sh [frames-dir]
#
# Steps stage.html frame by frame in Chromium (record.cjs; needs Playwright,
# PLAYWRIGHT=/path/to/playwright if node can't find it) and encodes each theme
# with ffmpeg at 960 px, 12 fps, one palette per loop. Rerun after editing
# stage.html or the images in img/. Preview one moment: open stage.html?t=7.2
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
WORK="${1:-$(mktemp -d)}"
for theme in light dark; do
  out="$WORK/$theme"; rm -rf "$out"; mkdir -p "$out"
  q=""; [ "$theme" = dark ] && q="&theme=dark"
  # record.cjs appends ?record=1; the stage reads theme from the query string
  STAGE_QUERY="$q" node "$HERE/record.cjs" "$HERE/stage.html" "$out" --fps 12
  name=hero; [ "$theme" = dark ] && name=hero-dark
  ffmpeg -loglevel error -y -framerate 12 -i "$out/f%04d.png" \
    -vf "scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=200:stats_mode=full[p];[b][p]paletteuse=dither=sierra2_4a" \
    -loop 0 "$ROOT/assets/$name.gif"
  rm -rf "$out"
  ls -la "$ROOT/assets/$name.gif"
done
