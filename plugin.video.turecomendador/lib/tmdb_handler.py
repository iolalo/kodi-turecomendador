from __future__ import annotations
import time
import requests
from collections import OrderedDict
from lib.config import TMDB_API_KEY

BASE_URL = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p"
REQUEST_TIMEOUT = 10
MAX_RETRIES = 3

try:
    import xbmc
    def _log(msg: str):
        xbmc.log(f"[turecomendador/tmdb] {msg}", xbmc.LOGWARNING)
except ImportError:
    def _log(msg: str):
        print(f"[WARN] {msg}")

_mem_cache: OrderedDict = OrderedDict()
_mem_cache_ts: dict = {}
MEMORY_CACHE_TTL = 6 * 3600
MEMORY_CACHE_MAX = 200


def _kodi_language() -> str:
    """Devuelve el código de idioma de Kodi para TMDB (ej. 'es-ES', 'en-US')."""
    try:
        import xbmc
        lang = xbmc.getLanguage(xbmc.ISO_639_1)
        mapping = {
            "es": "es-ES", "en": "en-US", "fr": "fr-FR",
            "de": "de-DE", "it": "it-IT", "pt": "pt-BR",
            "ja": "ja-JP", "ko": "ko-KR", "zh": "zh-CN",
        }
        return mapping.get(lang, "es-ES")
    except ImportError:
        return "es-ES"


def _get(endpoint: str, params: dict = None) -> dict | list | None:
    params = params or {}
    params["api_key"] = TMDB_API_KEY
    params.setdefault("language", _kodi_language())
    url = f"{BASE_URL}{endpoint}"
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                retry_after = int(r.headers.get("Retry-After", 2 ** attempt))
                _log(f"Rate limit TMDB en {endpoint}, esperando {retry_after}s")
                time.sleep(retry_after)
                continue
            _log(f"HTTP {r.status_code} en {endpoint}")
            return None
        except requests.exceptions.RequestException as e:
            _log(f"Request error en {endpoint} (intento {attempt + 1}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
    return None


def _cached_get(cache_key: str, endpoint: str, params: dict = None) -> dict | list | None:
    now = time.time()
    if cache_key in _mem_cache and now - _mem_cache_ts.get(cache_key, 0) < MEMORY_CACHE_TTL:
        _mem_cache.move_to_end(cache_key)
        return _mem_cache[cache_key]
    result = _get(endpoint, params)
    if result is not None:
        _mem_cache[cache_key] = result
        _mem_cache_ts[cache_key] = now
        if len(_mem_cache) > MEMORY_CACHE_MAX:
            oldest = next(iter(_mem_cache))
            del _mem_cache[oldest]
            _mem_cache_ts.pop(oldest, None)
    return result


def get_movie_details(tmdb_id: int) -> dict | None:
    return _cached_get(f"movie_{tmdb_id}", f"/movie/{tmdb_id}")


def get_movie_credits(tmdb_id: int) -> dict | None:
    return _cached_get(f"credits_{tmdb_id}", f"/movie/{tmdb_id}/credits")


def poster_url(path: str, size: str = "w500") -> str:
    return f"{IMAGE_BASE}/{size}{path}" if path else ""


def fanart_url(path: str) -> str:
    return f"{IMAGE_BASE}/original{path}" if path else ""


def search_person(name: str) -> int | None:
    data = _get("/search/person", {"query": name, "language": "en-US"})
    if data and data.get("results"):
        return data["results"][0]["id"]
    return None


def get_movies_by_director(
    person_id: int,
    pages: int = 2,
    without_genres: list[int] | None = None,
    vote_max: int = 12000,
) -> list[dict]:
    results = []
    params = {
        "with_crew": person_id,
        "sort_by": "vote_average.desc",
        "vote_count.gte": 20,
        "vote_count.lte": vote_max,
        "language": "en-US",
    }
    if without_genres:
        params["without_genres"] = ",".join(str(g) for g in without_genres)
    for page in range(1, pages + 1):
        params["page"] = page
        data = _get("/discover/movie", params)
        if not data or not data.get("results"):
            break
        results.extend(data["results"])
    return results


def discover_indie(
    genres: list[int],
    countries: list[str],
    without_genres: list[int] | None = None,
    vote_min: int = 150,
    vote_max: int = 8000,
    rating_min: float = 6.8,
    pages: int = 2,
) -> list[dict]:
    results = []
    for country in countries:
        params = {
            "with_genres": ",".join(str(g) for g in genres),
            "with_origin_country": country,
            "sort_by": "vote_average.desc",
            "vote_count.gte": vote_min,
            "vote_count.lte": vote_max,
            "vote_average.gte": rating_min,
            "language": "en-US",
        }
        if without_genres:
            params["without_genres"] = ",".join(str(g) for g in without_genres)
        for page in range(1, pages + 1):
            params["page"] = page
            data = _get("/discover/movie", params)
            if not data or not data.get("results"):
                break
            results.extend(data["results"])
    return results


def discover_by_keywords(
    keyword_ids: list[int],
    without_genres: list[int] | None = None,
    vote_max: int = 8000,
    pages: int = 2,
) -> list[dict]:
    results = []
    kw_str = "|".join(str(k) for k in keyword_ids)
    params = {
        "with_keywords": kw_str,
        "sort_by": "vote_average.desc",
        "vote_count.gte": 150,
        "vote_count.lte": vote_max,
        "language": "en-US",
    }
    if without_genres:
        params["without_genres"] = ",".join(str(g) for g in without_genres)
    for page in range(1, pages + 1):
        params["page"] = page
        data = _get("/discover/movie", params)
        if not data or not data.get("results"):
            break
        results.extend(data["results"])
    return results


def get_similar(tmdb_id: int, vote_min: int = 150, vote_max: int = 30000) -> list[dict]:
    data = _cached_get(
        f"similar_{tmdb_id}",
        f"/movie/{tmdb_id}/similar",
        {"language": "en-US"},
    )
    results = data.get("results", []) if data else []
    return [r for r in results if vote_min <= r.get("vote_count", 0) <= vote_max]


LANG_TO_COUNTRY = {
    "ja": "JP", "fr": "FR", "fi": "FI", "no": "NO", "sv": "SE",
    "da": "DK", "de": "DE", "it": "IT", "ko": "KR", "zh": "CN",
    "pt": "BR", "es": "ES", "ru": "RU", "pl": "PL", "ro": "RO",
    "tr": "TR", "nl": "NL", "hu": "HU", "cs": "CZ", "en": "US/GB",
}


def enrich_movie(raw: dict) -> dict:
    lang = raw.get("original_language", "")
    country = (
        raw.get("origin_country")
        or [c["iso_3166_1"] for c in raw.get("production_countries", [])]
        or ([LANG_TO_COUNTRY[lang]] if lang in LANG_TO_COUNTRY else [lang.upper()])
    )
    # Discover/search returns genre_ids (list of ints); details endpoint returns genres (list of dicts)
    genre_ids = raw.get("genre_ids") or [g["id"] for g in raw.get("genres", []) if isinstance(g, dict)]
    return {
        "tmdb_id": raw.get("id"),
        "title": raw.get("title", ""),
        "year": (raw.get("release_date") or "")[:4],
        "rating": raw.get("vote_average", 0),
        "votes": raw.get("vote_count", 0),
        "overview": raw.get("overview", ""),
        "poster": poster_url(raw.get("poster_path", "")),
        "fanart": fanart_url(raw.get("backdrop_path", "")),
        "genre_ids": genre_ids,
        "origin_country": country,
        "original_language": lang,
    }
