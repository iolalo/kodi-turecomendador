import os

# En Kodi: se sobreescribe desde main.py con xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
# En tests locales: usa la carpeta raíz del proyecto
_data_dir = os.path.join(os.path.dirname(__file__), "..")


def set_data_dir(path: str):
    global _data_dir
    _data_dir = path


def data_path(filename: str) -> str:
    return os.path.join(_data_dir, filename)
