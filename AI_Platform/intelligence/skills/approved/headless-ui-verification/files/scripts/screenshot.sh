#!/usr/bin/env bash
# Screenshot a local URL with a root-free Chromium.
#   scripts/screenshot.sh <url> <out.png> [width] [height]
# Requires the NSS/NSPR libs unpacked to ~/.local/chromium-libs (see SKILL.md step 1).
set -euo pipefail
URL="${1:?url}"; OUT="${2:?out.png}"; W="${3:-1400}"; H="${4:-3000}"
LIBS="$HOME/.local/chromium-libs/usr/lib/x86_64-linux-gnu"
CH="$(ls -d "$HOME"/.cache/ms-playwright/chromium-*/chrome-linux64/chrome 2>/dev/null | tail -1)"
[ -x "$CH" ] || { echo "no chromium under ~/.cache/ms-playwright" >&2; exit 1; }
LD_LIBRARY_PATH="$LIBS" "$CH" --headless=old --no-sandbox --disable-gpu --no-first-run \
  --disable-dev-shm-usage --hide-scrollbars --virtual-time-budget=3000 \
  --window-size="$W,$H" --screenshot="$OUT" "$URL" >/dev/null 2>&1
ls -la "$OUT"
