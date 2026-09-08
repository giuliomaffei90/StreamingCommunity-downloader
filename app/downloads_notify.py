"""Telling the user a download finished, through the Notification Centre.

It also collapses a season or a series asked for in one go into a single
message: twenty-four "episode ready" pings for one season is noise, not news.
That is the whole reason this module still keeps books rather than notifying
straight from the job listener.
"""

import logging
import re
import threading
from dataclasses import dataclass, field

from app import notify as notifier

logger = logging.getLogger(__name__)

# Enough to identify what failed without turning a notification into a log dump.
MAX_LISTED_FAILURES = 3
MAX_ERROR_CHARS = 120

_BATCH_TITLES = {
    "season": ("Stagione completata", "Stagione completata con errori", "Stagione non scaricata"),
    "series": ("Serie completata", "Serie completata con errori", "Serie non scaricata"),
    "anime_all": ("Anime completato", "Anime completato con errori", "Anime non scaricato"),
}


# ── Batch bookkeeping ──────────────────────────────────────────────────────────

@dataclass
class _Batch:
    kind: str
    label: str
    remaining: int
    done: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    cancelled: list[str] = field(default_factory=list)


_batches: dict[str, _Batch] = {}
_lock = threading.Lock()


def register(batch_id: str, *, kind: str, label: str, expected: int):
    """Open a batch. Must be called *before* the first job is submitted.

    A job can fail in the instant it is created, so registering afterwards would
    let the first result arrive before the batch it belongs to exists.
    """
    with _lock:
        _batches[batch_id] = _Batch(kind=kind, label=label, remaining=expected)


def abandon(batch_id: str, count: int):
    """Write off jobs that were never submitted, so the batch can still close."""
    summary = None
    with _lock:
        batch = _batches.get(batch_id)
        if batch is None:
            return
        batch.remaining -= count
        if batch.remaining <= 0:
            summary = _batches.pop(batch_id)
    if summary is not None:
        _announce_batch(summary)


def pending_batches() -> int:
    """Open batches. Only used by tests and for logging."""
    with _lock:
        return len(_batches)


# ── Labels and text ────────────────────────────────────────────────────────────

def _episode_label(job) -> str:
    """A label that stays unambiguous inside a whole-series batch."""
    if job.season is not None and job.episode_number is not None:
        return f"S{int(job.season):02d}E{str(job.episode_number).zfill(2)}"
    if job.episode_number is not None:
        return f"E{job.episode_number}"
    return job.media_label or job.title


def _clean_error(error: str | None) -> str:
    """Trim an error down to one readable line.

    ``job.error`` is str() of whatever the downloader raised and routinely
    carries the source URL with its query string and token. A notification is
    two lines on screen, so the tail goes; the full text stays in the log and on
    the job card, which is where anybody debugging actually looks.
    """
    text = (error or "errore sconosciuto").strip()
    text = re.sub(r"(https?://[^\s?]+)\?\S*", r"\1", text)
    text = " ".join(text.split())
    if len(text) > MAX_ERROR_CHARS:
        text = text[:MAX_ERROR_CHARS - 1] + "…"
    return text


def _media_title(job) -> str:
    year = f" ({job.year})" if job.year else ""
    return f"{job.title}{year}"


def _failure_summary(failed: list[tuple[str, str]]) -> str:
    shown = ", ".join(label for label, _ in failed[:MAX_LISTED_FAILURES])
    hidden = len(failed) - MAX_LISTED_FAILURES
    return f"{shown} e altri {hidden}" if hidden > 0 else shown


# ── Single downloads ───────────────────────────────────────────────────────────

def _announce_single(job):
    label = _media_title(job)
    if job.status == "done":
        notifier.notify("Download completato", f"«{label}» è pronto in libreria.")
        return
    notifier.notify("Download fallito", f"«{label}»: {_clean_error(job.error)}")


# ── Batch summaries ────────────────────────────────────────────────────────────

def _announce_batch(batch: _Batch):
    ok, failed, cancelled = len(batch.done), batch.failed, batch.cancelled
    total = ok + len(failed) + len(cancelled)
    ok_title, partial_title, none_title = _BATCH_TITLES.get(batch.kind, _BATCH_TITLES["season"])

    if not failed:
        notifier.notify(ok_title, f"«{batch.label}»: {ok} episodi su {total} scaricati.")
        return

    if ok == 0:
        notifier.notify(
            none_title,
            f"«{batch.label}»: nessuno scaricato, {len(failed)} falliti "
            f"({_failure_summary(failed)}).",
        )
        return

    notifier.notify(
        partial_title,
        f"«{batch.label}»: {ok} scaricati, {len(failed)} falliti "
        f"({_failure_summary(failed)}).",
    )


# ── The listener ───────────────────────────────────────────────────────────────

def on_job_finished(job):
    """Called for every job reaching a terminal state, batched or not."""
    if job.batch_id:
        _record_batch_result(job)
        return

    # Cancelling is a decision, not news: whoever pressed the button knows.
    if job.status == "cancelled":
        return

    _announce_single(job)


def _record_batch_result(job):
    summary = None
    with _lock:
        batch = _batches.get(job.batch_id)
        if batch is None:
            # Registration always precedes submission, so this means the batch
            # already closed — a duplicate terminal callback for one job.
            logger.warning("Job %s reported into unknown batch %s", job.job_id, job.batch_id)
            return
        label = _episode_label(job)
        if job.status == "done":
            batch.done.append(label)
        elif job.status == "cancelled":
            batch.cancelled.append(label)
        else:
            batch.failed.append((label, _clean_error(job.error)))
        batch.remaining -= 1
        if batch.remaining <= 0:
            summary = _batches.pop(job.batch_id)

    # Built and sent outside the lock: posting a notification shells out.
    if summary is not None:
        _announce_batch(summary)


_listener_registered = False


def register_batch_listener():
    """Wire the job manager to download notifications. Called once, from the app
    lifespan."""
    global _listener_registered
    if _listener_registered:
        return
    from app.jobs import job_manager
    job_manager.add_listener(on_job_finished)
    _listener_registered = True
