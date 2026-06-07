"""Sube plugin.video.turecomendador v0.4.2 a la Raspberry Pi via SFTP."""
import os
import paramiko

HOST = "192.168.0.203"
USER = "root"
PASS = "libreelec"
ADDON_ID = "plugin.video.turecomendador"
REMOTE_BASE = f"/storage/.kodi/addons/{ADDON_ID}"

EXCLUDE_DIRS = {"__pycache__", "temp"}
EXCLUDE_EXTS = {".pyc", ".pyo"}

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username=USER, password=PASS, timeout=10)
sftp = c.open_sftp()


def mkdir_p(sftp, remote_dir):
    parts = remote_dir.lstrip("/").split("/")
    current = ""
    for part in parts:
        current += "/" + part
        try:
            sftp.mkdir(current)
        except OSError:
            pass


count = 0
for root, dirs, files in os.walk(ADDON_ID):
    dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
    for fname in files:
        if any(fname.endswith(e) for e in EXCLUDE_EXTS):
            continue
        local_path = os.path.join(root, fname)
        rel = os.path.relpath(local_path, ADDON_ID).replace("\\", "/")
        remote_path = REMOTE_BASE + "/" + rel
        remote_dir = remote_path.rsplit("/", 1)[0]
        mkdir_p(sftp, remote_dir)
        sftp.put(local_path, remote_path)
        print(f"  OK  {rel}")
        count += 1

sftp.close()
c.close()
print(f"\n--- {count} archivos subidos. Plugin v0.4.2 instalado en la Pi ---")
