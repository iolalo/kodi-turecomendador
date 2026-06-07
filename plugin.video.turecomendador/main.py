from __future__ import annotations
import sys
import os
import threading
from urllib.parse import urlencode, parse_qs, urlparse

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
    get_watched_movies, get_watched_shows,
    get_recent_history, get_watched_tmdb_ids,
    _get_cache, _get_watched_cache,
)
from lib.recommendations import get_mubi_recommendations, get_mubi_recommendations_cached, get_general_recommendations
from lib.tmdb_handler import get_movie_details, enrich_movie
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
    return li


def show_movie_list(movies: list[dict]):
    if not _elementum_available():
        xbmcgui.Dialog().ok(
            "Elementum no instalado",
            "Para reproducir necesitás el addon [B]Elementum[/B].\n"
            "Instalalo desde el repositorio de Kodi y volvé a intentar.",
        )
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    xbmcplugin.setContent(HANDLE, "movies")
    items = []
    for movie in movies:
        tmdb_id = movie.get("tmdb_id")
        if not tmdb_id:
            continue
        li = _make_list_item(movie)
        items.append((_elementum_url(tmdb_id), li, False))

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


def view_mubi():
    token = require_token()
    if not token:
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

    xbmcplugin.setPluginCategory(HANDLE, "Recomendaciones Trakt")
    show_movie_list(movies or [])


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


def view_refresh():
    _get_cache().clear()
    _get_watched_cache().clear()
    notify("Caché limpiado. Historial y recomendaciones se recargarán.")
    xbmcplugin.endOfDirectory(HANDLE)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

def router():
    params = parse_qs(urlparse(sys.argv[2]).query)
    action = params.get("action", [None])[0]

    routes = {
        None:           view_main_menu,
        "mubi":         view_mubi,
        "trakt":        view_trakt,
        "history":      view_history,
        "watched":      view_watched,
        "stats":        view_stats,
        "stats_widget": view_stats_widget,
        "stats_month":  view_stats_month,
        "stats_year":   view_stats_year,
        "stats_all":    view_stats_all,
        "refresh":      view_refresh,
        "logout":       lambda: (logout(), notify("Sesión de Trakt cerrada")),
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
