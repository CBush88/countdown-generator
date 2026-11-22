"""Countdown Generator main window."""

import os
import queue
import threading
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

from ..core import (
    ALPHA_CHOICES,
    FIT_FILL,
    ALPHA_PNG,
    ALPHA_PRORES,
    DARK_TEXT,
    FINAL_MINUTE_BARE,
    FINAL_MINUTE_CHOICES,
    FIT_CHOICES,
    MODE_ALPHA,
    MODE_BAKED,
    MODE_CHOICES,
    RES_1080,
    RES_CHOICES,
    RenderConfig,
    background_brightness,
    imported_font_dir,
    load_user_config,
    normalize,
    result_color_for_background,
    save_user_config,
)
from ..core import fonts as fontlib
from ..core.encode import Progress, RenderCancelled, RenderError, render
from ..core.modes import alpha_format_notes, mode_tooltips, output_path
from .preview import PreviewPanel
from .widgets import ColorSwatch, DropTarget, Tooltip

BG = "#1b1b1b"
PANEL = "#242424"
FG = "#e6e6e6"
MUTED = "#9a9a9a"
ACCENT = "#3d6ea8"
WARN = "#d0a040"

# The preview shows the start of the countdown rather than a fixed offset. This
# is just past the fade-in so the digits are fully opaque.
PREVIEW_TIME = 0.8


def _label(parent, text, row, col=0, sticky="w", **kw):
    widget = tk.Label(parent, text=text, background=PANEL, foreground=kw.pop("fg", FG),
                      anchor="w", **kw)
    widget.grid(row=row, column=col, sticky=sticky, padx=(10, 4), pady=3)
    return widget


def _frame(parent):
    f = tk.Frame(parent, background=PANEL)
    return f


class CountdownStudio(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Countdown Generator")
        self.geometry("1180x760")
        self.minsize(1000, 640)
        self.configure(background=BG)

        self.cfg = load_user_config()
        self.render_thread = None
        self.render_queue = queue.Queue()
        self._progress = None
        self._preview_key = None

        # ttk.Scale fires its `command` the instant `.set()` is called, so
        # building and populating the layout re-enters _read_widgets() while
        # the widgets still hold their constructor defaults. Without this guard
        # that clobbered the freshly loaded config - a saved 1920x1080 came
        # back as 720p because the resolution combobox had not been synced yet.
        self._syncing = True
        self._init_style()
        self._build_layout()
        try:
            self._sync_from_config()
        finally:
            self._syncing = False
        self._refresh_preview()
        self.after(120, self._poll_render)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # -- styling -------------------------------------------------------

    def _init_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=PANEL, foreground=FG, fieldbackground="#2f2f2f",
                        bordercolor="#3a3a3a", lightcolor="#3a3a3a",
                        darkcolor="#2a2a2a")
        style.configure("TLabel", background=PANEL, foreground=FG)
        style.configure("TCheckbutton", background=PANEL, foreground=FG)
        style.configure("TRadiobutton", background=PANEL, foreground=FG)
        style.configure("TButton", background="#333333", foreground=FG, padding=5)
        style.map("TButton",
                  background=[("active", "#3d3d3d"), ("disabled", "#2a2a2a")])
        style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff")
        style.map("Accent.TButton", background=[("active", "#4a7fc4")])
        style.configure("TEntry", fieldbackground="#2f2f2f", foreground=FG)
        style.configure("TCombobox", fieldbackground="#2f2f2f", background="#333333",
                        foreground=FG, arrowcolor=FG)
        style.map("TCombobox", fieldbackground=[("readonly", "#2f2f2f")])
        style.configure("Horizontal.TProgressbar", background=ACCENT,
                        troughcolor="#2a2a2a", bordercolor="#3a3a3a",
                        lightcolor=ACCENT, darkcolor=ACCENT)

    # -- layout --------------------------------------------------------

    def _build_layout(self):
        outer = tk.Frame(self, background=BG)
        outer.pack(fill="both", expand=True, padx=10, pady=10)
        outer.columnconfigure(0, weight=1)
        outer.columnconfigure(1, weight=0)
        outer.rowconfigure(0, weight=1)

        left = tk.Frame(outer, background=BG)
        left.grid(row=0, column=0, sticky="nsew")
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)

        self.preview = PreviewPanel(left, max_width=860, max_height=500)
        self.preview.grid(row=0, column=0, sticky="nsew")

        controls = tk.Frame(left, background=BG)
        controls.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.render_btn = ttk.Button(controls, text="Render video",
                                     style="Accent.TButton", command=self._start_render)
        self.render_btn.pack(side="left")
        self.cancel_btn = ttk.Button(controls, text="Cancel", command=self._cancel_render,
                                     state="disabled")
        self.cancel_btn.pack(side="left", padx=(8, 0))
        self.preview_now = ttk.Button(controls, text="Refresh preview",
                                      command=self._refresh_preview)
        self.preview_now.pack(side="left", padx=(8, 0))

        self.progress = ttk.Progressbar(controls, mode="determinate",
                                        style="Horizontal.TProgressbar", length=240)
        self.progress.pack(side="left", padx=(16, 0), fill="x", expand=True)
        self.status = tk.Label(controls, text="Ready", background=BG, foreground=MUTED)
        self.status.pack(side="left", padx=(12, 0))

        # Right-hand settings panel in a scrollable canvas.
        sidebar = tk.Frame(outer, background=PANEL, width=430)
        sidebar.grid(row=0, column=1, sticky="nse", padx=(10, 0))
        sidebar.pack_propagate(False)
        sidebar.grid_propagate(False)

        canvas = tk.Canvas(sidebar, background=PANEL, highlightthickness=0, width=420)
        scroll = ttk.Scrollbar(sidebar, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.body = tk.Frame(canvas, background=PANEL)
        window = canvas.create_window((0, 0), window=self.body, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))
        self.body.bind("<Configure>",
                       lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        self._build_sections()

    def _section(self, title, row):
        header = tk.Frame(self.body, background=PANEL)
        header.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(14, 4))
        tk.Label(header, text=title, background=PANEL, foreground=MUTED,
                 font=("TkDefaultFont", 9, "bold")).pack(side="left", padx=(10, 0))
        return header

    def _row(self, parent, text, row, help_text=None):
        f = tk.Frame(parent, background=PANEL)
        f.grid(row=row, column=0, columnspan=3, sticky="ew", padx=10, pady=2)
        f.columnconfigure(1, weight=1)
        lab = tk.Label(f, text=text, background=PANEL, foreground=FG, anchor="w")
        lab.grid(row=0, column=0, sticky="w", padx=(0, 8))
        if help_text:
            Tooltip(lab, help_text)
        return f

    # -- sections ------------------------------------------------------

    def _build_sections(self):
        # Every section spans all three columns; let them expand to fill the panel.
        for col in range(3):
            self.body.columnconfigure(col, weight=1)

        r = 0
        self._section("BACKGROUND", r); r += 1

        self.bg_drop = DropTarget(self.body, command=self._choose_background)
        self.bg_drop.grid(row=r, column=0, columnspan=3, sticky="ew", padx=10, pady=4)
        Tooltip(self.bg_drop, "Choose the image behind the timer. Fill mode crops "
                              "edges; fit mode adds letterbox bars.")
        r += 1

        f = self._row(self.body, "Fit", r, "How a background that isn't 16:9 fills the frame.")
        self.fit_var = tk.StringVar(value=FIT_FILL)
        self.fit_combo = ttk.Combobox(f, textvariable=self.fit_var, state="readonly",
                                      values=[label for _v, label in FIT_CHOICES], width=24)
        self.fit_combo.grid(row=0, column=1, sticky="ew")
        self.fit_combo.bind("<<ComboboxSelected>>", lambda e: self._on_change())
        r += 1

        self._section("TIMER", r); r += 1

        f = self._row(self.body, "Minutes", r)
        self.min_var = tk.StringVar(value="5")
        self.min_spin = ttk.Spinbox(f, from_=0, to=180, textvariable=self.min_var, width=6)
        self.min_spin.grid(row=0, column=1, sticky="w")
        self.min_spin.bind("<KeyRelease>", lambda e: self._on_change())
        self.min_spin.bind("<FocusOut>", lambda e: self._on_change())
        r += 1

        f = self._row(self.body, "Seconds", r)
        self.sec_var = tk.StringVar(value="0")
        self.sec_spin = ttk.Spinbox(f, from_=0, to=59, textvariable=self.sec_var, width=6)
        self.sec_spin.grid(row=0, column=1, sticky="w")
        self.sec_spin.bind("<KeyRelease>", lambda e: self._on_change())
        self.sec_spin.bind("<FocusOut>", lambda e: self._on_change())
        r += 1

        f = self._row(self.body, "Final minute", r,
                      "In the last minute the timer can drop the '0:' prefix and "
                      "show bare seconds.")
        self.final_var = tk.StringVar(value=FINAL_MINUTE_BARE)
        self.final_combo = ttk.Combobox(f, textvariable=self.final_var, state="readonly",
                                        values=[label for _v, label in FINAL_MINUTE_CHOICES],
                                        width=24)
        self.final_combo.grid(row=0, column=1, sticky="ew")
        self.final_combo.bind("<<ComboboxSelected>>", lambda e: self._on_change())
        r += 1

        f = self._row(self.body, "Hold at 0:00", r,
                      "Seconds the finished video stays on 0:00 so the operator can "
                      "fade out.")
        self.hold_var = tk.StringVar(value="5")
        self.hold_spin = ttk.Spinbox(f, from_=0, to=60, textvariable=self.hold_var, width=6)
        self.hold_spin.grid(row=0, column=1, sticky="w")
        self.hold_spin.bind("<KeyRelease>", lambda e: self._on_change())
        self.hold_spin.bind("<FocusOut>", lambda e: self._on_change())
        r += 1

        self.fade_var = tk.BooleanVar(value=True)
        self.fade_chk = ttk.Checkbutton(self.body, text="Fade in at the start",
                                        variable=self.fade_var,
                                        command=self._on_change)
        self.fade_chk.grid(row=r, column=0, columnspan=3, sticky="w", padx=(14, 0), pady=4)
        r += 1

        self._section("TEXT", r); r += 1

        f = self._row(self.body, "Font family", r,
                      "Fonts installed on this computer. Use 'Import font file' for "
                      "anything not listed.")
        self.font_var = tk.StringVar(value="")
        self.font_combo = ttk.Combobox(f, textvariable=self.font_var, state="readonly",
                                       width=26)
        self.font_combo.grid(row=0, column=1, sticky="ew")
        self.font_combo.bind("<<ComboboxSelected>>", lambda e: self._on_font_pick())
        self.font_combo.bind("<KeyRelease>", lambda e: self._on_font_pick())
        self.font_combo.bind("<Return>", lambda e: self._on_font_pick())
        r += 1

        f = self._row(self.body, "", r)
        self.style_var = tk.StringVar(value="")
        self.style_combo = ttk.Combobox(f, textvariable=self.style_var, state="readonly",
                                        width=26)
        self.style_combo.grid(row=0, column=1, sticky="ew")
        self.style_combo.bind("<<ComboboxSelected>>", lambda e: self._on_change())
        r += 1

        f = self._row(self.body, "", r)
        self.import_btn = ttk.Button(f, text="Import font file...",
                                     command=self._import_font)
        self.import_btn.grid(row=0, column=1, sticky="w")
        r += 1

        f = self._row(self.body, "Text colour", r,
                      "Auto picks cream on dark backgrounds and near-black on light ones.")
        self.color_swatch = ColorSwatch(f, command=self._choose_color)
        self.color_swatch.grid(row=0, column=1, sticky="w")
        self.color_hex = tk.StringVar(value=DARK_TEXT)
        hex_entry = ttk.Entry(f, textvariable=self.color_hex, width=10)
        hex_entry.grid(row=0, column=2, sticky="w", padx=(6, 0))
        hex_entry.bind("<KeyRelease>", lambda e: self._on_hex_edit())
        hex_entry.bind("<FocusOut>", lambda e: self._on_hex_edit())
        r += 1

        self.auto_mode_var = tk.BooleanVar(value=True)
        self.auto_chk = ttk.Checkbutton(self.body, text="Auto-select mode from background",
                                        variable=self.auto_mode_var,
                                        command=self._on_change)
        self.auto_chk.grid(row=r, column=0, columnspan=3, sticky="w", padx=(14, 0), pady=4)
        r += 1

        f = self._row(self.body, "Background mode", r,
                      "Dark mode uses light text; light mode uses black text.")
        self.mode_var = tk.StringVar(value="dark")
        self.mode_frame = f
        self.mode_dark = ttk.Radiobutton(f, text="Dark", value="dark",
                                         variable=self.mode_var, command=self._on_mode_change)
        self.mode_dark.grid(row=0, column=1, sticky="w")
        self.mode_light = ttk.Radiobutton(f, text="Light", value="light",
                                          variable=self.mode_var, command=self._on_mode_change)
        self.mode_light.grid(row=0, column=1, sticky="w", padx=(70, 0))
        r += 1

        self.italic_var = tk.BooleanVar(value=False)
        self.italic_chk = ttk.Checkbutton(
            self.body, text="Italicize digits (synthetic slant)",
            variable=self.italic_var, command=self._on_italic_toggle)
        self.italic_chk.grid(row=r, column=0, columnspan=3, sticky="w", padx=(14, 0), pady=2)
        Tooltip(self.italic_chk,
                "Shears the digits upright-to-slanted. The bundled fonts are upright, "
                "so this is synthesised rather than a true italic.")
        r += 1

        f = self._row(self.body, "Slant", r,
                      "Italic amount. 0 is upright; around 0.22 matches the look of "
                      "an italic face. Only used when italic is on.")
        self.slant_var = tk.StringVar(value="0.22")
        self.slant_scale = ttk.Scale(f, from_=0.0, to=0.45, orient="horizontal",
                                     command=self._on_scale)
        self.slant_scale.grid(row=0, column=1, sticky="ew")
        self.slant_val = tk.Label(f, text="0.22", background=PANEL, foreground=MUTED,
                                  width=5)
        self.slant_val.grid(row=0, column=2, sticky="w", padx=(6, 0))
        r += 1

        self.glow_var = tk.BooleanVar(value=True)
        self.glow_chk = ttk.Checkbutton(self.body, text="Glow around digits",
                                        variable=self.glow_var, command=self._on_change)
        self.glow_chk.grid(row=r, column=0, columnspan=3, sticky="w", padx=(14, 0), pady=4)
        r += 1

        self._section("CONTRAST", r); r += 1

        self.contrast_var = tk.BooleanVar(value=False)
        self.contrast_chk = ttk.Checkbutton(self.body,
                                            text="High contrast (shadow + outline)",
                                            variable=self.contrast_var,
                                            command=self._on_change)
        self.contrast_chk.grid(row=r, column=0, columnspan=3, sticky="w", padx=(14, 0), pady=4)
        Tooltip(self.contrast_chk,
                "Adds a drop shadow and/or outline so the timer stays readable over "
                "mixed or busy backgrounds.")
        r += 1

        f = self._row(self.body, "Shadow", r)
        self.shadow_var = tk.DoubleVar(value=0.55)
        self.shadow_scale = ttk.Scale(f, from_=0.0, to=1.0, orient="horizontal",
                                      command=self._on_scale)
        self.shadow_scale.grid(row=0, column=1, sticky="ew")
        r += 1

        f = self._row(self.body, "Outline", r)
        self.outline_var = tk.DoubleVar(value=0.0)
        self.outline_scale = ttk.Scale(f, from_=0.0, to=0.06, orient="horizontal",
                                       command=self._on_scale)
        self.outline_scale.grid(row=0, column=1, sticky="ew")
        r += 1

        self._section("OUTPUT", r); r += 1

        f = self._row(self.body, "Resolution", r)
        self.res_var = tk.StringVar(value=RES_1080)
        self.res_combo = ttk.Combobox(f, textvariable=self.res_var, state="readonly",
                                      values=[label for _v, label in RES_CHOICES], width=24)
        self.res_combo.grid(row=0, column=1, sticky="ew")
        self.res_combo.bind("<<ComboboxSelected>>", lambda e: self._on_change())
        r += 1

        f = self._row(self.body, "Export mode", r,
                      "Baked-in includes the background. Alpha and luma key omit it.")
        self.export_var = tk.StringVar(value=MODE_BAKED)
        self.export_combo = ttk.Combobox(f, textvariable=self.export_var, state="readonly",
                                         values=[label for _v, label in MODE_CHOICES],
                                         width=24)
        self.export_combo.grid(row=0, column=1, sticky="ew")
        self.export_combo.bind("<<ComboboxSelected>>", lambda e: self._on_export_change())
        tip = mode_tooltips()
        Tooltip(self.export_combo, tip[MODE_BAKED])
        self.export_tip = tip
        r += 1

        f = self._row(self.body, "Alpha format", r,
                      "Only used when Export mode is Alpha channel.")
        self.alpha_var = tk.StringVar(value=ALPHA_PRORES)
        self.alpha_combo = ttk.Combobox(f, textvariable=self.alpha_var, state="readonly",
                                        values=[label for _v, label in ALPHA_CHOICES],
                                        width=24)
        self.alpha_combo.grid(row=0, column=1, sticky="ew")
        self.alpha_combo.bind("<<ComboboxSelected>>", lambda e: self._on_change())
        self.alpha_notes = alpha_format_notes()
        Tooltip(self.alpha_combo, self.alpha_notes[ALPHA_PRORES])
        self.alpha_row = f
        r += 1

        f = self._row(self.body, "Output folder", r)
        self.outdir_var = tk.StringVar(value=os.path.expanduser("~/Videos"))
        out_entry = ttk.Entry(f, textvariable=self.outdir_var)
        out_entry.grid(row=0, column=1, sticky="ew")
        ttk.Button(f, text="...", width=4,
                   command=self._choose_outdir).grid(row=0, column=2, padx=(6, 0))
        r += 1

        self.save_btn = ttk.Button(self.body, text="Save settings",
                                   command=self._save_settings)
        self.save_btn.grid(row=r, column=0, columnspan=3, sticky="w", padx=(10, 0), pady=10)

    # -- config <-> widgets --------------------------------------------

    def _sync_from_config(self):
        c = self.cfg
        self.bg_drop.set_path(c.background)
        self.fit_var.set(dict(FIT_CHOICES)[c.fit])
        self.min_var.set(str(c.minutes))
        self.sec_var.set(str(c.seconds))
        self.final_var.set(dict(FINAL_MINUTE_CHOICES)[c.final_minute])
        self.hold_var.set("%g" % c.hold_seconds)
        self.fade_var.set(c.fade_in)

        fams = fontlib.families()
        self.font_combo.configure(values=fams)
        family = c.font_family
        if not family and c.font_file:
            family = _family_from_path(c.font_file)
        self.font_var.set(family or (fams[0] if fams else ""))
        self._load_styles_for(family or (fams[0] if fams else ""), c.font_file)

        self.color_hex.set(c.color.upper())
        self.color_swatch.set(c.color)
        self.auto_mode_var.set(c.auto_mode)
        self.mode_var.set(c.mode)
        self.italic_var.set(c.italic)
        self.slant_var.set("%g" % c.slant)
        self.slant_scale.set(c.slant)
        self.slant_val.configure(text="%g" % c.slant)
        self._apply_italic_state()
        self.glow_var.set(c.glow)
        self.contrast_var.set(c.contrast)
        self.shadow_var.set(c.shadow)
        self.shadow_scale.set(c.shadow)
        self.outline_var.set(c.outline)
        self.outline_scale.set(c.outline)
        self.res_var.set(dict(RES_CHOICES)[c.resolution])
        self.export_var.set(dict(MODE_CHOICES)[c.export_mode])
        self.alpha_var.set(dict(ALPHA_CHOICES)[c.alpha_format])
        if c.last_output:
            self.outdir_var.set(os.path.dirname(c.last_output))
        self._update_mode_state()

    def _load_styles_for(self, family, prefer_path=""):
        entries = fontlib.styles_for(family)
        styles = [s for s, _p in entries]
        self.style_combo.configure(values=styles)
        if prefer_path:
            for s, p in entries:
                if os.path.abspath(p) == os.path.abspath(prefer_path):
                    self.style_var.set(s)
                    return
        if styles:
            for s in styles:
                if s.lower() in ("regular", "book", "normal"):
                    self.style_var.set(s)
                    return
            self.style_var.set(styles[0])
        else:
            self.style_var.set("")

    def _on_font_pick(self):
        family = self.font_var.get().strip()
        if not family:
            return
        self._load_styles_for(family)
        self.cfg.font_family = family
        self.cfg.font_file = fontlib.find_font(family, self.style_var.get())
        self._on_change()

    def _read_widgets(self):
        """Copy widget values back into self.cfg."""
        c = self.cfg
        if self._syncing:
            # Widgets are mid-population; they do not describe the config yet.
            return c
        c.background = c.background  # set by chooser only
        c.fit = _key_for(FIT_CHOICES, self.fit_var.get())
        try:
            c.minutes = max(0, min(180, int(float(self.min_var.get() or 0))))
        except (TypeError, ValueError):
            c.minutes = 0
        try:
            c.seconds = max(0, min(59, int(float(self.sec_var.get() or 0))))
        except (TypeError, ValueError):
            c.seconds = 0
        c.final_minute = _key_for(FINAL_MINUTE_CHOICES, self.final_var.get())
        try:
            c.hold_seconds = max(0.0, min(60.0, float(self.hold_var.get() or 0)))
        except (TypeError, ValueError):
            c.hold_seconds = 5.0
        c.fade_in = bool(self.fade_var.get())

        c.font_family = self.font_var.get().strip()
        c.font_file = fontlib.find_font(c.font_family, self.style_var.get())

        c.color = (self.color_hex.get() or DARK_TEXT).strip()
        c.auto_mode = bool(self.auto_mode_var.get())
        c.mode = self.mode_var.get()
        c.italic = bool(self.italic_var.get())
        c.slant = float(self.slant_scale.get())
        c.glow = bool(self.glow_var.get())
        c.contrast = bool(self.contrast_var.get())
        c.shadow = float(self.shadow_scale.get())
        c.outline = float(self.outline_scale.get())
        c.resolution = _key_for(RES_CHOICES, self.res_var.get())
        c.export_mode = _key_for(MODE_CHOICES, self.export_var.get())
        c.alpha_format = _key_for(ALPHA_CHOICES, self.alpha_var.get())
        return c

    def _apply_auto_mode(self):
        """Pick dark/light text from measured background brightness."""
        c = self.cfg
        if not c.auto_mode:
            return
        brightness = 0.0
        if c.background and os.path.exists(c.background):
            brightness = background_brightness(c.background)
        mode, color = result_color_for_background(self.cfg, brightness)
        c.mode = mode
        c.color = color
        self.mode_var.set(mode)
        self.color_hex.set(color.upper())
        self.color_swatch.set(color)

    def _update_mode_state(self):
        """Grey out controls that don't apply to the current export mode."""
        is_baked = self.export_var.get() == dict(MODE_CHOICES)[MODE_BAKED]
        self.fit_combo.configure(state="readonly" if is_baked else "disabled")

        alpha_on = self.export_var.get() == dict(MODE_CHOICES)[MODE_ALPHA]
        self.alpha_combo.configure(state="readonly" if alpha_on else "disabled")

        # A warm glow reads as a smudge on light backgrounds, so it is forced
        # off there. Remember the user's choice so dark mode restores it.
        is_light = self.mode_var.get() == "light"
        if is_light:
            if self.glow_var.get():
                self._glow_before_light = True
                self.glow_var.set(False)
            self.glow_chk.configure(state="disabled")
        else:
            if getattr(self, "_glow_before_light", False):
                self.glow_var.set(True)
                self._glow_before_light = False
            self.glow_chk.configure(state="normal")

    # -- events --------------------------------------------------------

    def _on_change(self):
        if self._syncing:
            return
        self._read_widgets()
        self._apply_auto_mode()
        self._update_mode_state()
        self._read_widgets()
        self._refresh_preview()

    def _on_mode_change(self):
        self._read_widgets()
        # Switching away from auto keeps the user's explicit choice.
        self.cfg.auto_mode = False
        self.auto_mode_var.set(False)
        self._apply_auto_mode()
        self._update_mode_state()
        self._read_widgets()
        self._refresh_preview()

    def _on_export_change(self):
        self._read_widgets()
        label = self.export_var.get()
        for key, text in self.export_tip.items():
            if dict(MODE_CHOICES)[key] == label:
                Tooltip(self.export_combo, text)
        self._update_mode_state()
        self._refresh_preview()

    def _on_scale(self, _value=None):
        self.slant_val.configure(text="%.2f" % float(self.slant_scale.get()))
        self._on_change()

    def _apply_italic_state(self):
        """The slant slider only matters while italic is on."""
        state = "normal" if self.italic_var.get() else "disabled"
        try:
            self.slant_scale.configure(state=state)
        except tk.TclError:
            pass

    def _on_italic_toggle(self):
        self._apply_italic_state()
        self._on_change()

    def _on_hex_edit(self):
        value = self.color_hex.get().strip()
        if not value:
            return
        if not value.startswith("#"):
            value = "#" + value
        if len(value) != 7:
            return
        try:
            int(value[1:], 16)
        except ValueError:
            return
        self.color_hex.set(value.upper())
        self.color_swatch.set(value)
        self._read_widgets()
        self._refresh_preview()

    def _choose_color(self):
        current = self.color_swatch.get()
        _rgb, hexval = colorchooser.askcolor(color=current, title="Text colour",
                                             parent=self)
        if hexval:
            self.color_hex.set(hexval.upper())
            self.color_swatch.set(hexval)
            self._read_widgets()
            self._refresh_preview()

    def _choose_background(self, path=None):
        if path is None:
            path = filedialog.askopenfilename(
                parent=self, title="Choose background image",
                filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"),
                           ("All files", "*.*")])
        if not path:
            return
        self.cfg.background = path
        self.bg_drop.set_path(path)
        if self.cfg.auto_mode:
            self._apply_auto_mode()
        self._refresh_preview()

    def _choose_outdir(self):
        path = filedialog.askdirectory(parent=self, title="Output folder")
        if path:
            self.outdir_var.set(path)

    def _import_font(self):
        path = filedialog.askopenfilename(
            parent=self, title="Import font file",
            filetypes=[("Fonts", "*.ttf *.otf *.ttc *.otc"),
                       ("All files", "*.*")])
        if not path:
            return
        try:
            stored = fontlib.import_font(path, imported_font_dir())
        except (OSError, ValueError) as exc:
            messagebox.showerror("Import failed", str(exc), parent=self)
            return
        fontlib.scan_fonts(refresh=True)
        family, style = fontlib._read_names(stored)
        if family:
            self.font_var.set(family)
            self.font_combo.configure(values=fontlib.families())
            self._load_styles_for(family, stored)
            self.cfg.font_family = family
            self.cfg.font_file = stored
            self._refresh_preview()

    def _refresh_preview(self):
        try:
            c = self._read_widgets()
            c = normalize(c)
            from ..core.renderer import Renderer
            renderer = Renderer(c)
            # t=0 would land inside the fade-in (invisible text), so sit just
            # past it. With no fade-in, the first frame is the right choice.
            # Clamp for very short timers so we never sample past the end.
            preview_t = (min(PREVIEW_TIME, c.total_seconds * 0.5)
                         if c.fade_in else 0.0)
            self.preview.schedule(renderer, preview_t)
            total = c.total_seconds
            self.preview.set_badge(
                "%d:%02d  ·  %dx%d  ·  %s"
                % (total // 60, total % 60, c.width, c.height,
                   dict(MODE_CHOICES)[c.export_mode]))
        except Exception as exc:
            self.preview.set_error("Preview failed: %s" % exc)

    def _save_settings(self):
        self._read_widgets()
        try:
            save_user_config(self.cfg)
        except OSError as exc:
            messagebox.showerror("Could not save", str(exc), parent=self)
            return
        self.status.configure(text="Settings saved")

    # -- rendering -----------------------------------------------------

    def _start_render(self):
        if self.render_thread and self.render_thread.is_alive():
            return
        c = normalize(self._read_widgets())
        problems = c.validate()
        if problems:
            messagebox.showwarning("Check settings", "\n".join(problems), parent=self)
            return

        outdir = self.outdir_var.get().strip() or os.path.expanduser("~/Videos")
        c.last_output = output_path(c, outdir)
        ext = os.path.splitext(c.last_output)[1].lower()
        if (c.export_mode == MODE_ALPHA and c.alpha_format == ALPHA_PRORES and ext != ".mov") \
                or (c.export_mode != MODE_ALPHA and ext not in (".mp4",)):
            c.last_output = os.path.splitext(c.last_output)[0] + _expected_ext(c)

        if os.path.exists(c.last_output):
            if not messagebox.askyesno(
                    "Overwrite?",
                    "Overwrite %s?" % os.path.basename(c.last_output), parent=self):
                return

        save_user_config(c)

        self._progress = Progress()
        self.render_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.progress.configure(value=0)
        self.status.configure(text="Starting")

        def work():
            try:
                from ..core.ffmpeg import find_ffmpeg
                path = render(c, self._progress, find_ffmpeg())
                self.render_queue.put(("done", path))
            except RenderCancelled:
                self.render_queue.put(("cancelled", None))
            except RenderError as exc:
                self.render_queue.put(("error", str(exc)))
            except Exception as exc:  # never let the thread die silently
                self.render_queue.put(("error", "Unexpected error: %s" % exc))

        self.render_thread = threading.Thread(target=work, daemon=True)
        self.render_thread.start()

    def _cancel_render(self):
        if self._progress:
            self._progress.cancel()
            self.status.configure(text="Cancelling")

    def _poll_render(self):
        try:
            while True:
                kind, payload = self.render_queue.get_nowait()
                if kind == "done":
                    self.progress.configure(value=100)
                    self.status.configure(text="Done: %s" % os.path.basename(payload))
                    messagebox.showinfo("Finished", "Wrote:\n%s" % payload, parent=self)
                    if messagebox.askyesno("Open folder",
                                           "Open the output folder?", parent=self):
                        self._reveal(payload)
                elif kind == "cancelled":
                    self.status.configure(text="Cancelled")
                elif kind == "error":
                    self.status.configure(text="Failed")
                    messagebox.showerror("Render failed", payload, parent=self)
                self.render_btn.configure(state="normal")
                self.cancel_btn.configure(state="disabled")
        except queue.Empty:
            pass

        if self._progress and (self.render_thread and self.render_thread.is_alive()):
            self.progress.configure(value=self._progress.value * 100)
            if not self._progress.cancelled:
                self.status.configure(text=self._progress.message or "Rendering")

        self.after(120, self._poll_render)

    def _reveal(self, path):
        folder = os.path.dirname(path) or "."
        try:
            import subprocess
            import sys
            if sys.platform == "win32":
                os.startfile(folder)  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except (OSError, AttributeError):
            pass

    def _on_close(self):
        if self.render_thread and self.render_thread.is_alive():
            if not messagebox.askyesno(
                    "Rendering",
                    "A render is in progress. Quit anyway? The file will be incomplete.",
                    parent=self):
                return
            if self._progress:
                self._progress.cancel()
        try:
            save_user_config(self._read_widgets())
        except OSError:
            pass
        self.destroy()


def _key_for(choices, label):
    """Map a combobox value back to its config key.

    The widgets are seeded with a raw key (e.g. ``RES_1080``) at construction
    and only later replaced with a human label by ``_sync_from_config``, so a
    value may arrive in either form. Matching only the label made every
    ``_read_widgets()`` call that ran before the sync fall through to
    ``choices[0][0]`` - which silently rewrote a saved 1920x1080 back to 720p.
    """
    for value, text in choices:
        if text == label or value == label:
            return value
    return choices[0][0]


def _family_from_path(path):
    try:
        family, _style = fontlib._read_names(path)
        return family or ""
    except Exception:
        return ""


def _expected_ext(cfg):
    from ..core.modes import default_extension
    return default_extension(cfg)