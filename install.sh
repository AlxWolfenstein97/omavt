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
warn() { printf 'omavt: %s\n' "$1" >&2; }

plugin_id="io.github.alxwolfenstein97.omavt"
state="$HOME/.local/state/omarchy/omavt"

mkdir -p "$state"

chmod 755 "$here"/bin/* "$here/check.sh" \
  "$here/install.sh" "$here/uninstall.sh" 2>/dev/null || true

export OMAVT_PLUGIN_DIR="$here"

ensure_pkg() {
  local pkg=$1
  local why=$2
  if pacman -Q "$pkg" &>/dev/null; then
    return 0
  fi
  note "installing $pkg — $why"
  if command -v omarchy >/dev/null 2>&1; then
    omarchy pkg add "$pkg" || warn "could not install $pkg"
  else
    warn "install $pkg manually — $why"
  fi
}

# Pillow draws Style carousel mockups — install before warming previews.
ensure_pkg python-pillow "draws Style → TTY Themes mockups (Pillow)"

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
