#!/usr/bin/env bash
#
# Clean-slate: menu, cache/state. Best-effort Default reset (remove vt.default_*
# drop-in; sudo; floating terminal if password needed). Dismiss the prompt and
# TTY paint stays — prepare with `omavt set default` before remove.
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

# Best-effort Default reset (sudo). Prefer immediate; else one floating
# terminal so vt.default_* actually go away before the plugin disappears.
if "$here/bin/omavt" set default --quiet 2>/dev/null; then
  note "removed omavt vt colour drop-in (Default)"
elif sudo -n "$here/bin/omavt" set default --quiet 2>/dev/null; then
  note "removed omavt vt colour drop-in (Default)"
elif command -v omarchy-launch-floating-terminal-with-presentation >/dev/null 2>&1; then
  note "sudo needed to reset TTY colours — opening a floating terminal"
  omarchy-launch-floating-terminal-with-presentation \
    "$here/bin/omavt set default" >/dev/null 2>&1 || true
  note "if you dismiss that prompt, TTY paint stays — run: $here/bin/omavt set default"
else
  note "vt colour drop-in left in place (sudo needed) — prepare before removal: $here/bin/omavt set default"
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

note "done — no omavt menu left; TTY colours reset to Default when sudo succeeded"
note "plugin files remain at $here until you omit/remove the plugin"
note "optional: omarchy pkg drop python-pillow  # if nothing else needs Pillow"
exit 0
