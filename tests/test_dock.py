"""The Dock badge: what it should read for a given set of jobs.

Only the decision is tested. Setting the badge is one AppKit call that does
nothing without a window server, and is a no-op unless desktop.py switched it
on — a browser session's Dock tile belongs to the Python process, not to
anything the user thinks of as this app.
"""

from types import SimpleNamespace

from app import dock


def _job(status, pct=None):
    return SimpleNamespace(status=status, progress={"pct": pct} if pct is not None else {})


def test_nothing_running_clears_the_badge():
    assert dock.badge_for([]) is None
    assert dock.badge_for([_job("done"), _job("error"), _job("cancelled")]) is None


def test_one_download_shows_its_percentage():
    assert dock.badge_for([_job("running", 42.4), _job("done")]) == "42%"


def test_several_downloads_show_how_many():
    """An average across them would be a figure that matches nothing on screen."""
    assert dock.badge_for([_job("running", 10), _job("running", 90), _job("queued")]) == "3"


def test_a_queued_download_counts_as_active():
    """It is why the icon should say something at all: work is outstanding."""
    assert dock.badge_for([_job("queued")]) == "0%"


def test_a_job_with_no_progress_yet_reads_zero():
    assert dock.badge_for([_job("running")]) == "0%"


def test_setting_the_badge_is_inert_until_activated(monkeypatch):
    """Every call is a no-op in a browser session, where there is no tile of
    ours to write on."""
    calls = []
    monkeypatch.setattr(dock, "_enabled", False)
    monkeypatch.setattr(dock, "_tile", SimpleNamespace(
        performSelectorOnMainThread_withObject_waitUntilDone_=lambda *a: calls.append(a)))

    dock.update([_job("running", 50)])

    assert calls == []
