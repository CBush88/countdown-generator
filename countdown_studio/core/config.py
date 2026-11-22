"""Configuration model for Countdown Generator."""

import json
import os
import sys
from dataclasses import dataclass, field, asdict, replace

# Text colour presets for dark / light background modes.
DARK_TEXT = "#F2EFE6"
LIGHT_TEXT = "#101010"

FINAL_MINUTE_BARE = "bare"
FINAL_MINUTE_FIXED = "fixed"
FINAL_MINUTE_STANDARD = "standard"
FINAL_MINUTE_CHOICES = [
    (FINAL_MINUTE_BARE, "Bare seconds, centered"),
    (FINAL_MINUTE_FIXED, "Bare seconds, fixed width"),
    (FINAL_MINUTE_STANDARD, "Always 0:59 style"),
]

FIT_FILL = "fill"
FIT_FIT = "fit"
FIT_CHOICES = [
    (FIT_FILL, "Fill frame (crop edges)"),
    (FIT_FIT, "Fit inside (letterbox)"),
]

MODE_BAKED = "baked"
MODE_ALPHA = "alpha"
MODE_LUMA = "luma"
MODE_CHOICES = [
    (MODE_BAKED, "Baked-in (background included)"),
    (MODE_ALPHA, "Alpha channel (transparent)"),
    (MODE_LUMA, "Luma key (white on black)"),
]

ALPHA_PRORES = "prores"
ALPHA_PNG = "png"
ALPHA_CHOICES = [
    (ALPHA_PRORES, "ProRes 4444 (.mov)"),
    (ALPHA_PNG, "PNG sequence (.zip)"),
]

RES_720 = "1280x720"
RES_1080 = "1920x1080"
RES_4K = "3840x2160"
RES_CHOICES = [
    (RES_720, "720p (1280x720)"),
    (RES_1080, "1080p (1920x1080)"),
    (RES_4K, "4K (3840x2160)"),
]


def parse_resolution(value):
    try:
        w, h = value.lower().split("x")
        return int(w), int(h)
    except (ValueError, AttributeError):
        return 1920, 1080


@dataclass
class RenderConfig:
    # Background
    background: str = ""
    fit: str = FIT_FILL

    # Timer
    minutes: int = 5
    seconds: int = 0
    final_minute: str = FINAL_MINUTE_BARE
    hold_seconds: float = 5.0
    fade_in: bool = True

    # Text
    font_family: str = ""
    font_file: str = ""
    color: str = DARK_TEXT
    mode: str = "dark"
    auto_mode: bool = True
    italic: bool = False
    slant: float = 0.22
    proportional: bool = False

    # Contrast
    contrast: bool = False
    shadow: float = 0.55
    outline: float = 0.0

    # Glow
    glow: bool = True
    glow_alpha: float = 0.41

    # Video
    resolution: str = RES_1080
    fps: int = 30
    crf: int = 18
    preset: str = "medium"

    # Output
    export_mode: str = MODE_BAKED
    alpha_format: str = ALPHA_PRORES

    # Last output path (not usually edited by hand)
    last_output: str = ""

    @property
    def width(self):
        return parse_resolution(self.resolution)[0]

    @property
    def height(self):
        return parse_resolution(self.resolution)[1]

    @property
    def total_seconds(self):
        return max(0, int(self.minutes)) * 60 + max(0, int(self.seconds))

    def validate(self):
        """Return a list of human-readable problems. Empty list means ready."""
        problems = []
        if self.total_seconds <= 0:
            problems.append("Set a timer length of at least one second.")
        if self.export_mode == MODE_BAKED and not self.background:
            problems.append("Choose a background image.")
        if self.export_mode == MODE_BAKED and self.background and not os.path.exists(self.background):
            problems.append("Background image no longer exists.")
        if not self.font_file:
            problems.append("Choose a font.")
        elif not os.path.exists(self.font_file):
            problems.append("Font file no longer exists.")
        return problems

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        known = {f for f in cls.__dataclass_fields__}
        clean = {k: v for k, v in data.items() if k in known}
        return cls(**clean)

    def save(self, path):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)
        os.replace(tmp, path)

    @classmethod
    def load(cls, path):
        with open(path, "r", encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))


def config_dir():
    """Per-user config directory that works on Windows, macOS and Linux."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "Countdown Generator")
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support",
                            "Countdown Generator")
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "countdown-generator")


def default_config_path():
    return os.path.join(config_dir(), "settings.json")


def load_user_config():
    path = default_config_path()
    if os.path.exists(path):
        try:
            return RenderConfig.load(path)
        except (OSError, ValueError):
            pass
    return RenderConfig()


def save_user_config(cfg):
    try:
        os.makedirs(config_dir(), exist_ok=True)
        cfg.save(default_config_path())
    except OSError:
        pass


def imported_font_dir():
    d = os.path.join(config_dir(), "fonts")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


def result_color_for_background(cfg, brightness):
    """Pick dark or light text based on measured background brightness (0-255)."""
    if not cfg.auto_mode:
        return cfg.mode, cfg.color
    mode = "light" if brightness > 140 else "dark"
    return mode, LIGHT_TEXT if mode == "light" else DARK_TEXT


def normalize(cfg):
    """Apply derived defaults that the GUI does not store directly."""
    cfg = replace(cfg)
    if cfg.mode == "light":
        # A glow reads as a smudge on light backgrounds; use a shadow instead.
        cfg.glow = False
        if not cfg.contrast:
            cfg.contrast = True
            cfg.shadow = max(cfg.shadow, 0.35)
    else:
        if cfg.contrast and cfg.shadow <= 0.0:
            cfg.shadow = 0.55
    if cfg.outline < 0.0:
        cfg.outline = 0.0
    if cfg.outline > 0.1:
        cfg.outline = min(cfg.outline, 0.1)
    return cfg