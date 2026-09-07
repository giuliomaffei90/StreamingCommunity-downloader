"""Running a failed download again, from the list, without searching for it anew.

The panel already holds the call that failed, so a retry is that same call —
not a second trip through the browser, where the token and the episode list have
usually gone stale by the time anybody notices the failure.
"""

import time

import pytest

from app.jobs import JobManager


@pytest.fixture
def manager():
    jm = JobManager()
    jm.update_max_concurrent(2)
    return jm


def _wait_for(predicate, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _flaky(failures: int):
    """A download that fails ``failures`` times, then succeeds."""
    state = {"calls": 0}

    def call():
        state["calls"] += 1
        if state["calls"] <= failures:
            raise RuntimeError("HTTP 403")
        return "/videos/f.mp4"

    return call, state


def test_a_failed_job_runs_again_and_can_succeed(manager):
    job_id = manager._submit_job(manager._make_job("Film", "film"), _flaky(1)[0])
    assert _wait_for(lambda: manager.get(job_id).status == "error")

    assert manager.retry(job_id) is True

    assert _wait_for(lambda: manager.get(job_id).status == "done")
    job = manager.get(job_id)
    assert job.output_path == "/videos/f.mp4"
    assert job.error is None


def test_the_retry_reaches_the_terminal_listeners(manager):
    """Anything counting completions must hear about the second run too."""
    # The listener is handed the job itself, which the retry mutates in place —
    # so what it was when it reported has to be read there, not afterwards.
    seen = []
    manager.add_listener(lambda job: seen.append(job.status))

    job_id = manager._submit_job(manager._make_job("Film", "film"), _flaky(1)[0])
    assert _wait_for(lambda: seen)
    manager.retry(job_id)

    assert _wait_for(lambda: len(seen) == 2)
    assert seen == ["error", "done"]


def test_a_retry_leaves_the_batch_it_belonged_to(manager):
    """Its season summary already counted the failure and has been sent.

    Reporting into that batch a second time would close it early, on episodes
    somebody is still waiting for.
    """
    job = manager._make_job("Serie S01E01", "episode", batch_id="b1",
                            batch_kind="season", batch_label="Serie — Stagione 1")
    job_id = manager._submit_job(job, _flaky(1)[0])
    assert _wait_for(lambda: manager.get(job_id).status == "error")

    manager.retry(job_id)

    assert _wait_for(lambda: manager.get(job_id).status == "done")
    assert manager.get(job_id).batch_id is None


def test_a_cancelled_job_can_be_run_again(manager):
    job_id = manager._submit_job(manager._make_job("Film", "film"), _flaky(0)[0])
    assert _wait_for(lambda: manager.get(job_id).status == "done")
    # Simulate the cancelled path: the flag must not survive into the retry.
    job = manager.get(job_id)
    job.status = "cancelled"
    job.cancel_event.set()

    assert manager.retry(job_id) is True

    assert _wait_for(lambda: manager.get(job_id).status == "done")
    assert not manager.get(job_id).cancel_event.is_set()


def test_a_finished_or_never_run_job_is_not_retryable(manager):
    done = manager._submit_job(manager._make_job("Film", "film"), _flaky(0)[0])
    assert _wait_for(lambda: manager.get(done).status == "done")
    assert manager.retry(done) is False

    # Cancelled before the executor ever saw it: there is no call to repeat.
    never_ran = manager._make_job("Film", "film")
    never_ran.status = "cancelled"
    manager._jobs[never_ran.job_id] = never_ran
    assert manager.retry(never_ran.job_id) is False

    assert manager.retry("no-such-job") is False
