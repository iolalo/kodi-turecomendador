"""
package_kodi.py — empaqueta la instalación completa de Kodi de esta notebook.

Uso:
    py package_kodi.py

Genera kodi-build.zip listo para subir como GitHub Release asset.
El wizard lo descarga e instala en cualquier Kodi (PC o Raspberry Pi).
"""
import os
import sys
import zipfile
from pathlib import Path
from datetime import datetime

KODI_HOME = Path(os.environ["APPDATA"]) / "Kodi"
OUTPUT = Path("kodi-build.zip")

# Addons con binarios nativos x86/x64 que no corren en ARM (LibreELEC/Raspberry Pi)
# El usuario los instala desde su repo oficial directamente en el dispositivo destino
EXCLUDE_ADDONS = {
    "plugin.video.elementum",    # binario nativo: elementum.exe / elementum (arm)
    "script.elementum.burst",    # depende de elementum
    "repository.elementumorg",   # repo de elementum
    "vfs.libarchive",            # binario nativo dependiente de plataforma
    "repository.addons4kodi",    # schema checksum sin algo= crashea Kodi 21
}

# Carpetas que no tienen sentido copiar
EXCLUDE_DIRS = {
    "packages",       # cache de zips descargados
    "temp",           # temporales
    "__pycache__",
    "Thumbnails",     # cache de imágenes (75 MB, se regenera sola)
    "Database",       # historial personal de reproducciones
    "Savestates",
    "logfiles",
}

# Archivos con credenciales personales o específicos de plataforma que no deben distribuirse
EXCLUDE_FILES = {
    # tokens Trakt y API keys del addon
    os.path.join("userdata", "addon_data", "plugin.video.turecomendador", "settings.xml"),
    # configuración de audio/video/display — específica de cada dispositivo
    os.path.join("userdata", "guisettings.xml"),
}

EXCLUDE_EXTS = {".pyc", ".pyo", ".log", ".bak"}


def should_exclude(rel: str) -> bool:
    parts = Path(rel).parts
    for part in parts:
        if part in EXCLUDE_DIRS:
            return True
    # Excluir addons con binarios nativos platform-específicos
    if parts[0] == "addons" and len(parts) > 1 and parts[1] in EXCLUDE_ADDONS:
        return True
    if rel in EXCLUDE_FILES:
        return True
    if Path(rel).suffix in EXCLUDE_EXTS:
        return True
    return False


def main():
    if not KODI_HOME.exists():
        print(f"ERROR: no se encontró Kodi en {KODI_HOME}", file=sys.stderr)
        sys.exit(1)

    print(f"Empaquetando {KODI_HOME} -> {OUTPUT}")
    count = 0
    skipped = 0

    with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, dirs, files in os.walk(KODI_HOME):
            # Filtrar carpetas excluidas en el walk
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

            for fname in files:
                full = Path(root) / fname
                rel = str(full.relative_to(KODI_HOME)).replace("\\", "/")

                if should_exclude(rel):
                    skipped += 1
                    continue

                zf.write(full, rel)
                count += 1
                if count % 100 == 0:
                    print(f"  {count} archivos...", end="\r")

    size_mb = OUTPUT.stat().st_size / 1_048_576
    print(f"\nListo: {count} archivos, {skipped} excluidos — {size_mb:.1f} MB")
    print(f"\nPróximo paso:")
    print(f"  gh release upload <tag> {OUTPUT} --clobber")
    print(f"  O crear un nuevo release:")
    print(f"  gh release create build-{datetime.now().strftime('%Y%m%d')} {OUTPUT} --title 'Kodi Build' --notes 'Build completa'")


if __name__ == "__main__":
    main()
