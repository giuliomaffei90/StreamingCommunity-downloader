"""Post-download hooks: what fires, what does not, and what never leaks back.

The design constraint driving most of these tests is that the settings are open
to whoever has the window — there is no login in front of them. There is
deliberately no shell hook. A webhook is still an outbound request to an address
that person chose, and pointing it at a private address is the whole point, so
the mitigation is that the request is *blind*: the response body never comes
back to the caller and is never logged, only the status code.
"""

import json
from types import SimpleNamespace

import pytest

from app import downloads_hooks


def _job(**overrides):
    base = dict(
        job_id="job-1", title="Test Series S01E01", status="done", type="episode",
        output_path="/Users/me/Movies/Test Series/Season 01/Test Series S01E01.mkv",
        season=1, episode_number="1", year="2019", error=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class _Response:
    def __init__(self, status_code=200, text="secret body"):
        self.status_code = status_code
        self.text = text
        self.ok = status_code < 400


@pytest.fixture
def sent(monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return _Response()

    monkeypatch.setattr(downloads_hooks.requests, "request", fake_request)
    return calls


@pytest.fixture
def quiet(monkeypatch):
    """Hook failures notify; that is a different module's business."""
    monkeypatch.setattr(downloads_hooks.notifier, "notify", lambda *a, **k: True)


@pytest.fixture
def hook():
    """One enabled hook subscribed to everything."""
    return downloads_hooks.create_hook(name="Casa", url="http://nas.local/refresh")


# ── Storage ───────────────────────────────────────────────────────────────────

def test_hooks_round_trip_through_data_json(hook):
    """They live beside the settings now, not in a database of their own."""
    stored = downloads_hooks.list_hooks()

    assert [h["id"] for h in stored] == [hook["id"]]
    assert stored[0]["url"] == "http://nas.local/refresh"


def test_ids_do_not_collide_after_a_delete(hook):
    second = downloads_hooks.create_hook(name="Due", url="http://x/y")
    downloads_hooks.delete_hook(hook["id"])
    third = downloads_hooks.create_hook(name="Tre", url="http://x/z")

    assert third["id"] != second["id"]
    assert len({h["id"] for h in downloads_hooks.list_hooks()}) == 2


# ── Event filtering ───────────────────────────────────────────────────────────

def test_an_empty_event_list_means_every_event(hook, sent, quiet):
    for status in ("done", "error", "cancelled"):
        downloads_hooks.on_job_finished(_job(status=status))

    assert len(sent) == 3


def test_a_hook_only_fires_for_the_events_it_asked_for(sent, quiet):
    downloads_hooks.create_hook(name="solo errori", url="http://x/y", events=["error"])

    downloads_hooks.on_job_finished(_job(status="done"))
    assert sent == []

    downloads_hooks.on_job_finished(_job(status="error", error="boom"))
    assert len(sent) == 1


def test_a_disabled_hook_never_fires(sent):
    downloads_hooks.create_hook(name="off", url="http://x/y", enabled=False)

    downloads_hooks.on_job_finished(_job())

    assert sent == []


def test_a_job_that_is_not_finished_fires_nothing(hook, sent):
    downloads_hooks.on_job_finished(_job(status="running"))

    assert sent == []


# ── Payload ───────────────────────────────────────────────────────────────────

def test_the_default_body_carries_every_token(hook, sent):
    downloads_hooks.on_job_finished(_job())

    body = json.loads(sent[0]["data"].decode())
    assert body["title"] == "Test Series S01E01"
    assert body["season"] == "1"
    assert body["status"] == "done"


def test_a_template_is_substituted(sent):
    downloads_hooks.create_hook(
        name="t", url="http://x/y",
        body_template='{"nome": "{title}", "dove": "{path}"}',
    )

    downloads_hooks.on_job_finished(_job())

    body = json.loads(sent[0]["data"].decode())
    assert body["nome"] == "Test Series S01E01"


def test_a_title_with_a_quote_does_not_break_the_payload(sent):
    """Not str.format: a quote in a title would produce invalid JSON."""
    downloads_hooks.create_hook(
        name="t", url="http://x/y", body_template='{"nome": "{title}"}',
    )

    downloads_hooks.on_job_finished(_job(title='Ocean"s Eleven'))

    assert json.loads(sent[0]["data"].decode())["nome"] == 'Ocean"s Eleven'


def test_missing_fields_render_empty_rather_than_raising(sent):
    """A job restored from schedule.json carries no season or year."""
    downloads_hooks.create_hook(
        name="t", url="http://x/y", body_template='{"anno": "{year}", "st": "{season}"}',
    )

    downloads_hooks.on_job_finished(_job(year=None, season=None))

    body = json.loads(sent[0]["data"].decode())
    assert body == {"anno": "", "st": ""}


# ── Isolation ─────────────────────────────────────────────────────────────────

def test_one_broken_hook_does_not_stop_the_others(monkeypatch, quiet):
    downloads_hooks.create_hook(name="rotto", url="http://broken/x")
    downloads_hooks.create_hook(name="buono", url="http://good/x")
    reached = []

    def fake_request(method, url, **kwargs):
        if "broken" in url:
            raise RuntimeError("connection refused")
        reached.append(url)
        return _Response()

    monkeypatch.setattr(downloads_hooks.requests, "request", fake_request)
    downloads_hooks.on_job_finished(_job())

    assert reached == ["http://good/x"]


def test_a_failing_hook_is_reported(monkeypatch):
    """A hook that fails silently is worse than not having one."""
    downloads_hooks.create_hook(name="rotto", url="http://broken/x")
    told = []
    monkeypatch.setattr(downloads_hooks.notifier, "notify",
                        lambda title, message: told.append(message) or True)
    monkeypatch.setattr(downloads_hooks.requests, "request",
                        lambda *a, **k: _Response(status_code=500))

    downloads_hooks.on_job_finished(_job())

    assert len(told) == 1
    assert "rotto" in told[0]


def test_an_unsupported_method_is_refused(sent, quiet):
    downloads_hooks.create_hook(name="x", url="http://x/y", method="DELETE")

    downloads_hooks.on_job_finished(_job())

    assert sent == []


def test_the_outbound_call_has_a_timeout(hook, sent):
    """Without one a hook pointing at a black hole would hold a worker forever."""
    downloads_hooks.on_job_finished(_job())

    assert sent[0]["timeout"] == downloads_hooks._TIMEOUT


# ── Endpoints ─────────────────────────────────────────────────────────────────

def test_create_list_and_delete(client):
    created = client.post("/api/download-hooks", json={
        "name": "Casa", "url": "http://nas.local/refresh",
    })
    assert created.status_code == 200, created.text
    hook_id = created.json()["hook"]["id"]

    assert len(client.get("/api/download-hooks").json()["hooks"]) == 1

    assert client.delete(f"/api/download-hooks/{hook_id}").status_code == 200
    assert client.get("/api/download-hooks").json()["hooks"] == []


def test_an_unknown_event_is_refused(client):
    res = client.post("/api/download-hooks", json={
        "name": "x", "url": "http://x/y", "events": ["exploded"],
    })
    assert res.status_code == 422


def test_a_non_http_url_is_refused(client):
    res = client.post("/api/download-hooks", json={
        "name": "x", "url": "file:///etc/passwd",
    })
    assert res.status_code == 422


def test_the_test_button_never_returns_the_response_body(client, monkeypatch):
    """Blind on purpose: a hook may point anywhere on the local network.

    Returning what the other end said would turn a webhook into a way of reading
    services the caller cannot otherwise reach.
    """
    created = downloads_hooks.create_hook(name="x", url="http://internal/secrets")
    monkeypatch.setattr(
        downloads_hooks.requests, "request",
        lambda *a, **k: _Response(status_code=200, text="TOP SECRET"),
    )

    body = client.post(f"/api/download-hooks/{created['id']}/test").json()

    assert body == {"ok": True, "status": 200}
    assert "TOP SECRET" not in json.dumps(body)
