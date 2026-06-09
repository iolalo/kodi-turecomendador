"""
Backup completo de Kodi desde Raspberry Pi LibreELEC.

Descarga:
  - Todos los addons (excepto binarios nativos y elementum)
  - userdata completo: guisettings, sources, RSS, skinshortcuts, skin settings,
    trakt settings, subtítulos, weather, base de datos de addons + historial

Crea:
  backups/YYYY-MM-DD_HHMMSS/   (carpeta estructurada)
  backups/YYYY-MM-DD_HHMMSS.zip (archivo comprimido)

Uso: python backup_pi.py
"""
import json
import stat
import zipfile
from datetime import datetime
from pathlib import Path

import paramiko

PI_HOST = "192.168.0.203"
PI_USER = "root"
PI_PASS = "libreelec"

# Addons que NO se incluyen en el backup
SKIP_ADDONS = {
    "plugin.video.elementum",   # binario ARM nativo — no portable
    "vfs.libarchive",           # binario nativo
    "script.elementum.burst",   # depende de elementum
    "repository.elementumorg",  # repo de elementum
    "packages",                 # ZIPs descargados, se regeneran
    "temp",                     # archivos temporales
}

# addon_data que se omiten (demasiado grandes o inútiles para restore)
SKIP_ADDON_DATA = {
    "plugin.video.elementum",           # 107MB de caché de elementum
    "plugin.video.themoviedb.helper",   # 5.8MB de caché de imágenes
}

# Archivos que se excluyen de addon_data
SKIP_FILES = {
    "trakt_token.json",     # token personal OAuth que expira — re-autenticar tras restore
    "queue.db",             # caché de Trakt
}

# Sufijos de archivos a excluir
SKIP_SUFFIXES = (
    "_cache.json",          # cachés enriquecidos (se regeneran solos)
    ".pyc",                 # bytecode Python compilado
    ".pyo",
)

# Directorios de userdata que se omiten
SKIP_USERDATA_DIRS = {
    "Thumbnails",   # 11MB de miniaturas — Kodi las regenera automáticamente
    "Savestates",   # estados de juegos
    "library",      # librería de video local (paths específicos del dispositivo)
    "playlists",    # playlists vacías
    "peripheral_data",
}

# Archivos de base de datos a incluir (el resto se regenera)
INCLUDE_DBS = {
    "Addons33.db",      # estado habilitado/deshabilitado de cada addon
    "MyVideos131.db",   # historial de vistas y ratings
    "ViewModes6.db",    # modos de vista por pantalla
}

STATIC_IP_CONFIG = {
    "address": "192.168.0.203",
    "netmask": "255.255.255.0",
    "gateway": "192.168.0.1",
    "nameservers": ["8.8.8.8", "1.1.1.1"],
    "wifi_service": "wifi_e45f01067fbb_506572736f6e616c2d373239_managed_psk",
    "wifi_ssid": "Personal-729",
}


# ---------------------------------------------------------------------------

def fmt(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / 1024 / 1024:.1f}MB"
    return f"{n / 1024:.0f}KB"


def should_skip(name: str) -> bool:
    if name in SKIP_FILES:
        return True
    return any(name.endswith(s) for s in SKIP_SUFFIXES)


def sftp_download_dir(sftp, remote: str, local: Path) -> int:
    """Descarga recursiva remote -> local. Retorna bytes descargados."""
    local.mkdir(parents=True, exist_ok=True)
    try:
        entries = sftp.listdir_attr(remote)
    except Exception as e:
        print(f"    WARN: no se puede listar {remote}: {e}")
        return 0

    total = 0
    for entry in entries:
        name = entry.filename
        if should_skip(name):
            continue
        rpath = f"{remote}/{name}"
        lpath = local / name
        if stat.S_ISDIR(entry.st_mode):
            total += sftp_download_dir(sftp, rpath, lpath)
        else:
            try:
                sftp.get(rpath, str(lpath))
                total += entry.st_size or lpath.stat().st_size
            except Exception as e:
                print(f"    WARN: {rpath}: {e}")
    return total


def download_file(sftp, remote: str, local: Path) -> int:
    local.parent.mkdir(parents=True, exist_ok=True)
    try:
        sftp.get(remote, str(local))
        return local.stat().st_size
    except Exception as e:
        print(f"  WARN: {remote}: {e}")
        return 0


# ---------------------------------------------------------------------------

def main():
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    backup_root = Path("backups") / stamp
    backup_root.mkdir(parents=True, exist_ok=True)

    print(f"Backup Kodi Pi -> {backup_root}")
    print(f"Conectando a {PI_HOST}...\n")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(PI_HOST, username=PI_USER, password=PI_PASS, timeout=30)
    sftp = client.open_sftp()

    grand_total = 0

    # ------------------------------------------------------------------
    # 1. ADDONS
    # ------------------------------------------------------------------
    print("=" * 55)
    print("[1/3] ADDONS")
    print("=" * 55)

    addons_dest = backup_root / "addons"
    addon_entries = [
        e for e in sftp.listdir_attr("/storage/.kodi/addons")
        if stat.S_ISDIR(e.st_mode) and e.filename not in SKIP_ADDONS
    ]
    addon_entries.sort(key=lambda e: e.filename)

    for i, entry in enumerate(addon_entries, 1):
        name = entry.filename
        print(f"  [{i:02d}/{len(addon_entries):02d}] {name}...", end=" ", flush=True)
        size = sftp_download_dir(sftp, f"/storage/.kodi/addons/{name}", addons_dest / name)
        print(fmt(size))
        grand_total += size

    # ------------------------------------------------------------------
    # 2. USERDATA
    # ------------------------------------------------------------------
    print(f"\n{'=' * 55}")
    print("[2/3] USERDATA")
    print("=" * 55)

    # 2a. Archivos raíz
    userdata_dest = backup_root / "userdata"
    for fname in ["guisettings.xml", "sources.xml", "RssFeeds.xml", "profiles.xml"]:
        size = download_file(sftp, f"/storage/.kodi/userdata/{fname}", userdata_dest / fname)
        if size:
            print(f"  {fname} ({fmt(size)})")
            grand_total += size

    # 2b. addon_data (configuraciones de cada addon)
    print("\n  addon_data/")
    addon_data_entries = [
        e for e in sftp.listdir_attr("/storage/.kodi/userdata/addon_data")
        if stat.S_ISDIR(e.st_mode) and e.filename not in SKIP_ADDON_DATA
    ]
    for entry in sorted(addon_data_entries, key=lambda e: e.filename):
        name = entry.filename
        dest = userdata_dest / "addon_data" / name
        size = sftp_download_dir(sftp, f"/storage/.kodi/userdata/addon_data/{name}", dest)
        if size > 0:
            print(f"    {name}: {fmt(size)}")
        grand_total += size

    # 2c. Database
    print("\n  Database/")
    db_dest = userdata_dest / "Database"
    db_dest.mkdir(parents=True, exist_ok=True)
    for fname in sftp.listdir("/storage/.kodi/userdata/Database"):
        if fname in INCLUDE_DBS:
            size = download_file(
                sftp,
                f"/storage/.kodi/userdata/Database/{fname}",
                db_dest / fname,
            )
            print(f"    {fname}: {fmt(size)}")
            grand_total += size

    # ------------------------------------------------------------------
    # 3. MANIFEST
    # ------------------------------------------------------------------
    print(f"\n{'=' * 55}")
    print("[3/3] MANIFEST + ZIP")
    print("=" * 55)

    manifest = {
        "created": stamp,
        "pi_host": PI_HOST,
        "kodi": "21.3 Omega",
        "libreelec": "12.x",
        "skin": "skin.arctic.zephyr.mod",
        "network": STATIC_IP_CONFIG,
        "excluded": [
            "plugin.video.elementum (binario nativo x64)",
            "plugin.video.themoviedb.helper/addon_data (caché de imágenes)",
            "trakt_token.json (token OAuth personal — re-autenticar tras restore)",
            "userdata/Thumbnails (se regeneran solas)",
            "*_cache.json (cachés de TMDB/Trakt — se regeneran solos)",
        ],
        "restore_notes": [
            "1. Instalar LibreELEC en la Pi",
            "2. Conectar a la misma red WiFi 'Personal-729'",
            "3. Ejecutar: python restore_pi.py",
            "4. Abrir addon turecomendador -> autenticar Trakt",
            "5. Abrir addon turecomendador -> 'Seguimiento de series/películas' para popular cachés",
        ],
    }
    (backup_root / "backup_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"  manifest: backup_manifest.json")

    sftp.close()
    client.close()

    # Crear ZIP
    zip_path = Path("backups") / f"{stamp}.zip"
    print(f"\n  Comprimiendo -> {zip_path} ...")
    file_count = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in sorted(backup_root.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(backup_root.parent))
                file_count += 1

    zip_size = zip_path.stat().st_size
    print(f"  {file_count} archivos | sin comprimir: {fmt(grand_total)} | ZIP: {fmt(zip_size)}")
    print(f"\nBackup completo: {zip_path}")


if __name__ == "__main__":
    main()
