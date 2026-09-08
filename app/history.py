"""What this app has downloaded, remembered across restarts.

Job state lives in memory in ``JobManager``, which is what makes closing the app
lose it: the list came back empty and a download interrupted half way through
left nothing behind saying so. This is the ledger that survives, and it answers
two different questions with the same records:

* **What was the download list?** The whole list is rebuilt from here on start
  and cleared by the user, not by closing the app — the same bargain a torrent
  client makes. Anything left non-terminal is marked ``interrupted`` first, so
  it comes back as failed and can be run again rather than claiming to still be
  going.
* **Which files on disk did this app produce?** The download folder is very
  often one the user already keeps things in, so "every video under it" is not
  the same question as "what did I download", and only the ledger knows.

Deliberately not in ``data.json``: that file is settings, read on nearly every
request and rewritten under a lock by the domain watcher. This grows with use
and is written only when a download changes state.
"""

import json
import logging
import threading
from datetime import datetime, timezone

from app.config import SUPPORT_DIR

logger = logging.getLogger(__name__)

HISTORY_FILE = SUPPORT_DIR / "downloads.json"

# Enough to be useful, bounded so the file cannot grow without limit. Oldest
# entries fall off the end.
MAX_RECORDS = 500

# A job that was still going when the process ended. Not a status JobManager
# ever produces itself — it only exists because a run was cut short from
# outside.
INTERRUPTED = "interrupted"

_lock = threading.Lock()


def _read() -> list[dict]:
    try:
        with open(HISTORY_FILE) as handle:
            data = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _write(records: list[dict]) -> None:
    try:
        with open(HISTORY_FILE, "w") as handle:
            json.dump(records[:MAX_RECORDS], handle)
    except OSError:
        # The ledger is a convenience; a download must not fail because it
        # could not be written down.
        logger.exception("Could not write the download history")


def all_records() -> list[dict]:
    with _lock:
        return _read()


def record(job, *, call_type: str | None = None, params: dict | None = None) -> None:
    """Insert or update the entry for *job*, newest first.

    ``call_type`` and ``params`` are what ``JobManager._build_call`` needs to
    reconstruct the download after a restart, when the original closure is gone.
    They are only supplied on the first write; later updates keep what is there.
    """
    with _lock:
        records = _read()
        existing = next((r for r in records if r.get("job_id") == job.job_id), None)
        entry = existing or {}
        entry.update({
            "job_id": job.job_id,
            "title": job.title,
            "type": job.type,
            "status": job.status,
            "error": job.error,
            "output_path": job.output_path,
            "media_label": job.media_label,
            "year": job.year,
            "season": job.season,
            "episode_number": job.episode_number,
            "phases": list(job.phases or []),
            "created_at": job.created_at.isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        if call_type is not None:
            entry["call_type"] = call_type
        if params is not None:
            entry["params"] = params
        if existing is not None:
            records.remove(existing)
        _write([entry] + records)


def forget(job_id: str) -> None:
    with _lock:
        _write([r for r in _read() if r.get("job_id") != job_id])


def close_interrupted() -> list[dict]:
    """Mark everything left unfinished as interrupted, and return those entries.

    Called once at startup. A record still saying ``running`` or ``queued`` has
    no worker behind it any more and never will — the process that owned it is
    gone.
    """
    with _lock:
        records = _read()
        touched = []
        for entry in records:
            # "scheduled" is no longer a status this app produces; entries
            # written before scheduling was removed still carry it, and
            # they have to be closed like any other unfinished row.
            if entry.get("status") in ("queued", "running", "scheduled"):
                entry["status"] = INTERRUPTED
                entry["error"] = "Interrotto dalla chiusura dell'app"
                touched.append(entry)
        if touched:
            _write(records)
        return touched


def produced_paths() -> set[str]:
    """Every path this app has written, whether or not it still exists.

    The File tab intersects this with what is on disk, so a file deleted outside
    the app simply stops appearing.
    """
    with _lock:
        return {r["output_path"] for r in _read() if r.get("output_path")}
