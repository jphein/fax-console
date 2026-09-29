#!/usr/bin/env bash
# Build the pitch deck and the fax test page with headless Chrome or Chromium.
#   docs/deck/build.sh          docs/deck.pdf in the dark theme
#   docs/deck/build.sh light    docs/deck.pdf in the light theme
# Slots still empty in slots.json render as dashed placeholders; fill.py lists them.
set -euo pipefail
root=$(git rev-parse --show-toplevel)
theme=${1:-dark}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
chrome=$(command -v google-chrome || command -v google-chrome-stable || command -v chromium || command -v chromium-browser || true)
[ -n "$chrome" ] || { echo "build.sh: needs google-chrome or chromium" >&2; exit 1; }

python3 "$root/docs/deck/fill.py" "$root/docs/deck/slots.json" "$root/docs/deck/deck.html" "$work/deck.html"
print_pdf() {
  "$chrome" --headless=new --disable-gpu --hide-scrollbars --no-first-run --no-default-browser-check \
    --user-data-dir="$work/profile" --no-pdf-header-footer --virtual-time-budget=4000 \
    --print-to-pdf="$1" "$2" 2>/dev/null
}
print_pdf "$root/docs/deck.pdf" "file://$work/deck.html?theme=$theme"
print_pdf "$root/demo/test-page.pdf" "file://$root/demo/test-page.html"
if command -v pdfinfo >/dev/null; then
  for f in docs/deck.pdf demo/test-page.pdf; do
    printf '%s: %s page(s)\n' "$f" "$(pdfinfo "$root/$f" | awk '/^Pages/{print $2}')"
  done
fi
