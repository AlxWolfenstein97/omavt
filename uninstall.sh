#!/usr/bin/env bash
#
# Full clean-slate: menu, cache/state, and the vt.default_* limine-entry-tool
# drop-in (same as picking Default). Rebuilds Limine entries when possible.
#
# Clearing the drop-in needs sudo (same class as Style → Unlock themes staying
# until changed). Attempt clear before disable; if non-interactive sudo fails,
# open one floating terminal best-effort.
#
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
plugin_id="io.github.alxwolfenstein97.omavt"
state="$HOME/.local/state/omarchy/omavt"
cache="$HOME/.cache/omarchy/omavt"
menu_lock="$HOME/.local/state/omarchy/style-extenders/menu.lock"

note() { printf 'omavt: %s\n' "$1"; }
warn() { printf 'omavt: %s\n' "$1" >&2; }

export OMAVT_PLUGIN_DIR="$here"
mkdir -p "$(dirname "$menu_lock")"
(
  flock 9
  "$here/bin/omavt" uninstall-menu || true
) 9>"$menu_lock"

# set default → remove_dropin + limine-update (sudo).
if ! "$here/bin/omavt" set default --quiet; then
  warn "could not remove vt colour drop-in (sudo required) — opening floating terminal"
  if command -v omarchy-launch-floating-terminal-with-presentation >/dev/null 2>&1; then
    omarchy-launch-floating-terminal-with-presentation \
      "$here/bin/omavt set default" >/dev/null 2>&1 &
  else
    warn "run: $here/bin/omavt set default"
  fi
fi

rm -rf "$state" "$cache"
mkdir -p "$state"
touch "$state/uninstalled"
note "cleared state/cache (tombstone left so quiet install cannot resurrect)"

omarchy-shell -q omarchy.menu refresh >/dev/null 2>&1 || true

if command -v omarchy >/dev/null 2>&1; then
  omarchy plugin disable "$plugin_id" >/dev/null 2>&1 || true
fi

note "done — no omavt menu or colour drop-in left"
note "plugin files remain at $here until you omit/remove the plugin"
note "optional: omarchy pkg drop python-pillow  # if nothing else needs Pillow"
exit 0
