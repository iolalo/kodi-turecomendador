from __future__ import annotations
import time
import requests
from collections import Counter
from calendar import monthrange
from datetime import date

from lib.config import TRAKT_CLIENT_ID
from lib.cache import CacheManager
from lib.paths import data_path

try:
    import xbmc
    def _log(msg: str):
        xbmc.log(f"[turecomendador/stats] {msg}", xbmc.LOGWARNING)
except ImportError:
    def _log(msg: str):
        print(f"[stats] {msg}")

BASE_URL = "https://api.trakt.tv"
STATS_CACHE_TTL = 1800  # 30 min

_cache: CacheManager | None = None


def _get_cache() -> CacheManager:
    global _cache
    if _cache is None:
        _cache = CacheManager(data_path("stats_cache.json"), ttl=STATS_CACHE_TTL)
    return _cache


def _headers(token: str) -> dict:
    return {
        "Content-Type": "application/json",
        "trakt-api-version": "2",
        "trakt-api-key": TRAKT_CLIENT_ID,
        "Authorization": f"Bearer {token}",
    }


def get_all_time_stats(token: str) -> dict:
    cache = _get_cache()
    cached = cache.get("all_time_stats")
    if cached is not None:
        return cached
    r = requests.get(f"{BASE_URL}/users/me/stats", headers=_headers(token), timeout=10)
    if r.status_code != 200:
        _log(f"Error /users/me/stats: {r.status_code}")
        return {}
    result = r.json()
    cache.set("all_time_stats", result)
    return result


def _get_history_range(token: str, start_at: str, end_at: str) -> list:
    results = []
    page = 1
    while True:
        r = requests.get(
            f"{BASE_URL}/users/me/history",
            headers=_headers(token),
            params={"start_at": start_at, "end_at": end_at, "limit": 100, "page": page},
            timeout=15,
        )
        if r.status_code != 200:
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


def compute_period_stats(token: str, start_at: str, end_at: str, update=None) -> dict:
    from lib.tmdb_handler import get_movie_details, get_movie_credits

    if update:
        update(5, "Descargando historial...")

    history = _get_history_range(token, start_at, end_at)

    movies_raw = [h for h in history if h.get("type") == "movie"]
    episodes_raw = [h for h in history if h.get("type") == "episode"]

    unique_shows = {h["show"]["title"] for h in episodes_raw if "show" in h}

    # Deduplicate movies por tmdb_id para no contar revisionados múltiples
    unique_movies: dict[int, str] = {}
    for h in movies_raw:
        m = h.get("movie", {})
        tmdb_id = m.get("ids", {}).get("tmdb")
        if tmdb_id and tmdb_id not in unique_movies:
            unique_movies[tmdb_id] = m.get("title", "")

    if update:
        update(15, "Obteniendo tiempos y directores...")

    movie_minutes = 0
    directors: Counter = Counter()
    genres: Counter = Counter()
    total = len(unique_movies)
    done = 0

    GENRE_NAMES = {
        28: "Acción", 12: "Aventura", 16: "Animación", 35: "Comedia",
        80: "Crimen", 99: "Documental", 18: "Drama", 10751: "Familia",
        14: "Fantasía", 36: "Historia", 27: "Terror", 10402: "Música",
        9648: "Misterio", 10749: "Romance", 878: "Ciencia Ficción",
        10770: "TV Movie", 53: "Suspenso", 10752: "Bélica", 37: "Western",
    }

    for tmdb_id, title in unique_movies.items():
        details = get_movie_details(tmdb_id)
        if details:
            movie_minutes += details.get("runtime") or 90
            for g in details.get("genres", []):
                gid = g["id"] if isinstance(g, dict) else g
                if gid in GENRE_NAMES:
                    genres[GENRE_NAMES[gid]] += 1

        credits = get_movie_credits(tmdb_id)
        if credits:
            for crew in credits.get("crew", []):
                if crew.get("job") == "Director":
                    directors[crew["name"]] += 1

        done += 1
        if update and total > 0:
            update(15 + int(done / total * 75), title)

    episode_minutes = len(episodes_raw) * 40

    if update:
        update(100)

    return {
        "plays_movies": len(movies_raw),
        "unique_movies": len(unique_movies),
        "episodes": len(episodes_raw),
        "shows": len(unique_shows),
        "movie_minutes": movie_minutes,
        "episode_minutes": episode_minutes,
        "total_minutes": movie_minutes + episode_minutes,
        "top_directors": directors.most_common(10),
        "top_genres": genres.most_common(5),
    }


def period_month() -> tuple[str, str, str]:
    today = date.today()
    _, last_day = monthrange(today.year, today.month)
    MONTHS = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
              "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
    label = f"{MONTHS[today.month]} {today.year}"
    start = f"{today.year}-{today.month:02d}-01T00:00:00.000Z"
    end = f"{today.year}-{today.month:02d}-{last_day:02d}T23:59:59.000Z"
    return label, start, end


def period_year() -> tuple[str, str, str]:
    year = date.today().year
    return (
        str(year),
        f"{year}-01-01T00:00:00.000Z",
        f"{year}-12-31T23:59:59.000Z",
    )


def _bar(value: int, max_val: int, width: int = 18) -> str:
    if max_val == 0:
        return ""
    filled = round(value * width / max_val)
    return "█" * filled + "░" * (width - filled)


def format_period_stats(stats: dict, title: str) -> str:
    total_h = stats["total_minutes"] // 60
    total_m = stats["total_minutes"] % 60
    movie_h = stats["movie_minutes"] // 60
    ep_h = stats["episode_minutes"] // 60
    ep_m = stats["episode_minutes"] % 60

    sep = "─" * 38
    lines = [
        f"  ESTADÍSTICAS — {title.upper()}",
        f"  {sep}",
        "",
        "  PELÍCULAS",
        f"    Reproducciones  . . . . . {stats['plays_movies']}",
        f"    Títulos únicos  . . . . . {stats['unique_movies']}",
        f"    Tiempo  . . . . . . . . . {movie_h}h",
        "",
        "  SERIES",
        f"    Shows distintos . . . . . {stats['shows']}",
        f"    Episodios . . . . . . . . {stats['episodes']}",
        f"    Tiempo estimado . . . . . {ep_h}h {ep_m}min",
        "",
        "  TOTAL",
        f"    Contenido visto . . . . . {total_h}h {total_m}min",
        "",
    ]

    if stats.get("top_genres"):
        lines.append("  GÉNEROS")
        max_g = stats["top_genres"][0][1]
        for genre, count in stats["top_genres"]:
            bar = _bar(count, max_g)
            lines.append(f"    {genre:<18} {bar}  {count}")
        lines.append("")

    if stats.get("top_directors"):
        lines.append("  TOP DIRECTORES")
        for i, (name, count) in enumerate(stats["top_directors"], 1):
            pelis = "película" if count == 1 else "películas"
            lines.append(f"    {i:2}. {name:<26} {count} {pelis}")

    return "\n".join(lines)


def format_all_time_stats(stats: dict) -> str:
    movies = stats.get("movies", {})
    episodes = stats.get("episodes", {})
    shows = stats.get("shows", {})
    ratings_data = stats.get("ratings", {})

    m_watched = movies.get("watched", 0)
    m_plays = movies.get("plays", 0)
    m_min = movies.get("minutes", 0)
    m_h = m_min // 60
    m_days = m_min // 1440

    ep_watched = episodes.get("watched", 0)
    ep_plays = episodes.get("plays", 0)
    ep_min = episodes.get("minutes", 0)
    ep_h = ep_min // 60

    total_min = m_min + ep_min
    total_h = total_min // 60
    total_days = total_min // 1440

    sep = "─" * 38
    lines = [
        "  ESTADÍSTICAS — HISTÓRICO COMPLETO",
        f"  {sep}",
        "",
        "  PELÍCULAS",
        f"    Vistas  . . . . . . . . . {m_watched}",
        f"    Reproducciones  . . . . . {m_plays}",
        f"    Tiempo  . . . . . . . . . {m_h}h  ({m_days} días)",
        "",
        "  SERIES",
        f"    Shows vistos  . . . . . . {shows.get('watched', 0)}",
        f"    Episodios vistos  . . . . {ep_watched}",
        f"    Reproducciones  . . . . . {ep_plays}",
        f"    Tiempo  . . . . . . . . . {ep_h}h",
        "",
        "  TOTAL",
        f"    Contenido visto . . . . . {total_h}h  ({total_days} días)",
        "",
    ]

    dist = ratings_data.get("distribution", {})
    total_ratings = ratings_data.get("total", 0)
    if total_ratings > 0 and dist:
        lines.append(f"  RATINGS  ({total_ratings} calificaciones)")
        max_val = max(int(v) for v in dist.values()) if dist else 1
        for score in range(10, 0, -1):
            count = int(dist.get(str(score), 0))
            if count:
                bar = _bar(count, max_val)
                lines.append(f"    {score:2}  {bar}  {count}")

    return "\n".join(lines)
