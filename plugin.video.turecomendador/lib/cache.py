from __future__ import annotations
import json
import os
import time
from typing import Any

try:
    import xbmc
    def _log(msg: str):
        xbmc.log(f"[turecomendador/cache] {msg}", xbmc.LOGWARNING)
except ImportError:
    def _log(msg: str):
        print(f"[WARN] {msg}")


class CacheManager:
    """Caché en disco con TTL. Thread-safe para lectura; writes son atómicos."""

    def __init__(self, cache_path: str, ttl: int = 900):
        self._path = cache_path
        self._ttl = ttl
        self._data: dict = {}
        self._loaded = False

    def _ensure_loaded(self):
        if not self._loaded:
            self._data = self._read_disk()
            self._loaded = True

    def _read_disk(self) -> dict:
        try:
            if os.path.exists(self._path):
                with open(self._path, encoding="utf-8") as f:
                    return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            _log(f"Error leyendo caché {self._path}: {e}")
        return {}

    def _write_disk(self):
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
        except OSError as e:
            _log(f"Error escribiendo caché {self._path}: {e}")

    def get(self, key: str) -> Any | None:
        self._ensure_loaded()
        entry = self._data.get(key)
        if entry is None:
            return None
        if time.time() - entry.get("ts", 0) > self._ttl:
            del self._data[key]
            return None
        return entry.get("value")

    def set(self, key: str, value: Any):
        self._ensure_loaded()
        self._data[key] = {"value": value, "ts": time.time()}
        self._write_disk()

    def delete(self, key: str):
        self._ensure_loaded()
        if key in self._data:
            del self._data[key]
            self._write_disk()

    def clear(self):
        self._data = {}
        self._loaded = True
        self._write_disk()
