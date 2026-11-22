"""Command-line interface for Countdown Generator.

Mirrors the renderer used by the GUI so anything scriptable here produces
exactly what the window would.
"""

import argparse
import os
import sys

from .core.config import (
    ALPHA_CHOICES,
    ALPHA_PRORES,
    DARK_TEXT,
    FINAL_MINUTE_BARE,
    FINAL_MINUTE_CHOICES,
    FIT_CHOICES,
    FIT_FILL,
    MODE_ALPHA,
    MODE_BAKED,
    MODE_CHOICES,
    MODE_LUMA,
    RES_1080,
    RES_CHOICES,
    RenderConfig,
)
from .core.encode import Progress, RenderError, render
from .core.ffmpeg import find_ffmpeg, install_hint

# Kept in step with RenderConfig.slant; used when --italic is given without --slant.
DEFAULT_SLANT = 0.22


def build_parser():
    p = argparse.ArgumentParser(
        prog="countdown-studio",
        description="Render a countdown timer video for ProPresenter.")
    p.add_argument("--background", default="", help="background image")
    p.add_argument("--fit", choices=[v for v, _ in FIT_CHOICES], default=FIT_FILL)
    p.add_argument("--font", default="", help="font file (.ttf/.otf/.ttc)")
    p.add_argument("--font-family", default="", help="installed font family name")
    p.add_argument("--color", default=DARK_TEXT, help="text colour as hex")
    p.add_argument("--mode", choices=["dark", "light"], default="dark")
    p.add_argument("--italic", action="store_true",
                   help="slant the digits for a synthetic italic (amount: --slant)")
    p.add_argument("--slant", type=float, default=None,
                   help="italic slant amount, e.g. 0.22; implies --italic")
    p.add_argument("--proportional", action="store_true",
                   help="use the font's natural widths instead of fixed digit cells")
    p.add_argument("--contrast", action="store_true", help="enable shadow + outline")
    p.add_argument("--shadow", type=float, default=0.55)
    p.add_argument("--outline", type=float, default=0.0)
    p.add_argument("--no-glow", dest="glow", action="store_false")

    p.add_argument("--minutes", type=int, default=5)
    p.add_argument("--seconds", type=int, default=0)
    p.add_argument("--final-minute", choices=[v for v, _ in FINAL_MINUTE_CHOICES],
                   default=FINAL_MINUTE_BARE)
    p.add_argument("--hold", type=float, default=5.0,
                   help="seconds to hold on 0:00 after the timer ends")
    p.add_argument("--no-fade-in", dest="fade_in", action="store_false")

    p.add_argument("--resolution", choices=[v for v, _ in RES_CHOICES],
                   default=RES_1080)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--crf", type=int, default=18)
    p.add_argument("--preset", default="medium")

    p.add_argument("--export", choices=[v for v, _ in MODE_CHOICES], default=MODE_BAKED)
    p.add_argument("--alpha-format", choices=[v for v, _ in ALPHA_CHOICES],
                   default=ALPHA_PRORES)

    p.add_argument("--output", default="", help="output file path")
    p.add_argument("--list-fonts", action="store_true",
                   help="print available font families and exit")
    p.add_argument("--quiet", action="store_true")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.list_fonts:
        from .core.fonts import families
        for name in families():
            print(name)
        return 0

    cfg = RenderConfig(
        background=args.background,
        fit=args.fit,
        minutes=args.minutes,
        seconds=args.seconds,
        final_minute=args.final_minute,
        hold_seconds=args.hold,
        fade_in=args.fade_in,
        color=args.color,
        mode=args.mode,
        auto_mode=False,
        # --slant implies --italic so existing command lines keep working.
        italic=bool(args.italic or args.slant is not None),
        slant=DEFAULT_SLANT if args.slant is None else args.slant,
        proportional=args.proportional,
        contrast=args.contrast,
        shadow=args.shadow,
        outline=args.outline,
        glow=args.glow,
        resolution=args.resolution,
        fps=args.fps,
        crf=args.crf,
        preset=args.preset,
        export_mode=args.export,
        alpha_format=args.alpha_format,
        last_output=args.output,
    )

    if args.font:
        cfg.font_file = args.font
    elif args.font_family:
        from .core.fonts import find_font
        cfg.font_file = find_font(args.font_family)
        cfg.font_family = args.font_family

    if not cfg.last_output:
        from .core.modes import suggested_filename
        cfg.last_output = os.path.join(os.getcwd(), suggested_filename(cfg))

    problems = cfg.validate()
    if problems:
        for problem in problems:
            print("error: %s" % problem, file=sys.stderr)
        return 2

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        print("error: %s" % install_hint(), file=sys.stderr)
        return 3

    progress = Progress()
    stop = {"done": False}

    def ticker():
        import time
        last = -1.0
        while not stop["done"]:
            value = progress.value
            if value - last >= 0.02 or value >= 1.0:
                last = value
                if not args.quiet:
                    sys.stdout.write("\r%s  %5.1f%%" % (progress.message[:40].ljust(40),
                                                        value * 100))
                    sys.stdout.flush()
            time.sleep(0.1)

    import threading
    thread = threading.Thread(target=ticker, daemon=True)
    thread.start()

    try:
        path = render(cfg, progress, ffmpeg)
    except RenderError as exc:
        stop["done"] = True
        print("\nerror: %s" % exc, file=sys.stderr)
        return 1

    stop["done"] = True
    if not args.quiet:
        print("\r" + " " * 70 + "\rWrote %s" % path)
    return 0