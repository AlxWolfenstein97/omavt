#!/usr/bin/env bash
#
# Clean-slate: menu, cache/state. Best-effort remove of the vt.default_*
# limine-entry-tool drop-in once (same as picking Default). Same class as
# Style → Unlock themes: paint may stay until you pick Default again — we do
# not open a floating-terminal retry.
#
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
plugin_id="io.github.alxwolfenstein97.omavt"
state="$HOME/.local/state/omarchy/omavt"
cache="$HOME/.cache/omarchy/omavt"
menu_lock="$HOME/.local/state/omarchy/style-extenders/menu.lock"

note() { printf 'omavt: %s\n' "$1"; }

export OMAVT_PLUGIN_DIR="$here"
mkdir -p "$(dirname "$menu_lock")"
(
  flock 9
  "$here/bin/omavt" uninstall-menu || true
) 9>"$menu_lock"

# Best-effort once — no floating-terminal fight if sudo is unavailable.
if ! "$here/bin/omavt" set default --quiet 2>/dev/null; then
  note "vt colour drop-in left in place (sudo needed) — pick Default in Style → TTY Themes or run: $here/bin/omavt set default"
fi

rm -rf "$state" "$cache"
mkdir -p "$state"
touch "$state/uninstalled"
note "cleared state/cache (tombstone left so quiet install cannot resurrect)"

omarchy-shell -q omarchy.menu refresh >/dev/null 2>&1 || true
omarchy-shell -q shell rescanPlugins >/dev/null 2>&1 || true

if command -v omarchy >/dev/null 2>&1; then
  omarchy plugin disable "$plugin_id" >/dev/null 2>&1 || true
fi

note "done — no omavt menu left; TTY paint stays until Default / clear succeeds"
note "plugin files remain at $here until you omit/remove the plugin"
note "optional: omarchy pkg drop python-pillow  # if nothing else needs Pillow"
exit 0
