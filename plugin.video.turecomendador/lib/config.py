try:
    import xbmcaddon as _xa
    _s = _xa.Addon().getSetting
    TRAKT_CLIENT_ID     = _s("trakt_client_id")
    TRAKT_CLIENT_SECRET = _s("trakt_client_secret")
    TMDB_API_KEY        = _s("tmdb_api_key")
    TRAKT_USERNAME      = _s("trakt_username")
except ImportError:
    # Entorno local / tests — configurar desde variables de entorno
    import os
    TRAKT_CLIENT_ID     = os.environ.get("TRAKT_CLIENT_ID", "")
    TRAKT_CLIENT_SECRET = os.environ.get("TRAKT_CLIENT_SECRET", "")
    TMDB_API_KEY        = os.environ.get("TMDB_API_KEY", "")
    TRAKT_USERNAME      = os.environ.get("TRAKT_USERNAME", "")
