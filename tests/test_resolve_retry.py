"""Retrying the resolution phase, which is what a source in trouble breaks.

Resolution is everything before the first byte: asking the source which episode,
and the video host where the playlist is. A failure there throws the whole job
away, and the loops that guarded it only ever looked at `status_code` — a
timeout raises before there is one, so it fell straight through.
"""

import requests
import pytest

from app.core import _shared


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    """The backoff is real seconds; the test does not need to live them."""
    monkeypatch.setattr(_shared.time, "sleep", lambda _: None)


class _Response:
    def __init__(self, status_code=200):
        self.status_code = status_code
        self.ok = status_code < 400


def _sequence(*outcomes):
    """A sender that yields each outcome in turn, raising the exceptions."""
    remaining = list(outcomes)
    calls = []

    def send():
        calls.append(len(calls) + 1)
        outcome = remaining.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    send.calls = calls
    return send


# ── What is worth another attempt ─────────────────────────────────────────────

def test_a_timeout_is_retried():
    """The whole reason this exists: the source answers a read timeout when it
    is struggling, and that used to kill the download outright."""
    send = _sequence(requests.exceptions.ReadTimeout("slow"), _Response(200))

    result = _shared.with_retry(send, what="test")

    assert result.status_code == 200
    assert len(send.calls) == 2


def test_a_dropped_connection_is_retried():
    send = _sequence(requests.exceptions.ConnectionError("reset"), _Response(200))

    assert _shared.with_retry(send, what="test").status_code == 200
    assert len(send.calls) == 2


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_the_source_being_unwell_is_retried(status):
    """502 is exactly what AnimeUnity returned while it was down."""
    send = _sequence(_Response(status), _Response(200))

    assert _shared.with_retry(send, what="test").status_code == 200
    assert len(send.calls) == 2


# ── What is not ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status", [400, 403, 404])
def test_a_verdict_is_not_retried(status):
    """A 4xx is an answer, not congestion — the same reasoning the segment
    limiter uses. Sending it again would only be slower."""
    send = _sequence(_Response(status))

    assert _shared.with_retry(send, what="test").status_code == status
    assert len(send.calls) == 1


def test_a_first_attempt_that_works_is_not_repeated():
    send = _sequence(_Response(200))

    _shared.with_retry(send, what="test")

    assert len(send.calls) == 1


# ── Giving up ─────────────────────────────────────────────────────────────────

def test_it_gives_up_and_reports_the_timeout():
    """A source that is genuinely down must still fail, with the error the
    caller can act on rather than a wrapped one."""
    send = _sequence(*[requests.exceptions.ReadTimeout("slow")] * 3)

    with pytest.raises(requests.exceptions.ReadTimeout):
        _shared.with_retry(send, what="test", attempts=3)

    assert len(send.calls) == 3


def test_it_gives_up_and_returns_the_last_response():
    """Persistent 502s come back as a response, so the caller's own message
    names the status."""
    send = _sequence(*[_Response(502)] * 3)

    assert _shared.with_retry(send, what="test", attempts=3).status_code == 502
    assert len(send.calls) == 3


def test_the_wait_grows_between_attempts(monkeypatch):
    waits = []
    monkeypatch.setattr(_shared.time, "sleep", waits.append)
    send = _sequence(_Response(502), _Response(502), _Response(200))

    _shared.with_retry(send, what="test")

    assert waits == [1, 2]
