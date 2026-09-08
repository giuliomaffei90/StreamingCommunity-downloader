"""Re-encode a finished download, following the HandBrake "Plex" preset.

Off by default, and deliberately so. The source here is already H.264 at around
1.5 Mbps — heavily compressed before it ever arrives — where the preset was
designed for Blu-ray and DVD rips many times that bitrate. Measured on a real
episode it buys about a third of the file size for roughly a third of the
running time in CPU, and some quality. That is a trade worth offering and not
worth imposing.

Where this departs from the preset, and why:

* **The output is always MP4**, as the preset says, even when the download was
  MKV for carrying several audio tracks — MP4 holds those too. Its subtitles do
  have to become ``mov_text``, the only text codec MP4 defines, which is why
  they are converted rather than copied.
* **Audio that is already AAC is copied, not re-encoded.** HandBrake encodes to
  AAC because its sources are AC3 or DTS; this source is AAC stereo already, so
  re-encoding it is pure generation loss for no gain. Anything else does go
  through AAC 160k stereo as the preset asks.
* **No auto-crop.** It needs a whole analysis pass over the file to find the
  black bars, and streams from this source are not letterboxed the way a DVD is.
* **No AC3 5.1 passthrough track.** The preset carries one when the source has
  it. This source sends stereo, so it never would.
"""

import logging
import os
import subprocess
import tempfile
from pathlib import Path

from app.core.ffmpeg_path import ffmpeg_file_arg, get_ffmpeg_exe, get_ffprobe_exe

logger = logging.getLogger(__name__)

# Straight from the preset: x265, constant quality 26, veryfast, and its own
# extra options.
CRF = "26"
PRESET = "veryfast"
X265_PARAMS = "strong-intra-smoothing=0:rect=0:aq-mode=1"

# PictureWidth/Height with PictureAllowUpscaling false and PictureKeepRatio
# true: cap the long edges, never enlarge, keep the aspect ratio.
MAX_WIDTH = 1920
MAX_HEIGHT = 1080
_SCALE = (
    f"scale='min({MAX_WIDTH},iw)':'min({MAX_HEIGHT},ih)'"
    ":force_original_aspect_ratio=decrease"
)

AUDIO_BITRATE = "160k"


def enabled() -> bool:
    from app.config import get_settings

    return bool(get_settings().get("transcode_enabled"))


def _audio_is_already_aac(path: str) -> bool:
    """True when every audio stream is AAC, so re-encoding would only lose.

    Without ffprobe the answer is unknown, and the safe unknown is False: encode
    it, which is what the preset asks for anyway.
    """
    ffprobe = get_ffprobe_exe()
    if not ffprobe:
        return False
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=codec_name", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30, check=True,
        )
    except Exception as exc:
        logger.warning("ffprobe could not read the audio streams: %s", type(exc).__name__)
        return False
    codecs = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return bool(codecs) and all(c == "aac" for c in codecs)


def duration_seconds(path: str) -> float | None:
    """How long the video is, for the progress bar to have a total.

    None when ffprobe is absent or cannot say — the encode still runs, it just
    reports no percentage.
    """
    ffprobe = get_ffprobe_exe()
    if not ffprobe:
        return None
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, timeout=30, check=True,
        )
        return float(result.stdout.strip())
    except Exception:
        return None


def build_command(source: str, destination: str, *, copy_audio: bool) -> list[str]:
    """The ffmpeg call. Separate from running it so a test can read the flags."""
    cmd = [
        get_ffmpeg_exe(), "-y",
        "-i", ffmpeg_file_arg(source),
        # Machine-readable progress on stdout instead of the human status line.
        "-progress", "pipe:1", "-nostats",
        # Everything the file carries, not just the first of each kind: a
        # download may hold several languages and their subtitles.
        "-map", "0",
        "-c:v", "libx265",
        "-crf", CRF,
        "-preset", PRESET,
        "-x265-params", X265_PARAMS,
        "-vf", _SCALE,
        # Without hvc1 the file is HEVC that QuickTime and Apple devices refuse
        # to play. HandBrake writes this tag too.
        "-tag:v", "hvc1",
    ]
    cmd += ["-c:a", "copy"] if copy_audio else [
        "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-ac", "2",
    ]
    # MP4 defines exactly one text subtitle codec, so a WebVTT or ASS track
    # carried in from an MKV has to be converted rather than copied.
    # ChapterMarkers and MetadataPassthru in the preset.
    cmd += ["-c:s", "mov_text", "-map_metadata", "0", "-map_chapters", "0"]
    cmd.append(ffmpeg_file_arg(destination))
    return cmd


def transcode(path: str, cancel_event=None, on_progress=None) -> str:
    """Re-encode *path* to MP4. Returns the resulting path, transcoded or not.

    Never raises, and never removes the original before the new file is
    complete. The download already succeeded by the time this runs; a failure
    here must cost the user a smaller file, never the file.
    """
    source = Path(path)
    if not source.is_file():
        logger.warning("Nothing to transcode at %s", path)
        return path

    # The preset's container. When the download was MKV the result replaces it
    # under a new name, so the old file has to go once the new one is in place.
    final = source.with_suffix(".mp4")
    handle, temp_path = tempfile.mkstemp(suffix=".mp4", dir=str(source.parent))
    os.close(handle)
    errors = tempfile.TemporaryFile()

    total = duration_seconds(str(source))
    cmd = build_command(str(source), temp_path, copy_audio=_audio_is_already_aac(str(source)))
    logger.info("Transcoding %s", source.name)

    try:
        # stderr goes to a file rather than a pipe nobody drains: a long encode
        # can emit enough warnings to fill a pipe and deadlock on writing to it.
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errors)
        cancelled = False
        try:
            for raw in process.stdout:
                if cancel_event is not None and cancel_event.is_set():
                    process.kill()
                    cancelled = True
                    break
                if on_progress is None:
                    continue
                line = raw.decode("utf-8", "replace").strip()
                if line.startswith("out_time_us="):
                    value = line.split("=", 1)[1]
                    if value.isdigit():
                        seconds = int(value) / 1_000_000
                        try:
                            on_progress(min(seconds, total) if total else seconds)
                        except Exception:
                            logger.exception("Transcode progress callback failed")
        finally:
            process.stdout.close()
        process.wait()

        if cancelled:
            logger.info("Transcode cancelled for %s", source.name)
            return path

        if process.returncode != 0:
            errors.seek(0)
            tail = errors.read().decode("utf-8", "replace").strip().splitlines()[-3:]
            logger.warning("Transcode failed for %s, keeping the original: %s",
                           source.name, " / ".join(tail))
            return path

        before = source.stat().st_size
        after = os.path.getsize(temp_path)
        # A bigger file means the encode lost the bet — the source was already
        # more efficient than what we produced. Keeping it would be a downgrade
        # in both size and quality.
        if after >= before:
            logger.info("Transcode of %s came out larger (%d -> %d), keeping the original",
                        source.name, before, after)
            return path

        os.replace(temp_path, final)
        if final != source:
            source.unlink(missing_ok=True)
        logger.info("Transcoded %s -> %s: %d -> %d bytes (-%d%%)",
                    source.name, final.name, before, after,
                    round(100 * (before - after) / before))
        return str(final)
    except Exception:
        logger.exception("Transcode of %s raised, keeping the original", source.name)
        return path
    finally:
        errors.close()
        if os.path.exists(temp_path):
            os.unlink(temp_path)
