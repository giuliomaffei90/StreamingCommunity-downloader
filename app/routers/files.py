import asyncio
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.config import download_dir

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/files", tags=["files"])



def _safe_path(rel_path: str) -> Path:
    """Resolve path and ensure it stays inside the download folder (no traversal).

    Resolved per call, not bound once: the folder is a setting, and the file
    manager must follow it the moment it changes.
    """
    base = download_dir().resolve()
    target = (base / rel_path).resolve()
    if not target.is_relative_to(base):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return target


def _safe_path_strict(rel_path: str) -> Path:
    """Like _safe_path but raises ValueError/FileNotFoundError instead of HTTPException."""
    base = download_dir().resolve()
    target = (base / rel_path).resolve()
    if not target.is_relative_to(base):
        raise ValueError("Invalid path")
    if not target.exists():
        raise FileNotFoundError("Not found")
    return target


# ── Disk usage ─────────────────────────────────────────────────────────────────
#
# Reported per *volume* rather than per folder, which is what the reading
# actually describes: free space belongs to the mount, not to the directory.

_DISK_USAGE_TTL = 20  # seconds; the file manager reloads on every navigation
_disk_usage_cache: dict = {"at": 0.0, "data": None}


def _library_paths() -> list[str]:
    return [str(download_dir())]


def _compute_disk_usage() -> dict:
    now = time.monotonic()
    if _disk_usage_cache["data"] is not None and now - _disk_usage_cache["at"] < _DISK_USAGE_TTL:
        return _disk_usage_cache["data"]

    volumes: dict[int, dict] = {}
    errors: list[str] = []
    for path in _library_paths():
        try:
            device = os.stat(path).st_dev
        except OSError as e:
            # An unmounted or mistyped library path is an expected failure mode
            # and must not blank out the volumes that are fine.
            errors.append(str(e))
            continue
        if device in volumes:
            volumes[device]["paths"].append(path)
            continue
        total, used, free = shutil.disk_usage(path)
        volumes[device] = {"total": total, "used": used, "free": free, "paths": [path]}

    result = {"volumes": list(volumes.values()), "errors": errors}
    _disk_usage_cache["at"] = now
    _disk_usage_cache["data"] = result
    return result


@router.get("/disk-usage")
async def get_disk_usage():
    return await asyncio.to_thread(_compute_disk_usage)


# What this app produces, and nothing else. The download folder is very often a
# folder the user already keeps other things in — ~/Downloads being the obvious
# one — and listing all of it turns the File tab into a second Finder showing
# archives, spreadsheets and installers.
_MEDIA_SUFFIXES = {
    ".mp4", ".mkv", ".avi", ".mov", ".m4v", ".webm", ".ts",
    ".vtt", ".srt", ".ass", ".sub",  # subtitle sidecars written beside a video
}


def _is_media(path: Path) -> bool:
    return path.suffix.lower() in _MEDIA_SUFFIXES


def _own_files() -> set[str]:
    """Resolved paths this app downloaded, plus their subtitle sidecars.

    An empty ledger means an empty tab, deliberately. The download folder is
    routinely one the user already keeps things in, so "every video under it"
    answers a different question than "what did I download" — and a tab that
    shows everything until the first download, then suddenly shows almost
    nothing, is harder to trust than one that only ever shows its own work.
    Files that predate the ledger are not listed; they are still on disk and
    still in the Finder.
    """
    from app import history

    paths = set()
    stems = set()
    for raw in history.produced_paths():
        try:
            resolved = Path(raw).resolve()
        except OSError:
            continue
        paths.add(str(resolved))
        stems.add(str(resolved.with_suffix("")))
    # Subtitles are written beside the video and share its stem; they are part
    # of the same download even though no job returned their path.
    for stem in stems:
        for suffix in (".vtt", ".srt", ".ass", ".sub"):
            paths.add(stem + suffix)
    return paths


def _wanted(item: Path, own: set[str]) -> bool:
    if not _is_media(item):
        return False
    try:
        return str(item.resolve()) in own
    except OSError:
        return False


def _build_tree(directory: Path, base: Path, excluded: set, own: set[str] | None = None) -> list[dict]:
    entries = []
    try:
        for item in sorted(directory.iterdir()):
            if item.name in excluded:
                continue
            if item.is_dir():
                children = _build_tree(item, base, excluded, own)
                # A directory with no media anywhere beneath it is somebody
                # else's folder, not a download: drop it rather than show it
                # empty.
                if not children:
                    continue
                entries.append({
                    "name": item.name,
                    "type": "directory",
                    "path": str(item.relative_to(base)),
                    "children": children,
                    "empty": False,
                })
            elif item.is_file() and _wanted(item, own):
                stat = item.stat()
                entries.append({
                    "name": item.name,
                    "type": "file",
                    "path": str(item.relative_to(base)),
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                })
    except PermissionError:
        pass
    return entries


# Folders that are never worth showing in a media library.
_DEFAULT_EXCLUDED = {"images", "snippets", "lost+found"}


def _search_tree(directory: Path, base: Path, query: str, excluded: set, own: set[str] | None = None) -> list[dict]:
    results = []
    try:
        for item in sorted(directory.iterdir()):
            if item.name in excluded:
                continue
            if query in item.name.lower():
                if item.is_dir():
                    results.append({
                        "name": item.name,
                        "type": "directory",
                        "path": str(item.relative_to(base)),
                    })
                elif item.is_file() and _wanted(item, own):
                    stat = item.stat()
                    results.append({
                        "name": item.name,
                        "type": "file",
                        "path": str(item.relative_to(base)),
                        "size": stat.st_size,
                        "mtime": stat.st_mtime,
                    })
            if item.is_dir():
                results.extend(_search_tree(item, base, query, excluded, own))
    except PermissionError:
        pass
    return results


@router.get("/search")
async def search_files(q: str):
    if not q or len(q.strip()) < 2:
        raise HTTPException(status_code=400, detail="Query troppo corta (min 2 caratteri)")
    if not download_dir().exists():
        return []
    excluded = _DEFAULT_EXCLUDED
    return await asyncio.to_thread(_search_tree, download_dir(), download_dir(), q.strip().lower(), excluded, _own_files())


@router.get("")
async def list_files():
    if not download_dir().exists():
        return []
    excluded = _DEFAULT_EXCLUDED
    return await asyncio.to_thread(_build_tree, download_dir(), download_dir(), excluded, _own_files())


@router.get("/stream/{file_path:path}")
def stream_file(file_path: str):
    target = _safe_path(file_path)
    return FileResponse(
        path=str(target),
        media_type="video/mp4",
        headers={"Content-Disposition": "inline"},
    )


@router.get("/download/{file_path:path}")
def download_file(file_path: str):
    target = _safe_path(file_path)
    return FileResponse(
        path=str(target),
        media_type="video/mp4",
        filename=target.name,
        headers={"Content-Disposition": f'attachment; filename="{target.name}"'},
    )


class MoveRequest(BaseModel):
    path: str
    dest_dir_path: str | None = None  # relative to the download folder (empty = its root)


class BatchMoveRequest(BaseModel):
    paths: list[str]
    dest_dir_path: str


class BatchDeleteRequest(BaseModel):
    paths: list[str]


class RenameRequest(BaseModel):
    path: str
    new_name: str


@router.post("/move")
async def move_file(body: MoveRequest):
    source = _safe_path(body.path)

    if body.dest_dir_path is None:
        raise HTTPException(status_code=400, detail="Specificare dest_dir_path")

    base = download_dir().resolve()
    dest_dir = (base / body.dest_dir_path).resolve() if body.dest_dir_path else base
    if not dest_dir.is_relative_to(base) and dest_dir != base:
        raise HTTPException(status_code=400, detail="Destinazione non valida")
    if not dest_dir.exists():
        raise HTTPException(status_code=400, detail="Cartella di destinazione non esiste")
    if source.is_dir():
        src_resolved = source.resolve()
        if dest_dir == src_resolved or dest_dir.is_relative_to(src_resolved):
            raise HTTPException(status_code=400, detail="Non puoi spostare una cartella dentro se stessa")
    dest = dest_dir / source.name

    if dest.exists():
        raise HTTPException(status_code=409, detail=f"'{source.name}' esiste già nella destinazione")

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.move, str(source), str(dest))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Spostamento fallito: {e}")

    return {"moved_to": str(dest)}


def _delete_sync(target: Path):
    """Synchronous delete helper (runs in thread)."""
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()


@router.delete("/delete/{file_path:path}", status_code=204)
async def delete_path(file_path: str):
    target = _safe_path(file_path)
    await asyncio.to_thread(_delete_sync, target)


def _batch_move_sync(paths: list[str], dest_dir_path: str) -> list[dict]:
    """Move multiple paths within the download folder (blocking, runs in thread)."""
    base = download_dir().resolve()
    dest_dir = (base / dest_dir_path).resolve() if dest_dir_path else base
    results = []
    for p in paths:
        try:
            source = (base / p).resolve()
            if not source.is_relative_to(base) or not source.exists():
                results.append({"path": p, "ok": False, "error": "File non trovato"})
                continue
            if not dest_dir.is_relative_to(base) and dest_dir != base:
                results.append({"path": p, "ok": False, "error": "Destinazione non valida"})
                continue
            if source.is_dir():
                if dest_dir == source.resolve() or dest_dir.is_relative_to(source.resolve()):
                    results.append({"path": p, "ok": False, "error": "Non puoi spostare una cartella dentro se stessa"})
                    continue
            dest = dest_dir / source.name
            if dest.exists():
                results.append({"path": p, "ok": False, "error": f"'{source.name}' esiste già nella destinazione"})
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(dest))
            results.append({"path": p, "ok": True, "moved_to": str(dest)})
        except Exception as e:
            results.append({"path": p, "ok": False, "error": str(e)})
    return results


@router.post("/move-batch")
async def batch_move(body: BatchMoveRequest):
    if not body.paths:
        raise HTTPException(status_code=400, detail="Nessun file selezionato")
    results = await asyncio.to_thread(_batch_move_sync, body.paths, body.dest_dir_path)
    return {"results": results}


def _batch_delete_sync(paths: list[str]) -> list[dict]:
    """Delete multiple paths within the download folder (blocking, runs in thread)."""
    results = []
    for p in paths:
        try:
            target = _safe_path_strict(p)
            _delete_sync(target)
            results.append({"path": p, "ok": True})
        except (ValueError, FileNotFoundError) as e:
            results.append({"path": p, "ok": False, "error": str(e)})
        except Exception as e:
            results.append({"path": p, "ok": False, "error": str(e)})
    return results


@router.post("/rename")
async def rename_path(body: RenameRequest):
    if not body.new_name or '/' in body.new_name or '\\' in body.new_name or body.new_name in ('.', '..') or '\x00' in body.new_name:
        raise HTTPException(status_code=400, detail="Nome non valido")
    source = _safe_path(body.path)
    dest = source.parent / body.new_name
    if dest.exists():
        raise HTTPException(status_code=409, detail=f"'{body.new_name}' esiste già")
    try:
        await asyncio.to_thread(source.rename, dest)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Rinomina fallita: {e}")
    return {"renamed_to": str(dest.relative_to(download_dir().resolve()))}


@router.post("/delete-batch")
async def batch_delete(body: BatchDeleteRequest):
    if not body.paths:
        raise HTTPException(status_code=400, detail="Nessun file selezionato")
    results = await asyncio.to_thread(_batch_delete_sync, body.paths)
    return {"results": results}


# ── Choosing a folder ─────────────────────────────────────────────────────────

# AppleScript, not a path typed into a text box. A library path is the one
# setting where a typo costs a whole download before anything complains, and the
# user cannot see the filesystem from inside the window. The panel and the
# person are on the same machine — that is what makes this possible at all, and
# it is only true because this is an app rather than a server.
_CHOOSE_FOLDER = """on run argv
    activate
    set chosen to choose folder with prompt (item 1 of argv)
    return POSIX path of chosen
end run"""

# No timeout: the dialog stays open until the user answers it, and picking a
# folder on an external drive that has to spin up is not a failure.
_PICK_PROMPT = "Scegli la cartella di destinazione"


def _choose_folder_sync() -> str | None:
    """The chosen folder, or None if the user cancelled."""
    try:
        result = subprocess.run(
            ["osascript", "-e", _CHOOSE_FOLDER, _PICK_PROMPT],
            capture_output=True, text=True,
        )
    except OSError as exc:
        logger.warning("Folder picker did not start: %s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Impossibile aprire il selettore")

    if result.returncode != 0:
        # Cancelling is the ordinary way out of a dialog, not an error.
        return None
    # AppleScript returns a directory path with a trailing slash; every other
    # layer stores them without one.
    return result.stdout.strip().rstrip("/") or None


@router.post("/pick-folder")
async def pick_folder():
    path = await asyncio.to_thread(_choose_folder_sync)
    return {"path": path}


# ── Showing a file in the Finder ──────────────────────────────────────────────

class RevealRequest(BaseModel):
    path: str


@router.post("/reveal")
async def reveal(body: RevealRequest):
    """Open the Finder with the file selected.

    Takes an absolute path because that is what a finished job carries, but
    refuses anything outside the download folder: revealing is harmless in
    itself, and constraining it anyway keeps the endpoint from becoming a way to
    point the Finder at any file on the machine.
    """
    target = Path(body.path).expanduser()
    base = download_dir().resolve()
    try:
        resolved = target.resolve()
    except OSError:
        raise HTTPException(status_code=400, detail="Percorso non valido")
    if not resolved.is_relative_to(base):
        raise HTTPException(status_code=400, detail="Percorso fuori dalla cartella dei download")
    if not resolved.exists():
        raise HTTPException(status_code=404, detail="Il file non esiste più")

    await asyncio.to_thread(subprocess.run, ["open", "-R", str(resolved)],
                            capture_output=True, timeout=10)
    return {"ok": True}
