from __future__ import annotations
import json
import os
import time
import requests

from lib.config import TRAKT_CLIENT_ID, TRAKT_USERNAME
from lib.paths import data_path
from lib.cache import CacheManager

try:
    import xbmc
    def _log(msg: str, level: int = None):
        xbmc.log(f"[turecomendador/trakt] {msg}", level or xbmc.LOGWARNING)
except ImportError:
    def _log(msg: str, level: int = None):
        print(f"[WARN] {msg}")

BASE_URL = "https://api.trakt.tv"
CACHE_TTL = 900         # recomendaciones y listas: 15 min
WATCHED_CACHE_TTL = 14400  # historial de vistas: 4 horas
REQUEST_TIMEOUT = 10
MAX_RETRIES = 3

_cache: CacheManager | None = None
_watched_cache: CacheManager | None = None


def _get_cache() -> CacheManager:
    global _cache
    if _cache is None:
        _cache = CacheManager(data_path("trakt_cache.json"), ttl=CACHE_TTL)
    return _cache


def _get_watched_cache() -> CacheManager:
    global _watched_cache
    if _watched_cache is None:
        _watched_cache = CacheManager(data_path("trakt_watched_cache.json"), ttl=WATCHED_CACHE_TTL)
    return _watched_cache


def _headers(token: str) -> dict:
    return {
        "Content-Type": "application/json",
        "trakt-api-version": "2",
        "trakt-api-key": TRAKT_CLIENT_ID,
        "Authorization": f"Bearer {token}",
    }


def _request_with_retry(method, url, **kwargs) -> requests.Response | None:
    """Ejecuta una petición HTTP con hasta MAX_RETRIES reintentos y backoff."""
    kwargs.setdefault("timeout", REQUEST_TIMEOUT)
    for attempt in range(MAX_RETRIES):
        try:
            r = method(url, **kwargs)
            if r.status_code < 500:
                return r
            _log(f"HTTP {r.status_code} en {url} (intento {attempt + 1}/{MAX_RETRIES})")
        except requests.exceptions.RequestException as e:
            _log(f"Request error en {url} (intento {attempt + 1}/{MAX_RETRIES}): {e}")
        if attempt < MAX_RETRIES - 1:
            time.sleep(2 ** attempt)
    _log(f"Todos los reintentos fallaron: {url}")
    return None


def _get_all_pages(url: str, token: str, params: dict = None) -> list:
    """Descarga todas las páginas de un endpoint paginado con reintentos."""
    params = params or {}
    params["limit"] = 100
    page = 1
    results = []

    while True:
        params["page"] = page
        r = _request_with_retry(requests.get, url, headers=_headers(token), params=params)
        if r is None or r.status_code != 200:
            break
        batch = r.json()
        if not batch:
            break
        results.extend(batch)
        total_pages = int(r.headers.get("X-Pagination-Page-Count", 1))
        if page >= total_pages:
            break
        page += 1

    return results


def get_watched_movies(token: str, use_cache: bool = True) -> list:
    cache = _get_watched_cache()
    if use_cache:
        cached = cache.get("movies")
        if cached is not None:
            return cached

    raw = _get_all_pages(f"{BASE_URL}/users/me/watched/movies", token)
    movies = []
    for item in raw:
        m = item.get("movie", {})
        tmdb_id = m.get("ids", {}).get("tmdb")
        movies.append({
            "title": m.get("title", ""),
            "year": m.get("year"),
            "tmdb_id": tmdb_id,
            "trakt_id": m.get("ids", {}).get("trakt"),
            "slug": m.get("ids", {}).get("slug"),
            "plays": item.get("plays", 1),
            "last_watched": item.get("last_watched_at", ""),
        })

    cache.set("movies", movies)
    return movies


def get_watched_shows(token: str, use_cache: bool = True) -> list:
    cache = _get_watched_cache()
    if use_cache:
        cached = cache.get("shows")
        if cached is not None:
            return cached

    raw = _get_all_pages(f"{BASE_URL}/users/me/watched/shows", token)
    shows = []
    for item in raw:
        s = item.get("show", {})
        shows.append({
            "title": s.get("title", ""),
            "year": s.get("year"),
            "tmdb_id": s.get("ids", {}).get("tmdb"),
            "trakt_id": s.get("ids", {}).get("trakt"),
            "slug": s.get("ids", {}).get("slug"),
            "seasons_watched": len(item.get("seasons", [])),
        })

    cache.set("shows", shows)
    return shows


def get_ratings(token: str, media_type: str = "movies") -> dict:
    raw = _get_all_pages(f"{BASE_URL}/users/me/ratings/{media_type}", token)
    ratings = {}
    for item in raw:
        key = "movie" if media_type == "movies" else "show"
        tmdb_id = item.get(key, {}).get("ids", {}).get("tmdb")
        if tmdb_id:
            ratings[tmdb_id] = item.get("rating", 0)
    return ratings


def get_recent_history(token: str, limit: int = 20) -> list:
    r = _request_with_retry(
        requests.get,
        f"{BASE_URL}/users/me/history",
        headers=_headers(token),
        params={"limit": limit},
    )
    return r.json() if r and r.status_code == 200 else []


def get_trakt_recommendations(token: str, limit: int = 40) -> list:
    r = _request_with_retry(
        requests.get,
        f"{BASE_URL}/recommendations/movies",
        headers=_headers(token),
        params={"limit": limit, "ignore_collected": True},
    )
    if not r or r.status_code != 200:
        return []

    results = []
    for item in r.json():
        results.append({
            "title": item.get("title", ""),
            "year": item.get("year"),
            "tmdb_id": item.get("ids", {}).get("tmdb"),
            "trakt_id": item.get("ids", {}).get("trakt"),
            "slug": item.get("ids", {}).get("slug"),
        })
    return results


def get_watched_tmdb_ids(token: str) -> set:
    movies = get_watched_movies(token)
    shows = get_watched_shows(token)
    ids = {m["tmdb_id"] for m in movies if m.get("tmdb_id")}
    ids |= {s["tmdb_id"] for s in shows if s.get("tmdb_id")}
    return ids


def get_mubi_list(token: str, list_slug: str = "mubi") -> list[dict]:
    cache = _get_cache()
    cache_key = f"list_{list_slug}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    raw = _get_all_pages(
        f"{BASE_URL}/users/me/lists/{list_slug}/items/movies", token
    )
    movies = []
    for item in raw:
        m = item.get("movie", {})
        tmdb_id = m.get("ids", {}).get("tmdb")
        if tmdb_id:
            movies.append({
                "title": m.get("title", ""),
                "year": m.get("year"),
                "tmdb_id": tmdb_id,
            })

    cache.set(cache_key, movies)
    return movies


def get_highly_rated_movies(token: str, min_rating: int = 8) -> list[dict]:
    cache = _get_cache()
    cache_key = f"rated_{min_rating}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    raw = _get_all_pages(f"{BASE_URL}/users/me/ratings/movies", token)
    movies = []
    for item in raw:
        if item.get("rating", 0) >= min_rating:
            m = item.get("movie", {})
            tmdb_id = m.get("ids", {}).get("tmdb")
            if tmdb_id:
                movies.append({
                    "title": m.get("title", ""),
                    "year": m.get("year"),
                    "tmdb_id": tmdb_id,
                    "rating": item["rating"],
                })

    movies.sort(key=lambda x: x["rating"], reverse=True)
    cache.set(cache_key, movies)
    return movies
