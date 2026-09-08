"""The app: a window with the panel in it, and the server behind it.

Still one process, which the download engine requires — job state lives in
memory in JobManager — so uvicorn runs on a background thread and the webview
owns the main one. That order is not a preference: on macOS the Cocoa event loop
must be on the main thread, while uvicorn is happy anywhere.

Closing the window ends the process. The server thread is a daemon, so there is
nothing to shut down gracefully: an interrupted download leaves temp segments
behind, and those are cleaned up by the next run of the job that owns them.
"""

import logging
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

WINDOW_TITLE = "StreamingCommunity Downloader"
WINDOW_SIZE = (1280, 860)
MIN_WINDOW_SIZE = (900, 600)

# How long to wait for the server before giving up and saying so.
STARTUP_TIMEOUT = 30


def _free_port() -> int:
    """A port the OS says is free, rather than a fixed one.

    A fixed 8000 is somebody else's dev server about half the time, and the
    failure would land as a blank window with nothing explaining it.
    """
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _serve(port: int):
    import uvicorn

    from app.main import app

    class _Server(uvicorn.Server):
        # Signal handlers can only be installed from the main thread, which
        # this is not. Nothing needs them: the window's lifetime is the
        # process's.
        def install_signal_handlers(self):
            pass

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info")
    _Server(config).run()


def _wait_until_up(port: int) -> bool:
    deadline = time.monotonic() + STARTUP_TIMEOUT
    url = f"http://127.0.0.1:{port}/"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1):
                return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.1)
    return False


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    port = _free_port()
    threading.Thread(target=_serve, args=(port,), daemon=True).start()

    if not _wait_until_up(port):
        logger.error("The server did not start within %ss", STARTUP_TIMEOUT)
        sys.exit(1)

    from app import dock

    dock.activate()

    import webview

    webview.create_window(
        WINDOW_TITLE,
        f"http://127.0.0.1:{port}/",
        width=WINDOW_SIZE[0], height=WINDOW_SIZE[1],
        min_size=MIN_WINDOW_SIZE,
    )
    webview.start()


if __name__ == "__main__":
    main()
