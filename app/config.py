"""Where things live, and the settings the user can change.

Everything writable is addressed absolutely, under the user's Application
Support directory. A bundled ``.app`` starts with its working directory set to
``/`` — relative paths like the old ``data.json`` would resolve against the root
of the filesystem and fail on the first write, which is the single most common
way a working script breaks the moment it becomes an app.

The environment still wins where it is set, which is what lets the tests point
these at a temporary directory.
"""

import json
import logging
import os
from pathlib import Path

from filelock import FileLock

logger = logging.getLogger(__name__)

APP_NAME = "StreamingCommunity Downloader"


def _app_support() -> Path:
    """The per-user directory for this app's own state, created on demand."""
    base = Path.home() / "Library" / "Application Support" / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def _path_from_env(name: str, default: Path) -> Path:
    raw = os.getenv(name)
    return Path(raw).expanduser() if raw else default


SUPPORT_DIR = _app_support()

DATA_FILE = _path_from_env("DATA_FILE", SUPPORT_DIR / "data.json")
TMP_DIR = _path_from_env("TMP_DIR", SUPPORT_DIR / "tmp")

# Where downloads land when no per-type library path is configured. Inside the
# user's own Movies folder rather than Application Support: these are files the
# user opens, moves and deletes, not state belonging to the app.
VIDEOS_DIR = _path_from_env("VIDEOS_DIR", Path.home() / "Movies" / "StreamingCommunity")

# The panel binds to loopback only. It is a local window onto a local process;
# there is no login in front of it, so it must not be reachable from the network.
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))

SETTINGS_DEFAULTS = {
    "max_concurrent_downloads": 3,
    # One by default, and not for caution: x265 already spreads itself across
    # every core, so three at once do not finish sooner — they all finish later.
    "max_concurrent_transcodes": 1,
    "max_segment_workers": 16,
    # Whether to look for a replacement when the source domain stops answering.
    "domain_auto_check_enabled": True,
    # Whether to adopt the replacement without asking. Off: a domain found on a
    # page we do not control is proposed, never applied on its own.
    # See app.core.domain_recovery.
    "domain_auto_apply": False,
    "domain_check_interval_minutes": 360,
    # Post a macOS notification when a download finishes. See app/notify.py.
    "notifications_enabled": True,
    # Re-encode each finished download to HEVC. Off: it costs about a third of
    # the running time in CPU to save about a third of the size, on a source
    # that is already heavily compressed. See app/core/transcode.py.
    "transcode_enabled": False,
}


def read_data() -> dict:
    try:
        with open(DATA_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def download_dir() -> Path:
    """The one folder downloads land in, and the one the file manager shows.

    There used to be three — a path per content type — which is why the file
    manager and the downloads could disagree: downloads went to the configured
    library paths while the file manager always browsed VIDEOS_DIR, so setting a
    library made the File tab stop showing what was being downloaded into it.
    One folder cannot drift from itself.

    Read on every call rather than bound at import: it is a setting, and a job
    submitted after it changes must land in the new place.
    """
    configured = (read_data().get("download_dir") or "").strip()
    return Path(configured).expanduser() if configured else VIDEOS_DIR


def configured_domain() -> str:
    """The source domain, as configured by the user.

    Every outbound request to the source resolves its host through here, and it
    is never taken from a request body — the window is a browser like any other,
    and a page it happens to load must not be able to redirect the downloader at
    a host of its choosing.
    """
    return (read_data().get("domain") or "").strip()


def get_settings() -> dict:
    try:
        with open(DATA_FILE) as f:
            data = json.load(f)
        return {**SETTINGS_DEFAULTS, **data.get("settings", {})}
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(SETTINGS_DEFAULTS)


def update_data(changes: dict):
    """Apply top-level changes to data.json under the shared lock.

    Read-modify-write inside the lock rather than "read it somewhere, mutate,
    write it back": the domain recovery loop writes ``domain`` from a background
    thread while the user may be saving library paths, and the last writer would
    otherwise drop the other's key wholesale.

    This lives here, not in the domain router, because ``app.core`` writes the
    domain too and importing a router from ``app.core`` would be a cycle.
    """
    lock = FileLock(str(DATA_FILE) + ".lock")
    with lock:
        try:
            with open(DATA_FILE) as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}
        data.update(changes)
        with open(DATA_FILE, "w") as f:
            json.dump(data, f)


def save_settings(new_settings: dict):
    update_data({"settings": new_settings})


def merge_settings(changes: dict) -> dict:
    """Apply *changes* over the stored settings, reading and writing under one
    lock, and return the result.

    Read-modify-write outside the lock loses updates whenever two saves overlap,
    and they do: closing the settings modal fires several at once. Each would
    read the same stored state, then write its own merge over the top, so the
    last one back silently reverted every field the others had just changed —
    while every one of them answered 200.
    """
    lock = FileLock(str(DATA_FILE) + ".lock")
    with lock:
        try:
            with open(DATA_FILE) as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}
        merged = {**SETTINGS_DEFAULTS, **data.get("settings", {}), **changes}
        data["settings"] = merged
        with open(DATA_FILE, "w") as f:
            json.dump(data, f)
        return merged
