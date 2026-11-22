"""Locate an ffmpeg binary.

Uses, in order:
1. ``COUNTDOWN_STUDIO_FFMPEG`` environment variable
2. An ``ffmpeg`` on PATH
3. The binary bundled with ``imageio-ffmpeg``
"""

import os
import shutil
import subprocess

ENV_VAR = "COUNTDOWN_STUDIO_FFMPEG"

_cached = None
_tried = False


def _bundled():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError, OSError):
        return None


def find_ffmpeg(refresh=False):
    """Return the path to an ffmpeg binary, or an empty string."""
    global _cached, _tried
    if _cached is not None and not refresh:
        return _cached
    if _tried and not refresh:
        return _cached or ""

    _tried = True
    for candidate in (
        os.environ.get(ENV_VAR, ""),
        shutil.which("ffmpeg") or "",
        _bundled() or "",
    ):
        if candidate and os.path.exists(candidate):
            _cached = candidate
            return candidate

    _cached = ""
    return ""


def ffmpeg_version(ffmpeg=None):
    """Return the first line of ``ffmpeg -version``, or '' on failure."""
    exe = ffmpeg or find_ffmpeg()
    if not exe:
        return ""
    try:
        out = subprocess.run([exe, "-version"], capture_output=True, text=True,
                             timeout=15, check=False)
        return out.stdout.splitlines()[0] if out.stdout else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def has_encoder(name, ffmpeg=None):
    """True if the named encoder is available in this ffmpeg build."""
    exe = ffmpeg or find_ffmpeg()
    if not exe:
        return False
    try:
        out = subprocess.run([exe, "-hide_banner", "-encoders"],
                             capture_output=True, text=True, timeout=20, check=False)
        return name in out.stdout
    except (OSError, subprocess.SubprocessError):
        return False


def install_hint():
    """Platform-appropriate guidance when no ffmpeg can be found."""
    import sys
    if sys.platform == "win32":
        return ("ffmpeg was not found. Countdown Generator installs it for you "
                "via the 'imageio-ffmpeg' package; run: pip install -r requirements.txt")
    if sys.platform == "darwin":
        return ("ffmpeg was not found. Install it with 'brew install ffmpeg', or "
                "run: pip install -r requirements.txt")
    return ("ffmpeg was not found. Install it with your package manager "
            "(e.g. 'sudo apt install ffmpeg'), or run: pip install -r requirements.txt")