"""Telling something else that a download finished.

A URL, a method, optional headers and a body template, fired when a download
reaches a terminal state. That is all this is now: the Jellyfin library refresh
that used to sit beside it went with Jellyfin itself.

There is no shell hook and there will not be one. The settings are open to
whoever has the window — there is no login in front of them — so a command
column here would turn a settings form into a shell.

A webhook is still an outbound request to an address the user chose, and
pointing it at ``192.168.x`` is the *point*. The mitigation is therefore not to
restrict the address but to make the request blind: the response body is never
returned to the caller and never logged, only its status code.

Hooks live in ``data.json`` beside the rest of the settings. They used to be a
SQLite table, back when the same database held users, sessions and API keys;
with those gone, a whole database engine for one list of webhooks is a
dependency that earns nothing.
"""

import json
import logging
import threading
from datetime import datetime, timezone

import requests

from app import notify as notifier
from app.config import read_data, update_data

logger = logging.getLogger(__name__)

# Which terminal states a hook can subscribe to. Same vocabulary as the job
# status, minus the states that are not terminal.
HOOK_EVENTS = ("done", "error", "cancelled")

ALLOWED_METHODS = ("POST", "PUT", "GET")

_TIMEOUT = 10

_listener_registered = False
_listener_lock = threading.Lock()

_KEY = "download_hooks"


# ── Storage ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_hooks() -> list[dict]:
    hooks = read_data().get(_KEY) or []
    return sorted(hooks, key=lambda h: h.get("id", 0))


def _save(hooks: list[dict]):
    # ponytail: read-modify-write outside the lock update_data holds, so two
    # simultaneous hook edits could lose one. One person in one window cannot
    # produce that; if hooks ever gain a second writer, move the whole list
    # operation inside config's lock.
    update_data({_KEY: hooks})


def get_hook(hook_id: int) -> dict | None:
    return next((h for h in list_hooks() if h["id"] == hook_id), None)


def create_hook(*, name: str, url: str, method: str = "POST", headers: dict | None = None,
                body_template: str = "", events: list[str] | None = None,
                enabled: bool = True) -> dict:
    hooks = list_hooks()
    timestamp = _now_iso()
    hook = {
        "id": max((h["id"] for h in hooks), default=0) + 1,
        "name": name,
        "url": url,
        "method": method,
        "headers": headers or {},
        "body_template": body_template,
        "events": events or [],
        "enabled": bool(enabled),
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    _save(hooks + [hook])
    return hook


def update_hook(hook_id: int, **fields) -> dict | None:
    hooks = list_hooks()
    hook = next((h for h in hooks if h["id"] == hook_id), None)
    if hook is None:
        return None
    for key in ("name", "url", "method", "headers", "body_template", "events", "enabled"):
        if fields.get(key) is not None:
            hook[key] = bool(fields[key]) if key == "enabled" else fields[key]
    hook["updated_at"] = _now_iso()
    _save(hooks)
    return hook


def delete_hook(hook_id: int):
    _save([h for h in list_hooks() if h["id"] != hook_id])


def list_enabled_for_event(event: str) -> list[dict]:
    """Enabled hooks subscribed to this event. An empty filter means all events."""
    return [h for h in list_hooks()
            if h.get("enabled") and (not h.get("events") or event in h["events"])]


# ── Payload ───────────────────────────────────────────────────────────────────

def job_tokens(job) -> dict:
    """The substitutions a body template can use.

    Every value is a string, empty rather than absent when unknown: a job
    restored from schedule.json carries no year, season or episode number, and a
    template must render rather than blow up inside a download.
    """
    return {
        "title": str(getattr(job, "title", "") or ""),
        "path": str(getattr(job, "output_path", "") or ""),
        "status": str(getattr(job, "status", "") or ""),
        "type": str(getattr(job, "type", "") or ""),
        "season": str(getattr(job, "season", "") or ""),
        "episode": str(getattr(job, "episode_number", "") or ""),
        "year": str(getattr(job, "year", "") or ""),
        "error": str(getattr(job, "error", "") or ""),
    }


def render_body(template: str, tokens: dict) -> str:
    """Substitute {tokens} in a body, escaping each value for JSON.

    Not str.format: a JSON body is full of braces, and a title containing a
    quote would produce a payload the other end rejects. Values go through
    json.dumps and lose their surrounding quotes, so `"title": "{title}"` in the
    template stays valid whatever the title is.
    """
    if not template:
        return json.dumps(tokens)

    rendered = template
    for key, value in tokens.items():
        rendered = rendered.replace("{" + key + "}", json.dumps(value)[1:-1])
    return rendered


# ── Delivery ──────────────────────────────────────────────────────────────────

def fire(hook: dict, tokens: dict) -> tuple[bool, int | None]:
    """Send one hook. Returns (ok, status code); never raises, never returns a body."""
    method = (hook.get("method") or "POST").upper()
    if method not in ALLOWED_METHODS:
        logger.warning("Hook %s has an unsupported method %r", hook.get("name"), method)
        return False, None

    body = render_body(hook.get("body_template") or "", tokens)
    headers = dict(hook.get("headers") or {})
    headers.setdefault("content-type", "application/json")

    try:
        response = requests.request(
            method,
            hook["url"],
            data=None if method == "GET" else body.encode("utf-8"),
            headers=headers,
            timeout=_TIMEOUT,
        )
    except Exception as exc:
        # The URL is not logged: it carries the token.
        logger.warning("Hook %s failed: %s", hook.get("name"), type(exc).__name__)
        return False, None

    if not response.ok:
        logger.warning("Hook %s returned HTTP %d", hook.get("name"), response.status_code)
    return response.ok, response.status_code


# ── The listener ──────────────────────────────────────────────────────────────

def _notify_failure(hook_name: str, status: int | None) -> None:
    """A hook that fails silently is worse than not having one."""
    detail = f"HTTP {status}" if status else "nessuna risposta"
    notifier.notify("Hook post-download", f"L'hook «{hook_name}» non è riuscito ({detail}).")


def on_job_finished(job) -> None:
    """Fire the configured hooks for one finished download.

    Runs on a worker thread outside the download semaphore, which is why the
    blocking requests here are fine, and JobManager isolates each listener's
    exceptions — so a broken hook cannot take a download down with it.
    """
    status = getattr(job, "status", None)
    if status not in HOOK_EVENTS:
        return

    tokens = job_tokens(job)
    for hook in list_enabled_for_event(status):
        try:
            ok, code = fire(hook, tokens)
        except Exception:
            logger.exception("Hook %s raised", hook.get("name"))
            ok, code = False, None
        if not ok:
            _notify_failure(hook.get("name") or "senza nome", code)


def register_hook_listener():
    """Register once. Idempotent, like the other listener."""
    global _listener_registered
    with _listener_lock:
        if _listener_registered:
            return
        from app.jobs import job_manager

        job_manager.add_listener(on_job_finished)
        _listener_registered = True
