"""The interface language, from the stored setting to the rendered page.

The page is translated in the browser, by app/static/i18n.js, off the ``lang``
attribute of ``<html>``. That attribute is the whole contract between the
setting and the translation: if the template stops carrying it the page renders
in Italian with nothing to say why, and every test of the settings endpoint
still passes.
"""

import pytest

from app import config


def test_the_default_is_italian():
    """Italian is not a preference but the source the templates are written in."""
    assert config.get_settings()["lang"] == "it"


def test_the_stored_language_reaches_the_page(client):
    assert 'lang="it"' in client.get("/").text

    client.put("/api/domain/settings", json={"lang": "en"})

    assert 'lang="en"' in client.get("/").text


@pytest.mark.parametrize("lang", ["it", "en"])
def test_both_languages_are_accepted(client, lang):
    assert client.put("/api/domain/settings", json={"lang": lang}).status_code == 200
    assert config.get_settings()["lang"] == lang


@pytest.mark.parametrize("rubbish", ["fr", "", "it-IT", '"><script>', "en en"])
def test_anything_else_is_refused(client, rubbish):
    """The value is written into an attribute of <html>, so it is not free text."""
    assert client.put("/api/domain/settings", json={"lang": rubbish}).status_code == 422
    assert config.get_settings()["lang"] == "it"
