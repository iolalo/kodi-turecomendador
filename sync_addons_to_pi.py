"""
Sync addons from notebook Kodi -> Raspberry Pi LibreELEC via SFTP.
Copies pure-Python addons only. Skips native-binary addons.
"""
import os
import sys
import paramiko
from pathlib import Path

PI_HOST = "192.168.0.203"
PI_USER = "root"
PI_PASS = "libreelec"
PI_ADDONS = "/storage/.kodi/addons"

NOTEBOOK_ADDONS = Path(os.environ["APPDATA"]) / "Kodi" / "addons"
DEV_DIR = Path(r"C:\Users\ralej\OneDrive\Kodi-dev")

# Addons with native binaries or irrelevant — skip these
SKIP = {
    "packages", "temp",
    "plugin.video.elementum",
    "vfs.libarchive",
    "script.elementum.burst",
    "repository.elementumorg",
    "plugin.onedrive",
    "plugin.video.helloworld",
}

# Already on Pi — skip unless we want to update
ALREADY_ON_PI = {
    "metadata.album.universal",
    "metadata.artists.universal",
    "metadata.common.fanart.tv",
    "metadata.generic.albums",
    "metadata.themoviedb.org.python",
    "metadata.tvshows.themoviedb.org.python",
    "script.embuary.helper",
    "script.skinshortcuts",
    "skin.arctic.zephyr.mod",
    "repository.turecomendador",
    "resource.language.es_es",
}

def sftp_put_dir(sftp, local_dir: Path, remote_dir: str):
    """Recursively upload a local directory to the Pi via SFTP."""
    try:
        sftp.stat(remote_dir)
    except FileNotFoundError:
        sftp.mkdir(remote_dir)

    for item in local_dir.iterdir():
        remote_path = remote_dir + "/" + item.name
        if item.is_dir():
            sftp_put_dir(sftp, item, remote_path)
        else:
            sftp.put(str(item), remote_path)


def main():
    # Build list of addons to copy from notebook
    notebook_addons = {
        p.name for p in NOTEBOOK_ADDONS.iterdir()
        if p.is_dir() and p.name not in SKIP and p.name not in ALREADY_ON_PI
    }

    print(f"Addons to copy: {len(notebook_addons)}")
    for a in sorted(notebook_addons):
        print(f"  {a}")

    print("\nConnecting to Pi...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(PI_HOST, username=PI_USER, password=PI_PASS, timeout=30)
    sftp = client.open_sftp()

    errors = []
    for i, addon_name in enumerate(sorted(notebook_addons), 1):
        src = NOTEBOOK_ADDONS / addon_name
        dst = f"{PI_ADDONS}/{addon_name}"
        print(f"[{i:02d}/{len(notebook_addons):02d}] Copying {addon_name}...", end=" ", flush=True)
        try:
            sftp_put_dir(sftp, src, dst)
            print("OK")
        except Exception as e:
            print(f"ERROR: {e}")
            errors.append((addon_name, str(e)))

    # Also copy turecomendador from dev dir (latest version)
    dev_plugin = DEV_DIR / "plugin.video.turecomendador"
    if dev_plugin.exists():
        print(f"\nUpdating plugin.video.turecomendador from dev dir...", end=" ", flush=True)
        try:
            sftp_put_dir(sftp, dev_plugin, f"{PI_ADDONS}/plugin.video.turecomendador")
            print("OK")
        except Exception as e:
            print(f"ERROR: {e}")
            errors.append(("plugin.video.turecomendador (dev)", str(e)))

    sftp.close()
    client.close()

    print("\n=== DONE ===")
    if errors:
        print(f"Errors ({len(errors)}):")
        for name, err in errors:
            print(f"  {name}: {err}")
    else:
        print("All addons copied successfully.")


if __name__ == "__main__":
    main()
