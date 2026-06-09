"""
Restaura un backup de Kodi a Raspberry Pi LibreELEC.

Uso:
  python restore_pi.py                   # usa el backup más reciente en backups/
  python restore_pi.py backups/2026-06-08_120000
  python restore_pi.py backups/2026-06-08_120000.zip

Requisitos:
  - Pi con LibreELEC arrancado y accesible por SSH en PI_HOST
  - Para restore a Pi nueva: conectar primero a la misma red WiFi
"""
import json
import stat
import sys
import time
import zipfile
from pathlib import Path

import paramiko
import requests as http

PI_HOST = "192.168.0.203"
PI_USER = "root"
PI_PASS = "libreelec"
KODI_RPC = f"http://{PI_HOST}:8080/jsonrpc"
KODI_AUTH = ("kodi", "35021590")


# ---------------------------------------------------------------------------

def fmt(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / 1024 / 1024:.1f}MB"
    return f"{n / 1024:.0f}KB"


def sftp_upload_dir(sftp, local: Path, remote: str) -> int:
    """Sube recursivamente local → remote. Crea directorios si no existen."""
    try:
        sftp.stat(remote)
    except FileNotFoundError:
        sftp.mkdir(remote)

    total = 0
    for item in sorted(local.iterdir()):
        rpath = f"{remote}/{item.name}"
        if item.is_dir():
            total += sftp_upload_dir(sftp, item, rpath)
        else:
            try:
                sftp.put(str(item), rpath)
                total += item.stat().st_size
            except Exception as e:
                print(f"    WARN: {item}: {e}")
    return total


def ssh_run(client, cmd: str) -> str:
    stdin, stdout, stderr = client.exec_command(cmd)
    return stdout.read().decode().strip()


def kodi_restart(client):
    """Intenta reiniciar Kodi vía JSON-RPC, fallback a systemctl."""
    try:
        r = http.post(
            KODI_RPC, auth=KODI_AUTH,
            json={"jsonrpc": "2.0", "method": "Application.Quit", "id": 1},
            timeout=8,
        )
        if r.json().get("result") == "OK":
            return
    except Exception:
        pass
    ssh_run(client, "systemctl restart kodi 2>/dev/null || true")


def kodi_wait(timeout=60) -> bool:
    print("  Esperando que Kodi arranque...", end=" ", flush=True)
    for _ in range(timeout // 3):
        time.sleep(3)
        try:
            r = http.post(
                KODI_RPC, auth=KODI_AUTH,
                json={"jsonrpc": "2.0", "method": "JSONRPC.Ping", "id": 1},
                timeout=4,
            )
            if r.json().get("result") == "pong":
                print("OK")
                return True
        except Exception:
            print(".", end="", flush=True)
    print(" TIMEOUT")
    return False


def resolve_backup(arg: str | None) -> Path:
    if arg:
        p = Path(arg)
        if p.suffix == ".zip":
            print(f"Descomprimiendo {p}...")
            with zipfile.ZipFile(p) as zf:
                zf.extractall("backups")
            return Path("backups") / p.stem
        return p

    backups = Path("backups")
    if not backups.exists():
        print("No hay carpeta backups/. Ejecutá backup_pi.py primero.")
        sys.exit(1)
    dirs = sorted([d for d in backups.iterdir() if d.is_dir()], reverse=True)
    if not dirs:
        print("No hay backups en backups/.")
        sys.exit(1)
    return dirs[0]


# ---------------------------------------------------------------------------

def main():
    backup_path = resolve_backup(sys.argv[1] if len(sys.argv) > 1 else None)

    # Load manifest
    manifest_path = backup_path / "backup_manifest.json"
    manifest = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    print(f"\nRestaurando desde: {backup_path}")
    print(f"  Backup creado: {manifest.get('created', '?')}")
    print(f"  Kodi: {manifest.get('kodi', '?')} / {manifest.get('libreelec', '?')}")
    if manifest.get("excluded"):
        print("  Excluido del backup (acción requerida tras restore):")
        for note in manifest["excluded"]:
            print(f"    - {note}")

    print(f"\nConectando a {PI_HOST}...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(PI_HOST, username=PI_USER, password=PI_PASS, timeout=30)
    sftp = client.open_sftp()

    grand_total = 0

    # ------------------------------------------------------------------
    # 1. ADDONS
    # ------------------------------------------------------------------
    addons_src = backup_path / "addons"
    if addons_src.exists():
        addon_dirs = sorted([d for d in addons_src.iterdir() if d.is_dir()])
        print(f"\n{'=' * 55}")
        print(f"[1/3] ADDONS ({len(addon_dirs)})")
        print("=" * 55)
        for i, addon_dir in enumerate(addon_dirs, 1):
            name = addon_dir.name
            print(f"  [{i:02d}/{len(addon_dirs):02d}] {name}...", end=" ", flush=True)
            size = sftp_upload_dir(sftp, addon_dir, f"/storage/.kodi/addons/{name}")
            print(fmt(size))
            grand_total += size

    # ------------------------------------------------------------------
    # 2. USERDATA
    # ------------------------------------------------------------------
    userdata_src = backup_path / "userdata"
    if userdata_src.exists():
        print(f"\n{'=' * 55}")
        print("[2/3] USERDATA")
        print("=" * 55)

        # Archivos raíz
        for fname in ["guisettings.xml", "sources.xml", "RssFeeds.xml", "profiles.xml"]:
            src = userdata_src / fname
            if src.exists():
                sftp.put(str(src), f"/storage/.kodi/userdata/{fname}")
                size = src.stat().st_size
                grand_total += size
                print(f"  {fname} ({fmt(size)})")

        # addon_data
        addon_data_src = userdata_src / "addon_data"
        if addon_data_src.exists():
            print("\n  addon_data/")
            for addon_dir in sorted(addon_data_src.iterdir()):
                if not addon_dir.is_dir():
                    continue
                size = sftp_upload_dir(
                    sftp, addon_dir,
                    f"/storage/.kodi/userdata/addon_data/{addon_dir.name}"
                )
                if size > 0:
                    print(f"    {addon_dir.name}: {fmt(size)}")
                grand_total += size

        # Database
        db_src = userdata_src / "Database"
        if db_src.exists():
            print("\n  Database/")
            for db_file in sorted(db_src.iterdir()):
                if db_file.is_file():
                    sftp.put(str(db_file), f"/storage/.kodi/userdata/Database/{db_file.name}")
                    print(f"    {db_file.name}: {fmt(db_file.stat().st_size)}")
                    grand_total += db_file.stat().st_size

    # ------------------------------------------------------------------
    # 3. RED + SKIN HASH
    # ------------------------------------------------------------------
    print(f"\n{'=' * 55}")
    print("[3/3] RED + CONFIGURACIÓN FINAL")
    print("=" * 55)

    # IP estática via ConnMan
    net = manifest.get("network", {})
    service = net.get("wifi_service")
    if service:
        ip      = net.get("address", "192.168.0.203")
        netmask = net.get("netmask", "255.255.255.0")
        gateway = net.get("gateway", "192.168.0.1")
        ns      = " ".join(net.get("nameservers", ["8.8.8.8", "1.1.1.1"]))

        ssh_run(client, f"connmanctl config {service} --ipv4 manual {ip} {netmask} {gateway}")
        ssh_run(client, f"connmanctl config {service} --nameservers {ns}")
        print(f"  IP estática: {ip} / {gateway} (WiFi: {net.get('wifi_ssid', service)})")

    # Eliminar hash de skinshortcuts → se regenera con nueva configuración
    try:
        sftp.remove(
            "/storage/.kodi/userdata/addon_data/script.skinshortcuts/skin.arctic.zephyr.mod.hash"
        )
        print("  skinshortcuts hash eliminado → se regenera en el próximo boot")
    except FileNotFoundError:
        pass

    sftp.close()

    # ------------------------------------------------------------------
    # Reiniciar Kodi
    # ------------------------------------------------------------------
    print(f"\n  Total restaurado: {fmt(grand_total)}")
    print("  Reiniciando Kodi...")
    kodi_restart(client)
    kodi_wait()

    client.close()

    # Notas post-restore
    print(f"\n{'=' * 55}")
    print("RESTORE COMPLETO — acciones requeridas:")
    print("=" * 55)
    for note in manifest.get("restore_notes", []):
        print(f"  {note}")


if __name__ == "__main__":
    main()
