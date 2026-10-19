"""Cliente mínimo de la API REST de Home Assistant.

Si Home Assistant no responde, no hay que trabar a Sana: los pedidos tienen un timeout corto, la lista de
dispositivos se guarda unos segundos, y después de una falla no se vuelve a intentar por un rato.
"""
import threading
import time

import requests

from . import config

# Dominios que Sana puede ver y controlar.
DOMINIOS = ("switch", "light", "fan", "vacuum", "media_player", "cover", "climate")
TIMEOUT = 3  # segundos
VIGENCIA_LISTA = 10  # segundos que se reutiliza la lista de dispositivos
PAUSA_TRAS_FALLA = 30  # segundos sin reintentar después de que Home Assistant no respondió

_cache: tuple[float, list[dict]] | None = None
_ultima_falla = 0.0
_bloqueo = threading.Lock()


class NoResponde(ConnectionError):
    pass


def disponible() -> bool:
    return bool(config.HA_URL and config.HA_TOKEN)


def _headers() -> dict:
    return {"Authorization": f"Bearer {config.HA_TOKEN}", "Content-Type": "application/json"}


def _pedido(metodo: str, ruta: str, **kwargs) -> requests.Response:
    global _ultima_falla
    if time.time() - _ultima_falla < PAUSA_TRAS_FALLA:
        raise NoResponde(f"Home Assistant no responde en {config.HA_URL} (reintento en unos segundos)")
    try:
        r = requests.request(metodo, f"{config.HA_URL}{ruta}", headers=_headers(), timeout=TIMEOUT, **kwargs)
        r.raise_for_status()
        return r
    except requests.ConnectionError as e:  # incluye timeouts de conexión: el equipo no está en la red
        _ultima_falla = time.time()
        raise NoResponde(f"Home Assistant no responde en {config.HA_URL}") from e
    except requests.Timeout as e:
        _ultima_falla = time.time()
        raise NoResponde(f"Home Assistant tardó demasiado en {config.HA_URL}") from e


def dispositivos() -> list[dict]:
    global _cache
    with _bloqueo:
        if _cache and time.time() - _cache[0] < VIGENCIA_LISTA:
            return _cache[1]
    lista = [
        {
            "entity_id": e["entity_id"],
            "nombre": e["attributes"].get("friendly_name", e["entity_id"]),
            "estado": e["state"],
        }
        for e in _pedido("GET", "/api/states").json()
        if e["entity_id"].split(".")[0] in DOMINIOS
    ]
    with _bloqueo:
        _cache = (time.time(), lista)
    return lista


def servicio(dominio: str, nombre: str, datos: dict) -> None:
    global _cache
    _pedido("POST", f"/api/services/{dominio}/{nombre}", json=datos)
    with _bloqueo:
        _cache = None  # el estado cambió: la próxima lista tiene que ser nueva
