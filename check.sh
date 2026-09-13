#!/usr/bin/env bash
# Lightweight self-check for OmaVT (no sudo, no live limine-entry-tool writes).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fail=0
pass() { printf 'ok  %s\n' "$1"; }
bad()  { printf 'FAIL %s\n' "$1"; fail=1; }

[[ -x $here/bin/omavt ]] || bad "omavt not executable"
[[ -x $here/bin/omavt-switcher ]] || bad "omavt-switcher not executable"
[[ -f $here/manifest.json ]] || bad "manifest.json missing"
[[ -f $here/lib/omavt.py ]] || bad "lib/omavt.py missing"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/themes/fixture" "$tmp/state" "$tmp/cache" \
  "$tmp/.config/omarchy/themes" "$tmp/.config/omarchy/extensions" \
  "$tmp/.local/state/omarchy/current" \
  "$tmp/limine-entry-tool.d" \
  "$tmp/etc-default"

# Fake /etc/default/limine with custom iommu parms — must never be opened/changed.
cat >"$tmp/etc-default/limine" <<'EOF'
ESP_PATH="/boot"

KERNEL_CMDLINE[default]+="root=PARTUUID=deadbeef zswap.enabled=0 rootflags=subvol=@ rw rootfstype=btrfs intel_iommu=on iommu=pt video=efifb:off"
EOF
cp "$tmp/etc-default/limine" "$tmp/etc-default/limine.orig"

# Fake omarchy-defaults — also must stay untouched when picking Default.
cat >"$tmp/limine-entry-tool.d/omarchy-defaults.conf" <<'EOF'
TARGET_OS_NAME="Omarchy"
KERNEL_CMDLINE[default]+=" quiet splash loglevel=0 systemd.show_status=false rd.udev.log_level=0 vt.global_cursor_default=0"
KERNEL_CMDLINE[default]+=" initramfs_async=0"
EOF
cp "$tmp/limine-entry-tool.d/omarchy-defaults.conf" "$tmp/omarchy-defaults.orig"

cat >"$tmp/themes/fixture/colors.toml" <<'EOF'
mode = "dark"
accent = "#FF3D9A"
background = "#0B0618"
foreground = "#F2E8FF"
dark_background = "#070412"
darker_background = "#04020C"
lighter_background = "#1A1030"
muted = "#5A4A78"
selection = "#2A1848"
red = "#FF3355"
green = "#3DFF9A"
yellow = "#FFD400"
blue = "#5B7CFF"
magenta = "#FF3D9A"
cyan = "#00E8FF"
EOF

# Tiny unlock.png so mockup paste path is exercised (1x1 PNG).
python3 - <<PY
from PIL import Image
Image.new("RGBA", (64, 32), (255, 61, 154, 200)).save("$tmp/themes/fixture/unlock.png")
PY

ln -s "$tmp/themes/fixture" "$tmp/.config/omarchy/themes/fixture"
printf 'fixture\n' >"$tmp/.local/state/omarchy/current/theme.name"

export OMAVT_HOME="$tmp"
export OMAVT_PLUGIN_DIR="$here"
export OMARCHY_PATH="$tmp"
export OMAVT_STATE_DIR="$tmp/state"
export OMAVT_CACHE_DIR="$tmp/cache"
export OMAVT_DROPIN="$tmp/limine-entry-tool.d/omavt-colors.conf"
export OMAVT_SKIP_LIMINE=1
export OMAVT_SKIP_SETVTRGB=1

if "$here/bin/omavt" list | grep -qx default; then
  pass "list includes default"
else
  bad "list includes default"
fi

if "$here/bin/omavt" list | grep -qx fixture; then
  pass "list discovers fixture"
else
  bad "list discovers fixture"
fi

if "$here/bin/omavt" set fixture --quiet; then
  pass "set fixture"
else
  bad "set fixture"
fi

[[ -f $tmp/limine-entry-tool.d/omavt-colors.conf ]] && pass "drop-in written" || bad "drop-in written"
grep -q '# omavt:start' "$tmp/limine-entry-tool.d/omavt-colors.conf" && pass "managed start" || bad "managed start"
grep -q '# omavt:end' "$tmp/limine-entry-tool.d/omavt-colors.conf" && pass "managed end" || bad "managed end"
grep -q 'theme: fixture' "$tmp/limine-entry-tool.d/omavt-colors.conf" && pass "theme tag" || bad "theme tag"
grep -q 'vt.default_red=' "$tmp/limine-entry-tool.d/omavt-colors.conf" && pass "vt.default_red" || bad "vt.default_red"
grep -q 'vt.default_grn=' "$tmp/limine-entry-tool.d/omavt-colors.conf" && pass "vt.default_grn" || bad "vt.default_grn"
grep -q 'vt.default_blu=' "$tmp/limine-entry-tool.d/omavt-colors.conf" && pass "vt.default_blu" || bad "vt.default_blu"
grep -q 'vt.color=0x07' "$tmp/limine-entry-tool.d/omavt-colors.conf" && pass "vt.color" || bad "vt.color"
# darker_background #04020C → 4,2,12 as colour 0
grep -q 'vt.default_red=4,' "$tmp/limine-entry-tool.d/omavt-colors.conf" && pass "red channel starts 4" || bad "red channel starts 4"

# Custom / Omarchy stock files must be byte-identical after set.
cmp -s "$tmp/etc-default/limine" "$tmp/etc-default/limine.orig" && pass "etc/default/limine untouched" || bad "etc/default/limine untouched"
cmp -s "$tmp/limine-entry-tool.d/omarchy-defaults.conf" "$tmp/omarchy-defaults.orig" && pass "omarchy-defaults untouched" || bad "omarchy-defaults untouched"

[[ "$(cat "$tmp/state/current")" == "fixture" ]] && pass "state current" || bad "state current"

# Re-set replaces the one drop-in.
"$here/bin/omavt" set fixture --quiet
blocks=$(grep -c '# omavt:start' "$tmp/limine-entry-tool.d/omavt-colors.conf" || true)
[[ $blocks -eq 1 ]] && pass "single block after re-set" || bad "single block after re-set"

# Default removes only the colour drop-in.
if "$here/bin/omavt" set default --quiet; then
  pass "set default"
else
  bad "set default"
fi
[[ ! -e $tmp/limine-entry-tool.d/omavt-colors.conf ]] && pass "drop-in removed" || bad "drop-in removed"
cmp -s "$tmp/etc-default/limine" "$tmp/etc-default/limine.orig" && pass "iommu parms still intact" || bad "iommu parms still intact"
cmp -s "$tmp/limine-entry-tool.d/omarchy-defaults.conf" "$tmp/omarchy-defaults.orig" && pass "defaults not restored/rewritten" || bad "defaults not restored/rewritten"
[[ "$(cat "$tmp/state/current")" == "default" ]] && pass "state default" || bad "state default"

if "$here/bin/omavt" preview fixture >/dev/null; then
  [[ -f $tmp/cache/previews/fixture.png ]] && pass "preview png" || bad "preview png"
else
  bad "preview fixture"
fi

if "$here/bin/omavt" preview default >/dev/null; then
  [[ -f $tmp/cache/previews/default.png ]] && pass "default preview png" || bad "default preview png"
else
  bad "preview default"
fi

"$here/bin/omavt" install-menu >/dev/null
grep -q 'style.tty-theme' "$tmp/.config/omarchy/extensions/omarchy-menu.jsonc" && pass "menu entry" || bad "menu entry"
grep -q 'TTY Themes' "$tmp/.config/omarchy/extensions/omarchy-menu.jsonc" && pass "menu label" || bad "menu label"

if command -v omarchy >/dev/null 2>&1; then
  if omarchy plugin validate "$here" >/dev/null 2>&1; then
    pass "omarchy plugin validate"
  else
    bad "omarchy plugin validate"
  fi
fi

if (( fail )); then
  echo "omavt check: FAILED"
  exit 1
fi
echo "omavt check: all good"
exit 0
