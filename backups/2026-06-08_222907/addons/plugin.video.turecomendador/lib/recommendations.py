from __future__ import annotations
try:
    import xbmc
    def _log(msg: str):
        xbmc.log(f"[turecomendador] {msg}", xbmc.LOGERROR)
except ImportError:
    def _log(msg: str):
        print(f"[ERROR] {msg}")

_MUBI_CACHE_TTL = 3600  # 1 hora

from lib.tmdb_handler import (
    search_person, get_movies_by_director,
    discover_indie, discover_by_keywords,
    get_similar, enrich_movie,
)
from lib.mubi_profile import DIRECTORS, GENRES, COUNTRIES, DISCOVER_PARAMS, EXCLUDED_GENRES
from lib.trakt_handler import (
    get_watched_tmdb_ids, get_trakt_recommendations,
    get_mubi_list, get_highly_rated_movies,
)

MUBI_KEYWORD_IDS = [
    158718,  # slow cinema
    9882,    # art house
    3691,    # melancholy
    10283,   # coming of age
    156792,  # slice of life
    4344,    # introspective
]

REFERENCE_MOVIES = {
    "Train Dreams":                   1197306,
    "Petite Maman":                   813276,
    "A Real Pain":                    1214314,
    "Perfect Days":                   976573,
    "Fallen Leaves":                  897087,
    "The Worst Person in the World":  618355,
}


def _resolve_director_ids() -> dict[str, int]:
    resolved = {}
    for name, cached_id in DIRECTORS.items():
        if cached_id:
            resolved[name] = cached_id
        else:
            pid = search_person(name)
            if pid:
                resolved[name] = pid
    return resolved


def _dedupe(movies: list[dict], seen: set) -> list[dict]:
    result = []
    for m in movies:
        mid = m.get("tmdb_id")
        if mid and mid not in seen:
            seen.add(mid)
            result.append(m)
    return result


def get_mubi_recommendations(
    watched_ids: set,
    token: str | None = None,
    limit: int = 40,
    mubi_list_slug: str = "mubi",
) -> list[dict]:
    """
    Motor de recomendaciones MUBI. 6 fuentes combinadas:
      1. Directores del perfil
      2. Discover indie por país
      3. Discover por keywords arthouse
      4. Similares a referencias estáticas
      5. Similares a lista 'mubi' de Trakt  [Opción B]
      6. Similares a películas con rating 8+ [Opción C]
    """
    seen = set(watched_ids)
    all_raw = []

    # 1. Por director
    director_ids = _resolve_director_ids()
    for name, pid in director_ids.items():
        try:
            raw = get_movies_by_director(
                pid, pages=2,
                without_genres=EXCLUDED_GENRES,
                vote_max=DISCOVER_PARAMS["vote_count.lte"],
            )
            all_raw.extend(raw)
        except Exception as e:
            _log(f"Director {name}: {e}")

    # 2. Discover indie por país
    try:
        indie = discover_indie(
            genres=GENRES,
            countries=COUNTRIES,
            without_genres=EXCLUDED_GENRES,
            vote_min=DISCOVER_PARAMS["vote_count.gte"],
            vote_max=DISCOVER_PARAMS["vote_count.lte"],
            rating_min=DISCOVER_PARAMS["vote_average.gte"],
            pages=2,
        )
        all_raw.extend(indie)
    except Exception as e:
        _log(f"Discover indie: {e}")

    # 3. Por keywords arthouse
    try:
        keyword_movies = discover_by_keywords(
            MUBI_KEYWORD_IDS,
            without_genres=EXCLUDED_GENRES,
            vote_max=DISCOVER_PARAMS["vote_count.lte"],
            pages=2,
        )
        all_raw.extend(keyword_movies)
    except Exception as e:
        _log(f"Keywords: {e}")

    # 4. Similares a referencias estáticas
    for title, tmdb_id in REFERENCE_MOVIES.items():
        try:
            all_raw.extend(get_similar(tmdb_id))
        except Exception as e:
            _log(f"Similar a {title}: {e}")

    if token:
        # 5. Opción B — lista 'mubi' de Trakt
        try:
            mubi_list = get_mubi_list(token, list_slug=mubi_list_slug)
            for item in mubi_list:
                all_raw.extend(get_similar(item["tmdb_id"]))
        except Exception as e:
            _log(f"Lista Trakt MUBI: {e}")

        # 6. Opción C — top 25 películas con rating >= 8
        try:
            top_rated = get_highly_rated_movies(token, min_rating=8)
            for item in top_rated[:25]:
                all_raw.extend(get_similar(item["tmdb_id"]))
        except Exception as e:
            _log(f"Ratings altos: {e}")

    enriched = [enrich_movie(m) for m in all_raw]
    filtered = _dedupe(enriched, seen)
    filtered.sort(key=lambda m: (m["rating"], m["votes"]), reverse=True)
    result = filtered[:limit]

    from lib.cache import CacheManager
    from lib.paths import data_path
    CacheManager(data_path("mubi_cache.json"), ttl=_MUBI_CACHE_TTL).set("recs", result)

    return result


def get_mubi_recommendations_cached(
    watched_ids: set,
    token: str | None = None,
    limit: int = 40,
    mubi_list_slug: str = "mubi",
) -> list[dict]:
    """Versión con caché en disco — carga instantánea después del primer cómputo."""
    from lib.cache import CacheManager
    from lib.paths import data_path
    cache = CacheManager(data_path("mubi_cache.json"), ttl=_MUBI_CACHE_TTL)
    cached = cache.get("recs")
    if cached is not None:
        fresh = [m for m in cached if m.get("tmdb_id") not in watched_ids]
        return fresh[:limit]
    return get_mubi_recommendations(watched_ids, token=token, limit=limit, mubi_list_slug=mubi_list_slug)


def get_general_recommendations(token: str, watched_ids: set, limit: int = 40) -> list[dict]:
    from lib.tmdb_handler import get_movie_details
    trakt_recs = get_trakt_recommendations(token, limit=limit * 2)
    seen = set(watched_ids)
    results = []

    for rec in trakt_recs:
        tmdb_id = rec.get("tmdb_id")
        if not tmdb_id or tmdb_id in seen:
            continue
        seen.add(tmdb_id)

        try:
            details = get_movie_details(tmdb_id)
            results.append(enrich_movie(details) if details else {
                "tmdb_id": tmdb_id,
                "title": rec.get("title", ""),
                "year": str(rec.get("year", "")),
                "rating": 0, "votes": 0,
                "overview": "", "poster": "", "fanart": "",
                "genre_ids": [], "origin_country": [], "original_language": "",
            })
        except Exception as e:
            _log(f"Detalle TMDB {tmdb_id}: {e}")

        if len(results) >= limit:
            break

    return results
