"""Ajustes del hogar (ubicación, zona horaria, cotizaciones), compartidos por la web y la voz.

Por ahora se guardan en datos/ajustes.json; para pasar a una base de datos alcanza con cambiar leer() y guardar().
"""
import json
import threading
from zoneinfo import ZoneInfo, available_timezones

from . import config

ARCHIVO = config.RAIZ / "datos" / "ajustes.json"
CAMPOS = ("ciudad", "region", "pais", "zona_horaria", "moneda", "cotizaciones", "clima_fuente")
_bloqueo = threading.Lock()


def _por_defecto() -> dict:
    partes = [p.strip() for p in config.CIUDAD.split(",")]
    return {
        "ciudad": partes[0],
        "region": "",
        "pais": partes[-1] if len(partes) > 1 else "",
        "zona_horaria": config.ZONA_HORARIA,
        "moneda": "",
        "cotizaciones": "",
        "clima_fuente": "open-meteo:best_match",
    }


def leer() -> dict:
    datos = _por_defecto()
    if ARCHIVO.exists():
        try:
            guardados = json.loads(ARCHIVO.read_text(encoding="utf-8"))
            datos.update({k: str(v) for k, v in guardados.items() if k in CAMPOS})
        except (OSError, ValueError) as e:
            print(f"(No pude leer {ARCHIVO}: {e}. Uso los valores por defecto.)")
    return datos


def guardar(nuevos: dict) -> dict:
    datos = {k: str(nuevos.get(k, "")).strip()[:120] for k in CAMPOS}
    if not datos["ciudad"]:
        raise ValueError("La ciudad no puede quedar vacía.")
    if datos["zona_horaria"] not in available_timezones():
        raise ValueError(f"Zona horaria desconocida: {datos['zona_horaria']}")
    with _bloqueo:
        ARCHIVO.parent.mkdir(exist_ok=True)
        temporal = ARCHIVO.with_suffix(".tmp")
        temporal.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
        temporal.replace(ARCHIVO)
    return datos


def ubicacion(datos: dict | None = None) -> str:
    """'Montevideo, Montevideo, Uruguay' (sin partes vacías ni repetidas seguidas)."""
    datos = datos or leer()
    partes = []
    for p in (datos["ciudad"], datos["region"], datos["pais"]):
        if p and (not partes or partes[-1].lower() != p.lower()):
            partes.append(p)
    return ", ".join(partes)


def zona_horaria() -> ZoneInfo:
    return ZoneInfo(leer()["zona_horaria"])


def contexto() -> str:
    """Lo que el modelo necesita saber del hogar para buscar bien."""
    datos = leer()
    texto = f"El hogar está en {ubicacion(datos)} (zona horaria {datos['zona_horaria']})."
    if datos["moneda"]:
        texto += f" La moneda local es {datos['moneda']}."
    if datos["cotizaciones"]:
        texto += f" Si piden 'la cotización' sin aclarar, se refieren a: {datos['cotizaciones']}."
    return texto
