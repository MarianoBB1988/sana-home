"""Cliente mínimo de la API REST de Home Assistant."""
import requests

from . import config

# Dominios que Sana puede ver y controlar.
DOMINIOS = ("switch", "light", "fan", "vacuum", "media_player", "cover", "climate")


def disponible() -> bool:
    return bool(config.HA_URL and config.HA_TOKEN)


def _headers() -> dict:
    return {"Authorization": f"Bearer {config.HA_TOKEN}", "Content-Type": "application/json"}


def dispositivos() -> list[dict]:
    r = requests.get(f"{config.HA_URL}/api/states", headers=_headers(), timeout=10)
    r.raise_for_status()
    return [
        {
            "entity_id": e["entity_id"],
            "nombre": e["attributes"].get("friendly_name", e["entity_id"]),
            "estado": e["state"],
        }
        for e in r.json()
        if e["entity_id"].split(".")[0] in DOMINIOS
    ]


def servicio(dominio: str, nombre: str, datos: dict) -> None:
    r = requests.post(
        f"{config.HA_URL}/api/services/{dominio}/{nombre}",
        headers=_headers(),
        json=datos,
        timeout=10,
    )
    r.raise_for_status()
