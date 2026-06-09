"""
Sync addon_data (configs, API keys, skin settings) from notebook -> Pi.
"""
import os
import paramiko
from pathlib import Path

PI_HOST = "192.168.0.203"
PI_USER = "root"
PI_PASS = "libreelec"
PI_ADDON_DATA = "/storage/.kodi/userdata/addon_data"

NOTEBOOK_ADDON_DATA = Path(os.environ["APPDATA"]) / "Kodi" / "userdata" / "addon_data"

# Only copy these addon_data dirs — everything else stays untouched on the Pi
TO_COPY = [
    "plugin.video.turecomendador",
    "plugin.video.themoviedb.helper",
    "script.trakt",
    "script.embuary.helper",
    "script.skinshortcuts",
    "skin.arctic.zephyr.mod",
    "service.autosubs",
    "service.subtitles.a4ksubtitles",
    "service.subtitles.opensubtitles",
    "service.subtitles.opensubtitles-com",
    "service.subtitles.rvm.addic7ed",
    "weather.gismeteo",
]


def sftp_put_dir(sftp, local_dir: Path, remote_dir: str):
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
    print("Connecting to Pi...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(PI_HOST, username=PI_USER, password=PI_PASS, timeout=30)
    sftp = client.open_sftp()

    errors = []
    for i, addon_name in enumerate(TO_COPY, 1):
        src = NOTEBOOK_ADDON_DATA / addon_name
        dst = f"{PI_ADDON_DATA}/{addon_name}"
        if not src.exists():
            print(f"[{i:02d}/{len(TO_COPY):02d}] SKIP {addon_name} (not in notebook)")
            continue
        print(f"[{i:02d}/{len(TO_COPY):02d}] Copying {addon_name}...", end=" ", flush=True)
        try:
            sftp_put_dir(sftp, src, dst)
            print("OK")
        except Exception as e:
            print(f"ERROR: {e}")
            errors.append((addon_name, str(e)))

    sftp.close()
    client.close()

    print("\n=== DONE ===")
    if errors:
        print(f"Errors ({len(errors)}):")
        for name, err in errors:
            print(f"  {name}: {err}")
    else:
        print("All configs copied successfully.")


if __name__ == "__main__":
    main()
