"""The anime search: which endpoint it calls, and what it asks it for.

AnimeUnity has two search endpoints. ``/livesearch`` is the obvious one and is
capped at 8 records by the source for every query, with no filters — this app
used it and that cap was the whole reason searches looked thin.
``/archivio/get-animes`` answers 30 at a time and applies the dub and type
filters itself, which is what makes them filters over the catalogue rather than
over whichever 8 rows arrived.

So the load-bearing facts here are that the request goes to the archive
endpoint and that both filters travel with it.
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
    """Answers the two calls search() makes, and records the second one."""

    def __init__(self, records):
        self.records = records
        self.url = None
        self.payload = None

    def get(self, url, **kwargs):
        return _Response(text="<html><head></head><body></body></html>")

    def post(self, url, **kwargs):
        self.url = url
        self.payload = kwargs.get("json")
        return _Response(payload={"records": self.records, "tot": len(self.records)})


def _record(n, *, dub=False, kind="TV"):
    suffix = " (ITA)" if dub else ""
    return {
        "id": n,
        "slug": f"show-{n}{'-ita' if dub else ''}",
        "title_eng": f"Show {n}{suffix}",
        "dub": 1 if dub else 0,
        "type": kind,
        "episodes_count": 12,
    }


@pytest.fixture
def source(monkeypatch):
    """Installs a fake scraper and hands back the object, so a test can read
    what the search actually asked the source for."""
    holder = {}

    def install(records):
        holder["scraper"] = _Scraper(records)
        monkeypatch.setattr(animeunity, "_get_scraper", lambda: holder["scraper"])
        return holder["scraper"]

    return install


def test_it_asks_the_archive_endpoint_not_livesearch(source):
    """livesearch caps at 8 whatever is asked of it, so it is the wrong door."""
    scraper = source([_record(1)])

    animeunity.search("show")

    assert scraper.url.endswith("/archivio/get-animes")
    assert "livesearch" not in scraper.url


def test_both_filters_are_sent_to_the_source(source):
    """Applied here they could only narrow one page of results."""
    scraper = source([_record(1, dub=True, kind="Movie")])

    animeunity.search("show", dubbed_only=True, media_type="Movie")

    assert scraper.payload["title"] == "show"
    assert scraper.payload["dubbed"] == 1
    assert scraper.payload["type"] == "Movie"


def test_an_unfiltered_search_sends_neither(source):
    """An absent filter must not reach the source as an empty one."""
    scraper = source([_record(1)])

    animeunity.search("show")

    assert "dubbed" not in scraper.payload
    assert "type" not in scraper.payload


def test_no_results_is_an_empty_list_not_an_error(source):
    """It used to raise, which reached the panel as a red "search failed" box
    for a query that had simply matched nothing."""
    source([])

    assert animeunity.search("show") == []


def test_the_source_classification_survives(source):
    """`type` is "anime" on every record because the whole anime flow keys off
    it, so the source's own kind rides alongside in `media_type`. Dropping it
    is what made the card label a film "TV"."""
    source([_record(1, kind="Movie"), _record(2, kind="OVA")])

    results = animeunity.search("show")

    assert [r["type"] for r in results] == ["anime", "anime"]
    assert [r["media_type"] for r in results] == ["Movie", "OVA"]


def test_more_than_eight_results_survive_normalisation(source):
    """The old cap was 21 here and 8 at the source. Both are gone; a full
    archive page is 30 and all of it has to come through."""
    source([_record(n) for n in range(30)])

    assert len(animeunity.search("show")) == 30


def test_plot_and_genres_ride_along_with_the_search(source):
    """The detail panel is filled from the search record, not a second request.

    genres arrive as rows with ids and pivot tables; the panel wants names, and
    a row without one must not become an empty badge.
    """
    source([_record(1) | {
        "plot": "Un ninja.",
        "genres": [{"id": 51, "name": "Action", "pivot": {}},
                   {"id": 21, "name": "Shounen", "pivot": {}},
                   {"id": 99, "pivot": {}}],
    }])

    result = animeunity.search("show")[0]

    assert result["plot"] == "Un ninja."
    assert result["genres"] == ["Action", "Shounen"]


def test_a_record_with_neither_is_still_usable(source):
    """Older or sparse rows carry no plot and no genres."""
    source([_record(1)])

    result = animeunity.search("show")[0]

    assert result["plot"] == ""
    assert result["genres"] == []
