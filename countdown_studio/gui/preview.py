"""Live preview panel.

Renders a single frame with PIL and hands it to Tkinter. This is deliberately
kept separate from the encoder: previewing must never spawn ffmpeg, so it
stays responsive while the user drags a slider.
"""

import tkinter as tk

from PIL import Image, ImageTk

from ..core.renderer import Renderer


class PreviewPanel(tk.Frame):
    """Displays a scaled preview of the countdown.

    The canvas is sized by the geometry manager, not by us: asking Tk for
    ``winfo_width()``/``winfo_height()`` before the widget is mapped returns 1,
    which used to make the first preview draw at the wrong offset and then jump
    once layout settled. We keep the rendered frame and re-fit it whenever the
    canvas actually changes size.
    """

    def __init__(self, master, max_width=900, max_height=520, **kw):
        super().__init__(master, **kw)
        self.max_width = max_width
        self.max_height = max_height
        self._image = None      # ImageTk.PhotoImage, keep a reference
        self._source = None     # PIL.Image at render size
        self._item = None       # canvas item id
        self._after = None
        self._pending = None

        self.canvas = tk.Canvas(self, background="#111111", highlightthickness=1,
                                highlightbackground="#3a3a3a", width=max_width,
                                height=max_height)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _event: self._relayout())

        self.badge = tk.Label(self, text="", background="#111111", foreground="#8a8a8a",
                              font=("TkDefaultFont", 9), anchor="w")
        self.badge.pack(fill="x")

    # -- sizing --------------------------------------------------------

    def _available(self):
        """Current canvas size in pixels, falling back to the requested size."""
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w < 2 or h < 2:      # not mapped yet
            return self.max_width, self.max_height
        return w, h

    def _fit(self, img):
        """Scale ``img`` down to fit the canvas, preserving aspect ratio."""
        w, h = self._available()
        if not img.width or not img.height:
            return img
        scale = min(w / img.width, h / img.height, 1.0)
        if scale >= 1.0:
            return img
        size = (max(1, int(round(img.width * scale))),
                max(1, int(round(img.height * scale))))
        return img.resize(size, Image.LANCZOS)

    # -- drawing -------------------------------------------------------

    def _relayout(self):
        """Re-fit and re-centre the current frame for the current canvas size."""
        if self._source is None:
            return
        img = self._fit(self._source)
        self._image = ImageTk.PhotoImage(img)
        self.canvas.delete("all")
        self._item = self.canvas.create_image(0, 0, image=self._image)
        self._recenter()

    def _recenter(self):
        if self._item is None:
            return
        w, h = self._available()
        self.canvas.coords(self._item, w / 2.0, h / 2.0)

    def show(self, renderer, t=0.0):
        """Render and display a preview at time ``t``."""
        try:
            self._source = renderer.preview(t, max_width=self.max_width)
        except Exception as exc:  # keep the window alive on any render error
            self._source = None
            self.set_error(str(exc))
            return
        self._relayout()

    def set_image(self, img):
        """Display an already-rendered PIL image."""
        if not isinstance(img, Image.Image):
            return
        self._source = img
        self._relayout()

    def set_error(self, message):
        self._source = None
        self._item = None
        self.canvas.delete("all")
        self.canvas.create_text(20, 20, anchor="nw", fill="#d06060",
                                text=message, font=("TkDefaultFont", 10))

    def schedule(self, renderer, t=0.0, delay=90):
        """Coalesce rapid updates so dragging a slider stays smooth."""
        self._pending = (renderer, t)
        if self._after is None:
            self._after = self.after(delay, self._flush)

    def _flush(self):
        self._after = None
        if self._pending:
            renderer, t = self._pending
            self._pending = None
            self.show(renderer, t)

    def set_badge(self, text):
        self.badge.configure(text=text)