"""macOS notifications, posted through osascript.

Replaces the Apprise fan-out the panel used when it was a multi-user server.
There is one user here and they are at the machine, so the Notification Centre
is the whole delivery layer: no channels to configure, no credentials, and
nothing to bundle.

The text is passed to AppleScript as ``argv`` rather than interpolated into the
script source. Titles come from the source — someone else's database — and a
film called ``Ocean"s Eleven`` interpolated into a quoted AppleScript string
stops being data and starts being syntax. Passing arguments removes the question
entirely rather than answering it with an escaping function that has to stay
correct forever.
"""

import logging
import subprocess

logger = logging.getLogger(__name__)

_SCRIPT = """on run argv
    display notification (item 1 of argv) with title (item 2 of argv)
end run"""

_TIMEOUT = 5


def notify(title: str, message: str) -> bool:
    """Post a notification. Returns whether it was handed to the system.

    Never raises: every caller is a job listener, where an exception would be
    logged and swallowed anyway, and a missing notification must not be able to
    affect a download that has already finished.
    """
    from app.config import get_settings

    if not get_settings().get("notifications_enabled", True):
        return False

    try:
        subprocess.run(
            ["osascript", "-e", _SCRIPT, str(message), str(title)],
            capture_output=True,
            timeout=_TIMEOUT,
            check=True,
        )
        return True
    except Exception as exc:
        logger.warning("Notification not delivered: %s", type(exc).__name__)
        return False


if __name__ == "__main__":
    # A quote in the title used to be able to break out of the AppleScript
    # string; passing argv is what makes this inert. If the notification shows
    # the title verbatim, quotes included, the escaping question is settled.
    assert notify('Ocean"s "Eleven" \\ test', "Se lo leggi, l'escaping regge.")
    print("ok")
