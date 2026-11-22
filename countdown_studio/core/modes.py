"""Export-mode helpers shared by the GUI and CLI."""

import os

from .config import ALPHA_PNG, ALPHA_PRORES, MODE_ALPHA, MODE_BAKED, MODE_LUMA


def default_extension(cfg):
    """Output file extension for the current export settings."""
    if cfg.export_mode == MODE_ALPHA:
        return ".zip" if cfg.alpha_format == ALPHA_PNG else ".mov"
    return ".mp4"


def suggested_filename(cfg):
    """A readable default output name, e.g. 'countdown-5m00s.mp4'."""
    total = cfg.total_seconds
    stem = "countdown-%dm%02ds" % (total // 60, total % 60)
    if cfg.export_mode == MODE_ALPHA:
        stem += "-alpha"
    elif cfg.export_mode == MODE_LUMA:
        stem += "-luma"
    return stem + default_extension(cfg)


def output_path(cfg, directory):
    """Place a freshly named render inside ``directory``, avoiding collisions.

    ``last_output`` only remembers the folder between sessions; the file name
    always comes from the current settings so it matches the timer length and
    export mode. Returning ``last_output`` verbatim made the GUI's output-folder
    field a no-op and could write a file into a folder the user had left.
    """
    name = suggested_filename(cfg)
    path = os.path.join(directory, name)
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(name)
    i = 2
    while os.path.exists(path):
        path = os.path.join(directory, "%s-%d%s" % (stem, i, ext))
        i += 1
    return path


def mode_tooltips():
    """Explanatory text for each export mode."""
    return {
        MODE_BAKED: (
            "The background image is drawn into the video. Plays anywhere and "
            "produces a small file. Use this when the background is always the "
            "same image."
        ),
        MODE_ALPHA: (
            "The background is omitted and transparency is stored in the file, "
            "so you can layer the timer over other slides or a live camera in "
            "ProPresenter. Needs an alpha-capable codec and produces very large "
            "files."
        ),
        MODE_LUMA: (
            "White text on pure black with no transparency. In ProPresenter, use "
            "a luma (brightness) key to drop the black. Works with any MP4 and "
            "any platform, at the cost of slightly softer edges."
        ),
    }


def alpha_format_notes():
    return {
        ALPHA_PRORES: (
            "ProRes 4444 .mov is the standard alpha format for ProPresenter on "
            "macOS. Windows support is weaker; if it misbehaves, choose the PNG "
            "sequence instead."
        ),
        ALPHA_PNG: (
            "A ZIP of lossless PNG frames with transparency. Works on any "
            "platform but is large (several GB) and contains thousands of files."
        ),
    }