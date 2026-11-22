# Countdown Generator

A countdown timer video generator for [ProPresenter](https://www.renewedvision.com/propresenter.php), with a graphical interface for choosing the background, font and timing.

It renders a video you can drop straight into a ProPresenter media bin, or into anything else that plays video.

---

## Quick start

### Windows

1. Install [Git](https://git-scm.com/download/win) and [Python](https://www.python.org/downloads/) if you don't have them. **Tick "Add python.exe to PATH"** on the first screen of the Python installer.
2. Clone the repository:

   ```bat
   git clone https://github.com/CBush88/countdown-generator.git
   cd countdown-generator
   ```

3. Double-click `setup.bat`.
4. The app opens. Settings are saved automatically between sessions.

### macOS

```bash
git clone https://github.com/CBush88/countdown-generator.git
cd countdown-generator

python3 -m pip install -r requirements.txt
python3 countdown-studio.py
```

### Linux

Tkinter is a separate package on some distributions:

```bash
git clone https://github.com/CBush88/countdown-generator.git
cd countdown-generator

sudo apt install python3-tk        # Debian / Ubuntu
sudo dnf install python3-tkinter   # Fedora
sudo pacman -S tk                  # Arch

python3 -m pip install -r requirements.txt
python3 countdown-studio.py
```

---

## Using it

1. **Choose a background image.** Click the drop zone or drag a file onto it. Images that aren't 16:9 are either cropped to fill the frame or letterboxed, depending on the *Fit* setting.
2. **Set the timer.** Minutes and seconds, plus how long to hold on `0:00` at the end so the operator can fade out.
3. **Choose a font.** The dropdown lists every font installed on your system. Use **Import font file** for anything not listed, including `.otf`, `.ttf`, `.ttc` and `.otc` files.
4. **Pick a look.** Dark mode uses cream text, light mode uses near-black. *High contrast* adds a shadow and/or outline for busy backgrounds. *Italicize digits* shears the text for a slanted look.
5. **Choose an export mode**, then **Render video**.

The preview updates as you change settings, so you can see the result before committing to a render.

---

## Export modes

The right choice depends on whether your background is always the same image.

| Mode | Background | Best for | Notes |
|---|---|---|---|
| **Baked-in** | Included | A fixed background image | Smallest file, plays anywhere. Default. |
| **Alpha channel** | Transparent | Layering over other slides or a live camera | Needs an alpha-capable codec; very large files |
| **Luma key** | Omitted | Layering, but on any computer | White text on pure black; key it out in ProPresenter |

### About alpha channel

In ProPresenter you can stack layers: put your background image (or a live camera) on one layer and the alpha timer on another. Wherever the timer isn't drawing, the layer beneath shows through.

Two formats are available:

- **ProRes 4444 (.mov)** — the standard ProPresenter alpha format on macOS. Windows support is weaker; if it misbehaves, use the PNG sequence instead.
- **PNG sequence (.zip)** — lossless frames with transparency. Works on any platform, but is several gigabytes and contains thousands of files.

Alpha files are roughly **100–400× larger** than a baked-in MP4 for the same duration.

### About luma key

The video is rendered as white text on pure black, with no transparency. In ProPresenter, apply a **luma key** (also called brightness key) to drop the black. This works with any MP4 on any platform, at the cost of slightly softer edges around the glow.

Luma key is not the same as alpha, and a baked-in video **cannot** be converted to transparency afterwards — the background pixels are already opaque.

---

## Command line

Everything the window does is available as a script, which is handy for automation.

```bash
python3 countdown-studio.py \
  --background "background.png" \
  --font "/path/to/font.otf" \
  --slant 0.22 \
  --minutes 5 --seconds 0 \
  --output countdown.mp4
```

Useful flags:

| Flag | Description |
|---|---|
| `--list-fonts` | Print available font families and exit |
| `--mode dark\|light` | Text colour scheme |
| `--italic` | Slant the digits (synthetic italic); amount via `--slant` |
| `--contrast --shadow 0.55 --outline 0.02` | High-contrast text |
| `--final-minute bare\|fixed\|standard` | How the last minute is displayed |
| `--export baked\|alpha\|luma` | Export mode |
| `--alpha-format prores\|png` | Alpha container |
| `--resolution 1280x720\|1920x1080\|3840x2160` | Output size |
| `--no-glow` | Disable the glow effect |

Run `--help` for the full list.

---

## Fonts

Numeric-only display fonts often ship proportional figures — the `1` is narrower than the `0` — which makes a timer jitter sideways as digits change. Countdown Generator lays digits out in fixed-width cells by default so the block stays steady. Pass `--proportional` to use the font's natural widths instead.

**Italic is opt-in.** The slant is synthesised by shearing upright glyphs — slanted rather than redrawn curves. Tick *Italicize digits* in the GUI, or pass `--italic` (or `--slant 0.22`, which implies it). It reads correctly at a glance, but it is not a true italic. A font family that ships a real oblique (Inter, Roboto) will look better if you want genuine italic.

---

## Project layout

```
countdown-studio.py          Entry point (GUI or --help for CLI)
setup.bat                    Windows setup and launch
countdown_studio/
  core/
    config.py                RenderConfig, JSON persistence
    renderer.py              Frame rendering (shared by preview and encoder)
    fonts.py                 System font enumeration and import
    ffmpeg.py                ffmpeg discovery
    encode.py                Encoding, progress, cancellation
  gui/
    app.py                   Main window
    preview.py               Live preview panel
    widgets.py               Colour swatch, drop target, tooltips
  cli.py                     Command-line interface
```

The GUI is a thin shell: it builds a `RenderConfig` and hands it to the same renderer the CLI uses, so a preview and a rendered video always agree.

---

## Troubleshooting

**"No module named 'tkinter'"** — Tkinter isn't installed. See the Linux section above, or reinstall Python from python.org with the default options on macOS/Windows.

**"ffmpeg was not found"** — Run `pip install -r requirements.txt`. That installs `imageio-ffmpeg`, which bundles a binary. Alternatively set `COUNTDOWN_STUDIO_FFMPEG` to a path, or install ffmpeg with your package manager.

**Alpha export won't play** — Try the PNG sequence format instead of ProRes, especially on Windows.

**Text is hard to read over the background** — Turn on *High contrast*, or switch text mode. The auto mode picks cream on dark backgrounds and near-black on light ones.

**Settings don't stick** — Settings live in `%APPDATA%\Countdown Generator` (Windows), `~/Library/Application Support/Countdown Generator` (macOS), or `~/.config/countdown-generator` (Linux).

---

## Requirements

- Python 3.9 or newer
- `pillow`, `numpy`, `imageio-ffmpeg`, `fonttools` (see `requirements.txt`)
- Tkinter (ships with most Python installs; separate package on some Linux distributions)

## License

MIT License — free to use, modify, and distribute, including commercially.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.