"""Download progress on the Dock icon.

A badge, not a progress bar drawn across the tile. macOS gives an app a badge
label for free; a real bar means replacing the tile's content view with one that
draws itself, which is a lot of Cocoa for a number that fits in five characters.

Only alive in the windowed app. Running ``main.py`` in a browser there is no
Dock tile that means anything — the tile belongs to the Python process — so
every call is a no-op unless :func:`activate` has been told otherwise by
``desktop.py``.
"""

import logging

logger = logging.getLogger(__name__)

_enabled = False
_tile = None
_last = None


def activate() -> None:
    """Start showing progress. Called by desktop.py, never by the server."""
    global _enabled, _tile
    try:
        from AppKit import NSApplication

        _tile = NSApplication.sharedApplication().dockTile()
        _enabled = True
    except Exception:
        # No AppKit, or no window server: the app still works, it just has
        # nowhere to put a badge.
        logger.info("Dock badge unavailable")


def _set(label: str | None) -> None:
    global _last
    if not _enabled or _tile is None or label == _last:
        return
    _last = label
    try:
        # setBadgeLabel_ is documented as thread-safe, but the tile itself is
        # UI, and this runs on a download worker.
        _tile.performSelectorOnMainThread_withObject_waitUntilDone_(
            "setBadgeLabel:", label, False)
    except Exception:
        logger.debug("Could not set the Dock badge", exc_info=True)


def badge_for(jobs: list) -> str | None:
    """What the badge should read, or None to clear it.

    One download shows its percentage, which is the number worth a glance.
    Several show how many are running, because an average across them would be
    a figure that matches nothing on screen.
    """
    active = [j for j in jobs if j.status in ("running", "queued")]
    if not active:
        return None
    if len(active) > 1:
        return str(len(active))
    pct = (active[0].progress or {}).get("pct") or 0
    return f"{round(pct)}%"


def update(jobs: list) -> None:
    _set(badge_for(jobs))
