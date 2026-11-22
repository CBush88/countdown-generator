"""System font discovery.

Enumerates the standard per-platform font directories, reads family/style
names, and caches the result so opening the font dropdown is instant.
"""

import os
import shutil
import sys

from PIL import ImageFont

try:
    from fontTools.ttLib import TTFont, TTLibError
    _HAVE_FONTTOOLS = True
except ImportError:  # pragma: no cover - fontTools is a declared dependency
    _HAVE_FONTTOOLS = False

FONT_EXTENSIONS = (".ttf", ".otf", ".ttc", ".otc", ".woff", ".woff2")

_cache = None


def font_directories():
    """Candidate font directories for the current platform."""
    dirs = []
    home = os.path.expanduser("~")

    if sys.platform == "win32":
        win = os.environ.get("WINDIR", r"C:\Windows")
        dirs.append(os.path.join(win, "Fonts"))
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(os.path.join(local, "Microsoft", "Windows", "Fonts"))
    elif sys.platform == "darwin":
        dirs.extend([
            "/System/Library/Fonts",
            "/Library/Fonts",
            os.path.join(home, "Library", "Fonts"),
        ])
    else:
        dirs.extend([
            "/usr/share/fonts",
            "/usr/local/share/fonts",
            os.path.join(home, ".fonts"),
            os.path.join(home, ".local", "share", "fonts"),
        ])

    # Also honour anything the user dropped into the app's own folder.
    dirs.append(os.path.join(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))), "fonts"))

    seen = set()
    out = []
    for d in dirs:
        if d and d not in seen and os.path.isdir(d):
            seen.add(d)
            out.append(d)
    return out


def _read_names(path):
    """Return (family, style) for a font file, falling back to PIL."""
    if _HAVE_FONTTOOLS:
        try:
            font = TTFont(path, fontNumber=0, lazy=True)
            name = font["name"]
            family = name.getDebugName(16) or name.getDebugName(1)
            style = name.getDebugName(17) or name.getDebugName(2)
            font.close()
            if family:
                return family.strip(), (style or "").strip()
        except (TTLibError, KeyError, OSError, Exception):
            pass

    try:
        # FreeTypeFont is not a context manager in any Pillow release, so this
        # must not use `with`.
        font = ImageFont.truetype(path, 20)
        family, style = font.getname()
        return (family or "").strip(), (style or "").strip()
    except (OSError, ValueError):
        return None, None


def scan_fonts(refresh=False):
    """Return a sorted list of ``(family, style, path)`` for system fonts."""
    global _cache
    if _cache is not None and not refresh:
        return _cache

    found = []
    for directory in font_directories():
        for root, _dirs, files in os.walk(directory):
            for fname in files:
                if not fname.lower().endswith(FONT_EXTENSIONS):
                    continue
                path = os.path.join(root, fname)
                family, style = _read_names(path)
                if family:
                    found.append((family, style, path))

    # De-duplicate on (family, style) keeping the first path seen.
    seen = set()
    unique = []
    for family, style, path in sorted(found, key=lambda r: (r[0].lower(), (r[1] or "").lower())):
        key = (family.lower(), (style or "").lower())
        if key in seen:
            continue
        seen.add(key)
        unique.append((family, style, path))

    _cache = unique
    return _cache


def families():
    """Sorted unique family names."""
    return sorted({family for family, _style, _path in scan_fonts()},
                  key=lambda s: s.lower())


def styles_for(family):
    """All (style, path) entries belonging to a family."""
    return [(style, path) for fam, style, path in scan_fonts() if fam == family]


def find_font(family, style=None):
    """Best path for a family, preferring an exact style match then Regular."""
    entries = styles_for(family)
    if not entries:
        return ""

    if style:
        for sty, path in entries:
            if sty.lower() == style.lower():
                return path

    for sty, path in entries:
        if sty.lower() in ("regular", "book", "normal"):
            return path
    for sty, path in entries:
        if "bold" not in sty.lower() and "italic" not in sty.lower():
            return path
    return entries[0][1]


def import_font(source, dest_dir):
    """Copy a font file into the app's user font directory.

    Returns the stored path. The original is left untouched.
    """
    os.makedirs(dest_dir, exist_ok=True)
    base = os.path.basename(source)
    stem, ext = os.path.splitext(base)
    if ext.lower() not in FONT_EXTENSIONS:
        raise ValueError("Unsupported font format: %s" % (ext or "(none)"))

    target = os.path.join(dest_dir, base)
    if os.path.exists(target) and os.path.abspath(source) != os.path.abspath(target):
        i = 1
        while os.path.exists(target):
            target = os.path.join(dest_dir, "%s-%d%s" % (stem, i, ext))
            i += 1

    if os.path.abspath(source) != os.path.abspath(target):
        shutil.copy2(source, target)
    return target


def validate_font(path):
    """Return (ok, message) describing whether a font file is usable."""
    if not path:
        return False, "No font selected."
    if not os.path.exists(path):
        return False, "Font file not found."
    try:
        ImageFont.truetype(path, 20)
    except (OSError, ValueError) as exc:
        return False, "Cannot load font: %s" % exc
    return True, ""