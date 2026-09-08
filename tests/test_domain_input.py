"""What the source-domain field accepts.

It stores a bare hostname, but the obvious thing to paste is the address out of
a browser. Reaching the connection pool untouched, that produced
``HTTPSConnectionPool(host='https', ...)`` — an error naming neither the mistake
nor the field it was made in.
"""

import pytest

from app.routers.domain import _normalise_domain


@pytest.mark.parametrize("pasted", [
    "https://streamingcommunityz.taxi",
    "http://streamingcommunityz.taxi",
    "https://streamingcommunityz.taxi/",
    "https://streamingcommunityz.taxi/film/123",
    "  https://streamingcommunityz.taxi  ",
    "//streamingcommunityz.taxi",
    "streamingcommunityz.taxi/",
    "streamingcommunityz.taxi",
])
def test_everything_reduces_to_the_hostname(pasted):
    assert _normalise_domain(pasted) == "streamingcommunityz.taxi"


@pytest.mark.parametrize("empty", ["", "   ", "https://", "//", "/"])
def test_nothing_usable_reduces_to_nothing(empty):
    """So the endpoint's own empty check refuses it, rather than a host of ''."""
    assert _normalise_domain(empty) == ""


def test_a_pasted_url_is_accepted_by_the_endpoint(client, monkeypatch):
    from app.routers import domain as domain_router

    monkeypatch.setattr(domain_router, "get_domain_version", lambda d: "v1")

    response = client.put("/api/domain", json={"domain": "https://example.test/"})

    assert response.status_code == 200
    assert response.json()["domain"] == "example.test"


def test_the_stored_value_is_the_hostname_not_the_url(client, monkeypatch, _configured_domain):
    """Everything downstream builds its own URLs from this, so a scheme stored
    here would be concatenated into every one of them."""
    import json

    from app.routers import domain as domain_router

    monkeypatch.setattr(domain_router, "get_domain_version", lambda d: "v1")

    client.put("/api/domain", json={"domain": "https://example.test/film/9"})

    assert json.loads(_configured_domain.read_text())["domain"] == "example.test"
