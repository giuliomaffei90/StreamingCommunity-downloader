"""Download notifications: what reaches the Notification Centre, and how often.

A season or a series asked for in one go must produce one summary, not one
message per episode.
"""

import pytest

from app import downloads_notify
from app.jobs import JobManager


@pytest.fixture(autouse=True)
def _clean_batches():
    downloads_notify._batches.clear()
    yield
    downloads_notify._batches.clear()


@pytest.fixture
def delivered(monkeypatch):
    """Capture notifications instead of posting them.

    Patched on the name ``downloads_notify`` holds rather than on the notifier
    module, so a test can never post a real notification by accident.
    """
    calls: list[dict] = []
    monkeypatch.setattr(
        downloads_notify.notifier, "notify",
        lambda title, message: calls.append({"title": title, "message": message}) or True,
    )
    return calls


def _job(manager, **kwargs):
    kwargs.setdefault("title", "Film")
    kwargs.setdefault("type_", "film")
    title = kwargs.pop("title")
    type_ = kwargs.pop("type_")
    status = kwargs.pop("status", "done")
    error = kwargs.pop("error", None)
    job = manager._make_job(title, type_, **kwargs)
    job.status = status
    job.error = error
    return job


@pytest.fixture
def manager():
    return JobManager()


# ── Single downloads ───────────────────────────────────────────────────────────

def test_a_finished_film_notifies_once(manager, delivered):
    downloads_notify.on_job_finished(_job(manager, title="Film", year="2020"))

    assert len(delivered) == 1
    assert delivered[0]["title"] == "Download completato"
    assert "Film (2020)" in delivered[0]["message"]


def test_a_failed_download_reports_the_error(manager, delivered):
    downloads_notify.on_job_finished(
        _job(manager, status="error", error="HTTP 403")
    )

    assert delivered[0]["title"] == "Download fallito"
    assert "HTTP 403" in delivered[0]["message"]


def test_a_cancelled_download_is_not_announced(manager, delivered):
    """Cancelling is a decision, not news: whoever pressed the button knows."""
    downloads_notify.on_job_finished(_job(manager, status="cancelled"))

    assert delivered == []


def test_an_error_is_stripped_of_its_query_string(manager, delivered):
    """job.error routinely carries the source URL, token included."""
    downloads_notify.on_job_finished(_job(
        manager, status="error",
        error="GET https://vixcloud.co/playlist/123?token=SECRET&expires=999 failed",
    ))

    assert "SECRET" not in delivered[0]["message"]
    assert "https://vixcloud.co/playlist/123" in delivered[0]["message"]


def test_a_notification_the_user_switched_off_is_not_posted(manager, monkeypatch):
    """The setting is read at post time, not cached at import."""
    from app import notify as notifier

    # notify() imports get_settings from app.config inside the call, so that is
    # the binding a patch has to reach.
    monkeypatch.setattr("app.config.get_settings",
                        lambda: {"notifications_enabled": False})
    ran = []
    monkeypatch.setattr(notifier.subprocess, "run", lambda *a, **k: ran.append(a))

    notifier.notify("Titolo", "Messaggio")

    assert ran == []


# ── Batches ────────────────────────────────────────────────────────────────────

def _season_job(manager, number, status="done", error=None):
    return _job(manager, title=f"Serie S02E{number:02d}", type_="episode", status=status,
                error=error, batch_id="b1", batch_kind="season",
                batch_label="Serie — Stagione 2", media_label="Serie",
                season=2, episode_number=str(number))


def test_a_batch_emits_one_summary_not_one_per_episode(manager, delivered):
    downloads_notify.register("b1", kind="season", label="Serie — Stagione 2", expected=3)

    for n in (1, 2, 3):
        downloads_notify.on_job_finished(_season_job(manager, n))

    assert len(delivered) == 1
    assert delivered[0]["title"] == "Stagione completata"
    assert "3 episodi su 3" in delivered[0]["message"]


def test_a_partial_batch_names_the_failed_episodes(manager, delivered):
    downloads_notify.register("b1", kind="season", label="Serie — Stagione 2", expected=3)

    downloads_notify.on_job_finished(_season_job(manager, 1))
    downloads_notify.on_job_finished(_season_job(manager, 2, status="error", error="HTTP 500"))
    downloads_notify.on_job_finished(_season_job(manager, 3))

    assert len(delivered) == 1
    assert delivered[0]["title"] == "Stagione completata con errori"
    assert "S02E02" in delivered[0]["message"]


def test_a_batch_where_nothing_worked_says_so(manager, delivered):
    downloads_notify.register("b1", kind="season", label="Serie — Stagione 2", expected=2)

    for n in (1, 2):
        downloads_notify.on_job_finished(_season_job(manager, n, status="error", error="boom"))

    assert delivered[0]["title"] == "Stagione non scaricata"


def test_a_cancelled_episode_still_closes_its_batch(manager, delivered):
    """Otherwise the summary waits forever on a job nobody will finish."""
    downloads_notify.register("b1", kind="season", label="Serie — Stagione 2", expected=2)

    downloads_notify.on_job_finished(_season_job(manager, 1))
    downloads_notify.on_job_finished(_season_job(manager, 2, status="cancelled"))

    assert len(delivered) == 1


def test_the_summary_waits_for_every_episode(manager, delivered):
    downloads_notify.register("b1", kind="season", label="Serie — Stagione 2", expected=3)

    downloads_notify.on_job_finished(_season_job(manager, 1))
    downloads_notify.on_job_finished(_season_job(manager, 2))

    assert delivered == []
    assert downloads_notify.pending_batches() == 1


def test_jobs_that_were_never_submitted_are_written_off(manager, delivered):
    """A batch that fails half way through submission must still close."""
    downloads_notify.register("b1", kind="season", label="Serie — Stagione 2", expected=3)

    downloads_notify.on_job_finished(_season_job(manager, 1))
    downloads_notify.abandon("b1", 2)

    assert len(delivered) == 1
    assert downloads_notify.pending_batches() == 0


def test_a_long_failure_list_is_capped(manager, delivered):
    """A notification is two lines on screen, not a log dump."""
    downloads_notify.register("b1", kind="season", label="Serie — Stagione 2", expected=8)

    for n in range(1, 9):
        downloads_notify.on_job_finished(_season_job(manager, n, status="error", error="boom"))

    assert "e altri 5" in delivered[0]["message"]


def test_an_anime_batch_uses_flat_episode_labels(manager, delivered):
    """No seasons there, so S00E01 would be a lie."""
    downloads_notify.register("b1", kind="anime_all", label="Anime", expected=1)

    job = _job(manager, title="Anime E7", type_="anime", status="error", error="boom",
               batch_id="b1", batch_kind="anime_all", batch_label="Anime",
               media_label="Anime", episode_number="7")
    downloads_notify.on_job_finished(job)

    assert delivered[0]["title"] == "Anime non scaricato"
    assert "E7" in delivered[0]["message"]
