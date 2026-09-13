#!/usr/bin/env bash
#
# OmaVT installer. Safe to re-run: rewrites the Style menu row it owns.
# Does NOT touch limine-entry-tool drop-ins until you pick a theme (sudo).
# Does NOT install a theme-set hook — applying needs a password.
#
# Flags:
#   --quiet   less chatter (used by the shell service on startup)
#
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
quiet=0
for arg in "$@"; do
  case $arg in
    --quiet) quiet=1 ;;
  esac
done

note() { (( quiet )) || printf 'omavt: %s\n' "$1"; }

plugin_id="io.github.alxwolfenstein97.omavt"
state="$HOME/.local/state/omarchy/omavt"

mkdir -p "$state"

chmod 755 "$here"/bin/* "$here/check.sh" \
  "$here/install.sh" "$here/uninstall.sh" 2>/dev/null || true

export OMAVT_PLUGIN_DIR="$here"

"$here/bin/omavt" install-menu
omarchy-shell -q omarchy.menu refresh >/dev/null 2>&1 || true
omarchy-shell -q shell rescanPlugins >/dev/null 2>&1 || true

# Warm mockups in the background so Style > TTY Themes opens quickly.
(
  "$here/bin/omavt" preview >/dev/null 2>&1 || true
) &

if command -v omarchy >/dev/null 2>&1; then
  omarchy plugin enable "$plugin_id" >/dev/null 2>&1 || true
fi

note "done — Style > TTY Themes, or '$here/bin/omavt switcher'"
note "applying prompts for sudo in a floating terminal (not tied to theme set)"
exit 0
