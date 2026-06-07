"""
upload_skin.py — sube skin Arctic Zephyr Mod + skinshortcuts a la Raspberry Pi.
Transfiere ~89 MB via SFTP. Puede tardar 2-5 minutos según la velocidad del WiFi.
"""
import os
import paramiko
import time

HOST = "192.168.0.203"
USER = "root"
PASS = "libreelec"

KODI_WIN = r"C:\Users\ralej\AppData\Roaming\Kodi"
KODI_PI  = "/storage/.kodi"

TRANSFERS = [
    # (carpeta local,                                          carpeta remota)
    (r"addons\skin.arctic.zephyr.mod",                        "addons/skin.arctic.zephyr.mod"),
    (r"addons\script.skinshortcuts",                          "addons/script.skinshortcuts"),
    (r"userdata\addon_data\skin.arctic.zephyr.mod",           "userdata/addon_data/skin.arctic.zephyr.mod"),
    (r"userdata\addon_data\script.skinshortcuts",             "userdata/addon_data/script.skinshortcuts"),
]

EXCLUDE_EXTS = {".pyc", ".pyo"}
EXCLUDE_DIRS = {"__pycache__"}


def mkdir_p(sftp, remote_dir):
    parts = remote_dir.strip("/").split("/")
    current = ""
    for part in parts:
        current += "/" + part
        try:
            sftp.mkdir(current)
        except OSError:
            pass


def upload_tree(sftp, local_root, remote_root, stats):
    for root, dirs, files in os.walk(local_root):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for fname in files:
            if any(fname.endswith(e) for e in EXCLUDE_EXTS):
                continue
            local_path = os.path.join(root, fname)
            rel = os.path.relpath(local_path, local_root).replace("\\", "/")
            remote_path = remote_root + "/" + rel
            remote_dir  = remote_path.rsplit("/", 1)[0]
            mkdir_p(sftp, remote_dir)
            sftp.put(local_path, remote_path)
            stats["count"] += 1
            stats["bytes"] += os.path.getsize(local_path)
            if stats["count"] % 20 == 0:
                mb = stats["bytes"] / 1_048_576
                print(f"  {stats['count']:4d} archivos  {mb:5.1f} MB transferidos...", end="\r")


def main():
    print(f"Conectando a {HOST}...")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASS, timeout=15)
    sftp = c.open_sftp()

    stats = {"count": 0, "bytes": 0}
    t0 = time.time()

    for local_rel, remote_rel in TRANSFERS:
        local_abs  = os.path.join(KODI_WIN, local_rel)
        remote_abs = KODI_PI + "/" + remote_rel
        name = os.path.basename(local_rel)

        if not os.path.exists(local_abs):
            print(f"  SKIP {name} (no existe localmente)")
            continue

        print(f"\n  Subiendo {name}...")
        upload_tree(sftp, local_abs, remote_abs, stats)
        print(f"  OK  {name}                                    ")

    sftp.close()

    elapsed = time.time() - t0
    mb = stats["bytes"] / 1_048_576
    speed = mb / elapsed if elapsed > 0 else 0
    print(f"\n{'='*50}")
    print(f"  Completado en {elapsed:.0f}s")
    print(f"  {stats['count']} archivos  |  {mb:.1f} MB  |  {speed:.1f} MB/s")
    print(f"{'='*50}")
    print()
    print("PRÓXIMO PASO en Kodi:")
    print("  Settings → Interface → Skin → Arctic Zephyr Mod")
    print("  (Kodi se reinicia automáticamente al cambiar la skin)")

    c.close()


if __name__ == "__main__":
    main()
