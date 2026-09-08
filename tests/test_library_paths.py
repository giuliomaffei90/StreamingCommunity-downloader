r"""A Windows library path on a Linux deployment, and what it cost.

Reported as "AnimeUnity does not download at all". Every segment of every
episode was fetched correctly and the job then died at the last step with

    Error opening output file N:\Jellyfin\Anime/Le Bizzarre .../... .mp4
    Error opening output files: Protocol not found

The anime library was configured with the *host* side of the Docker volume
mapping. Nothing on the way down objects to that: a backslash is an ordinary
character in a Linux filename, so ``os.makedirs`` cheerfully created a single
directory literally called ``N:\Jellyfin\Anime`` next to the app and the
download ran to completion into it. Only FFmpeg complained, and it complained
about a protocol called ``N`` — an error that points nowhere near the mistake.

Two defences, because they catch different deployments: the path is refused
when it is saved, and refused again before a download that inherited an
already-saved one fetches anything. Plus ``file:``, so a colon in a path
FFmpeg *should* accept is never read as a protocol name to begin with.
"""

import json
import os
from pathlib import Path

import pytest

from app.core import paths
from app.core.ffmpeg_path import ffmpeg_file_arg
from app.core.paths import looks_like_windows_path, validate_library_path, windows_path_problem


@pytest.fixture
def posix_host(monkeypatch):
    """Pretend to be the Linux container the report came from."""
    monkeypatch.setattr(paths, "_host_is_windows", lambda: False)


# ── recognising one ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", [
    r"N:\Jellyfin\Anime",
    r"C:\Users\me\Videos",
    "C:/Media",
    r"\\nas\media\anime",
])
def test_a_host_path_is_recognised(path):
    assert looks_like_windows_path(path)


@pytest.mark.parametrize("path", [
    "/media/anime",
    "/mnt/jellyfin/Anime",
    "videos",
    "",
    "  ",
])
def test_a_container_path_is_left_alone(path):
    assert not looks_like_windows_path(path)


def test_the_message_says_what_to_type_instead(posix_host):
    """The whole point of catching it: saying what to do instead.

    "Protocol not found" is true and useless, and so is "that path is wrong".
    The advice names a shape the user can actually copy, and points at the
    button that fills it in for them.
    """
    problem = windows_path_problem(r"N:\Jellyfin\Anime")

    assert problem is not None
    assert r"N:\Jellyfin\Anime" in problem
    assert "/Users/" in problem
    assert "Sfoglia" in problem


def test_a_windows_host_is_not_told_off(monkeypatch):
    """The same path is correct when the panel really does run on Windows."""
    monkeypatch.setattr(paths, "_host_is_windows", lambda: True)

    assert windows_path_problem(r"N:\Jellyfin\Anime") is None
    assert validate_library_path(r"N:\Jellyfin\Anime") == r"N:\Jellyfin\Anime"


def test_an_empty_path_is_refused_everywhere():
    with pytest.raises(ValueError, match="vuoto"):
        validate_library_path("   ")


def test_a_valid_path_comes_back_trimmed(posix_host):
    assert validate_library_path("  /media/anime  ") == "/media/anime"


# ── which host this is ──────────────────────────────────────────────

def test_the_real_host_has_the_last_word():
    """No patching at all, on whatever machine the suite is running.

    The check must never get in the way of a manual Windows install, where a
    drive path is simply the correct answer; and it must fire on Linux, where
    it is not. Running on both platforms, this asserts the same rule from
    opposite sides.
    """
    problem = windows_path_problem(r"N:\Jellyfin\Anime")

    assert (problem is None) == (os.name == "nt")


# ── refused when saved ────────────────────────────────────────────────────────

def test_saving_a_host_path_is_rejected(client, posix_host):
    response = client.put("/api/domain/download-dir",
                          json={"path": r"N:\Jellyfin\Anime"})

    assert response.status_code == 400
    assert "percorso Windows" in response.json()["detail"]


def test_a_rejected_save_writes_nothing(client, posix_host):
    """A refused folder must not be left half-applied."""
    from app import config

    client.put("/api/domain/download-dir", json={"path": r"N:\Jellyfin\Anime"})

    stored = json.loads(config.DATA_FILE.read_text(encoding="utf-8"))
    assert "download_dir" not in stored


def test_posix_paths_still_save(client, posix_host, tmp_path):
    target = tmp_path / "media"

    response = client.put("/api/domain/download-dir", json={"path": str(target)})

    assert response.status_code == 200, response.text
    # Created on save rather than at the first download: the file manager is
    # rooted here, and an absent root shows as an empty library.
    assert target.is_dir()


def test_clearing_it_goes_back_to_the_default(client, posix_host):
    from app import config

    client.put("/api/domain/download-dir", json={"path": ""})

    assert client.get("/api/domain/download-dir").json()["path"] == ""
    assert config.download_dir() == config.VIDEOS_DIR


# ── refused before the download runs ──────────────────────────────────────────

def test_a_download_to_a_host_path_fails_before_fetching_anything(posix_host, monkeypatch):
    """The deployment in the report already had the bad path saved.

    Validating on save does nothing for it, so the check runs again at the top
    of the download — before a single segment is requested, rather than after
    all 186 of them.
    """
    from app.core import m3u8

    def explode(*args, **kwargs):
        raise AssertionError("nothing may be fetched before the path is checked")

    monkeypatch.setattr(m3u8.requests.Session, "get", explode)

    with pytest.raises(RuntimeError) as excinfo:
        m3u8.download_m3u8(
            m3u8_index="https://cdn.example.test/playlist.m3u8",
            output_filename=r"N:\Jellyfin\Anime\Show (2021)\Show S01E01.mp4",
        )

    assert "percorso Windows" in str(excinfo.value)


# ── and the colon itself ──────────────────────────────────────────────────────

def test_ffmpeg_is_told_the_path_is_a_path():
    """``N:`` is a drive letter to everyone except FFmpeg, to which it is a
    protocol. The prefix removes the ambiguity."""
    assert ffmpeg_file_arg(r"N:\Jellyfin\out.mp4") == r"file:N:\Jellyfin\out.mp4"
    assert ffmpeg_file_arg("/media/anime/out.mp4") == "file:/media/anime/out.mp4"


def test_the_prefix_is_not_applied_twice():
    once = ffmpeg_file_arg("/media/anime/out.mp4")
    assert ffmpeg_file_arg(once) == once


def test_the_extension_stays_at_the_end():
    """FFmpeg picks the muxer from the extension, so the prefix must not
    disturb it."""
    assert ffmpeg_file_arg("/media/x/out.mkv").endswith(".mkv")
