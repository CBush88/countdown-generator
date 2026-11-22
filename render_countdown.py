#!/usr/bin/env python3
"""Render a countdown timer video over a background image (for ProPresenter)."""

import argparse
import math
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_BOLD = "/usr/share/fonts/noto/NotoSans-Bold.ttf"
REFERENCE_TEXT = "0123456789:"

CREAM = (242, 239, 230)
AMBER = (255, 180, 60)


def format_time(secs, show_minutes=True):
    secs = max(0, int(secs))
    if show_minutes:
        return "%d:%02d" % (secs // 60, secs % 60)
    return str(secs)


def urgency(remaining):
    """Fill colour and glow multiplier for the current time remaining."""
    return CREAM, 1.0


def digit_cell(font):
    """Advance width of a fixed cell that fits every digit, so digits never jitter."""
    widths = [font.getlength(d) for d in "0123456789"]
    return max(widths)


def make_text_sprite(text, font, fill, glow_rgb, glow_radius, glow_alpha, pad,
                     slant=0.0, cell=None):
    probe = ImageDraw.Draw(Image.new("L", (8, 8)))
    ref = probe.textbbox((0, 0), REFERENCE_TEXT, font=font)
    tw, th = ref[2] - ref[0], ref[3] - ref[1]
    if cell:
        colon_w = font.getlength(":")
        tw = sum(colon_w if ch == ":" else cell for ch in text)

    slant_px = int(round(th * slant))
    W, H = int(tw + pad * 2 + abs(slant_px)), int(th + pad * 2)

    mask = Image.new("L", (W, H), 0)
    ox = pad + (slant_px if slant_px < 0 else 0)
    d = ImageDraw.Draw(mask)
    base = pad - ref[1]

    if cell:
        x = float(ox - ref[0])
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

    if slant:
        mask = mask.transform(
            (W, H), Image.AFFINE,
            (1, slant, -slant * (pad + th), 0, 1, 0),
            resample=Image.BICUBIC,
        )

    sprite = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if glow_alpha > 0:
        glow = mask.filter(ImageFilter.GaussianBlur(glow_radius))
        glow = glow.point(lambda v: int(v * glow_alpha / 255))
        layer = Image.new("RGBA", (W, H), tuple(glow_rgb) + (0,))
        layer.putalpha(glow)
        sprite = Image.alpha_composite(sprite, layer)

    layer = Image.new("RGBA", (W, H), tuple(fill) + (0,))
    layer.putalpha(mask)
    sprite = Image.alpha_composite(sprite, layer)
    return sprite, W / 2.0, H / 2.0


def composite(canvas, sprite, x, y, opacity=1.0):
    x, y = int(round(x)), int(round(y))
    x0, y0 = max(0, x), max(0, y)
    x1 = min(canvas.shape[1], x + sprite.width)
    y1 = min(canvas.shape[0], y + sprite.height)
    if x1 <= x0 or y1 <= y0:
        return
    sub = sprite.crop((x0 - x, y0 - y, x0 - x + (x1 - x0), y0 - y + (y1 - y0)))
    a = np.asarray(sub, dtype=np.float32)
    alpha = (a[..., 3:4] / 255.0) * float(opacity)
    dst = canvas[y0:y1, x0:x1].astype(np.float32)
    canvas[y0:y1, x0:x1] = (dst * (1.0 - alpha) + a[..., :3] * alpha).astype(np.uint8)


def draw_bar(canvas, cx, cy, bar_w, bar_h, frac, fill, pad, opacity=1.0):
    area = Image.new("RGBA", (int(bar_w) + pad * 2, int(bar_h) + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(area)
    ox, oy, r = pad, pad, bar_h / 2.0

    d.rounded_rectangle([ox, oy, ox + bar_w - 1, oy + bar_h - 1], radius=r,
                        fill=(255, 255, 255, 26))

    fw = max(0.0, min(1.0, frac)) * bar_w
    if fw >= 1.0:
        glow_src = Image.new("L", area.size, 0)
        ImageDraw.Draw(glow_src).rounded_rectangle(
            [ox, oy, ox + fw - 1, oy + bar_h - 1], radius=r, fill=105)
        glow = glow_src.filter(ImageFilter.GaussianBlur(bar_h * 0.9))
        glow_layer = Image.new("RGBA", area.size, tuple(fill) + (0,))
        glow_layer.putalpha(glow)
        area = Image.alpha_composite(glow_layer, area)

        d = ImageDraw.Draw(area)
        d.rounded_rectangle([ox, oy, ox + fw - 1, oy + bar_h - 1], radius=r,
                            fill=tuple(fill) + (235,))

    if opacity < 1.0:
        area.putalpha(area.getchannel("A").point(lambda v: int(v * opacity)))

    composite(canvas, area, cx - area.width / 2.0, cy - area.height / 2.0)


class Renderer:
    def __init__(self, args):
        self.args = args
        self.W, self.H = args.width, args.height
        self.s = self.H / 2160.0
        self.countdown = args.minutes * 60.0
        self.digits_cy = 1040 * self.s
        self.bar_cy = 1450 * self.s
        self.bar_w = 1500 * self.s
        self.bar_h = max(6.0, 14 * self.s)
        self.bar_pad = int(self.bar_h * 4)
        self.glow_radius = max(2.0, 34 * self.s)
        self.text_pad = int(self.glow_radius * 3)
        self.font = ImageFont.truetype(args.font, int(round(950 * self.s)))
        self.slant = args.slant
        self.cell = digit_cell(self.font) if not args.proportional else None

        bg = Image.open(args.bg).convert("RGB")
        if bg.size != (self.W, self.H):
            bg = bg.resize((self.W, self.H), Image.LANCZOS)
        self.plate = np.asarray(bg).copy()
        self.canvas = self.plate.copy()

        self.sprite_cache = {}
        self.cur_key = None

    def frame(self, t):
        a = self.args
        remaining = max(0.0, self.countdown - t)
        display = 0 if remaining <= 0 else int(math.ceil(remaining - 1e-6))
        fill, gscale = urgency(remaining)

        glow_alpha = int(max(0, min(255, 105 * gscale)))
        glow_alpha = (glow_alpha // 32) * 32

        show_minutes = display >= 60
        text = format_time(display, show_minutes)
        key = (text, fill, glow_alpha)
        if key != self.cur_key:
            sprite = self.sprite_cache.get(key)
            if sprite is None:
                sprite = make_text_sprite(text, self.font, fill, AMBER,
                                          self.glow_radius, glow_alpha, self.text_pad,
                                          slant=self.slant, cell=self.cell)
                if len(self.sprite_cache) > 48:
                    self.sprite_cache.pop(next(iter(self.sprite_cache)))
                self.sprite_cache[key] = sprite
            self.canvas[:] = self.plate
            img, scx, scy = sprite
            composite(self.canvas, img, self.W / 2.0 - scx, self.digits_cy - scy)
            self.cur_key = key

        if not a.no_bar:
            by0 = int(self.bar_cy - (self.bar_h + self.bar_pad * 2) / 2)
            bh = int(self.bar_h + self.bar_pad * 2)
            self.canvas[by0:by0 + bh, :] = self.plate[by0:by0 + bh, :]
            draw_bar(self.canvas, self.W / 2.0, self.bar_cy, self.bar_w, self.bar_h,
                     remaining / self.countdown, fill, self.bar_pad)

        if a.fade_in and t < 0.8:
            k = t / 0.8
            self.canvas[:] = (self.plate.astype(np.float32) * (1 - k) +
                              self.canvas.astype(np.float32) * k).astype(np.uint8)
        return self.canvas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bg", default="Crossway corner 2160p.png")
    ap.add_argument("--font", default=FONT_BOLD,
                    help="path to a .ttf/.otf font file")
    ap.add_argument("--slant", type=float, default=0.0,
                    help="synthetic italic shear, e.g. 0.22")
    ap.add_argument("--proportional", action="store_true",
                    help="use the font's natural widths instead of fixed digit cells")
    ap.add_argument("--out", default="5min-countdown-4k.mp4")
    ap.add_argument("--minutes", type=float, default=5.0)
    ap.add_argument("--hold", type=float, default=5.0)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--width", type=int, default=3840)
    ap.add_argument("--height", type=int, default=2160)
    ap.add_argument("--crf", type=int, default=18)
    ap.add_argument("--preset", default="medium")
    ap.add_argument("--no-fade-in", dest="fade_in", action="store_false")
    ap.add_argument("--no-bar", dest="no_bar", action="store_true")
    ap.add_argument("--preview", default=None)
    args = ap.parse_args()

    r = Renderer(args)
    total = r.countdown + args.hold

    if args.preview:
        for ts in args.preview.split(","):
            Image.fromarray(r.frame(float(ts))).save("preview-%05.1f.png" % float(ts))
        print("previews written")
        return

    frames = int(round(total * args.fps))
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", "%dx%d" % (r.W, r.H), "-r", str(args.fps), "-i", "-",
        "-an", "-c:v", "libx264", "-preset", args.preset, "-crf", str(args.crf),
        "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "5.1",
        "-g", str(args.fps * 2), "-bf", "2",
        "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
        "-movflags", "+faststart", args.out,
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(frames):
        proc.stdin.write(r.frame(i / float(args.fps)).tobytes())
        if i % 300 == 0:
            print("frame %d/%d" % (i, frames), flush=True)
    proc.stdin.close()
    if proc.wait() != 0:
        sys.exit("ffmpeg failed")
    print("wrote %s" % args.out)


if __name__ == "__main__":
    main()