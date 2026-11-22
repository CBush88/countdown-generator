#!/usr/bin/env python3
"""Countdown Generator - entry point.

Usage:
    python countdown-studio.py            # open the window
    python countdown-studio.py --help     # command-line options
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from countdown_studio.cli import main as cli_main


def main():
    if len(sys.argv) > 1:
        return cli_main()

    try:
        import tkinter  # noqa: F401
    except ImportError:
        sys.stderr.write(
            "Countdown Generator needs Tkinter, which is not installed.\n"
            "\n"
            "On Debian/Ubuntu:  sudo apt install python3-tk\n"
            "On Fedora:         sudo dnf install python3-tkinter\n"
            "On Arch:           sudo pacman -S tk\n"
            "On macOS/Windows: Tkinter ships with python.org installers.\n"
            "\n"
            "You can still use the command line: python countdown-studio.py --help\n")
        return 1

    from countdown_studio.gui.app import CountdownStudio
    app = CountdownStudio()
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())