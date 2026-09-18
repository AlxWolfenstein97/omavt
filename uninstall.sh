#!/usr/bin/env bash
#
# Menu + cache/state. Opens a floating terminal to run Default (remove
# vt.default_* drop-in, sudo) — we clean up our extra TTY paint. Optional y/N
# pkg drop in the same floater. Omarchy's plugin remove does not run this
# script (dir delete only).
#
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
plugin_id="io.github.alxwolfenstein97.omavt"
state="$HOME/.local/state/omarchy/omavt"
cache="$HOME/.cache/omarchy/omavt"
menu_lock="$HOME/.local/state/omarchy/style-extenders/menu.lock"

note() { printf 'omavt: %s\n' "$1"; }

launch_cleanup_floater() {
  local -a have=()
  local pkg
  for pkg in "$@"; do
    pacman -Q "$pkg" &>/dev/null && have+=("$pkg")
  done
  local list="${have[*]}"
  local script="$state/uninstall-floater.sh"
  mkdir -p "$state"
  {
    printf '%s\n' '#!/usr/bin/env bash' 'set -uo pipefail'
    printf '%s\n' "printf 'OmaVT uninstall — resetting TTY colours to Default (sudo)\\n'"
    printf '%s\n' "if $(printf '%q ' "$here/bin/omavt" set default); then"
    printf '%s\n' "  printf 'vt colour drop-in removed\\n'"
    printf '%s\n' 'else'
    printf '%s\n' "  printf 'Default failed — omavt-colors.conf may still be present\\n' >&2"
    printf '%s\n' 'fi'
    if ((${#have[@]})); then
      printf '%s\n' ''
      printf '%s\n' "printf '\\nOptional: drop shared packages only if nothing else needs them.\\n'"
      printf '%s\n' "read -r -p 'Drop ${list}? [y/N] ' a"
      printf '%s\n' 'case $a in'
      printf '%s\n' "  [yY]|[yY][eE][sS]) omarchy pkg drop ${list} ;;"
      printf '%s\n' "  *) printf 'skipped package drop\\n' ;;"
      printf '%s\n' 'esac'
    fi
  } >"$script"
  chmod 755 "$script"
  if command -v omarchy-launch-floating-terminal-with-presentation >/dev/null 2>&1; then
    note "opening floating terminal to reset TTY paint (+ optional pkg drop)"
    omarchy-launch-floating-terminal-with-presentation "bash $(printf %q "$script")" >/dev/null 2>&1 &
  else
    note "run: $here/bin/omavt set default"
    ((${#have[@]})) && note "optional: omarchy pkg drop $list"
  fi
}

export OMAVT_PLUGIN_DIR="$here"

mkdir -p "$state"
touch "$state/uninstalled"
if command -v omarchy >/dev/null 2>&1; then
  omarchy plugin disable "$plugin_id" >/dev/null 2>&1 || true
fi

mkdir -p "$(dirname "$menu_lock")"
(
  flock 9
  "$here/bin/omavt" uninstall-menu || true
) 9>"$menu_lock"

rm -rf "$cache"
find "$state" -mindepth 1 ! -name uninstalled -delete 2>/dev/null || true
touch "$state/uninstalled"
note "cleared state/cache (tombstone left so quiet install cannot resurrect)"

omarchy-shell -q omarchy.menu refresh >/dev/null 2>&1 || true
omarchy-shell -q shell rescanPlugins >/dev/null 2>&1 || true

launch_cleanup_floater python-pillow

note "done — no omavt menu left; TTY paint reset in floating terminal"
note "plugin files remain at $here until you omit/remove the plugin"
exit 0
