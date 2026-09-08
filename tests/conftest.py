"""Shared test fixtures."""

import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _no_real_notifications(request, monkeypatch):
    """Nothing in the suite may reach the Notification Centre.

    app/notify.py shells out to osascript, so a test that walks the domain
    recovery flow or finishes a job posted a real notification on the machine
    running it — announcing "example.test" and the fixture's replacement domain
    to whoever happened to be at the keyboard. Autouse and global, because the
    fault was that each test had to remember, and none did.

    A test that means to exercise notify() itself marks itself
    ``@pytest.mark.real_notifier`` and stubs the subprocess call instead.
    """
    if "real_notifier" in request.keywords:
        return

    from app import notify

    monkeypatch.setattr(notify, "notify", lambda title, message: True)


@pytest.fixture(autouse=True)
def _isolated_history(tmp_path, monkeypatch):
    """No test may write to the real download ledger.

    JobManager records every job it runs, so any test that submits one wrote
    into the user's own history — 288 fixture entries had accumulated there,
    and with the list now restored on startup they would all have shown up in
    the app. Autouse and global, for the same reason as the notifications
    above: relying on each test to remember is what failed.
    """
    from app import history

    monkeypatch.setattr(history, "HISTORY_FILE", tmp_path / "downloads.json")


@pytest.fixture(autouse=True)
def _configured_domain(tmp_path, monkeypatch):
    """Give every test a configured source domain, in a throwaway file.

    Also isolates ``data.json``: the real one lives in the user's Application
    Support directory, and a test that saved a setting would otherwise write to
    it. Patched on ``app.config`` because the readers call the functions there;
    they import the function, not the path.
    """
    from app import config

    data_file = tmp_path / "config-data.json"
    data_file.write_text(json.dumps({"domain": "example.test"}), encoding="utf-8")
    monkeypatch.setattr(config, "DATA_FILE", data_file)
    yield data_file


@pytest.fixture
def client():
    """TestClient with the app lifespan not started.

    Not entered as a context manager on purpose: the lifespan registers the
    job listeners, rebuilds the download list from the ledger and starts the
    domain watch loop, none of which belongs in a unit test.
    """
    from app.main import app

    yield TestClient(app)


@pytest.fixture
def stub_jobs(monkeypatch):
    """Stop download submissions from actually reaching the network.

    The call is bound against the *real* signature before being recorded, so a
    caller passing an argument JobManager does not accept fails here instead of
    passing the tests and raising in production — which is exactly what happened
    with strict_audio.
    """
    import inspect

    from app.jobs import job_manager

    submitted: list[tuple] = []

    def fake_submit(name):
        signature = inspect.signature(getattr(job_manager, name))

        def _submit(*args, **kwargs):
            signature.bind(*args, **kwargs)  # raises TypeError on a bad call
            submitted.append((name, args, kwargs))
            return f"job-{len(submitted)}"

        return _submit

    for name in ("submit_film", "submit_episode", "submit_anime_episode"):
        monkeypatch.setattr(job_manager, name, fake_submit(name))
    return submitted


class FakeSource:
    """Stands in for StreamingCommunity / AnimeUnity."""

    def __init__(self):
        self.audio = ["ita", "eng"]
        self.subtitles = ["ita", "eng"]
        self.dead = False
        self.episodes = [{"id": 900 + n, "n": str(n), "name": f"Episodio {n}"} for n in (1, 2, 3)]
        self.anime_episodes = [{"id": 800 + n, "number": str(n)} for n in (1, 2, 3)]

    @property
    def languages(self) -> dict:
        if self.dead:
            raise RuntimeError("HTTP 404")
        return {"audio": list(self.audio), "subtitles": list(self.subtitles)}


@pytest.fixture
def source(monkeypatch, tmp_path):
    """Fake external source plus a temporary library and configured domain."""
    from app import config
    from app.core import animeunity, film, page, tv

    fake = FakeSource()

    data_file = tmp_path / "data.json"
    library = tmp_path / "library"
    library.mkdir()
    data_file.write_text(
        json.dumps({
            "domain": "example.test",
            "libraries": [
                {"type": "film", "path": str(library)},
                {"type": "tv", "path": str(library)},
                {"type": "anime", "path": str(library)},
            ],
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "DATA_FILE", data_file)
    fake.library = library

    monkeypatch.setattr(film, "get_film_languages", lambda *a, **k: fake.languages)
    monkeypatch.setattr(page, "get_domain_version", lambda *a, **k: "v1")
    monkeypatch.setattr(tv, "get_token", lambda *a, **k: "xsrf-token")
    monkeypatch.setattr(
        tv, "get_info_season",
        lambda *a, **k: ([] if fake.dead else list(fake.episodes)),
    )
    monkeypatch.setattr(tv, "get_episode_languages", lambda *a, **k: fake.languages)
    monkeypatch.setattr(
        animeunity, "get_episodes",
        lambda *a, **k: ([] if fake.dead else list(fake.anime_episodes)),
    )
    monkeypatch.setattr(animeunity, "get_episode_languages", lambda *a, **k: fake.languages)
    return fake
