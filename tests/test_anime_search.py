"""The "Italian dub only" filter on the anime search.

AnimeUnity lists a dubbed anime as its own record — same show, separate id and
slug, a ``dub`` flag and "(ITA)" on the title — so the filter drops records
rather than reading a property off a title.
"""

import pytest

from app.core import animeunity


class _Response:
    def __init__(self, payload=None, text=""):
        self.ok = True
        self.status_code = 200
        self.text = text
        self._payload = payload or {}

    def json(self):
        return self._payload


class _Scraper:
    """Answers the two calls search() makes: the home page, then /livesearch."""

    def __init__(self, records):
        self.records = records

    def get(self, url, **kwargs):
        return _Response(text="<html><head></head><body></body></html>")

    def post(self, url, **kwargs):
        return _Response(payload={"records": self.records})


def _record(n, *, dub):
    suffix = " (ITA)" if dub else ""
    return {
        "id": n,
        "slug": f"show-{n}{'-ita' if dub else ''}",
        "title_eng": f"Show {n}{suffix}",
        "dub": 1 if dub else 0,
        "episodes_count": 12,
    }


@pytest.fixture
def source(monkeypatch):
    def install(records):
        monkeypatch.setattr(animeunity, "_get_scraper", lambda: _Scraper(records))
    return install


def test_the_filter_runs_before_the_result_cap(source):
    """A dub past the 21st record still comes back.

    _normalize_titles stops at 21. Filtering its output instead of its input
    would let subtitled entries take every slot and then throw them away,
    answering "no Italian dub" for a show that has one.
    """
    records = [_record(n, dub=False) for n in range(22)] + [
        _record(100, dub=True), _record(101, dub=True),
    ]
    source(records)

    results = animeunity.search("show", dubbed_only=True)

    assert [r["name"] for r in results] == ["Show 100 (ITA)", "Show 101 (ITA)"]


def test_without_the_filter_everything_comes_back(source):
    source([_record(1, dub=False), _record(2, dub=True)])

    assert len(animeunity.search("show")) == 2


def test_nothing_dubbed_is_an_empty_list_not_an_error(source):
    """Ticking the box on a show with no dub must not read as a broken search.

    search() raises when the source returns nothing, and that surfaces as a red
    error box. Filtering to empty is an answer and has to stay one.
    """
    source([_record(1, dub=False), _record(2, dub=False)])

    assert animeunity.search("show", dubbed_only=True) == []


def test_a_genuinely_empty_search_still_raises(source):
    """The filter must not turn a broken search into a quiet empty page."""
    source([])

    with pytest.raises(RuntimeError):
        animeunity.search("show", dubbed_only=True)


def test_the_source_classification_survives(source):
    """AnimeUnity says Movie/TV/OVA/ONA/Special; the card needs it to say so too.

    `type` is "anime" on every record because the whole anime flow keys off it,
    so the source's own classification rides alongside in `media_type`. Dropping
    it is what made the card label a film "TV".
    """
    records = [_record(1, dub=False) | {"type": "Movie"},
               _record(2, dub=False) | {"type": "OVA"}]
    source(records)

    results = animeunity.search("show")

    assert [r["type"] for r in results] == ["anime", "anime"]
    assert [r["media_type"] for r in results] == ["Movie", "OVA"]
