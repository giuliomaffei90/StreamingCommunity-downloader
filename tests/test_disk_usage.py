"""Free space: reported per volume, on the mounted storage.

Inside Docker the container root says nothing useful — the figure has to come
from the library paths themselves, which are the mounted volume.
"""

import json

import pytest

from app.routers import files


@pytest.fixture(autouse=True)
def _clear_cache():
    files._disk_usage_cache["data"] = None
    yield
    files._disk_usage_cache["data"] = None


@pytest.fixture
def libraries(tmp_path, monkeypatch):
    """Two library paths on one volume, plus one that does not exist."""
    films = tmp_path / "films"
    series = tmp_path / "series"
    films.mkdir()
    series.mkdir()
    data_file = tmp_path / "data.json"
    data_file.write_text(json.dumps({
        "domain": "example.test",
        "libraries": [
            {"type": "film", "path": str(films)},
            {"type": "tv", "path": str(series)},
            {"type": "anime", "path": str(tmp_path / "missing")},
        ],
    }))
    monkeypatch.setattr(files, "DATA_FILE", data_file)
    return films, series


def test_libraries_on_one_volume_are_reported_once(client, libraries):
    """Three folders on one mount used to produce three identical readings."""

    response = client.get("/api/files/disk-usage")

    assert response.status_code == 200
    volumes = response.json()["volumes"]
    assert len(volumes) == 1
    assert volumes[0]["total"] > 0
    assert volumes[0]["used"] + volumes[0]["free"] <= volumes[0]["total"]
    # Both readable libraries are attributed to it.
    assert len(volumes[0]["paths"]) == 2


def test_an_unreadable_path_is_reported_without_losing_the_rest(
    client, libraries
):

    body = client.get("/api/files/disk-usage").json()

    assert body["errors"], "the missing library should be reported"
    assert body["volumes"][0]["total"] > 0


def test_it_falls_back_to_the_videos_dir_with_no_libraries(
    client, tmp_path, monkeypatch
):
    data_file = tmp_path / "empty.json"
    data_file.write_text(json.dumps({"domain": "example.test"}))
    monkeypatch.setattr(files, "DATA_FILE", data_file)
    monkeypatch.setattr(files, "VIDEOS_DIR", tmp_path)

    volumes = client.get("/api/files/disk-usage").json()["volumes"]

    assert len(volumes) == 1
    assert volumes[0]["total"] > 0



def test_the_reading_is_cached_briefly(client, libraries, monkeypatch):
    """The file manager reloads on every navigation; an NFS share should not be
    stat'ed each time."""
    calls = []
    real = files.shutil.disk_usage
    monkeypatch.setattr(files.shutil, "disk_usage",
                        lambda p: calls.append(p) or real(p))

    client.get("/api/files/disk-usage")
    client.get("/api/files/disk-usage")

    assert len(calls) == 1
