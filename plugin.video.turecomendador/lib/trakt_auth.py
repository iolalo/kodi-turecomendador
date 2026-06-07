from __future__ import annotations
import time
import json
import os
import requests

from lib.config import TRAKT_CLIENT_ID, TRAKT_CLIENT_SECRET

from lib.paths import data_path

BASE_URL = "https://api.trakt.tv"


def _token_file() -> str:
    return data_path("trakt_token.json")


def _base_headers() -> dict:
    return {
        "Content-Type": "application/json",
        "trakt-api-version": "2",
        "trakt-api-key": TRAKT_CLIENT_ID,
    }


def _save_token(token_data: dict):
    with open(_token_file(), "w") as f:
        json.dump(token_data, f)


def _load_token() -> dict | None:
    path = _token_file()
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        os.remove(path)
        return None


def _refresh_token(token_data: dict) -> dict | None:
    payload = {
        "refresh_token": token_data["refresh_token"],
        "client_id": TRAKT_CLIENT_ID,
        "client_secret": TRAKT_CLIENT_SECRET,
        "grant_type": "refresh_token",
    }
    r = requests.post(f"{BASE_URL}/oauth/token", json=payload, headers=_base_headers())
    if r.status_code == 200:
        new_token = r.json()
        _save_token(new_token)
        return new_token
    return None


def get_valid_token() -> str | None:
    """Devuelve un access_token válido, o None si no hay sesión."""
    token_data = _load_token()
    if not token_data:
        return None

    # Trakt tokens duran 3 meses; refresh_token dura 6 meses
    expires_at = token_data.get("created_at", 0) + token_data.get("expires_in", 0)
    if time.time() < expires_at - 86400:  # válido por al menos 1 día más
        return token_data["access_token"]

    refreshed = _refresh_token(token_data)
    return refreshed["access_token"] if refreshed else None


def device_auth_flow() -> str | None:
    """
    Inicia el flujo de autenticación por dispositivo.
    Devuelve el access_token si el usuario acepta, o None si cancela/expira.
    Imprime la URL y el código para que el llamador los muestre al usuario.
    """
    # Paso 1: solicitar código de dispositivo
    r = requests.post(
        f"{BASE_URL}/oauth/device/code",
        json={"client_id": TRAKT_CLIENT_ID},
        headers=_base_headers(),
    )
    if r.status_code != 200:
        raise RuntimeError(f"Error solicitando código: {r.status_code} {r.text}")

    data = r.json()
    device_code = data["device_code"]
    user_code = data["user_code"]
    verify_url = data["verification_url"]
    expires_in = data["expires_in"]      # segundos hasta que expira
    poll_interval = data["interval"]     # segundos entre intentos de polling

    print(f"\n{'='*50}")
    print(f"  Abrí esta URL en tu navegador:")
    print(f"  {verify_url}")
    print(f"  Ingresá este código: {user_code}")
    print(f"{'='*50}\n")

    # Paso 2: polling hasta que el usuario autorice o el código expire
    deadline = time.time() + expires_in
    while time.time() < deadline:
        time.sleep(poll_interval)
        poll = requests.post(
            f"{BASE_URL}/oauth/device/token",
            json={
                "code": device_code,
                "client_id": TRAKT_CLIENT_ID,
                "client_secret": TRAKT_CLIENT_SECRET,
            },
            headers=_base_headers(),
        )
        if poll.status_code == 200:
            token_data = poll.json()
            _save_token(token_data)
            print("Autenticación exitosa.")
            return token_data["access_token"]
        elif poll.status_code == 400:
            # Pendiente — el usuario todavía no autorizó
            continue
        elif poll.status_code == 404:
            print("Código inválido.")
            return None
        elif poll.status_code == 409:
            print("Ya aprobado previamente.")
            return None
        elif poll.status_code == 410:
            print("Código expirado.")
            return None
        elif poll.status_code == 418:
            print("Autenticación rechazada por el usuario.")
            return None
        elif poll.status_code == 429:
            # Rate limit — esperar más tiempo
            time.sleep(poll_interval * 2)

    print("El código expiró sin que el usuario autorizara.")
    return None


def logout():
    """Revoca el token y borra el archivo local."""
    token_data = _load_token()
    if token_data:
        requests.post(
            f"{BASE_URL}/oauth/revoke",
            json={
                "token": token_data["access_token"],
                "client_id": TRAKT_CLIENT_ID,
                "client_secret": TRAKT_CLIENT_SECRET,
            },
            headers=_base_headers(),
        )
    if os.path.exists(_token_file()):
        os.remove(_token_file())
    print("Sesión cerrada.")
