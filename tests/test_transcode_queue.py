"""Downloading and re-encoding queue separately.

The two used to share one semaphore, so a download that had finished went on
holding its slot for the whole encode. With three of each and four files that
meant three downloads, then a silent network for as long as the encoders took —
the fourth file could not start even though nothing was downloading.
"""

import threading
import time

import pytest

from app.jobs import JobManager


@pytest.fixture
def blocking_transcode(monkeypatch):
    """An encoder that starts, reports itself, and then hangs until released."""
    from app.core import transcode

    started = threading.Semaphore(0)
    release = threading.Event()

    def fake_transcode(path, **kwargs):
        started.release()
        release.wait(timeout=5)
        return path

    monkeypatch.setattr(transcode, "enabled", lambda: True)
    monkeypatch.setattr(transcode, "duration_seconds", lambda path: 0)
    monkeypatch.setattr(transcode, "transcode", fake_transcode)
    yield started, release
    release.set()


def test_a_download_slot_is_freed_before_the_encoder_queue(blocking_transcode):
    started, release = blocking_transcode
    jm = JobManager()
    jm.update_max_concurrent(3)
    jm.update_max_transcodes(1)

    downloaded = threading.Semaphore(0)

    def fake_download(*args, **kwargs):
        downloaded.release()
        return "/tmp/out.mp4"

    try:
        jobs = [jm._make_job(f"t{i}", "film") for i in range(4)]
        for job in jobs:
            jm._submit_job(job, fake_download)

        # All four downloads run even though the encoder only lets one through:
        # the fourth is only reachable if the first three gave their download
        # slots back on the way into the encoder queue.
        for i in range(4):
            assert downloaded.acquire(timeout=3), f"only {i} downloads ran before stalling"

        assert started.acquire(timeout=3), "the first encode never started"
        assert not started.acquire(timeout=0.3), "more encodes ran at once than allowed"

        release.set()
        deadline = time.time() + 5
        while time.time() < deadline and any(j.status not in ("done", "error") for j in jobs):
            time.sleep(0.02)
        assert all(j.status == "done" for j in jobs), [j.error for j in jobs]
    finally:
        release.set()
        jm._executor.shutdown(wait=False)


def test_transcoding_off_means_no_encoder_queue_at_all(monkeypatch):
    """A job that will not encode must not wait behind one that will."""
    from app.core import transcode

    monkeypatch.setattr(transcode, "enabled", lambda: False)
    jm = JobManager()
    jm.update_max_transcodes(1)
    jm._transcode_semaphore.acquire()  # the only slot, held by nobody real

    try:
        job = jm._make_job("t", "film")
        jm._submit_job(job, lambda *a, **k: "/tmp/out.mp4")
        deadline = time.time() + 3
        while time.time() < deadline and job.status not in ("done", "error"):
            time.sleep(0.02)
        assert job.status == "done", "a job with transcoding off queued for an encoder slot"
    finally:
        jm._executor.shutdown(wait=False)
