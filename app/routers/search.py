import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from app.config import configured_domain
from app.core.page import search as core_search
from app.core.film import get_film_languages
from app.core.tv import get_tv_languages
from app.core import animeunity

logger = logging.getLogger(__name__)

# Searching is the entry point to both flows, so either privilege grants it.
# The language endpoint is part of the same flow: a requester has to see the
# real audio and subtitle tracks before choosing them.
router = APIRouter(
    prefix="/api/search",
    tags=["search"],
)


def _domain() -> str:
    domain = configured_domain()
    if not domain:
        raise HTTPException(status_code=409, detail="Nessun dominio configurato")
    return domain


@router.get("")
async def search(
    q: str = Query(..., min_length=1),
    source: str = Query(default="streamingcommunity"),
    dubbed_only: bool = Query(default=False),
    # Lower case is StreamingCommunity's vocabulary, capitalised is
    # AnimeUnity's. Constrained rather than free text because it is forwarded
    # to the source as a query field.
    media_type: str | None = Query(
        default=None, pattern="^(movie|tv|Movie|TV|OVA|ONA|Special)$"),
):
    try:
        if source == "animeunity":
            results = await asyncio.to_thread(
                animeunity.search, q, dubbed_only, media_type)
        else:
            results = await asyncio.to_thread(core_search, q, _domain(), media_type)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Search error")
        raise HTTPException(status_code=502, detail=str(e))
    return results


@router.get("/languages/{title_id}")
async def title_languages(
    title_id: int,
    type: str = Query(..., pattern="^(movie|tv)$"),
    slug: str = Query(default=None),
    version: str = Query(default=""),
):
    domain = _domain()
    try:
        if type == "movie":
            langs = await asyncio.to_thread(get_film_languages, title_id, domain)
        else:
            if not slug:
                raise ValueError("slug is required for tv type")
            langs = await asyncio.to_thread(get_tv_languages, title_id, slug, domain, version)
    except Exception as e:
        logger.warning("Languages fetch error for %s %d: %s", type, title_id, e)
        raise HTTPException(status_code=502, detail=str(e))
    return langs
