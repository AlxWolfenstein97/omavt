#!/usr/bin/env python3
"""OmaVT — Style-menu TTY palettes from any Omarchy theme.

Discovers every theme with a colors.toml (no extra theme assets required),
renders centered VT-session mockups for the Style carousel, and manages only
a limine-entry-tool.d drop-in of vt.default_* / vt.color kernel parameters.
Custom cmdline (iommu, root=, resume=, …) lives elsewhere and is never opened.
Default removes that colour drop-in only — it does not rewrite Omarchy stock
parms. Mockups are illustrative, not WYSIWYG screenshots of a live VT.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

PLUGIN_ID = "io.github.alxwolfenstein97.omavt"
BLOCK_START = "# omavt:start"
BLOCK_END = "# omavt:end"
MENU_START = "  // omavt:start"
MENU_END = "  // omavt:end"
DEFAULT_SLUG = "default"
DROPIN_NAME = "omavt-colors.conf"

HEX_RE = re.compile(r"^#?[0-9A-Fa-f]{6}$")

# Classic VGA console palette — what the kernel uses with no vt.default_*.
VGA_RGB: list[tuple[int, int, int]] = [
    (0, 0, 0),
    (170, 0, 0),
    (0, 170, 0),
    (170, 85, 0),
    (0, 0, 170),
    (170, 0, 170),
    (0, 170, 170),
    (170, 170, 170),
    (85, 85, 85),
    (255, 85, 85),
    (85, 255, 85),
    (255, 255, 85),
    (85, 85, 255),
    (255, 85, 255),
    (85, 255, 255),
    (255, 255, 255),
]


def home() -> Path:
    return Path(os.environ.get("OMAVT_HOME", Path.home())).expanduser()


def omarchy_path() -> Path:
    return Path(os.environ.get("OMARCHY_PATH", "/usr/share/omarchy"))


def plugin_dir() -> Path:
    override = os.environ.get("OMAVT_PLUGIN_DIR")
    if override:
        return Path(override).expanduser()
    return Path(__file__).resolve().parent.parent


def dropin_path() -> Path:
    override = os.environ.get("OMAVT_DROPIN")
    if override:
        return Path(override).expanduser()
    return Path("/etc/limine-entry-tool.d") / DROPIN_NAME


def paths() -> dict[str, Path]:
    h = home()
    return {
        "user_themes": h / ".config/omarchy/themes",
        "stock_themes": omarchy_path() / "themes",
        "state": Path(os.environ.get("OMAVT_STATE_DIR", h / ".local/state/omarchy/omavt")),
        "cache": Path(os.environ.get("OMAVT_CACHE_DIR", h / ".cache/omarchy/omavt")),
        "menu": h / ".config/omarchy/extensions/omarchy-menu.jsonc",
        "current_theme_name": h / ".local/state/omarchy/current/theme.name",
        "dropin": dropin_path(),
    }


def note(msg: str) -> None:
    print(f"omavt: {msg}", file=sys.stderr)


def slugify(name: str) -> str:
    cleaned = re.sub(r"<[^>]+>", "", name or "")
    return cleaned.strip().lower().replace(" ", "-")


def pretty_name(slug: str) -> str:
    if slugify(slug) == DEFAULT_SLUG:
        return "Default"
    return re.sub(
        r"(^|-)([a-z])",
        lambda m: (" " if m.group(1) == "-" else "") + m.group(2).upper(),
        slugify(slug),
    )


def parse_hex(value: str, fallback: str) -> str:
    raw = (value or fallback).strip().strip('"').strip("'")
    if not HEX_RE.match(raw):
        raw = fallback
    if not raw.startswith("#"):
        raw = "#" + raw
    return raw.lower()


def bare_hex(value: str, fallback: str = "000000") -> str:
    return parse_hex(value, fallback).lstrip("#")


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    h = bare_hex(value)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, int(c))) for c in rgb))


def mix(a: str, b: str, t: float) -> str:
    ar, ag, ab = hex_to_rgb(a)
    br, bg, bb = hex_to_rgb(b)
    return rgb_to_hex(
        (
            round(ar + (br - ar) * t),
            round(ag + (bg - ag) * t),
            round(ab + (bb - ab) * t),
        )
    )


def lighten(color: str, amount: float) -> str:
    return mix(color, "#ffffff", amount)


def darken(color: str, amount: float) -> str:
    return mix(color, "#000000", amount)


def read_colors_toml(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            data[key] = value
    return data


def theme_dir(slug: str) -> Path | None:
    slug = slugify(slug)
    if slug == DEFAULT_SLUG:
        return None
    for root in (paths()["user_themes"], paths()["stock_themes"]):
        candidate = root / slug
        if (candidate / "colors.toml").is_file():
            return candidate
    return None


def list_theme_slugs() -> list[str]:
    found: set[str] = set()
    for root in (paths()["user_themes"], paths()["stock_themes"]):
        if not root.is_dir():
            continue
        for entry in root.iterdir():
            if entry.name.startswith("."):
                continue
            if entry.is_dir() or entry.is_symlink():
                if (entry / "colors.toml").is_file():
                    found.add(entry.name)
    return sorted(found)


def list_picker_slugs() -> list[str]:
    return [DEFAULT_SLUG] + list_theme_slugs()


def current_omarchy_slug() -> str | None:
    name_path = paths()["current_theme_name"]
    if name_path.is_file():
        return slugify(name_path.read_text(encoding="utf-8").strip())
    return None


def current_omavt_slug() -> str | None:
    current = paths()["state"] / "current"
    if current.is_file():
        return slugify(current.read_text(encoding="utf-8").strip())
    return None


def ansi16_from_theme(raw: dict[str, str]) -> list[tuple[int, int, int]]:
    """Map colors.toml → the 16 VGA indices the kernel VT palette uses."""
    background = parse_hex(raw.get("background", ""), "#1a1b26")
    dark_background = parse_hex(raw.get("dark_background", ""), darken(background, 0.25))
    darker_background = parse_hex(raw.get("darker_background", ""), darken(background, 0.4))
    foreground = parse_hex(raw.get("foreground", ""), "#a9b1d6")
    bright_foreground = parse_hex(
        raw.get("bright_foreground", raw.get("light_foreground", "")),
        lighten(foreground, 0.15),
    )
    muted = parse_hex(raw.get("muted", ""), lighten(dark_background, 0.3))
    accent = parse_hex(raw.get("accent", raw.get("blue", "")), "#7aa2f7")
    red = parse_hex(raw.get("red", ""), "#f7768e")
    green = parse_hex(raw.get("green", ""), accent)
    yellow = parse_hex(raw.get("yellow", ""), "#e0af68")
    blue = parse_hex(raw.get("blue", ""), accent)
    magenta = parse_hex(raw.get("magenta", ""), "#bb9af7")
    cyan = parse_hex(raw.get("cyan", ""), "#7dcfff")

    bright_red = parse_hex(raw.get("bright_red", ""), lighten(red, 0.12))
    bright_green = parse_hex(raw.get("bright_green", ""), lighten(green, 0.12))
    bright_yellow = parse_hex(raw.get("bright_yellow", ""), lighten(yellow, 0.12))
    bright_blue = parse_hex(raw.get("bright_blue", ""), lighten(blue, 0.12))
    bright_magenta = parse_hex(raw.get("bright_magenta", ""), lighten(magenta, 0.12))
    bright_cyan = parse_hex(raw.get("bright_cyan", ""), lighten(cyan, 0.12))

    # Index 0 is the console background when vt.color uses bg=0.
    colors = [
        darker_background,
        red,
        green,
        yellow,
        blue,
        magenta,
        cyan,
        foreground,
        muted,
        bright_red,
        bright_green,
        bright_yellow,
        bright_blue,
        bright_magenta,
        bright_cyan,
        bright_foreground,
    ]
    return [hex_to_rgb(c) for c in colors]


def palette_from_theme(slug: str) -> dict[str, Any]:
    slug = slugify(slug)
    if slug == DEFAULT_SLUG:
        rgb = list(VGA_RGB)
        return {
            "slug": DEFAULT_SLUG,
            "name": "Default",
            "background": rgb_to_hex(rgb[0]),
            "foreground": rgb_to_hex(rgb[7]),
            "bright_foreground": rgb_to_hex(rgb[15]),
            "muted": rgb_to_hex(rgb[8]),
            "accent": rgb_to_hex(rgb[2]),
            "red": rgb_to_hex(rgb[1]),
            "green": rgb_to_hex(rgb[2]),
            "yellow": rgb_to_hex(rgb[3]),
            "blue": rgb_to_hex(rgb[4]),
            "magenta": rgb_to_hex(rgb[5]),
            "cyan": rgb_to_hex(rgb[6]),
            "ansi": rgb,
            "vt_color": "0x07",
            "is_default": True,
        }

    directory = theme_dir(slug)
    if directory is None:
        raise FileNotFoundError(f"theme not found or missing colors.toml: {slug}")

    raw = read_colors_toml(directory / "colors.toml")
    ansi = ansi16_from_theme(raw)
    background = parse_hex(raw.get("background", ""), "#1a1b26")
    foreground = parse_hex(raw.get("foreground", ""), "#a9b1d6")
    bright_foreground = parse_hex(
        raw.get("bright_foreground", raw.get("light_foreground", "")),
        lighten(foreground, 0.15),
    )
    muted = parse_hex(raw.get("muted", ""), lighten(background, 0.25))
    accent = parse_hex(raw.get("accent", raw.get("blue", "")), "#7aa2f7")

    return {
        "slug": slug,
        "name": pretty_name(slug),
        "background": background,
        "foreground": foreground,
        "bright_foreground": bright_foreground,
        "muted": muted,
        "accent": accent,
        "red": parse_hex(raw.get("red", ""), "#f7768e"),
        "green": parse_hex(raw.get("green", ""), accent),
        "yellow": parse_hex(raw.get("yellow", ""), "#e0af68"),
        "blue": parse_hex(raw.get("blue", ""), accent),
        "magenta": parse_hex(raw.get("magenta", ""), "#bb9af7"),
        "cyan": parse_hex(raw.get("cyan", ""), "#7dcfff"),
        "ansi": ansi,
        "vt_color": "0x07",
        "is_default": False,
    }


def vt_cmdline_params(palette: dict[str, Any]) -> str:
    ansi: list[tuple[int, int, int]] = palette["ansi"]
    reds = ",".join(str(c[0]) for c in ansi)
    greens = ",".join(str(c[1]) for c in ansi)
    blues = ",".join(str(c[2]) for c in ansi)
    vt_color = palette.get("vt_color", "0x07")
    return (
        f"vt.default_red={reds} "
        f"vt.default_grn={greens} "
        f"vt.default_blu={blues} "
        f"vt.color={vt_color}"
    )


def render_dropin(palette: dict[str, Any]) -> str:
    params = vt_cmdline_params(palette)
    lines = [
        BLOCK_START,
        f"# Omarchy TTY palette — managed by omavt ({PLUGIN_ID})",
        f"# theme: {palette['slug']}",
        "# Style → TTY Themes. This file is the only thing omavt writes.",
        "# Removing it (Default) drops vt.default_* / vt.color only —",
        "# /etc/default/limine and omarchy-defaults.conf are never touched.",
        f'KERNEL_CMDLINE[default]+=" {params}"',
        BLOCK_END,
        "",
    ]
    return "\n".join(lines)


def setvtrgb_file_contents(palette: dict[str, Any]) -> str:
    """Hexadecimal setvtrgb FILE format (16 #RRGGBB lines)."""
    return "".join(rgb_to_hex(c) + "\n" for c in palette["ansi"])


def atomic_write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        if isinstance(content, bytes):
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        else:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def read_dropin() -> str | None:
    path = dropin_path()
    if path.is_file() and os.access(path, os.R_OK):
        return path.read_text(encoding="utf-8")
    if not path.exists():
        return None
    result = subprocess.run(
        ["sudo", "cat", "--", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def read_dropin_nosudo() -> str | None:
    """Picker path only — never block Style open on a sudo password."""
    path = dropin_path()
    try:
        if path.is_file() and os.access(path, os.R_OK):
            return path.read_text(encoding="utf-8")
    except OSError:
        return None
    return None


def write_dropin(content: str) -> None:
    path = dropin_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.access(path.parent, os.W_OK) and (not path.exists() or os.access(path, os.W_OK)):
        atomic_write(path, content)
        return

    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        prefix="omavt-dropin.",
        suffix=".conf",
        delete=False,
    ) as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
        staged = handle.name

    try:
        script = (
            "set -euo pipefail\n"
            f'dest={json.dumps(str(path))}\n'
            f'src={json.dumps(staged)}\n'
            'install -d -m 755 -- "$(dirname -- "$dest")"\n'
            'tmp=$(mktemp --tmpdir="$(dirname -- "$dest")" ".$(basename -- "$dest").omavt.XXXXXXXX")\n'
            'cp --reflink=never -- "$src" "$tmp"\n'
            'chown root:root -- "$tmp"\n'
            'chmod 644 -- "$tmp"\n'
            'mv -f -- "$tmp" "$dest"\n'
        )
        result = subprocess.run(
            ["sudo", "/bin/bash", "-c", script],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip() or f"exit {result.returncode}"
            raise RuntimeError(f"failed to write {path}: {err}")
    finally:
        try:
            os.unlink(staged)
        except FileNotFoundError:
            pass


def remove_dropin() -> None:
    path = dropin_path()
    if not path.exists():
        return
    if os.access(path.parent, os.W_OK) and os.access(path, os.W_OK):
        path.unlink()
        return
    result = subprocess.run(
        ["sudo", "rm", "-f", "--", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip() or f"exit {result.returncode}"
        raise RuntimeError(f"failed to remove {path}: {err}")


def apply_live_palette(palette: dict[str, Any]) -> None:
    """Best-effort live VT palette via setvtrgb (no reboot)."""
    if os.environ.get("OMAVT_SKIP_SETVTRGB"):
        return
    setvtrgb = shutil.which("setvtrgb")
    if not setvtrgb:
        return

    if palette.get("is_default"):
        cmd = ["sudo", setvtrgb, "vga"] if os.geteuid() != 0 else [setvtrgb, "vga"]
        subprocess.run(cmd, check=False, capture_output=True, text=True)
        return

    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        prefix="omavt-vtrgb.",
        suffix=".txt",
        delete=False,
    ) as handle:
        handle.write(setvtrgb_file_contents(palette))
        handle.flush()
        staged = handle.name

    try:
        if os.geteuid() == 0 or os.access("/sys/module/vt/parameters/default_red", os.W_OK):
            cmd = [setvtrgb, staged]
        else:
            cmd = ["sudo", setvtrgb, staged]
        subprocess.run(cmd, check=False, capture_output=True, text=True)
    finally:
        try:
            os.unlink(staged)
        except FileNotFoundError:
            pass


def rebuild_limine() -> None:
    if os.environ.get("OMAVT_SKIP_LIMINE"):
        return
    if not shutil.which("limine-update"):
        note("limine-update not found — drop-in written; rebuild boot entries yourself")
        return
    result = subprocess.run(
        ["sudo", "limine-update"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip() or f"exit {result.returncode}"
        raise RuntimeError(f"limine-update failed: {err}")


# omarchy-menu-images serves 1536×864 then crops to a 768×475 tile
# (PreserveAspectCrop — shaves the sides). Keep session + strip inside ~8%
# horizontal margins so the carousel does not eat the getty text.
MOCKUP_SIZE = (1536, 864)
SAFE_X = 120
SAFE_Y = 56
# Bump when render_mockup chrome changes so cached tiles re-draw.
MOCKUP_LAYOUT_VERSION = "2"


def _input_token(path: Path | None) -> str:
    if path is None:
        return "none"
    try:
        st = path.stat()
    except OSError:
        return "missing"
    return f"{st.st_mtime_ns}:{st.st_size}"


def _preview_meta_path(dest: Path) -> Path:
    return Path(str(dest) + ".meta")


def _preview_fresh(dest: Path, fingerprint: str) -> bool:
    if not dest.is_file():
        return False
    try:
        return _preview_meta_path(dest).read_text(encoding="utf-8").strip() == fingerprint
    except OSError:
        return False


def _write_preview_meta(dest: Path, fingerprint: str) -> None:
    try:
        _preview_meta_path(dest).write_text(fingerprint + "\n", encoding="utf-8")
    except OSError:
        pass


def _preview_fingerprint(slug: str) -> str:
    if slugify(slug) == DEFAULT_SLUG:
        return f"layout:{MOCKUP_LAYOUT_VERSION}|default"
    directory = theme_dir(slug)
    colors = (directory / "colors.toml") if directory else None
    return f"layout:{MOCKUP_LAYOUT_VERSION}|colors:{_input_token(colors)}"


def tty_banner(tty: str = "tty1") -> str:
    """Match getty banner: Omarchy <uname -r> (ttyN). Nested VM often lands on tty1."""
    try:
        release = subprocess.check_output(
            ["uname", "-r"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.SubprocessError):
        release = "7.2.3-arch1-3"
    return f"Omarchy {release} ({tty})"


def try_font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/liberation/LiberationMono-Regular.ttf",
        "/usr/share/fonts/Adwaita/AdwaitaMono-Regular.ttf",
        "/usr/share/fonts/TTF/JetBrainsMonoNerdFont-Regular.ttf",
        "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/noto/NotoSansMono-Regular.ttf",
    ]
    for path in candidates:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def render_mockup(
    palette: dict[str, Any],
    dest: Path,
    size: tuple[int, int] = MOCKUP_SIZE,
) -> Path:
    """Fake /dev/tty session wearing the theme (or VGA default) palette.

    Layout tracked from a default dark TTY QEMU capture (getty on tty1 after
    SDDM off — nested Omarchy cannot Ctrl+Alt+F3). Same session script as
    OmaTTY: login as wolf, then the single-GPU passthrough starter. Not a
    live VT framebuffer capture. Content stays inside SAFE_X for the Style
    carousel crop.
    """
    w, h = size
    ansi: list[tuple[int, int, int]] = palette["ansi"]
    bg = ansi[0]
    fg = ansi[7]
    bright = ansi[15]
    muted = ansi[8]
    cyan = ansi[6]

    img = Image.new("RGB", size, bg)
    draw = ImageDraw.Draw(img)

    mono = try_font(26)
    mono_sm = try_font(18)

    # Top-left like real getty, but inset so side crop does not shave glyphs.
    origin_x, origin_y = SAFE_X, SAFE_Y
    line_h = 34
    max_x = w - SAFE_X

    # Keep session lines in sync with OmaTTY (sibling Style plugin).
    banner = tty_banner("tty1")
    prompt = "~ > "
    command = "sudo /home/wolf/vm-space/windows-11/single-gpu-start.sh"

    def draw_clipped(x: int, y: int, text: str, fill: tuple[int, int, int], font: ImageFont.ImageFont) -> None:
        # Drop characters that would paint past the right safe edge.
        while text and x + int(draw.textlength(text, font=font)) > max_x:
            text = text[:-1]
        if text:
            draw.text((x, y), text, font=font, fill=fill)

    y = origin_y
    draw_clipped(origin_x, y, banner, bright, mono)
    y += line_h
    draw_clipped(origin_x, y, "omarchy login: wolf", fg, mono)
    y += line_h
    draw_clipped(origin_x, y, "Password:", fg, mono)
    y += line_h
    draw_clipped(origin_x, y, prompt, cyan, mono)
    prompt_w = int(draw.textlength(prompt, font=mono))
    draw_clipped(origin_x + prompt_w, y, command, fg, mono)
    y += line_h
    draw.rectangle((origin_x, y + 4, origin_x + 14, y + line_h - 6), fill=fg)

    if palette.get("is_default"):
        note = "stock VGA — Default removes omavt colours only"
        draw_clipped(origin_x, y + line_h + 8, note, muted, mono_sm)

    strip_y = h - 72
    cell_w = 68
    total = cell_w * 16
    x0 = max(SAFE_X, (w - total) // 2)
    x0 = min(x0, max(SAFE_X, w - SAFE_X - total))
    for index, rgb in enumerate(ansi):
        cx = x0 + index * cell_w
        draw.rectangle((cx + 3, strip_y, cx + cell_w - 3, strip_y + 40), fill=rgb)
        ink = ansi[0] if (rgb[0] + rgb[1] + rgb[2]) > 380 else ansi[15]
        draw.text((cx + 8, strip_y + 8), f"{index:X}", font=mono_sm, fill=ink)

    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, format="PNG", optimize=True)
    return dest


def preview_path(slug: str) -> Path:
    return paths()["cache"] / "previews" / f"{slugify(slug)}.png"


def generate_preview(slug: str, *, force: bool = False) -> Path:
    dest = preview_path(slug)
    fp = _preview_fingerprint(slug)
    if not force and _preview_fresh(dest, fp):
        return dest
    palette = palette_from_theme(slug)
    render_mockup(palette, dest)
    _write_preview_meta(dest, fp)
    return dest


def bust_image_picker_cache(preview_root: Path) -> None:
    """Invalidate omarchy-menu-images rows/thumbnails for our preview dir."""
    try:
        os.utime(preview_root, None)
    except OSError:
        pass

    cache_dir = Path(
        os.environ.get(
            "OMAVT_IMAGE_SELECTOR_CACHE",
            home() / ".cache/omarchy/image-selector",
        )
    )
    if not cache_dir.is_dir():
        return

    needle = str(preview_root.resolve())
    for path in cache_dir.iterdir():
        name = path.name
        if not (
            name.endswith(".rows")
            or name.endswith(".signature")
            or name.endswith(".fast-signature")
            or name.endswith(".rows.lock")
        ):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if needle in text or str(preview_root) in text:
            path.unlink(missing_ok=True)

    index = cache_dir / "index.tsv"
    if index.is_file():
        try:
            lines = index.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            lines = []
        kept: list[str] = []
        for line in lines:
            parts = line.split("\t")
            if parts and (needle in parts[0] or str(preview_root) in parts[0]):
                if len(parts) >= 3:
                    (cache_dir / f"{parts[2]}.jpg").unlink(missing_ok=True)
                    (cache_dir / f"{parts[2]}.jpg.lock").unlink(missing_ok=True)
                continue
            kept.append(line)
        try:
            atomic_write(index, ("\n".join(kept) + ("\n" if kept else "")))
        except OSError:
            pass


def _preview_pool(workers: int) -> ProcessPoolExecutor:
    # See omacursor: force fork so bin/* → python3 lib/*.py workers do not
    # re-import __main__ under Python 3.14's forkserver default.
    try:
        ctx = mp.get_context("fork")
    except ValueError:
        ctx = mp.get_context()
    return ProcessPoolExecutor(max_workers=workers, mp_context=ctx)


def generate_all_previews() -> list[Path]:
    out: list[Path] = []
    preview_root = paths()["cache"] / "previews"
    preview_root.mkdir(parents=True, exist_ok=True)
    wanted = list(list_picker_slugs())
    wanted_set = set(wanted)
    for existing in preview_root.glob("*.png"):
        if existing.stem not in wanted_set:
            existing.unlink(missing_ok=True)
            _preview_meta_path(existing).unlink(missing_ok=True)
    dirty = [
        slug
        for slug in wanted
        if not _preview_fresh(preview_path(slug), _preview_fingerprint(slug))
    ]
    if not dirty:
        return out
    workers = max(1, min(len(dirty), os.cpu_count() or 2))
    with _preview_pool(workers) as pool:
        futures = {
            pool.submit(generate_preview, slug, force=True): slug for slug in dirty
        }
        for fut in as_completed(futures):
            slug = futures[fut]
            try:
                out.append(fut.result())
            except Exception as error:  # noqa: BLE001
                note(f"preview {slug}: {error}")
    bust_image_picker_cache(preview_root)
    return out


def set_theme(slug: str, *, quiet: bool = False, dry_run: bool = False) -> int:
    slug = slugify(slug)
    if slug != DEFAULT_SLUG and theme_dir(slug) is None:
        note(f"theme not found: {slug}")
        return 1

    palette = palette_from_theme(slug)

    if slug == DEFAULT_SLUG:
        if dry_run:
            sys.stdout.write("# default → remove colour drop-in only\n")
            existing = read_dropin()
            if existing:
                sys.stdout.write(existing)
            else:
                sys.stdout.write("# (no drop-in present)\n")
            return 0

        remove_dropin()
        rebuild_limine()
        apply_live_palette(palette)

        state = paths()["state"]
        state.mkdir(parents=True, exist_ok=True)
        atomic_write(state / "current", DEFAULT_SLUG + "\n")
        (state / "last-dropin.conf").unlink(missing_ok=True)

        if not quiet:
            note(f"removed {dropin_path()} (colour block only)")
            note("custom cmdline / omarchy-defaults left untouched; reboot for cold VT")
        return 0

    content = render_dropin(palette)
    if dry_run:
        sys.stdout.write(content)
        return 0

    write_dropin(content)
    rebuild_limine()
    apply_live_palette(palette)

    state = paths()["state"]
    state.mkdir(parents=True, exist_ok=True)
    atomic_write(state / "current", slug + "\n")
    atomic_write(state / "last-dropin.conf", content)

    if not quiet:
        note(f"drop-in ← {pretty_name(slug)} ({dropin_path()})")
        note("only vt.default_* / vt.color appended; reboot for cold VT")
    return 0


def remove_marked(content: str, start: str, end: str) -> str:
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end) + r"\n?", re.S)
    return pattern.sub("", content)


def menu_action() -> str:
    switcher = plugin_dir() / "bin" / "omavt-switcher"
    setter = plugin_dir() / "bin" / "omavt-set"
    return (
        f'theme="$({switcher})"; '
        f'if [[ $theme == default ]]; then '
        f'omarchy-launch-floating-terminal-with-presentation "{setter} default"; '
        f'elif [[ -n $theme ]]; then '
        f'omarchy-launch-floating-terminal-with-presentation '
        f'"{setter} $(printf %q "$theme")"; '
        f'fi'
    )


def install_menu_entry() -> None:
    path = paths()["menu"]
    content = path.read_text(encoding="utf-8") if path.is_file() else "{\n}\n"
    content = remove_marked(content, MENU_START, MENU_END)
    entries = [
        (
            "style.tty-theme",
            {
                "icon": "󰯂",
                "label": "TTY Themes",
                "aliases": ["tty-theme", "vt", "console-color", "vtrgb"],
                "description": "Preview unlock-style TTY mockups and append vt.default_* colours via limine-entry-tool.d (sudo)",
                "action": menu_action(),
            },
        )
    ]
    brace = content.find("{")
    if brace < 0:
        raise RuntimeError(f"menu config has no root object: {path}")
    body = [MENU_START]
    for key, value in entries:
        body.append(f"  {json.dumps(key)}: {json.dumps(value, ensure_ascii=False)},")
    body.append(MENU_END)
    insertion = "\n".join(body) + "\n"
    atomic_write(path, content[: brace + 1] + "\n" + insertion + content[brace + 1 :])


def uninstall_menu_entry() -> None:
    path = paths()["menu"]
    if not path.is_file():
        return
    content = path.read_text(encoding="utf-8")
    if MENU_START in content:
        atomic_write(path, remove_marked(content, MENU_START, MENU_END))


def cmd_list(_: argparse.Namespace) -> int:
    for slug in list_picker_slugs():
        print(slug)
    return 0


def cmd_current(_: argparse.Namespace) -> int:
    slug = current_omavt_slug()
    if not slug:
        # Infer from drop-in theme tag when state is missing.
        existing = read_dropin()
        if existing:
            match = re.search(r"^# theme:\s*(\S+)", existing, re.M)
            if match:
                print(match.group(1))
                return 0
            print("custom")
            return 0
        print(DEFAULT_SLUG)
        return 0
    print(slug)
    return 0


def cmd_preview(args: argparse.Namespace) -> int:
    if args.theme:
        slug = slugify(args.theme)
        if slug != DEFAULT_SLUG and theme_dir(slug) is None:
            note(f"theme not found: {args.theme}")
            return 1
        path = generate_preview(slug)
        print(path)
        return 0
    written = generate_all_previews()
    print(len(written))
    return 0


def cmd_set(args: argparse.Namespace) -> int:
    return set_theme(args.theme, quiet=args.quiet, dry_run=args.dry_run)


def cmd_show(args: argparse.Namespace) -> int:
    slug = slugify(args.theme)
    if slug != DEFAULT_SLUG and theme_dir(slug) is None:
        note(f"theme not found: {slug}")
        return 1
    palette = palette_from_theme(slug)
    if slug == DEFAULT_SLUG:
        sys.stdout.write("# default → remove colour drop-in only\n")
        return 0
    sys.stdout.write(render_dropin(palette))
    return 0


def cmd_switcher(_: argparse.Namespace) -> int:
    generate_all_previews()
    preview_dir = paths()["cache"] / "previews"
    current = current_omavt_slug()
    if not current:
        existing = read_dropin_nosudo()
        current = DEFAULT_SLUG if not existing else None
    selected = ""
    if current and (preview_dir / f"{current}.png").is_file():
        selected = str(preview_dir / f"{current}.png")

    cmd = [
        "omarchy-menu-images",
        "--print-name",
        "--show-labels",
        "--filterable",
    ]
    if selected:
        cmd.extend(["--selected", selected])
    cmd.append(str(preview_dir))

    try:
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    except FileNotFoundError:
        note("omarchy-menu-images not found")
        return 1

    choice = (result.stdout or "").strip()
    if result.returncode != 0 and not choice:
        return result.returncode or 1
    if choice:
        print(choice)
    return 0


def cmd_install_menu(_: argparse.Namespace) -> int:
    install_menu_entry()
    note(f"menu entry → {paths()['menu']}")
    return 0


def cmd_uninstall_menu(_: argparse.Namespace) -> int:
    uninstall_menu_entry()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="omavt", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List default + Omarchy theme slugs").set_defaults(func=cmd_list)
    sub.add_parser("current", help="Print the last applied omavt theme slug").set_defaults(
        func=cmd_current
    )

    preview = sub.add_parser("preview", help="Render TTY unlock mockup PNG(s)")
    preview.add_argument("theme", nargs="?", help="Theme slug; omit for all")
    preview.set_defaults(func=cmd_preview)

    show = sub.add_parser("show", help="Print the managed limine-entry-tool drop-in")
    show.add_argument("theme", help="Theme slug or 'default'")
    show.set_defaults(func=cmd_show)

    setter = sub.add_parser("set", help="Write/remove vt colour drop-in (sudo)")
    setter.add_argument("theme", help="Theme slug or 'default'")
    setter.add_argument("--quiet", action="store_true")
    setter.add_argument("--dry-run", action="store_true", help="Print drop-in / removal plan")
    setter.set_defaults(func=cmd_set)

    sub.add_parser("switcher", help="Open image picker; print chosen slug").set_defaults(
        func=cmd_switcher
    )
    sub.add_parser("install-menu", help="Add Style → TTY Themes").set_defaults(
        func=cmd_install_menu
    )
    sub.add_parser("uninstall-menu", help="Remove Style → TTY Themes").set_defaults(
        func=cmd_uninstall_menu
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except BrokenPipeError:
        return 0
    except Exception as exc:  # noqa: BLE001 — CLI surface
        note(str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
