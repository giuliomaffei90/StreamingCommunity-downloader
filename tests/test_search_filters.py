"""Filtering the StreamingCommunity search by film or series.

Both sources cut their result list at 21. Filtering that cut list instead of
what went into it answers "no films" for a search whose films all sat at
position 22, which is the failure this file exists to catch.
"""

import pytest

from app.core import page


class _Response:
    def __init__(self, payload=None, text=""):
        self.ok = True
        self.text = text
        self._payload = payload or {}

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _Session:
    """Answers the two GETs search() makes: the homepage, then /it/search."""

    def __init__(self, titles):
        self.titles = titles
        self.calls = 0
        self.params = None

    def get(self, url, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return _Response(text="<html><div id='app'></div></html>")
        self.params = kwargs.get("params")
        return _Response(payload={"props": {"titles": self.titles}})


def _title(n, kind):
    return {"id": n, "name": f"Title {n}", "type": kind, "slug": f"title-{n}", "images": []}


@pytest.fixture
def source(monkeypatch):
    holder = {}

    def install(titles):
        holder["session"] = _Session(titles)
        monkeypatch.setattr(page.requests, "Session", lambda: holder["session"])
        return holder["session"]

    return install


def test_the_filter_runs_before_the_result_cap(source):
    """A film past the 21st title still comes back."""
    titles = [_title(n, "tv") for n in range(22)] + [_title(100, "movie"), _title(101, "movie")]
    source(titles)

    results = page.search("q", "example.tld", media_type="movie")

    assert [r["name"] for r in results] == ["Title 100", "Title 101"]


def test_without_a_filter_everything_comes_back(source):
    source([_title(1, "movie"), _title(2, "tv")])

    assert len(page.search("q", "example.tld")) == 2


def test_filtering_to_nothing_is_an_empty_list(source):
    source([_title(1, "tv"), _title(2, "tv")])

    assert page.search("q", "example.tld", media_type="movie") == []


def test_the_first_page_asks_for_no_page_at_all(source):
    """The source's own default is page one; sending page=1 is noise."""
    session = source([_title(1, "movie")])

    page.search("q", "example.tld")

    assert "page" not in session.params


def test_a_later_page_is_asked_for_by_number(source):
    """Without this the "Carica altri" button re-fetches page one and the
    caller sees the same titles again, or nothing new at all."""
    session = source([_title(1, "movie")])

    page.search("q", "example.tld", page=3)

    assert session.params["page"] == 3
