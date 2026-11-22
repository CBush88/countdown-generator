"""Encoding pipeline.

Frames are streamed to ffmpeg as raw video, which avoids writing tens of
gigabytes of intermediate image files. Progress and cancellation are reported
through callbacks so the GUI can drive a progress bar without knowing
anything about subprocesses.
"""

import os
import shutil
import subprocess
import tempfile
import threading
import zipfile

from .config import ALPHA_PNG, MODE_ALPHA, MODE_BAKED, MODE_LUMA


class RenderCancelled(Exception):
    """Raised when the user cancels an in-progress render."""


class RenderError(Exception):
    """Raised when encoding fails for a reason the user can act on."""


class Progress:
    """Thread-safe progress tracker with a cancel flag."""

    def __init__(self):
        self._lock = threading.Lock()
        self._value = 0.0
        self._cancelled = False
        self._message = ""

    def set(self, value, message=None):
        with self._lock:
            self._value = max(0.0, min(1.0, float(value)))
            if message is not None:
                self._message = message

    def advance(self, done, total, message=None):
        self.set(done / float(total) if total else 0.0, message)

    @property
    def value(self):
        with self._lock:
            return self._value

    @property
    def message(self):
        with self._lock:
            return self._message

    def cancel(self):
        with self._lock:
            self._cancelled = True

    @property
    def cancelled(self):
        with self._lock:
            return self._cancelled

    def check(self):
        if self.cancelled:
            raise RenderCancelled()


def _probe_size(path):
    """Best-effort duration in seconds using ffprobe."""
    probe = shutil.which("ffprobe")
    if not probe:
        return 0.0
    try:
        out = subprocess.run(
            [probe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=20, check=False)
        return float(out.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


def _mp4_args(ffmpeg, path, cfg):
    return [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", "%dx%d" % (cfg.width, cfg.height), "-r", str(cfg.fps), "-i", "-",
        "-an",
        "-c:v", "libx264", "-preset", cfg.preset, "-crf", str(cfg.crf),
        "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "5.1",
        "-g", str(cfg.fps * 2), "-bf", "2",
        "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
        "-movflags", "+faststart",
        # The temp filename has no .mp4 extension, so name the muxer explicitly.
        "-f", "mp4",
        path,
    ]


def _prores_args(ffmpeg, path, cfg):
    return [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgba",
        "-s", "%dx%d" % (cfg.width, cfg.height), "-r", str(cfg.fps), "-i", "-",
        "-an",
        "-c:v", "prores_ks", "-profile:v", "4", "-pix_fmt", "yuva444p10le",
        "-alpha_bits", "16",
        "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
        # The temp filename has no .mov extension, so name the muxer explicitly.
        "-f", "mov",
        path,
    ]


def _remove_partial(path):
    """Delete a partially written output file."""
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def _render_to_pipe(renderer, proc, progress, total_frames, fps):
    """Stream frames to an ffmpeg process running on stdin."""
    stdin = proc.stdin
    try:
        for i in range(total_frames):
            progress.check()
            frame = renderer.frame(i / float(fps))
            stdin.write(frame.tobytes())
            if i % 5 == 0 or i == total_frames - 1:
                progress.advance(i + 1, total_frames, "Rendering frame %d of %d"
                                 % (i + 1, total_frames))
    except (BrokenPipeError, ValueError):
        # ffmpeg died; the return code check below reports why.
        pass
    finally:
        try:
            stdin.close()
        except (BrokenPipeError, ValueError, OSError):
            pass
    return proc.wait()


def _png_sequence(renderer, directory, progress, total_frames, fps):
    for i in range(total_frames):
        progress.check()
        # ProRes-free alpha path: RGBA PNG keeps the transparency losslessly.
        from PIL import Image
        Image.fromarray(renderer.frame_rgba(i / float(fps)), "RGBA").save(
            os.path.join(directory, "frame-%06d.png" % i))
        if i % 5 == 0 or i == total_frames - 1:
            progress.advance(i + 1, total_frames, "Rendering frame %d of %d"
                             % (i + 1, total_frames))


def render(cfg, progress=None, ffmpeg=None):
    """Render a countdown video according to ``cfg``.

    Returns the path to the finished file. Raises RenderCancelled or RenderError.
    """
    from .renderer import Renderer

    progress = progress or Progress()
    exe = ffmpeg or None
    if exe is None:
        from .ffmpeg import find_ffmpeg, install_hint
        exe = find_ffmpeg()
        if not exe and cfg.export_mode == MODE_BAKED:
            raise RenderError(install_hint())
        if not exe and cfg.export_mode == MODE_LUMA:
            raise RenderError(install_hint())

    problems = cfg.validate()
    if problems:
        raise RenderError(" ".join(problems))

    renderer = Renderer(cfg)
    total_frames = renderer.frame_count()
    fps = float(cfg.fps)

    out_dir = os.path.dirname(os.path.abspath(cfg.last_output or "output.mp4"))
    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError as exc:
        raise RenderError("Cannot write to output folder: %s" % exc)

    base = cfg.last_output or os.path.join(out_dir, "countdown.mp4")
    stem, _ext = os.path.splitext(base)

    progress.set(0.0, "Preparing")

    if cfg.export_mode == MODE_ALPHA and cfg.alpha_format == ALPHA_PNG:
        progress.set(0.02, "Rendering PNG sequence")
        tmpdir = tempfile.mkdtemp(prefix="countdown-alpha-")
        zip_path = stem + ".zip" if not base.lower().endswith(".zip") else base
        tmp_zip = zip_path + ".part"
        try:
            _png_sequence(renderer, tmpdir, progress, total_frames, fps)
            progress.check()
            progress.set(0.9, "Zipping frames")
            with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                for name in sorted(os.listdir(tmpdir)):
                    zf.write(os.path.join(tmpdir, name), name)
            # Publish only once complete, so nothing ever sees a half-written file.
            os.replace(tmp_zip, zip_path)
            progress.set(1.0, "Done")
            return zip_path
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
            _remove_partial(tmp_zip)

    if cfg.export_mode == MODE_ALPHA:
        path = stem + ".mov"
        pix_fmt = "rgba"
        args = _prores_args
    else:
        path = stem + ".mp4"
        pix_fmt = "rgb24"
        args = _mp4_args

    # Encode beside the target and rename into place only once the file is
    # complete. The temp name is hidden and carries no video extension, so file
    # managers and thumbnailers leave it alone instead of trying to decode a
    # half-written MP4 (which is what produces "moov atom not found"). ffmpeg
    # gets the container forced explicitly since it can no longer infer it.
    tmp_path = os.path.join(out_dir, "." + os.path.basename(stem) + ".part")
    cmd = args(exe, tmp_path, cfg)

    progress.set(0.01, "Starting encoder")
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except OSError as exc:
        _remove_partial(tmp_path)
        raise RenderError("Could not start ffmpeg: %s" % exc)

    stderr_chunks = []
    if proc.stderr is not None:
        def drain():
            for line in proc.stderr:
                if isinstance(line, bytes):
                    line = line.decode("utf-8", "replace")
                stderr_chunks.append(line)
        threading.Thread(target=drain, daemon=True).start()

    try:
        if pix_fmt == "rgba":
            _render_rgba_to_pipe(renderer, proc, progress, total_frames, fps)
        else:
            _render_to_pipe(renderer, proc, progress, total_frames, fps)
    except RenderCancelled:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except (subprocess.SubprocessError, OSError):
            proc.kill()
        # A half-written file is worse than no file.
        _remove_partial(tmp_path)
        raise
    except BaseException:
        # Any other failure (including KeyboardInterrupt) must not leave a
        # truncated video behind at the temporary path.
        _remove_partial(tmp_path)
        raise

    if proc.returncode != 0:
        detail = "".join(stderr_chunks).strip()
        _remove_partial(tmp_path)
        raise RenderError("ffmpeg failed (exit %d). %s"
                          % (proc.returncode, detail.splitlines()[-1] if detail else ""))

    os.replace(tmp_path, path)
    progress.set(1.0, "Done")
    return path


def _render_rgba_to_pipe(renderer, proc, progress, total_frames, fps):
    stdin = proc.stdin
    try:
        for i in range(total_frames):
            progress.check()
            frame = renderer.frame_rgba(i / float(fps))
            stdin.write(frame.tobytes())
            if i % 5 == 0 or i == total_frames - 1:
                progress.advance(i + 1, total_frames, "Rendering frame %d of %d"
                                 % (i + 1, total_frames))
    except (BrokenPipeError, ValueError):
        pass
    finally:
        try:
            stdin.close()
        except (BrokenPipeError, ValueError, OSError):
            pass
    return proc.wait()