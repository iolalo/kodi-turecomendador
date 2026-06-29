"""
Empaqueta el addon + configuración de skin + subtítulos en un ZIP instalable.

Uso:
    python package_build.py [--output ./dist] [--subtitles ./kodi_backup_subtitles]

Estructura del ZIP resultante:
    plugin.video.turecomendador.zip/
        addons/
            plugin.video.turecomendador/
        userdata/
            addon_data/
                script.skinshortcuts/
                service.subtitles.*/   (si existen en el backup)
"""
import argparse
import os
import platform
import zipfile
from pathlib import Path

ADDON_ID = "plugin.video.turecomendador"

EXCLUDE_PATTERNS = {
    "__pycache__", ".pyc", ".pyo", ".git", ".gitignore",
    "package_build.py", ".DS_Store", "Thumbs.db",
    "kodi_backup_subtitles", "dist", "sync_subtitles_from_pi",
    "apply_subtitles_config",
}

ADDON_SRC = Path(__file__).parent


def _kodi_appdata() -> Path:
    sys = platform.system()
    if sys == "Windows":
        return Path(os.environ.get("APPDATA", "")) / "Kodi"
    elif sys == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Kodi"
    return Path.home() / ".kodi"


def _should_exclude(path: Path) -> bool:
    return any(pat in path.name for pat in EXCLUDE_PATTERNS)


def _add_tree(zf: zipfile.ZipFile, src: Path, arc_prefix: str):
    for item in src.rglob("*"):
        if _should_exclude(item):
            continue
        if item.is_file():
            arc = arc_prefix + "/" + item.relative_to(src).as_posix()
            zf.write(item, arc)


def build(output_dir: Path, subtitles_backup: Path | None):
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / f"{ADDON_ID}.zip"

    kodi = _kodi_appdata()
    skinshortcuts = kodi / "userdata" / "addon_data" / "script.skinshortcuts"

    included = []
    skipped  = []

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:

        # 1. Addon
        _add_tree(zf, ADDON_SRC, f"addons/{ADDON_ID}")
        included.append(f"addons/{ADDON_ID}/")

        # 2. Skinshortcuts (menú personalizado)
        if skinshortcuts.exists():
            _add_tree(zf, skinshortcuts, "userdata/addon_data/script.skinshortcuts")
            included.append("userdata/addon_data/script.skinshortcuts/")
        else:
            skipped.append(f"skinshortcuts ({skinshortcuts})")

        # 3. Configuraciones de subtítulos
        backup = subtitles_backup or (ADDON_SRC / "kodi_backup_subtitles")
        if backup.exists():
            subtitle_dirs = [d for d in backup.iterdir()
                             if d.is_dir() and d.name.startswith("service.subtitles.")]
            for sd in subtitle_dirs:
                _add_tree(zf, sd, f"userdata/addon_data/{sd.name}")
                included.append(f"userdata/addon_data/{sd.name}/")
            if not subtitle_dirs:
                skipped.append("subtítulos (backup vacío)")
        else:
            skipped.append(f"subtítulos (no hay backup en {backup})")

    size_kb = zip_path.stat().st_size / 1024
    print(f"\n{'='*50}")
    print(f"  ZIP generado: {zip_path}")
    print(f"  Tamaño: {size_kb:.1f} KB")
    print(f"\n  Incluido:")
    for item in included:
        print(f"    + {item}")
    if skipped:
        print(f"\n  Omitido (no encontrado):")
        for item in skipped:
            print(f"    - {item}")
    print(f"\n  Instalación:")
    print(f"    1. Copiar el ZIP al dispositivo destino")
    print(f"    2. Kodi → Add-ons → Instalar desde archivo ZIP")
    print(f"    3. Reiniciar Kodi")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Empaqueta el addon para distribución")
    parser.add_argument("--output",    default="./dist",
                        help="Carpeta de salida (default: ./dist)")
    parser.add_argument("--subtitles", default=None,
                        help="Carpeta con backup de subtítulos de la Pi")
    args = parser.parse_args()
    build(Path(args.output),
          Path(args.subtitles) if args.subtitles else None)
