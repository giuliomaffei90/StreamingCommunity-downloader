"""Re-encoding a finished download, following the HandBrake "Plex" preset.

The load-bearing property is not the encode: it is that a download already on
disk survives every way the encode can go wrong. The file is the thing the user
waited for; a smaller version of it is a bonus.
"""

import subprocess
from types import SimpleNamespace

import pytest

from app.core import transcode


@pytest.fixture
def video(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    target = library / "Film (2020).mp4"
    target.write_bytes(b"x" * 5_000_000)
    return target


def _flags(cmd: list[str]) -> dict:
    """Flag -> value, so a test can ask what was passed without index arithmetic."""
    return {cmd[i]: cmd[i + 1] for i in range(len(cmd) - 1) if cmd[i].startswith("-")}


# ── The preset ────────────────────────────────────────────────────────────────

def test_the_video_settings_come_from_the_preset():
    flags = _flags(transcode.build_command("in.mp4", "out.mp4", copy_audio=True))

    assert flags["-c:v"] == "libx265"
    assert flags["-crf"] == "26"
    assert flags["-preset"] == "veryfast"
    assert flags["-x265-params"] == "strong-intra-smoothing=0:rect=0:aq-mode=1"


def test_it_caps_at_1080p_without_upscaling():
    """PictureAllowUpscaling is false in the preset: a 720p source stays 720p."""
    flags = _flags(transcode.build_command("in.mp4", "out.mp4", copy_audio=True))

    assert "min(1920,iw)" in flags["-vf"]
    assert "min(1080,ih)" in flags["-vf"]
    assert "force_original_aspect_ratio=decrease" in flags["-vf"]


def test_hevc_is_tagged_hvc1():
    """Without the tag QuickTime and Apple devices refuse to play the file."""
    assert _flags(transcode.build_command("in.mp4", "out.mp4", copy_audio=True))["-tag:v"] == "hvc1"


def test_every_stream_is_carried_over():
    """A download can hold several languages and their subtitles."""
    cmd = transcode.build_command("in.mp4", "out.mp4", copy_audio=True)

    assert "-map" in cmd and cmd[cmd.index("-map") + 1] == "0"
    assert _flags(cmd)["-c:s"] == "copy"
    assert _flags(cmd)["-map_metadata"] == "0"
    assert _flags(cmd)["-map_chapters"] == "0"


def test_audio_already_aac_is_copied_not_re_encoded():
    """The preset encodes because its sources are AC3; this one is AAC already,
    so encoding it again would be generation loss for nothing."""
    assert _flags(transcode.build_command("in.mp4", "out.mp4", copy_audio=True))["-c:a"] == "copy"


def test_other_audio_goes_to_aac_stereo_at_the_preset_bitrate():
    flags = _flags(transcode.build_command("in.mp4", "out.mp4", copy_audio=False))

    assert flags["-c:a"] == "aac"
    assert flags["-b:a"] == "160k"
    assert flags["-ac"] == "2"


# ── Never lose the download ───────────────────────────────────────────────────

def _ffmpeg(monkeypatch, returncode=0, produces=None):
    """Stand in for the encoder, optionally writing an output of a given size."""
    monkeypatch.setattr(transcode, "_audio_is_already_aac", lambda path: True)

    class _Process:
        def __init__(self, cmd, **kwargs):
            self._out = cmd[-1].removeprefix("file:")
            if produces is not None:
                with open(self._out, "wb") as handle:
                    handle.write(b"y" * produces)
            self.returncode = returncode

        def communicate(self, timeout=None):
            return b"", b"boom"

    monkeypatch.setattr(transcode.subprocess, "Popen", _Process)


def test_a_smaller_result_replaces_the_original(monkeypatch, video):
    _ffmpeg(monkeypatch, produces=1_000_000)

    transcode.transcode(str(video))

    assert video.stat().st_size == 1_000_000


def test_a_larger_result_is_thrown_away(monkeypatch, video):
    """The encode lost the bet: the source was already more efficient, so
    keeping the new file would be worse on both size and quality."""
    _ffmpeg(monkeypatch, produces=9_000_000)

    transcode.transcode(str(video))

    assert video.stat().st_size == 5_000_000


def test_a_failed_encode_keeps_the_file(monkeypatch, video):
    _ffmpeg(monkeypatch, returncode=1, produces=1_000)

    assert transcode.transcode(str(video)) == str(video)
    assert video.stat().st_size == 5_000_000


def test_an_encoder_that_will_not_start_keeps_the_file(monkeypatch, video):
    def boom(*a, **k):
        raise OSError("no ffmpeg")

    monkeypatch.setattr(transcode, "_audio_is_already_aac", lambda path: True)
    monkeypatch.setattr(transcode.subprocess, "Popen", boom)

    assert transcode.transcode(str(video)) == str(video)
    assert video.stat().st_size == 5_000_000


def test_nothing_is_left_behind_when_it_fails(monkeypatch, video):
    """A temp file beside the video would show up in the file manager."""
    _ffmpeg(monkeypatch, returncode=1, produces=1_000)

    transcode.transcode(str(video))

    assert [p.name for p in video.parent.iterdir()] == [video.name]


def test_a_missing_file_is_not_an_error(monkeypatch, tmp_path):
    """The path comes from a download that reported success; if it is not there
    anyway, that is not this module's problem to raise about."""
    assert transcode.transcode(str(tmp_path / "gone.mp4")) == str(tmp_path / "gone.mp4")


# ── The switch ────────────────────────────────────────────────────────────────

def test_it_is_off_unless_switched_on(monkeypatch):
    monkeypatch.setattr("app.config.get_settings", lambda: {})
    assert transcode.enabled() is False

    monkeypatch.setattr("app.config.get_settings", lambda: {"transcode_enabled": True})
    assert transcode.enabled() is True


def test_the_job_skips_it_when_off(monkeypatch):
    from app.jobs import JobManager

    monkeypatch.setattr(transcode, "enabled", lambda: False)
    called = []
    monkeypatch.setattr(transcode, "transcode", lambda *a, **k: called.append(a))

    manager = JobManager()
    job = manager._make_job("Film", "film")
    assert manager._maybe_transcode(job, "/videos/f.mp4") == "/videos/f.mp4"
    assert called == []


def test_the_step_appears_only_when_it_is_on(monkeypatch):
    from app.jobs import JobManager

    monkeypatch.setattr(transcode, "enabled", lambda: False)
    assert "transcoding" not in JobManager._compute_phases(["ita"])

    monkeypatch.setattr(transcode, "enabled", lambda: True)
    steps = JobManager._compute_phases(["ita"])
    assert steps[-2:] == ["transcoding", "done"]


def test_cancelling_stops_it_and_keeps_the_file(monkeypatch, video):
    """A cancel during the encode must leave the downloaded file untouched."""
    killed = []

    class _Process:
        def __init__(self, cmd, **kwargs):
            self.returncode = None

        def communicate(self, timeout=None):
            raise subprocess.TimeoutExpired("ffmpeg", timeout)

        def kill(self):
            killed.append(True)

        def wait(self):
            pass

    monkeypatch.setattr(transcode, "_audio_is_already_aac", lambda path: True)
    monkeypatch.setattr(transcode.subprocess, "Popen", _Process)
    cancel = SimpleNamespace(is_set=lambda: True)

    assert transcode.transcode(str(video), cancel_event=cancel) == str(video)
    assert killed == [True]
    assert video.stat().st_size == 5_000_000
