"""The native folder chooser behind the library paths.

Typing a path from memory is how a library ends up pointing at a directory that
does not exist, which is not discovered until a download has finished. This is
only possible because the panel and the person are on the same machine.
"""

from types import SimpleNamespace

import pytest

from app.routers import files


def _osascript(monkeypatch, returncode=0, stdout=""):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")

    monkeypatch.setattr(files.subprocess, "run", fake_run)
    return calls


def test_a_chosen_folder_comes_back_without_its_trailing_slash(monkeypatch):
    """AppleScript returns directories with one; everything else stores them without."""
    _osascript(monkeypatch, stdout="/Users/me/Movies/Serie/\n")

    assert files._choose_folder_sync() == "/Users/me/Movies/Serie"


def test_cancelling_is_not_an_error(monkeypatch):
    """Closing a dialog is the ordinary way out of it."""
    _osascript(monkeypatch, returncode=1, stdout="")

    assert files._choose_folder_sync() is None


def test_a_path_with_spaces_survives(monkeypatch):
    _osascript(monkeypatch, stdout="/Volumes/Disco Esterno/Film e Serie/\n")

    assert files._choose_folder_sync() == "/Volumes/Disco Esterno/Film e Serie"


def test_the_prompt_is_passed_as_an_argument(monkeypatch):
    """Not interpolated into the script, like every other osascript call here."""
    calls = _osascript(monkeypatch, stdout="/tmp/x/\n")

    files._choose_folder_sync()

    assert calls[0][:2] == ["osascript", "-e"]
    assert calls[0][-1] == files._PICK_PROMPT


def test_the_endpoint_reports_a_cancellation_as_a_null_path(client, monkeypatch):
    _osascript(monkeypatch, returncode=1)

    assert client.post("/api/files/pick-folder").json() == {"path": None}


def test_a_missing_osascript_is_a_500_not_a_crash(client, monkeypatch):
    def boom(*a, **k):
        raise OSError("no such binary")

    monkeypatch.setattr(files.subprocess, "run", boom)

    assert client.post("/api/files/pick-folder").status_code == 500
