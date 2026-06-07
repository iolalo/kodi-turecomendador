import os
import zipfile
import urllib.request
import xbmc
import xbmcgui
import xbmcvfs

GITHUB_REPO = "iolalo/kodi-turecomendador"
BUILD_TAG = "build-20260607"
BUILD_URL = f"https://github.com/{GITHUB_REPO}/releases/download/{BUILD_TAG}/kodi-build.zip"


def _kodi_home():
    return xbmcvfs.translatePath("special://home/")


def _tmp_path():
    return xbmcvfs.translatePath("special://temp/kodi-build.zip")


def _download(url, dest, dialog):
    def _hook(count, block, total):
        if total > 0:
            pct = min(int(count * block * 100 / total), 70)
            dialog.update(pct, f"Descargando build... {pct}%")

    try:
        urllib.request.urlretrieve(url, dest, _hook)
        return True
    except Exception as e:
        xbmcgui.Dialog().ok("Error", f"No se pudo descargar la build:\n{e}")
        return False


def _extract(zip_path, dest_dir, dialog):
    dialog.update(75, "Extrayendo archivos...")
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            members = zf.namelist()
            total = len(members)
            for i, member in enumerate(members):
                zf.extract(member, dest_dir)
                if i % 50 == 0:
                    pct = 75 + int(i * 20 / total)
                    dialog.update(pct, f"Extrayendo... {i}/{total}")
        return True
    except Exception as e:
        xbmcgui.Dialog().ok("Error", f"No se pudo extraer la build:\n{e}")
        return False


def main():
    ok = xbmcgui.Dialog().yesno(
        "Instalador de Build",
        "Esto va a instalar la build completa de Mi Recomendador:\n\n"
        "• Skin Arctic Zephyr Mod\n"
        "• Addons: Elementum, TMDB Helper, Subtítulos\n"
        "• Configuración completa\n\n"
        "¿Continuar?",
    )
    if not ok:
        return

    dialog = xbmcgui.DialogProgress()
    dialog.create("Instalando build...", "Iniciando descarga...")

    tmp = _tmp_path()
    home = _kodi_home()

    if not _download(BUILD_URL, tmp, dialog):
        dialog.close()
        return

    if dialog.iscanceled():
        dialog.close()
        return

    if not _extract(tmp, home, dialog):
        dialog.close()
        return

    try:
        os.remove(tmp)
    except Exception:
        pass

    dialog.update(100, "Instalación completa.")
    xbmc.sleep(1000)
    dialog.close()

    xbmcgui.Dialog().ok(
        "Build instalada",
        "La build se instaló correctamente.\n\n"
        "Al reiniciar Kodi vas a ver la skin y todos los addons.\n"
        "Configurá las API keys en: Mi Recomendador → Ajustes",
    )
    xbmc.executebuiltin("RestartApp")


main()
