import json
import logging
import os
import re

import requests
from bs4 import BeautifulSoup

from app.core._shared import with_retry
from app.core.headers import sanitize_filename

logger = logging.getLogger(__name__)

ANIMEUNITY_HOST = os.getenv("ANIMEUNITY_HOST", "www.animeunity.so")
BATCH_SIZE = 120

# What a search shows. /archivio/get-animes answers 30 rows per call, so this
# is really "everything the source gave us"; the number is a ceiling for the
# day it starts answering with more.
MAX_RESULTS = 60

_scraper = None


def _get_scraper():
    global _scraper
    if _scraper is None:
        try:
            import cloudscraper
            _scraper = cloudscraper.create_scraper(
                browser={"browser": "firefox", "platform": "darwin", "desktop": True}
            )
        except ImportError:
            logger.warning("cloudscraper not installed, falling back to requests.Session")
            _scraper = requests.Session()
    return _scraper


def _normalize_titles(titles: list) -> list[dict]:
    """Convert raw AnimeUnity title dicts to the normalized format used by the frontend."""
    results = []
    seen_ids = set()
    for t in titles:
        # Handle both old format (title/name) and new livesearch format (title_eng)
        title_str = (
            t.get("title_eng") or t.get("title") or t.get("name") or ""
        ).strip()
        slug = t.get("slug", "")
        id_num = t.get("id", "")
        anime_id = f"{id_num}-{slug}" if slug else str(id_num)
        if not title_str or anime_id in seen_ids:
            continue
        seen_ids.add(anime_id)
        poster = (
            t.get("imageurl") or t.get("cover") or
            t.get("poster") or t.get("image") or ""
        )
        results.append({
            "id": anime_id,
            "name": title_str,
            "type": "anime",
            # The source's own classification — Movie, TV, OVA, ONA, Special.
            # Kept beside `type` rather than in it: `type` is "anime" for every
            # record and the whole anime flow keys off that, from the detail
            # modal to the episodes endpoint to the job kind. Dropping this used
            # to leave the card with nothing to go on, so it labelled a film "TV".
            "media_type": t.get("type") or "",
            "slug": slug,
            "poster": poster,
            "episodes_count": t.get("episodes_count", 0),
            # The archive endpoint returns these with the search, so the detail
            # panel costs no request of its own. genres arrive as rows with ids
            # and pivot tables; the panel wants names.
            "plot": t.get("plot") or "",
            "genres": [g.get("name") for g in (t.get("genres") or []) if g.get("name")],
            "score": t.get("score") or t.get("vote"),
            "release_date": t.get("date") or t.get("release_date") or "",
        })
        if len(results) >= MAX_RESULTS:
            break
    return results


def search(query: str, dubbed_only: bool = False,
           media_type: str | None = None) -> list[dict]:
    """Search AnimeUnity. Handles the Laravel CSRF token.

    Uses ``/archivio/get-animes`` rather than ``/livesearch``. The latter is
    what this used to call and it is capped at **8 records** by the source, for
    every query, with no way to ask for more and no filters — measured, not
    guessed. The archive endpoint answers 30 at a time, reports the true total,
    and applies both filters itself, so they run over the whole catalogue
    instead of over whichever 8 rows came back.

    ``dubbed_only`` keeps the Italian dubs; a dubbed anime is its own record on
    this source — same show, separate id and slug, "(ITA)" in the title.
    ``media_type`` is the source's own classification: Movie, TV, OVA, ONA,
    Special.
    """
    scraper = _get_scraper()
    host = ANIMEUNITY_HOST

    # Initial GET to establish session and get CSRF token
    r_home = with_retry(lambda: scraper.get(f"https://{host}/", timeout=15),
                        what="AnimeUnity home")
    
    # Extract CSRF token from meta tag if present
    csrf_token = None
    try:
        soup = BeautifulSoup(r_home.text, "lxml")
        csrf_meta = soup.find("meta", {"name": "csrf-token"})
        if csrf_meta:
            csrf_token = csrf_meta.get("content", "")
            logger.debug("CSRF token found: %s", csrf_token[:20] if csrf_token else "None")
    except Exception as e:
        logger.debug("Error extracting CSRF token: %s", e)

    # Standard AJAX headers with browser mimicry
    headers_ajax = {
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"https://{host}/archivio",
        "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }
    
    # Add CSRF token if available
    if csrf_token:
        headers_ajax["X-CSRF-TOKEN"] = csrf_token

    # Both filters go to the source rather than being applied to what comes
    # back: filtering here could only ever narrow one page, and would answer
    # "no Italian dub" for a show whose dub sat on page two.
    payload = {"title": query, "offset": 0}
    if dubbed_only:
        payload["dubbed"] = 1
    if media_type:
        payload["type"] = media_type

    r = with_retry(lambda: scraper.post(
        f"https://{host}/archivio/get-animes",
        json=payload,
        headers=headers_ajax,
        timeout=20,
    ), what="AnimeUnity search")

    if not r.ok:
        logger.error("Archive search failed with status %d. CSRF token was: %s",
                     r.status_code, "present" if csrf_token else "missing")
        raise RuntimeError(f"AnimeUnity search failed: HTTP {r.status_code}")

    try:
        records = r.json().get("records", [])
    except Exception as e:
        logger.error("Error parsing archive response: %s", e)
        raise

    # No rows is an answer, not a failure — the same one StreamingCommunity
    # gives. This used to raise, which reached the panel as a red error box
    # saying the search had broken when the query simply matched nothing.
    return _normalize_titles(records)


def get_episodes(anime_id: str) -> list[dict]:
    """
    Fetch all episodes for an anime using the AnimeUnity info_api.
    Uses BATCH_SIZE-chunked requests to handle long series.
    Returns list of {id, number} dicts.
    """
    scraper = _get_scraper()
    host = ANIMEUNITY_HOST

    r = with_retry(lambda: scraper.get(f"https://{host}/info_api/{anime_id}", timeout=15),
                   what="AnimeUnity episode count")
    r.raise_for_status()
    episodes_count = r.json().get("episodes_count", 0)

    if not episodes_count:
        return []

    episodes = []
    for start in range(0, episodes_count + 1, BATCH_SIZE):
        end = min(start + BATCH_SIZE - 1, episodes_count)
        batch_r = with_retry(lambda: scraper.get(
            f"https://{host}/info_api/{anime_id}/0",
            params={"start_range": start, "end_range": end},
            timeout=15,
        ), what="AnimeUnity episode list")
        if batch_r.ok:
            episodes.extend(batch_r.json().get("episodes", []))

    return episodes


def _get_embed_content(episode_id) -> tuple[str, str]:
    """
    Fetch the vixcloud.co embed page for an episode.
    Returns (script_text, embed_url) — same shape as film._get_iframe().
    """
    scraper = _get_scraper()
    host = ANIMEUNITY_HOST

    # AnimeUnity returns the vixcloud.co embed URL as plain text
    r = with_retry(lambda: scraper.get(f"https://{host}/embed-url/{episode_id}", timeout=15),
                   what="AnimeUnity embed URL")
    r.raise_for_status()
    embed_url = r.text.strip()

    if not embed_url.startswith("http"):
        raise RuntimeError(f"Unexpected embed-url response: {embed_url[:100]!r}")

    logger.info("Episode %s embed URL: %s", episode_id, embed_url[:80])

    # Fetch the vixcloud.co embed page. vixcloud.co now serves this /embed/ HTML
    # page behind Cloudflare, so plain requests.get returns a 403 challenge page.
    # Use the cloudscraper session to clear the challenge. (The downstream
    # /playlist, /storage/enc.key and CDN segment URLs are NOT Cloudflare-gated
    # and still work with plain requests.)
    req_embed = with_retry(lambda: scraper.get(
        embed_url,
        headers={"Referer": f"https://{host}/"},
        timeout=15,
    ), what="vixcloud embed page")
    req_embed.raise_for_status()

    soup = BeautifulSoup(req_embed.text, "lxml")
    body = soup.find("body")
    if not body:
        raise RuntimeError("Empty embed page body")
    script = body.find("script")
    if not script:
        raise RuntimeError("No script tag found in vixcloud.co embed page")

    logger.info("Embed script (first 400 chars): %s", script.text[:400])
    return script.text, embed_url


def get_episode_languages(episode_id) -> dict:
    """Audio and subtitle languages available on one anime episode."""
    from app.core._shared import _parse_content, _get_m3u8_url
    from app.core.m3u8 import fetch_master_languages

    embed_content, embed_url = _get_embed_content(episode_id)
    json_win_video, json_win_param = _parse_content(embed_content, embed_url)
    return fetch_master_languages(_get_m3u8_url(json_win_video, json_win_param), embed_url)


def download_anime_episode(
    anime_id: str,
    episode: dict,
    anime_name: str,
    anime_type: str = "tv",
    output_dir: str = "videos",
    temp_dir: str = None,
    progress_factory=None,
    cancel_event=None,
    year: str = None,
    audio_languages: list[str] = None,
    subtitle_languages: list[str] = None,
    strict_audio: bool = False,
) -> str:
    """
    Full download pipeline for a single anime episode.
    - Series (anime_type="tv"): videos/AnimeName/Season 01/AnimeName S01E01.mp4
    - Movies (anime_type="movie"): videos/AnimeName (YYYY)/AnimeName.mp4
    """
    audio_languages = audio_languages or ["ita"]
    subtitle_languages = subtitle_languages or []

    from app.core.film import _collect_audio_tracks, _collect_subtitle_tracks
    from app.core._shared import _parse_content, _get_m3u8_url, _get_m3u8_key
    from app.core.m3u8 import download_m3u8
    from app.core.paths import anime_path

    episode_id = episode["id"]
    episode_number = str(episode.get("number", "0"))

    embed_content, embed_url = _get_embed_content(episode_id)
    json_win_video, json_win_param = _parse_content(embed_content, embed_url)

    logger.info(
        "Anime episode %s — video_id=%s token=%.8s...",
        episode_number, json_win_video.get("id"), json_win_param.get("token", ""),
    )

    m3u8_url = _get_m3u8_url(json_win_video, json_win_param)
    m3u8_key = _get_m3u8_key(json_win_video, json_win_param, embed_url)

    audio_track_urls = _collect_audio_tracks(
        m3u8_url, embed_url, audio_languages, strict=strict_audio
    )
    subtitle_track_urls = _collect_subtitle_tracks(m3u8_url, embed_url, subtitle_languages)

    mp4_path = anime_path(output_dir, anime_name, episode_number, anime_type, year)

    final_path = download_m3u8(
        m3u8_index=m3u8_url,
        key=m3u8_key,
        output_filename=mp4_path,
        temp_dir=temp_dir,
        progress_factory=progress_factory,
        referer=embed_url,
        cancel_event=cancel_event,
        audio_languages=audio_languages,
        subtitle_languages=subtitle_languages,
        audio_track_urls=audio_track_urls,
        subtitle_track_urls=subtitle_track_urls,
    )

    # download_m3u8 returns the real output path (e.g. .mkv after remux)
    return final_path or mp4_path
