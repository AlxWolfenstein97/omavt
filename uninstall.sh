#!/usr/bin/env bash
#
# Remove OmaVT menu wiring. Does not rewrite limine-entry-tool.d — your last
# applied vt.default_* drop-in stays until you pick Default or remove it.
#
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
plugin_id="io.github.alxwolfenstein97.omavt"
state="$HOME/.local/state/omarchy/omavt"
cache="$HOME/.cache/omarchy/omavt"

note() { printf 'omavt: %s\n' "$1"; }

export OMAVT_PLUGIN_DIR="$here"
"$here/bin/omavt" uninstall-menu || true

rm -rf "$state" "$cache"
note "cleared state/cache"

omarchy-shell -q omarchy.menu refresh >/dev/null 2>&1 || true

if command -v omarchy >/dev/null 2>&1; then
  omarchy plugin disable "$plugin_id" >/dev/null 2>&1 || true
fi

note "done — plugin files left at $here; colour drop-in left as last applied"
exit 0
