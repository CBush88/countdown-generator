"""Small custom ttk widgets used by the Countdown Generator window."""

import os

import tkinter as tk
from tkinter import ttk


class Tooltip:
    """Attach a hover tooltip to any widget."""

    _instances = 0

    def __init__(self, widget, text, delay=450):
        self.widget = widget
        self.text = text
        self.delay = delay
        self._after = None
        self._window = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._cancel()
        self._after = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self._after is not None:
            try:
                self.widget.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None

    def _show(self):
        if self._window or not self.text:
            return
        x = self.widget.winfo_rootx() + 16
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self._window = tk.Toplevel(self.widget)
        self._window.wm_overrideredirect(True)
        self._window.wm_geometry("+%d+%d" % (x, y))
        label = tk.Label(self._window, text=self.text, justify="left",
                         background="#1e1e1e", foreground="#e8e8e8",
                         relief="solid", borderwidth=1,
                         font=("TkDefaultFont", 9), padx=8, pady=5,
                         wraplength=420)
        label.pack()

    def _hide(self, _event=None):
        self._cancel()
        if self._window:
            self._window.destroy()
            self._window = None


class ColorSwatch(tk.Frame):
    """A clickable colour chip with an optional hex label."""

    def __init__(self, master, command=None, width=64, height=26, **kw):
        super().__init__(master, **kw)
        self.command = command
        self._hex = "#F2EFE6"
        self.canvas = tk.Canvas(self, width=width, height=height, highlightthickness=0,
                                background="#3a3a3a")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self._clicked)
        self.set("#F2EFE6")

    def set(self, hex_value):
        self._hex = (hex_value or "#000000").upper()
        self.canvas.delete("all")
        self.canvas.create_rectangle(0, 0, 2000, 2000, fill=self._hex, outline="")
        self.canvas.create_rectangle(0, 0, self.winfo_width() - 1,
                                     self.winfo_height() - 1,
                                     outline="#555555")

    def get(self):
        return self._hex

    def _clicked(self, _event=None):
        if self.command:
            self.command()


class DropTarget(tk.Label):
    """A label that accepts a dropped file path via drag-and-drop."""

    def __init__(self, master, command=None, **kw):
        super().__init__(master, **kw)
        self.command = command
        self.configure(background="#2a2a2a", foreground="#9a9a9a",
                       relief="groove", borderwidth=1, padx=8, pady=10)
        self.bind("<Button-1>", lambda e: self.command() if self.command else None)
        _register_drop(self, self._on_drop)

    def _on_drop(self, path):
        if self.command:
            self.command(path)

    def set_text(self, text):
        self.configure(text=text)

    def set_path(self, path):
        if path:
            name = os.path.basename(path)
            self.configure(text="%s\n(click to change)" % name, foreground="#d0d0d0")
        else:
            self.configure(text="Click to choose a background image",
                           foreground="#9a9a9a")


def _register_drop(widget, callback):
    """Enable drag-and-drop on platforms that expose Tk's XDND, else no-op."""
    try:
        widget.drop_target_register("DND_Files")
        widget.dnd_bind("<<Drop>>", lambda e: _parse_drop(e.data, callback))
    except (AttributeError, tk.TclError):
        # tkinterdnd2 is not installed; clicking still works.
        pass


def _parse_drop(data, callback):
    if not data:
        return
    for token in data.split():
        path = token.strip("{}")
        if path and os.path.exists(path):
            callback(path)
            return