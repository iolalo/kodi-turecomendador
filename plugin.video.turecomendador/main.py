from __future__ import annotations
import sys
import os
import threading
from urllib.parse import urlencode, parse_qs, urlparse

# Bootstrap: add module paths for addons not registered by Kodi's addon manager
_ADDONS_DIR = '/storage/.kodi/addons'
_MODULES = [
    'script.module.requests', 'script.module.urllib3', 'script.module.certifi',
    'script.module.chardet', 'script.module.idna', 'script.module.six',
    'script.module.dateutil', 'script.module.arrow', 'script.module.trakt',
    'script.module.simplecache', 'script.module.routing', 'script.module.future',
    'script.module.beautifulsoup4', 'script.module.soupsieve', 'script.module.html5lib',
    'script.module.webencodings', 'script.module.addon.signals',
]
for _mod in _MODULES:
    _lib = os.path.join(_ADDONS_DIR, _mod, 'lib')
    if os.path.isdir(_lib) and _lib not in sys.path:
        sys.path.insert(0, _lib)

import xbmc
import xbmcgui
import xbmcplugin
import xbmcaddon
import xbmcvfs

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo("id")
ADDON_NAME = ADDON.getAddonInfo("name")
HANDLE = int(sys.argv[1])
BASE_URL = sys.argv[0]

# Configurar rutas antes de importar módulos propios
_profile = xbmcvfs.translatePath(ADDON.getAddonInfo("profile"))
os.makedirs(_profile, exist_ok=True)
sys.path.insert(0, xbmcvfs.translatePath(ADDON.getAddonInfo("path")))

from lib import paths
paths.set_data_dir(_profile)

from lib.trakt_auth import get_valid_token, logout
from lib.trakt_handler import (
    get_watched_movies, get_watched_shows, get_watchlist_movies, get_watchlist_shows,
    get_recent_history, get_watched_tmdb_ids,
    rate_movie,
    _get_cache, _get_watched_cache,
)
from lib.recommendations import get_mubi_recommendations, get_mubi_recommendations_cached, get_general_recommendations
from lib.tmdb_handler import get_movie_details, enrich_movie, get_show_details, enrich_show
from lib.stats import (
    get_all_time_stats, compute_period_stats,
    period_month, period_year,
)
from lib.stats_window import show_stats_window


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_url(action: str, **kwargs) -> str:
    params = {"action": action}
    params.update(kwargs)
    return f"{BASE_URL}?{urlencode(params)}"


def notify(msg: str, title: str = ADDON_NAME, icon: str = xbmcgui.NOTIFICATION_INFO):
    xbmcgui.Dialog().notification(title, msg, icon, 4000)


def _elementum_available() -> bool:
    return bool(xbmc.getCondVisibility("System.HasAddon(plugin.video.elementum)"))


def _elementum_url(tmdb_id: int) -> str:
    return f"plugin://plugin.video.elementum/play?tmdb={tmdb_id}&type=movie"


def _download_spanish_subtitle(tmdb_id: int) -> str | None:
    """Opción A: descarga el mejor subtítulo en español vía OpenSubtitles.com REST API."""
    api_key = ADDON.getSetting("opensubtitles_api_key").strip()
    if not api_key:
        return None
    try:
        import requests as _req
        import tempfile
        headers = {
            "Api-Key": api_key,
            "Content-Type": "application/json",
            "User-Agent": f"MiRecomendador v{ADDON.getAddonInfo('version')}",
        }
        r = _req.get(
            "https://api.opensubtitles.com/api/v1/subtitles",
            params={"tmdb_id": tmdb_id, "languages": "es", "type": "movie"},
            headers=headers, timeout=10,
        )
        if r.status_code != 200:
            return None
        data = r.json().get("data", [])
        if not data:
            return None
        file_id = data[0]["attributes"]["files"][0]["file_id"]

        r2 = _req.post(
            "https://api.opensubtitles.com/api/v1/download",
            json={"file_id": file_id},
            headers=headers, timeout=10,
        )
        if r2.status_code != 200:
            return None
        link = r2.json().get("link")
        if not link:
            return None

        r3 = _req.get(link, timeout=15)
        if r3.status_code != 200:
            return None

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".srt", mode="wb")
        tmp.write(r3.content)
        tmp.close()
        return tmp.name
    except Exception as e:
        xbmc.log(f"[turecomendador] OpenSubtitles download error: {e}", xbmc.LOGWARNING)
        return None


def _schedule_subtitle_search(tmdb_id: int | None = None, delay_after_start: int = 5):
    """
    Opción A: descarga directo vía OpenSubtitles.com si hay API key.
    Opción B (fallback): dispara SubtitleSearch — a4ksubtitles con auto_download=true
                         baja solo sin mostrar diálogo.
    """
    import threading

    def _worker():
        player = xbmc.Player()
        monitor = xbmc.Monitor()
        for _ in range(30):
            if player.isPlaying():
                break
            if monitor.waitForAbort(1):
                return
        else:
            return
        if monitor.waitForAbort(delay_after_start):
            return
        if not player.isPlaying():
            return

        sub_path = _download_spanish_subtitle(tmdb_id) if tmdb_id else None
        if sub_path:
            player.setSubtitles(sub_path)
            player.showSubtitles(True)
            xbmc.log(f"[turecomendador] Subtítulo ES cargado: {sub_path}", xbmc.LOGINFO)
        else:
            xbmc.executebuiltin("SubtitleSearch")

    threading.Thread(target=_worker, daemon=True).start()


def run_with_progress(fn, title: str, steps: list[str]) -> tuple:
    """
    Ejecuta `fn` en un hilo secundario mostrando un diálogo de progreso.
    `fn` recibe un callback `update(pct, msg)` para reportar avance.
    Devuelve (result, error).
    """
    result_holder = [None]
    error_holder = [None]
    progress_holder = [0, steps[0] if steps else ""]

    def update(pct: int, msg: str = ""):
        progress_holder[0] = pct
        progress_holder[1] = msg

    def worker():
        try:
            result_holder[0] = fn(update)
        except Exception as e:
            error_holder[0] = e

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    dialog = xbmcgui.DialogProgressBG()
    dialog.create(ADDON_NAME, title)
    monitor = xbmc.Monitor()

    while t.is_alive():
        if monitor.abortRequested():
            dialog.close()
            return None, None
        dialog.update(progress_holder[0], ADDON_NAME, progress_holder[1])
        monitor.waitForAbort(0.1)

    dialog.close()
    return result_holder[0], error_holder[0]


def require_token() -> str | None:
    """Devuelve el token activo o lanza el flujo de autenticación."""
    token = get_valid_token()
    if token:
        return token

    ok = xbmcgui.Dialog().yesno(
        "Conectar con Trakt",
        "No estás autenticado. ¿Querés conectar tu cuenta de Trakt ahora?",
    )
    if not ok:
        return None

    import requests
    import json as _json
    from lib.config import TRAKT_CLIENT_ID, TRAKT_CLIENT_SECRET

    headers = {
        "Content-Type": "application/json",
        "trakt-api-version": "2",
        "trakt-api-key": TRAKT_CLIENT_ID,
    }
    try:
        r = requests.post(
            "https://api.trakt.tv/oauth/device/code",
            json={"client_id": TRAKT_CLIENT_ID},
            headers=headers,
            timeout=10,
        )
        r.raise_for_status()
    except Exception as e:
        notify(f"Error al contactar Trakt: {e}", icon=xbmcgui.NOTIFICATION_ERROR)
        return None

    data = r.json()
    xbmcgui.Dialog().ok(
        "Autenticación Trakt",
        f"1. Abrí: [B]{data['verification_url']}[/B]\n"
        f"2. Ingresá el código: [COLOR yellow][B]{data['user_code']}[/B][/COLOR]\n"
        f"Luego volvé aquí y presioná OK.",
    )

    import time
    token_data = None
    deadline = time.time() + data["expires_in"]
    poll_interval = data["interval"]
    retries = 0
    max_retries = data["expires_in"] // poll_interval

    while time.time() < deadline and retries < max_retries:
        time.sleep(poll_interval)
        retries += 1
        try:
            poll = requests.post(
                "https://api.trakt.tv/oauth/device/token",
                json={
                    "code": data["device_code"],
                    "client_id": TRAKT_CLIENT_ID,
                    "client_secret": TRAKT_CLIENT_SECRET,
                },
                headers=headers,
                timeout=10,
            )
            if poll.status_code == 200:
                token_data = poll.json()
                break
            elif poll.status_code == 400:
                continue
            elif poll.status_code in (404, 410, 418):
                break
            elif poll.status_code == 429:
                time.sleep(poll_interval * 2)
        except Exception:
            time.sleep(poll_interval)

    if not token_data:
        notify("Autenticación fallida o cancelada", icon=xbmcgui.NOTIFICATION_ERROR)
        return None

    token_path = paths.data_path("trakt_token.json")
    with open(token_path, "w") as f:
        _json.dump(token_data, f)
    notify("Conectado a Trakt correctamente")
    return token_data["access_token"]


# ---------------------------------------------------------------------------
# Listado de ítems
# ---------------------------------------------------------------------------

def _make_list_item(movie: dict) -> xbmcgui.ListItem:
    label = f"{movie['title']} ({movie['year']})" if movie.get("year") else movie["title"]
    li = xbmcgui.ListItem(label=label)
    li.setInfo("video", {
        "title": movie["title"],
        "year": int(movie["year"]) if str(movie.get("year", "")).isdigit() else 0,
        "plot": movie.get("overview", ""),
        "rating": movie.get("rating", 0),
        "votes": str(movie.get("votes", "")),
        "mediatype": "movie",
    })
    li.setArt({
        "thumb": movie.get("poster", ""),
        "poster": movie.get("poster", ""),
        "fanart": movie.get("fanart", ""),
    })
    li.setProperty("IsPlayable", "true")
    tmdb_id = movie.get("tmdb_id")
    if tmdb_id:
        rate_url = build_url("rate_movie", tmdb_id=tmdb_id)
        li.addContextMenuItems([("Puntuar en Trakt", f"RunPlugin({rate_url})")])
    return li


def _make_show_list_item(show: dict) -> xbmcgui.ListItem:
    label = f"{show['title']} ({show['year']})" if show.get("year") else show["title"]
    li = xbmcgui.ListItem(label=label)
    li.setInfo("video", {
        "tvshowtitle": show["title"],
        "year": int(show["year"]) if str(show.get("year", "")).isdigit() else 0,
        "plot": show.get("overview", ""),
        "rating": show.get("rating", 0),
        "mediatype": "tvshow",
    })
    li.setArt({
        "thumb": show.get("poster", ""),
        "poster": show.get("poster", ""),
        "fanart": show.get("fanart", ""),
    })
    return li


def show_show_list(shows: list[dict]):
    xbmcplugin.setContent(HANDLE, "tvshows")
    items = []
    for show in shows:
        tmdb_id = show.get("tmdb_id")
        if not tmdb_id:
            continue
        li = _make_show_list_item(show)
        # TMDB Helper para navegación por temporadas/episodios
        show_url = (
            f"plugin://plugin.video.themoviedb.helper/"
            f"?info=seasons&tmdb_id={tmdb_id}&type=tv"
        )
        items.append((show_url, li, True))

    if not items:
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    xbmcplugin.addDirectoryItems(HANDLE, items, len(items))
    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_NONE)
    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_VIDEO_RATING)
    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_LABEL)
    xbmcplugin.endOfDirectory(HANDLE)


def show_movie_list(movies: list[dict]):
    xbmcplugin.setContent(HANDLE, "movies")
    items = []
    for movie in movies:
        tmdb_id = movie.get("tmdb_id")
        if not tmdb_id:
            continue
        li = _make_list_item(movie)
        # Routed via nuestro play handler para que funcione desde widget/home screen
        play_url = build_url("play", tmdb_id=tmdb_id)
        items.append((play_url, li, False))

    if not items:
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    xbmcplugin.addDirectoryItems(HANDLE, items, len(items))
    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_NONE)
    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_VIDEO_RATING)
    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_VIDEO_YEAR)
    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_LABEL)
    xbmcplugin.endOfDirectory(HANDLE)


# ---------------------------------------------------------------------------
# Vistas
# ---------------------------------------------------------------------------

def view_main_menu():
    sections = [
        ("MUBI — Tu perfil personal",   "mubi",    "Cine indie contemplativo calibrado a tus gustos"),
        ("Recomendaciones Trakt",        "trakt",   "Sugerencias basadas en todo tu historial"),
        ("Seguimiento de películas",      "watchlist_movies", "Películas en tu watchlist de Trakt"),
        ("Seguimiento de series",        "shows",   "Series en tu watchlist de Trakt con pósters"),
        ("Lo que estoy viendo",          "history", "Tu actividad reciente en Trakt"),
        ("Películas vistas",             "watched", "Tu biblioteca completa de películas"),
        ("Estadísticas",                 "stats",   "Resumen mensual, anual e histórico de lo visto"),
        ("Refrescar caché",              "refresh", "Fuerza la actualización de datos de Trakt"),
    ]
    for label, action, description in sections:
        li = xbmcgui.ListItem(label=label)
        li.setInfo("video", {"plot": description, "mediatype": "movie"})
        xbmcplugin.addDirectoryItem(HANDLE, build_url(action), li, isFolder=True)
    xbmcplugin.endOfDirectory(HANDLE)


def view_watchlist_movies():
    token = require_token()
    if not token:
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    from lib.cache import CacheManager
    monitor = xbmc.Monitor()
    is_widget = monitor.abortRequested()

    _cache = CacheManager(paths.data_path("watchlist_movies_cache.json"), ttl=86400 if is_widget else 3600)
    _cached = _cache.get("movies")
    if _cached:
        xbmcplugin.setPluginCategory(HANDLE, "Seguimiento de películas")
        show_movie_list(_cached[:40])
        return

    if is_widget:
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    def fetch(update):
        update(10, "Descargando watchlist de Trakt...")
        raw = get_watchlist_movies(token)
        raw.sort(key=lambda m: m.get("listed_at", ""), reverse=True)
        limit = min(len(raw), 40)
        enriched = []
        for i, m in enumerate(raw[:limit]):
            tmdb_id = m.get("tmdb_id")
            if not tmdb_id:
                continue
            details = get_movie_details(tmdb_id)
            enriched.append(enrich_movie(details) if details else {
                "tmdb_id": tmdb_id,
                "title": m.get("title", ""),
                "year": str(m.get("year", "")),
                "rating": 0, "votes": 0, "overview": "",
                "poster": "", "fanart": "",
                "genre_ids": [], "origin_country": [], "original_language": "",
            })
            update(10 + int((i + 1) / max(limit, 1) * 90), m.get("title", ""))
        update(100)
        return enriched

    movies, err = run_with_progress(fetch, "Cargando seguimiento de películas...", [])
    if err:
        notify(f"Error: {err}", icon=xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    movies = movies or []
    _cache.set("movies", movies)
    xbmcplugin.setPluginCategory(HANDLE, "Seguimiento de películas")
    show_movie_list(movies)


def view_shows():
    token = require_token()
    if not token:
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    from lib.cache import CacheManager
    monitor = xbmc.Monitor()
    is_widget = monitor.abortRequested()

    cache_ttl = 86400 if is_widget else 3600
    _cache = CacheManager(paths.data_path("shows_cache.json"), ttl=cache_ttl)
    _cached = _cache.get("shows")
    if _cached:
        xbmcplugin.setPluginCategory(HANDLE, "Series vistas")
        show_show_list(_cached[:40])
        return

    if is_widget:
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    def fetch(update):
        update(10, "Descargando seguimiento de Trakt...")
        raw = get_watchlist_shows(token)
        # Most recently added first
        raw.sort(key=lambda s: s.get("listed_at", ""), reverse=True)
        limit = min(len(raw), 40)
        enriched = []
        for i, s in enumerate(raw[:limit]):
            tmdb_id = s.get("tmdb_id")
            if not tmdb_id:
                continue
            details = get_show_details(tmdb_id)
            enriched.append(enrich_show(details) if details else {
                "tmdb_id": tmdb_id,
                "title": s.get("title", ""),
                "year": str(s.get("year", "")),
                "rating": 0, "votes": 0, "overview": "",
                "poster": "", "fanart": "",
                "seasons": 0, "episodes": 0, "genre_ids": [],
            })
            update(10 + int((i + 1) / max(limit, 1) * 90), s.get("title", ""))
        update(100)
        return enriched

    shows, err = run_with_progress(fetch, "Cargando series vistas...", [])
    if err:
        notify(f"Error: {err}", icon=xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    shows = shows or []
    _cache.set("shows", shows)
    xbmcplugin.setPluginCategory(HANDLE, "Series vistas")
    show_show_list(shows)


def view_mubi():
    token = require_token()
    if not token:
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    from lib.cache import CacheManager
    monitor = xbmc.Monitor()
    is_widget = monitor.abortRequested()

    # Widget context: abortRequested() is True immediately from CDirectoryProvider.
    # Use a 24h TTL so the widget keeps showing content between user-initiated refreshes.
    cache_ttl = 86400 if is_widget else 3600
    _cache = CacheManager(paths.data_path("mubi_cache.json"), ttl=cache_ttl)
    _cached = _cache.get("recs")
    if _cached:
        xbmcplugin.setPluginCategory(HANDLE, "MUBI — Tu perfil personal")
        show_movie_list(_cached[:40])
        return

    if is_widget:
        # No cache and can't block on API in widget context — fail gracefully.
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    def fetch(update):
        update(10, "Obteniendo historial...")
        watched = get_watched_tmdb_ids(token)
        update(30, "Buscando por directores y país...")
        movies = get_mubi_recommendations_cached(watched, token=token, limit=40)
        update(100)
        return movies

    movies, err = run_with_progress(fetch, "Calculando recomendaciones MUBI...", [])
    if err:
        notify(f"Error: {err}", icon=xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return
    if not movies:
        notify("Sin resultados", icon=xbmcgui.NOTIFICATION_WARNING)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    xbmcplugin.setPluginCategory(HANDLE, "MUBI — Tu perfil personal")
    show_movie_list(movies)


def view_trakt():
    token = require_token()
    if not token:
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    from lib.cache import CacheManager
    monitor = xbmc.Monitor()
    is_widget = monitor.abortRequested()

    _cache = CacheManager(paths.data_path("trakt_recs_cache.json"), ttl=86400 if is_widget else 3600)
    _cached = _cache.get("recs")
    if _cached:
        xbmcplugin.setPluginCategory(HANDLE, "Recomendaciones Trakt")
        show_movie_list(_cached[:40])
        return

    if is_widget:
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    def fetch(update):
        update(20, "Consultando Trakt...")
        watched = get_watched_tmdb_ids(token)
        update(60, "Enriqueciendo con TMDB...")
        movies = get_general_recommendations(token, watched, limit=40)
        update(100)
        return movies

    movies, err = run_with_progress(fetch, "Obteniendo recomendaciones de Trakt...", [])
    if err:
        notify(f"Error: {err}", icon=xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    movies = movies or []
    _cache.set("recs", movies)
    xbmcplugin.setPluginCategory(HANDLE, "Recomendaciones Trakt")
    show_movie_list(movies)


def view_history():
    token = require_token()
    if not token:
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    def fetch(update):
        update(20, "Descargando historial...")
        raw = get_recent_history(token, limit=50)
        movies = []
        total = len([x for x in raw if x.get("type") == "movie"])
        done = 0
        for item in raw:
            if item.get("type") != "movie":
                continue
            m = item["movie"]
            tmdb_id = m.get("ids", {}).get("tmdb")
            if not tmdb_id:
                continue
            details = get_movie_details(tmdb_id)
            movies.append(enrich_movie(details) if details else {
                "tmdb_id": tmdb_id, "title": m.get("title", ""),
                "year": str(m.get("year", "")), "rating": 0, "votes": 0,
                "overview": "", "poster": "", "fanart": "",
                "genre_ids": [], "origin_country": [], "original_language": "",
            })
            done += 1
            update(20 + int(done / max(total, 1) * 80), m.get("title", ""))
        return movies

    movies, err = run_with_progress(fetch, "Cargando historial reciente...", [])
    if err:
        notify(f"Error: {err}", icon=xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    xbmcplugin.setPluginCategory(HANDLE, "Lo que estoy viendo")
    show_movie_list(movies or [])


def view_watched():
    token = require_token()
    if not token:
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    def fetch(update):
        update(10, "Descargando historial de Trakt...")
        raw = get_watched_movies(token)
        # Sort most recently watched first
        raw.sort(key=lambda m: m.get("last_watched", ""), reverse=True)
        total = len(raw)
        enriched = []
        limit = min(total, 60)
        for i, m in enumerate(raw[:limit]):
            tmdb_id = m.get("tmdb_id")
            if not tmdb_id:
                continue
            details = get_movie_details(tmdb_id)
            enriched.append(enrich_movie(details) if details else {
                "tmdb_id": tmdb_id, "title": m.get("title", ""),
                "year": str(m.get("year", "")), "rating": 0, "votes": 0,
                "overview": "", "poster": "", "fanart": "",
                "genre_ids": [], "origin_country": [], "original_language": "",
            })
            pct = 10 + int((i + 1) / limit * 90)
            update(pct, m.get("title", ""))
        update(100)
        return enriched, total

    result, err = run_with_progress(fetch, "Cargando películas vistas...", [])
    if err:
        notify(f"Error: {err}", icon=xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    movies, total = result if result else ([], 0)
    shown = len(movies)
    label = f"Películas vistas ({shown} de {total})" if total > shown else f"Películas vistas ({total})"
    xbmcplugin.setPluginCategory(HANDLE, label)
    show_movie_list(movies)


def view_stats():
    import datetime
    today = datetime.date.today()
    MONTHS = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
              "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
    month_label = f"Este mes — {MONTHS[today.month]} {today.year}"
    year_label = f"Este año — {today.year}"

    entries = [
        (month_label, "stats_month", "Películas, series, minutos y directores del mes actual"),
        (year_label,  "stats_year",  f"Resumen completo del año {today.year}"),
        ("Histórico", "stats_all",   "Todos los datos acumulados de tu cuenta Trakt"),
    ]
    for label, action, description in entries:
        li = xbmcgui.ListItem(label=label)
        li.setInfo("video", {"plot": description, "mediatype": "movie"})
        xbmcplugin.addDirectoryItem(HANDLE, build_url(action), li, isFolder=False)
    xbmcplugin.endOfDirectory(HANDLE)


def view_stats_widget():
    """Items shown in the home screen spotlight for the Estadísticas segment."""
    import datetime
    today = datetime.date.today()
    MONTHS = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
              "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

    ICONS_BASE = "special://skin/extras/icons/"
    entries = [
        (f"Este mes — {MONTHS[today.month]} {today.year}", "stats_month",
         "Películas y series del mes actual", ICONS_BASE + "timer.png"),
        (f"Este año — {today.year}", "stats_year",
         f"Resumen completo del año {today.year}", ICONS_BASE + "year.png"),
        ("Histórico completo", "stats_all",
         "Todos los datos acumulados de tu cuenta Trakt", ICONS_BASE + "database.png"),
    ]
    for label, action, description, icon in entries:
        li = xbmcgui.ListItem(label=label)
        li.setInfo("video", {"plot": description, "mediatype": "movie"})
        li.setArt({"thumb": icon, "icon": icon})
        xbmcplugin.addDirectoryItem(HANDLE, build_url(action), li, isFolder=False)
    xbmcplugin.endOfDirectory(HANDLE)


def view_stats_month():
    token = require_token()
    if not token:
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    label, start_at, end_at = period_month()

    def fetch(update):
        return compute_period_stats(token, start_at, end_at, update)

    stats, err = run_with_progress(fetch, f"Calculando estadísticas — {label}...", [])
    if err:
        notify(f"Error: {err}", icon=xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    show_stats_window(stats or {}, label, is_all_time=False)
    xbmcplugin.endOfDirectory(HANDLE, succeeded=False)


def view_stats_year():
    token = require_token()
    if not token:
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    label, start_at, end_at = period_year()

    def fetch(update):
        return compute_period_stats(token, start_at, end_at, update)

    stats, err = run_with_progress(fetch, f"Calculando estadísticas — {label}...", [])
    if err:
        notify(f"Error: {err}", icon=xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    show_stats_window(stats or {}, label, is_all_time=False)
    xbmcplugin.endOfDirectory(HANDLE, succeeded=False)


def view_stats_all():
    token = require_token()
    if not token:
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    def fetch(update):
        update(10, "Consultando Trakt...")
        result = get_all_time_stats(token)
        update(100)
        return result

    stats, err = run_with_progress(fetch, "Cargando historial completo...", [])
    if err:
        notify(f"Error: {err}", icon=xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    show_stats_window(stats or {}, "Histórico Completo", is_all_time=True)
    xbmcplugin.endOfDirectory(HANDLE, succeeded=False)


def view_play():
    """Resuelve el play de una película vía Elementum. Funciona desde widget y desde el addon."""
    params = parse_qs(urlparse(sys.argv[2]).query)
    tmdb_id_str = params.get("tmdb_id", [""])[0]
    if not tmdb_id_str:
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return
    tmdb_id = int(tmdb_id_str)
    elementum_url = _elementum_url(tmdb_id)
    li = xbmcgui.ListItem(path=elementum_url)
    li.setProperty("IsPlayable", "true")
    xbmcplugin.setResolvedUrl(HANDLE, True, li)
    if ADDON.getSettingBool("auto_subtitles"):
        _schedule_subtitle_search(tmdb_id=tmdb_id)


def view_rate_movie():
    """Menú de puntuación 1-10 para una película, guarda en Trakt."""
    params = parse_qs(urlparse(sys.argv[2]).query)
    tmdb_id_str = params.get("tmdb_id", [""])[0]
    if not tmdb_id_str:
        return
    tmdb_id = int(tmdb_id_str)

    token = require_token()
    if not token:
        return

    options = [f"{i}/10  {'★' * i}{'☆' * (10 - i)}" for i in range(1, 11)]
    idx = xbmcgui.Dialog().select("Puntuar en Trakt", options)
    if idx == -1:
        return
    rating = idx + 1

    ok = rate_movie(token, tmdb_id, rating)
    if ok:
        notify(f"Puntuación {rating}/10 guardada en Trakt ✓")
    else:
        notify("Error al guardar la puntuación", icon=xbmcgui.NOTIFICATION_ERROR)


def view_refresh():
    _get_cache().clear()
    _get_watched_cache().clear()
    # También limpia los caches de watchlist para reflejar cambios en Trakt
    from lib.cache import CacheManager
    CacheManager(paths.data_path("shows_cache.json"), ttl=0).clear()
    CacheManager(paths.data_path("watchlist_movies_cache.json"), ttl=0).clear()
    notify("Caché limpiado. Seguimientos, recomendaciones e historial se recargarán.")
    xbmcplugin.endOfDirectory(HANDLE)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

def router():
    params = parse_qs(urlparse(sys.argv[2]).query)
    action = params.get("action", [None])[0]

    routes = {
        None:               view_main_menu,
        "play":             view_play,
        "rate_movie":       view_rate_movie,
        "mubi":             view_mubi,
        "trakt":            view_trakt,
        "watchlist_movies": view_watchlist_movies,
        "shows":            view_shows,
        "history":          view_history,
        "watched":          view_watched,
        "stats":            view_stats,
        "stats_widget":     view_stats_widget,
        "stats_month":      view_stats_month,
        "stats_year":       view_stats_year,
        "stats_all":        view_stats_all,
        "refresh":          view_refresh,
        "logout":           lambda: (logout(), notify("Sesión de Trakt cerrada")),
    }

    handler = routes.get(action)
    if handler:
        try:
            handler()
        except Exception as e:
            xbmc.log(f"[{ADDON_ID}] Error en '{action}': {e}", xbmc.LOGERROR)
            notify(f"Error inesperado: {e}", icon=xbmcgui.NOTIFICATION_ERROR)
            xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
    else:
        xbmc.log(f"[{ADDON_ID}] Acción desconocida: {action}", xbmc.LOGWARNING)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)


if __name__ == "__main__":
    router()
