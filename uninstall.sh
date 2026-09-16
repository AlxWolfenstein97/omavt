#!/usr/bin/env bash
#
# Full clean-slate: menu, cache/state, and the vt.default_* limine-entry-tool
# drop-in (same as picking Default). Rebuilds Limine entries when possible.
#
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
plugin_id="io.github.alxwolfenstein97.omavt"
state="$HOME/.local/state/omarchy/omavt"
cache="$HOME/.cache/omarchy/omavt"

note() { printf 'omavt: %s\n' "$1"; }
warn() { printf 'omavt: %s\n' "$1" >&2; }

export OMAVT_PLUGIN_DIR="$here"
"$here/bin/omavt" uninstall-menu || true

# set default → remove_dropin + limine-update (sudo).
if ! "$here/bin/omavt" set default --quiet; then
  warn "could not remove vt colour drop-in (sudo?) — menu/cache still removed"
fi

rm -rf "$state" "$cache"
note "cleared state/cache"

omarchy-shell -q omarchy.menu refresh >/dev/null 2>&1 || true

if command -v omarchy >/dev/null 2>&1; then
  omarchy plugin disable "$plugin_id" >/dev/null 2>&1 || true
fi

note "done — no omavt menu or colour drop-in left"
note "plugin files remain at $here until you omit/remove the plugin"
exit 0
