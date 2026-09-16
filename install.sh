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

# Style extenders all rewrite the same extensions file. Shell-service --quiet
# starts them in parallel — flock so we don't clobber each other's rows, then
# refresh the live menu only when the file actually changed (avoids stacked
# Hypr "zoom strokes" on every boot).
menu_lock="$HOME/.local/state/omarchy/style-extenders/menu.lock"
menu_sha="$HOME/.local/state/omarchy/style-extenders/menu.sha"
menu_file="$HOME/.config/omarchy/extensions/omarchy-menu.jsonc"
mkdir -p "$(dirname "$menu_lock")"
(
  flock 9
  "$here/bin/omavt" install-menu
  if command -v omarchy-shell >/dev/null 2>&1 && [[ -f $menu_file ]]; then
    new_sha=$(sha256sum "$menu_file" 2>/dev/null | awk '{print $1}')
    old_sha=$(cat "$menu_sha" 2>/dev/null || true)
    if [[ -n $new_sha && $new_sha != "$old_sha" ]]; then
      omarchy-shell -q omarchy.menu refresh >/dev/null 2>&1 || true
      printf '%s\n' "$new_sha" >"$menu_sha"
    fi
  fi
) 9>"$menu_lock"
if (( ! quiet )); then
  omarchy-shell -q shell rescanPlugins >/dev/null 2>&1 || true
fi

if (( ! quiet )); then
  (
    "$here/bin/omavt" preview >/dev/null 2>&1 || true
  ) &
fi

if command -v omarchy >/dev/null 2>&1; then
  omarchy plugin enable "$plugin_id" >/dev/null 2>&1 || true
fi

note "done — Style > TTY Themes, or '$here/bin/omavt switcher'"
note "applying prompts for sudo in a floating terminal (not tied to theme set)"
exit 0
