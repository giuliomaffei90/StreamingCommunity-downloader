"""Free space: reported per volume, for the folder downloads land in.

Per volume rather than per folder because that is what the reading actually
describes — free space belongs to the mount, not to a directory on it.
"""

import json

import pytest

from app import config
from app.routers import files


@pytest.fixture(autouse=True)
def _clear_cache():
    files._disk_usage_cache["data"] = None
    yield
    files._disk_usage_cache["data"] = None


def _configure(tmp_path, monkeypatch, path) -> None:
    data_file = tmp_path / "data.json"
    data_file.write_text(json.dumps({"domain": "example.test", "download_dir": str(path)}))
    monkeypatch.setattr(config, "DATA_FILE", data_file)


@pytest.fixture
def library(tmp_path, monkeypatch):
    target = tmp_path / "media"
    target.mkdir()
    _configure(tmp_path, monkeypatch, target)
    return target


def test_the_download_folder_reports_its_volume(client, library):
    response = client.get("/api/files/disk-usage")

    assert response.status_code == 200
    volumes = response.json()["volumes"]
    assert len(volumes) == 1
    assert volumes[0]["total"] > 0
    assert volumes[0]["used"] + volumes[0]["free"] <= volumes[0]["total"]
    assert volumes[0]["paths"] == [str(library)]


def test_a_folder_that_is_not_there_is_reported_not_swallowed(client, tmp_path, monkeypatch):
    """A folder can be on a drive that is currently unplugged."""
    _configure(tmp_path, monkeypatch, tmp_path / "missing")

    body = client.get("/api/files/disk-usage").json()

    assert body["errors"], "the missing folder should be reported"
    assert body["volumes"] == []


def test_with_nothing_configured_it_reads_the_default(client, tmp_path, monkeypatch):
    data_file = tmp_path / "empty.json"
    data_file.write_text(json.dumps({"domain": "example.test"}))
    monkeypatch.setattr(config, "DATA_FILE", data_file)
    monkeypatch.setattr(config, "VIDEOS_DIR", tmp_path)

    volumes = client.get("/api/files/disk-usage").json()["volumes"]

    assert len(volumes) == 1
    assert volumes[0]["paths"] == [str(tmp_path)]


def test_the_reading_is_cached_briefly(client, library, monkeypatch):
    """The file manager reloads on every navigation; a sleeping external drive
    should not be stat'ed each time."""
    calls = []
    real = files.shutil.disk_usage
    monkeypatch.setattr(files.shutil, "disk_usage",
                        lambda p: calls.append(p) or real(p))

    client.get("/api/files/disk-usage")
    client.get("/api/files/disk-usage")

    assert len(calls) == 1
