"""The ledger of what has been downloaded, and what it is for.

Two questions, one set of records: what was in flight when the app closed, and
which files on disk this app actually produced.
"""

import json

import pytest

from app import history
from app.jobs import JobManager


@pytest.fixture
def ledger(tmp_path):
    """The path conftest's _isolated_history already points the module at."""
    return tmp_path / "downloads.json"


@pytest.fixture
def manager():
    return JobManager()


def _job(manager, **kwargs):
    status = kwargs.pop("status", "queued")
    job = manager._make_job(kwargs.pop("title", "Film"), kwargs.pop("type_", "film"), **kwargs)
    job.status = status
    return job


# ── Recording ─────────────────────────────────────────────────────────────────

def test_a_job_is_written_and_read_back(manager):
    history.record(_job(manager, title="Film", status="done"))

    records = history.all_records()
    assert len(records) == 1
    assert records[0]["title"] == "Film"
    assert records[0]["status"] == "done"


def test_recording_the_same_job_twice_updates_it(manager):
    """A job is written at submit and again at every state it reaches."""
    job = _job(manager, title="Film")
    history.record(job, call_type="film", params={"id": 1})
    job.status = "done"
    job.output_path = "/videos/f.mp4"
    history.record(job)

    records = history.all_records()
    assert len(records) == 1
    assert records[0]["status"] == "done"
    # The rebuild parameters are written once and survive later updates.
    assert records[0]["params"] == {"id": 1}


def test_forgetting_removes_only_that_entry(manager):
    first, second = _job(manager, title="A"), _job(manager, title="B")
    history.record(first)
    history.record(second)

    history.forget(first.job_id)

    assert [r["title"] for r in history.all_records()] == ["B"]


def test_the_file_does_not_grow_without_limit(manager, monkeypatch):
    monkeypatch.setattr(history, "MAX_RECORDS", 3)
    for n in range(6):
        history.record(_job(manager, title=f"Film {n}"))

    records = history.all_records()
    assert len(records) == 3
    # Newest first, so the oldest are the ones dropped.
    assert records[0]["title"] == "Film 5"


def test_unreadable_history_is_not_fatal(ledger, manager):
    """A truncated or hand-edited file must not stop the app starting."""
    ledger.write_text("{ this is not json")

    assert history.all_records() == []
    history.record(_job(manager, title="Film"))
    assert len(history.all_records()) == 1


# ── Surviving a restart ───────────────────────────────────────────────────────

def test_unfinished_records_become_interrupted(manager):
    for status in ("queued", "running", "scheduled"):
        history.record(_job(manager, title=status, status=status))
    history.record(_job(manager, title="finito", status="done"))

    touched = history.close_interrupted()

    assert {r["title"] for r in touched} == {"queued", "running", "scheduled"}
    assert all(r["status"] == history.INTERRUPTED for r in touched)
    # And it stuck: a second start finds nothing left to close.
    assert history.close_interrupted() == []
    assert next(r for r in history.all_records() if r["title"] == "finito")["status"] == "done"


def test_an_interrupted_download_comes_back_as_a_failed_job(manager):
    """Not resumed — a half-written file is not something to pick up mid-stream.
    The point is that it stops vanishing."""
    job = _job(manager, title="Serie S01E01", type_="episode", status="running")
    history.record(job, call_type="film",
                   params={"id": 1, "title": "Serie", "domain": "example.test"})

    fresh = JobManager()
    fresh.restore_from_history()

    restored = fresh.get(job.job_id)
    assert restored is not None
    assert restored.status == "error"
    assert restored.title == "Serie S01E01"


def test_a_restored_job_can_be_retried(manager):
    """The call is rebuilt from the recorded parameters, since the original
    closure died with the process."""
    job = _job(manager, title="Film", status="running")
    history.record(job, call_type="film",
                   params={"id": 1, "title": "Film", "domain": "example.test"})

    fresh = JobManager()
    fresh.restore_from_history()

    assert fresh.get(job.job_id).call is not None


def test_a_record_that_cannot_be_rebuilt_still_shows(manager):
    """Better a failed entry with no Riprova than an entry that vanished."""
    job = _job(manager, title="Film", status="running")
    history.record(job, call_type="nonsense", params={})

    fresh = JobManager()
    fresh.restore_from_history()

    restored = fresh.get(job.job_id)
    assert restored is not None and restored.status == "error"
    assert restored.call is None


# ── Which files are ours ──────────────────────────────────────────────────────

def test_produced_paths_lists_what_was_written(manager):
    done = _job(manager, title="Film", status="done")
    done.output_path = "/videos/Film.mp4"
    history.record(done)
    history.record(_job(manager, title="Fallito", status="error"))

    assert history.produced_paths() == {"/videos/Film.mp4"}


def test_an_empty_ledger_means_an_empty_tab():
    """Deliberate: the tab only ever shows this app's own work, rather than
    showing everything until the first download and then almost nothing."""
    from app.routers import files

    assert files._own_files() == set()


def test_sidecar_subtitles_count_as_part_of_the_download(manager, tmp_path):
    from app.routers import files

    video = tmp_path / "Film.mp4"
    subtitle = tmp_path / "Film.eng.vtt"
    video.touch()
    subtitle.touch()
    done = _job(manager, title="Film", status="done")
    done.output_path = str(video)
    history.record(done)

    own = files._own_files()

    assert files._wanted(video, own)
    # Written beside the video by the same download, though no job returned it.
    assert str(video.with_suffix("")) + ".vtt" in own


# ── The list outlives the app ─────────────────────────────────────────────────

def test_finished_downloads_come_back_too(manager):
    """The list is cleared by the user, not by closing the app."""
    done = _job(manager, title="Film", status="done")
    done.output_path = "/videos/Film.mp4"
    history.record(done)
    history.record(_job(manager, title="Fallito", status="error"))

    fresh = JobManager()
    fresh.restore_from_history()

    titles = {j.title: j.status for j in fresh.list_jobs_raw()}
    assert titles == {"Film": "done", "Fallito": "error"}


def test_a_restored_download_keeps_where_its_file_went(manager):
    """Otherwise "mostra nel Finder" has nothing to open."""
    done = _job(manager, title="Film", status="done")
    done.output_path = "/videos/Film.mp4"
    history.record(done)

    fresh = JobManager()
    fresh.restore_from_history()

    assert fresh.get(done.job_id).output_path == "/videos/Film.mp4"


def test_a_restored_download_keeps_its_steps(manager):
    """A card with no phases draws an empty strip where the steps were."""
    job = _job(manager, title="Film", status="done", phases=["video", "merging", "done"])
    history.record(job)

    fresh = JobManager()
    fresh.restore_from_history()

    assert fresh.get(job.job_id).phases == ["video", "merging", "done"]


def test_a_finished_download_reads_as_complete(manager):
    job = _job(manager, title="Film", status="done")
    history.record(job)

    fresh = JobManager()
    fresh.restore_from_history()

    assert fresh.get(job.job_id).progress["pct"] == 100


def test_the_original_order_survives(manager):
    """The list sorts by when the download started, not when it was restored."""
    first = _job(manager, title="Primo", status="done")
    history.record(first)
    second = _job(manager, title="Secondo", status="done")
    history.record(second)

    fresh = JobManager()
    fresh.restore_from_history()

    assert fresh.get(first.job_id).created_at < fresh.get(second.job_id).created_at


def test_dismissing_a_card_stops_it_coming_back(manager):
    """Clearing the list has to mean it, or nothing could ever be cleared."""
    job = _job(manager, title="Film", status="done")
    history.record(job)
    manager._jobs[job.job_id] = job
    manager.dismiss(job.job_id)

    fresh = JobManager()
    fresh.restore_from_history()

    assert fresh.get(job.job_id) is None
