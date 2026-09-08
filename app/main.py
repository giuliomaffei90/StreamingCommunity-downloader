import asyncio
import hashlib
import logging
import sys
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from fastapi.responses import HTMLResponse

from app import __version__, downloads_notify
from app.core import domain_recovery
from app.jobs import job_manager
from app.config import download_dir
from app.routers import (
    domain, search, tv, downloads, progress, files, images, anime,
    metadata as metadata_router,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

# PyInstaller unpacks the bundle somewhere it chooses and points sys._MEIPASS
# at it. __file__ is inside a zipped archive there, so the templates and static
# files it would resolve to do not exist as paths.
BASE_DIR = (Path(sys._MEIPASS) / "app") if getattr(sys, "frozen", False) else Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"


@lru_cache(maxsize=None)
def _asset_version(name: str) -> str:
    """Short content hash of a static file. Empty when the file is missing.

    Computed once per process: the files ship inside the app bundle and cannot
    change while it runs.
    """
    try:
        return hashlib.sha256((STATIC_DIR / name).read_bytes()).hexdigest()[:10]
    except OSError:
        logger.warning("Static asset not found, serving it unversioned: %s", name)
        return ""


def asset(name: str) -> str:
    """URL for a static file, carrying a hash of its contents.

    Templates go through this rather than hardcoding ``/static/...`` so that an
    updated build can never be served against a cached copy of the previous one.
    """
    version = _asset_version(name)
    return f"/static/{name}?v={version}" if version else f"/static/{name}"


class VersionedStaticFiles(StaticFiles):
    """Static files with an explicit caching policy.

    Requests carrying a version query (everything ``asset()`` emits) may be kept
    indefinitely, since a changed file means a changed URL. Anything else must be
    revalidated — the ETag keeps that cheap — so an unversioned path can never
    pin a stale file.
    """

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        versioned = b"v=" in scope.get("query_string", b"")
        response.headers["Cache-Control"] = (
            "public, max-age=31536000, immutable" if versioned else "no-cache"
        )
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The destination, created up front rather than on the first download: it is
    # where the settings say files will go, and a folder the user is told about
    # but cannot find reads as something already broken. The file manager is
    # rooted here too, and an absent root shows as an empty library.
    download_dir().mkdir(parents=True, exist_ok=True)
    downloads_notify.register_batch_listener()
    # Before anything can submit: whatever the previous run left unfinished has
    # no worker behind it and never will, so it comes back as failed rather than
    # as nothing at all.
    job_manager.restore_from_history()
    job_manager.set_loop(asyncio.get_event_loop())
    # Watches the source itself rather than anything in it, and sleeps before
    # its first pass so the lifespan never does network I/O.
    domain_task = asyncio.create_task(domain_recovery.domain_watch_loop())
    try:
        yield
    finally:
        domain_task.cancel()


app = FastAPI(title="StreamingCommunity Downloader", version=__version__, lifespan=lifespan)

app.mount("/static", VersionedStaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals["asset"] = asset

app.include_router(domain.router)
app.include_router(metadata_router.router)
app.include_router(search.router)
app.include_router(tv.router)
app.include_router(downloads.router)
app.include_router(progress.router)
app.include_router(files.router)
app.include_router(images.router)
app.include_router(anime.router)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")
