import xbmc, xbmcaddon, time
xbmc.log("[script.install.modules] Starting installation...", xbmc.LOGINFO)
addons = ['script.module.requests', 'script.module.unidecode', 'script.module.urllib3', 'script.module.certifi', 'script.module.chardet', 'script.module.idna', 'script.module.six', 'script.module.dateutil', 'script.module.arrow', 'script.module.beautifulsoup4', 'script.module.soupsieve', 'script.module.html5lib', 'script.module.webencodings', 'script.module.future', 'script.module.simplecache', 'script.module.simpleeval', 'script.module.routing', 'script.module.trakt', 'script.module.infotagger', 'script.module.addon.signals', 'script.module.kodi-six', 'script.trakt', 'script.globalsearch', 'script.favourites', 'plugin.video.themoviedb.helper', 'service.autosubs', 'weather.gismeteo']
for addon_id in addons:
    xbmc.log(f"[script.install.modules] Installing {addon_id}", xbmc.LOGINFO)
    xbmc.executebuiltin(f"InstallAddon({addon_id})")
    time.sleep(2)
xbmc.log("[script.install.modules] Done.", xbmc.LOGINFO)
