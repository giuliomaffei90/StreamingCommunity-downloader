"""Re-encode a finished download, following the HandBrake "Plex" preset.

Off by default, and deliberately so. The source here is already H.264 at around
1.5 Mbps — heavily compressed before it ever arrives — where the preset was
designed for Blu-ray and DVD rips many times that bitrate. Measured on a real
episode it buys about a third of the file size for roughly a third of the
running time in CPU, and some quality. That is a trade worth offering and not
worth imposing.

Where this departs from the preset, and why:

* **The container is left alone.** The preset says MP4; this app already picks
  MP4 for one audio track and MKV for several, because carrying several
  languages is what MKV is for. Forcing MP4 here would fight a decision made
  for a reason the preset knows nothing about.
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


def build_command(source: str, destination: str, *, copy_audio: bool) -> list[str]:
    """The ffmpeg call. Separate from running it so a test can read the flags."""
    cmd = [
        get_ffmpeg_exe(), "-y",
        "-i", ffmpeg_file_arg(source),
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
    # ChapterMarkers and MetadataPassthru in the preset.
    cmd += ["-c:s", "copy", "-map_metadata", "0", "-map_chapters", "0"]
    cmd.append(ffmpeg_file_arg(destination))
    return cmd


def transcode(path: str, cancel_event=None) -> str:
    """Re-encode *path* in place. Returns the path, transcoded or not.

    Never raises and never removes the original before the new file is complete.
    The download already succeeded by the time this runs; a failure here must
    cost the user a smaller file, never the file.
    """
    source = Path(path)
    if not source.is_file():
        logger.warning("Nothing to transcode at %s", path)
        return path

    handle, temp_path = tempfile.mkstemp(suffix=source.suffix, dir=str(source.parent))
    os.close(handle)

    cmd = build_command(str(source), temp_path, copy_audio=_audio_is_already_aac(str(source)))
    logger.info("Transcoding %s", source.name)

    try:
        process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        while True:
            try:
                _, stderr = process.communicate(timeout=1)
                break
            except subprocess.TimeoutExpired:
                if cancel_event is not None and cancel_event.is_set():
                    process.kill()
                    process.wait()
                    logger.info("Transcode cancelled for %s", source.name)
                    return path

        if process.returncode != 0:
            tail = (stderr or b"").decode("utf-8", "replace").strip().splitlines()[-3:]
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

        os.replace(temp_path, source)
        logger.info("Transcoded %s: %d -> %d bytes (-%d%%)",
                    source.name, before, after, round(100 * (before - after) / before))
        return path
    except Exception:
        logger.exception("Transcode of %s raised, keeping the original", source.name)
        return path
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
