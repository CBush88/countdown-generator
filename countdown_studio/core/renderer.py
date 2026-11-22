"""Frame renderer for Countdown Generator.

The renderer draws a countdown over a background image. It is deliberately
free of any GUI or encoding concerns so the same code path serves the live
preview, the CLI and the encoder.

Coordinate system
-----------------
Layout values are authored against a 2160-line reference frame and scaled by
``height / 2160``. That keeps the composition identical at 1080p and 4K.
"""

import math

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from .config import (
    DARK_TEXT,
    FIT_FIT,
    FINAL_MINUTE_FIXED,
    FINAL_MINUTE_STANDARD,
    LIGHT_TEXT,
    MODE_ALPHA,
    MODE_LUMA,
    normalize,
)

REFERENCE_TEXT = "0123456789:"

_REF_HEIGHT = 2160.0
_DIGITS_CY = 1040.0
_FONT_SIZE = 950.0
_GLOW_RADIUS = 34.0
_GLOW_ALPHA = 105.0
_FADE_IN_SECONDS = 0.8

# A glow reads as a smudge on light backgrounds; luma-key export needs pure
# white on pure black so the key is mathematically clean.
LUMA_WHITE = (255, 255, 255)
LUMA_BLACK = (0, 0, 0)
GLOW_WARM = (255, 180, 60)


def hex_to_rgb(value, fallback=(242, 239, 230)):
    """'#F2EFE6' or 'F2EFE6' -> (242, 239, 230). Returns fallback if unparsable."""
    if not value:
        return fallback
    h = str(value).strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return fallback
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return fallback


def format_time(secs, show_minutes=True):
    secs = max(0, int(secs))
    if show_minutes:
        return "%d:%02d" % (secs // 60, secs % 60)
    return str(secs)


def digit_cell(font):
    """A fixed advance width wide enough for every digit.

    Numeric-only display fonts often ship proportional figures, which makes a
    timer jitter sideways as digits change. Drawing each glyph inside a cell of
    equal width keeps the block steady.
    """
    return max(font.getlength(d) for d in "0123456789")


def fit_image(img, width, height, fit):
    """Scale an image to the target frame, either filling it or letterboxing."""
    src_w, src_h = img.size
    if src_w == 0 or src_h == 0:
        return Image.new("RGB", (width, height), (0, 0, 0))

    if fit == FIT_FIT:
        scale = min(width / src_w, height / src_h)
        new_w = max(1, int(round(src_w * scale)))
        new_h = max(1, int(round(src_h * scale)))
        scaled = img.resize((new_w, new_h), Image.LANCZOS)
        canvas = Image.new("RGB", (width, height), (0, 0, 0))
        canvas.paste(scaled, ((width - new_w) // 2, (height - new_h) // 2))
        return canvas

    scale = max(width / src_w, height / src_h)
    new_w = max(width, int(round(src_w * scale)))
    new_h = max(height, int(round(src_h * scale)))
    scaled = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - width) // 2
    top = (new_h - height) // 2
    return scaled.crop((left, top, left + width, top + height))


def background_brightness(path):
    """Mean luminance (0-255) of a background image, used to pick text colour."""
    try:
        with Image.open(path) as img:
            small = img.convert("L").resize((32, 32))
            data = list(small.getdata())
            return sum(data) / float(len(data)) if data else 0.0
    except (OSError, ValueError):
        return 0.0


def make_sprite(text, font, fill_rgb, glow_rgb, glow_radius, glow_alpha, pad,
                slant=0.0, cell=None, outline=0.0, shadow=0.0):
    """Render text with optional glow, outline and drop shadow.

    Returns ``(image, center_x, center_y)``. Every string is drawn from one
    shared baseline so changing digits never shift the block vertically.
    """
    probe = ImageDraw.Draw(Image.new("L", (8, 8)))
    ref = probe.textbbox((0, 0), REFERENCE_TEXT, font=font)
    ref_w, ref_h = ref[2] - ref[0], ref[3] - ref[1]

    if cell:
        colon_w = font.getlength(":")
        text_w = sum(colon_w if ch == ":" else cell for ch in text)
    else:
        text_w = ref_w

    slant_px = int(round(ref_h * slant))
    outline_px = int(round(ref_h * outline))
    shadow_px = int(round(ref_h * shadow))

    # Leave room for every effect so nothing clips at the sprite edge.
    extra = max(pad, outline_px * 2, shadow_px * 2, abs(slant_px), 1)
    W = int(text_w + extra * 2)
    H = int(ref_h + extra * 2 + shadow_px)

    ox = float(extra + (slant_px if slant_px < 0 else 0))
    base = extra - ref[1]

    mask = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(mask)

    if cell:
        x = ox - ref[0]
        for ch in text:
            if ch == ":":
                d.text((x, base), ch, font=font, fill=255)
                x += colon_w
            else:
                gw = font.getlength(ch)
                d.text((x + (cell - gw) / 2.0, base), ch, font=font, fill=255)
                x += cell
    else:
        d.text((ox - ref[0], base), text, font=font, fill=255)

    stroke = None
    if outline_px > 0:
        grown = mask.filter(ImageFilter.MaxFilter(outline_px * 2 + 1))
        stroke = ImageChops.subtract(grown, mask)

    if slant:
        coeffs = (1, slant, -slant * (extra + ref_h), 0, 1, 0)
        mask = mask.transform((W, H), Image.AFFINE, coeffs, resample=Image.BICUBIC)
        if stroke is not None:
            stroke = stroke.transform((W, H), Image.AFFINE, coeffs,
                                      resample=Image.BICUBIC)

    sprite = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    if shadow_px > 0:
        sh = mask.filter(ImageFilter.GaussianBlur(max(1.0, shadow_px * 0.5)))
        shadow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        shadow_layer.paste((0, 0, 0, 255), (0, shadow_px), sh)
        sprite = Image.alpha_composite(sprite, shadow_layer)

    if glow_alpha > 0 and glow_radius > 0:
        glow = mask.filter(ImageFilter.GaussianBlur(glow_radius))
        glow = glow.point(lambda v: int(v * glow_alpha / 255))
        glow_layer = Image.new("RGBA", (W, H), tuple(glow_rgb) + (0,))
        glow_layer.putalpha(glow)
        sprite = Image.alpha_composite(sprite, glow_layer)

    if stroke is not None:
        outline_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        outline_layer.paste((0, 0, 0, 255), (0, 0), stroke)
        sprite = Image.alpha_composite(sprite, outline_layer)

    text_layer = Image.new("RGBA", (W, H), tuple(fill_rgb) + (0,))
    text_layer.putalpha(mask)
    sprite = Image.alpha_composite(sprite, text_layer)

    # Centre on the advance box, not on the ink. Ink extents differ from glyph to
    # glyph, so centring on ink would drag the fixed-width cell grid sideways
    # every time a digit changes. The shear displaces ink by a fixed amount that
    # depends only on the font metrics, so compensate for it directly.
    cx = ox - ref[0] + text_w / 2.0 + slant * ref_h / 2.0
    # The vertical centre must be the text's own centre, not the sprite's. The
    # drop shadow only extends downward, so centring on H/2 would raise the text
    # by shadow_px / 2 -- 96 px at 1080p with the default shadow.
    return sprite, cx, extra + ref_h / 2.0


def composite_into(dst, src, x, y):
    """Alpha-composite an RGBA PIL image onto an RGB uint8 array in place."""
    x = int(round(x))
    y = int(round(y))
    x0, y0 = max(0, x), max(0, y)
    x1 = min(dst.shape[1], x + src.width)
    y1 = min(dst.shape[0], y + src.height)
    if x1 <= x0 or y1 <= y0:
        return
    sub = src.crop((x0 - x, y0 - y, x0 - x + (x1 - x0), y0 - y + (y1 - y0)))
    a = np.asarray(sub, dtype=np.float32)
    alpha = a[..., 3:4] / 255.0
    region = dst[y0:y1, x0:x1].astype(np.float32)
    dst[y0:y1, x0:x1] = (region * (1.0 - alpha) + a[..., :3] * alpha).astype(np.uint8)


def composite_into_rgba(dst, src, x, y):
    """Alpha-composite an RGBA PIL image onto an RGBA uint8 array in place."""
    x = int(round(x))
    y = int(round(y))
    x0, y0 = max(0, x), max(0, y)
    x1 = min(dst.shape[1], x + src.width)
    y1 = min(dst.shape[0], y + src.height)
    if x1 <= x0 or y1 <= y0:
        return
    sub = src.crop((x0 - x, y0 - y, x0 - x + (x1 - x0), y0 - y + (y1 - y0)))
    a = np.asarray(sub, dtype=np.float32)
    src_a = a[..., 3:4] / 255.0
    region = dst[y0:y1, x0:x1].astype(np.float32)
    dst_a = region[..., 3:4] / 255.0
    out_a = src_a + dst_a * (1.0 - src_a)
    safe = np.where(out_a == 0, 1.0, out_a)
    region[..., :3] = (a[..., :3] * src_a +
                       region[..., :3] * dst_a * (1.0 - src_a)) / safe
    region[..., 3:4] = out_a * 255.0
    dst[y0:y1, x0:x1] = region.astype(np.uint8)


def flatten(rgba, background=0):
    """Composite an RGBA array over a flat grey level, returning RGB uint8."""
    a = rgba[..., 3:4].astype(np.float32) / 255.0
    rgb = rgba[..., :3].astype(np.float32)
    return (rgb * a + background * (1.0 - a)).astype(np.uint8)


class Renderer:
    """Turns a RenderConfig into frames, one timestamp at a time."""

    def __init__(self, cfg):
        cfg = normalize(cfg)
        self.cfg = cfg
        self.W = cfg.width
        self.H = cfg.height
        self.scale = self.H / _REF_HEIGHT
        self.total = float(cfg.total_seconds)
        self.countdown = max(1.0, self.total)

        self.digits_cy = _DIGITS_CY * self.scale
        self.font_size = max(8, int(round(_FONT_SIZE * self.scale)))
        self.glow_radius = max(1.0, _GLOW_RADIUS * self.scale)
        self.text_pad = int(self.glow_radius * 3)

        self.font = self._load_font()
        self.cell = None if cfg.proportional else digit_cell(self.font)

        # Slant is the italic amount, but only applied when the user asked for
        # italic text.
        self.slant = cfg.slant if cfg.italic else 0.0

        self.outline = cfg.outline if cfg.contrast else 0.0
        self.shadow = cfg.shadow if cfg.contrast else 0.0

        self._configure_colors()
        self.base = self._build_base()

        self.sprite_cache = {}
        self._cached_key = None
        self._cached_frame = None
        self.alpha_canvas = np.zeros((self.H, self.W, 4), dtype=np.uint8)

    # -- setup ---------------------------------------------------------

    def _configure_colors(self):
        mode = self.cfg.export_mode
        if mode == MODE_LUMA:
            # White on pure black so a luma key in ProPresenter is clean.
            self.fill_rgb = LUMA_WHITE
            self.glow_rgb = (255, 255, 255)
            self.glow_alpha = 0
            return

        self.fill_rgb = hex_to_rgb(self.cfg.color)
        if self.cfg.mode == "light":
            # A warm glow on a light background reads as a smudge.
            self.glow_rgb = (0, 0, 0)
        else:
            self.glow_rgb = GLOW_WARM
        self.glow_alpha = int(_GLOW_ALPHA * self.cfg.glow_alpha) if self.cfg.glow else 0

    def _load_font(self):
        try:
            return ImageFont.truetype(self.cfg.font_file, self.font_size)
        except (OSError, ValueError):
            return ImageFont.load_default()

    def _build_base(self):
        mode = self.cfg.export_mode
        if mode in (MODE_ALPHA, MODE_LUMA):
            fill = 0
            return np.full((self.H, self.W, 3), fill, dtype=np.uint8)

        if not self.cfg.background:
            return np.zeros((self.H, self.W, 3), dtype=np.uint8)
        try:
            with Image.open(self.cfg.background) as img:
                fitted = fit_image(img.convert("RGB"), self.W, self.H, self.cfg.fit)
            return np.asarray(fitted).copy()
        except (OSError, ValueError):
            return np.zeros((self.H, self.W, 3), dtype=np.uint8)

    # -- text ----------------------------------------------------------

    def _text_for(self, display):
        mode = self.cfg.final_minute
        if mode == FINAL_MINUTE_STANDARD:
            return format_time(display, True)
        if display >= 60:
            return format_time(display, True)
        if mode == FINAL_MINUTE_FIXED:
            return "%02d" % display
        return format_time(display, False)

    def _sprite_for(self, display):
        text = self._text_for(display)
        key = (text, self.fill_rgb, self.glow_alpha, self.outline, self.shadow)
        sprite = self.sprite_cache.get(key)
        if sprite is None:
            sprite = make_sprite(
                text, self.font, self.fill_rgb, self.glow_rgb,
                self.glow_radius, self.glow_alpha, self.text_pad,
                slant=self.slant, cell=self.cell,
                outline=self.outline, shadow=self.shadow,
            )
            if len(self.sprite_cache) > 64:
                self.sprite_cache.pop(next(iter(self.sprite_cache)))
            self.sprite_cache[key] = sprite
        return sprite

    def _sprite_position(self, sprite):
        _, scx, scy = sprite
        return self.W / 2.0 - scx, self.digits_cy - scy

    def _display_for(self, t):
        remaining = max(0.0, self.countdown - t)
        return 0 if remaining <= 0 else int(math.ceil(remaining - 1e-6))

    # -- frames --------------------------------------------------------

    def frame_rgba(self, t):
        """Render one frame as an RGBA uint8 array of shape (H, W, 4)."""
        sprite = self._sprite_for(self._display_for(t))
        x, y = self._sprite_position(sprite)

        out = self.alpha_canvas
        out[:] = 0
        composite_into_rgba(out, sprite[0], x, y)

        if self.cfg.fade_in and 0 <= t < _FADE_IN_SECONDS:
            k = max(0.0, t / _FADE_IN_SECONDS)
            out[..., 3:4] = (out[..., 3:4].astype(np.float32) * k).astype(np.uint8)
        return out

    def frame(self, t):
        """Render one frame as an RGB uint8 array of shape (H, W, 3)."""
        mode = self.cfg.export_mode

        if mode == MODE_ALPHA:
            return flatten(self.frame_rgba(t), 128)
        if mode == MODE_LUMA:
            return flatten(self.frame_rgba(t), 0)

        sprite = self._sprite_for(self._display_for(t))
        key = (id(sprite), self.cfg.fade_in, round(t, 6) if t < _FADE_IN_SECONDS else -1)

        if key == self._cached_key:
            return self._cached_frame

        canvas = self.base.copy()
        composite_into(canvas, sprite[0], *self._sprite_position(sprite))

        if self.cfg.fade_in and 0 <= t < _FADE_IN_SECONDS:
            k = max(0.0, t / _FADE_IN_SECONDS)
            canvas = (self.base.astype(np.float32) * (1.0 - k) +
                      canvas.astype(np.float32) * k).astype(np.uint8)

        self._cached_key = key
        self._cached_frame = canvas
        return canvas

    def frame_count(self, fps=None):
        fps = fps or self.cfg.fps
        total = self.total + max(0.0, self.cfg.hold_seconds)
        return max(1, int(round(total * fps)))

    def preview(self, t=0.0, max_width=960):
        """A downscaled RGB PIL image for the GUI preview."""
        frame = self.frame(t)
        img = Image.fromarray(frame)
        if img.width > max_width:
            h = max(1, int(round(img.height * max_width / img.width)))
            img = img.resize((max_width, h), Image.LANCZOS)
        return img