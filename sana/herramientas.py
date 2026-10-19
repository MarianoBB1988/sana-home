"""Herramientas que el LLM puede usar. Cada una devuelve un texto que vuelve al modelo."""
import json
from datetime import datetime

from groq import Groq

from . import ajustes, clima, config, homeassistant as ha

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

# Lo que Sana dice mientras corre una herramienta lenta, para que la espera no sea en silencio.
AVISOS = {"buscar_en_internet": "Dejame fijarme."}


def obtener_hora() -> str:
    ahora = datetime.now(ajustes.zona_horaria())
    return f"{DIAS[ahora.weekday()]} {ahora:%d/%m/%Y}, {ahora:%H:%M}"


def buscar_en_internet(cliente: Groq, consulta: str) -> str:
    r = cliente.chat.completions.create(
        model=config.GROQ_MODELO_BUSQUEDA,
        messages=[
            {
                "role": "system",
                "content": "Buscá en internet y respondé en español con datos concretos y actuales, "
                "de fuentes de esa ubicación cuando se pueda (servicio meteorológico nacional, banco central, diarios locales). "
                f"{ajustes.contexto()} Fecha y hora local: {obtener_hora()}.",
            },
            {"role": "user", "content": consulta},
        ],
        tools=[{"type": "browser_search"}],
        tool_choice="required",
        reasoning_effort="low",
    )
    return r.choices[0].message.content or "No encontré nada."


def listar_dispositivos() -> str:
    return json.dumps(ha.dispositivos(), ensure_ascii=False)


def controlar_dispositivo(entity_id: str, accion: str) -> str:
    servicios = {"encender": "turn_on", "apagar": "turn_off", "alternar": "toggle"}
    ha.servicio("homeassistant", servicios[accion], {"entity_id": entity_id})
    return f"Listo: {accion} {entity_id}"


def controlar_aspiradora(entity_id: str, accion: str) -> str:
    servicios = {
        "limpiar": "start",
        "pausar": "pause",
        "detener": "stop",
        "volver_a_base": "return_to_base",
        "localizar": "locate",
    }
    ha.servicio("vacuum", servicios[accion], {"entity_id": entity_id})
    return f"Listo: aspiradora {accion}"


def controlar_musica(entity_id: str, accion: str, volumen: int | None = None) -> str:
    servicios = {
        "reproducir": "media_play",
        "pausar": "media_pause",
        "siguiente": "media_next_track",
        "anterior": "media_previous_track",
    }
    if accion == "volumen":
        if volumen is None:
            return "Falta indicar el volumen (0 a 100)."
        ha.servicio("media_player", "volume_set", {"entity_id": entity_id, "volume_level": volumen / 100})
    else:
        ha.servicio("media_player", servicios[accion], {"entity_id": entity_id})
    return f"Listo: música {accion}"


def _funcion(nombre: str, descripcion: str, propiedades: dict | None = None, requeridos: list | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": nombre,
            "description": descripcion,
            "parameters": {"type": "object", "properties": propiedades or {}, "required": requeridos or []},
        },
    }


_ENTITY = {"type": "string", "description": "entity_id de Home Assistant, sacado de listar_dispositivos"}


def definiciones() -> list[dict]:
    defs = [
        _funcion("obtener_hora", "Fecha, día y hora local actual."),
        _funcion(
            "clima_actual",
            "Clima de ahora y de hoy en el hogar: estado, temperatura, máxima, mínima, humedad, viento y probabilidad de lluvia. "
            "Usala para cualquier pregunta del clima de hoy en casa; para otras ciudades o días usá buscar_en_internet.",
        ),
        _funcion(
            "buscar_en_internet",
            "Busca información actual en internet: clima, noticias, cotizaciones, resultados deportivos, etc.",
            {
                "consulta": {
                    "type": "string",
                    "description": "Qué buscar, bien específico, incluyendo ciudad y país del hogar si es algo local (clima, cotización, noticias)",
                }
            },
            ["consulta"],
        ),
    ]
    if ha.disponible():
        defs += [
            _funcion("listar_dispositivos", "Lista los dispositivos de la casa con su entity_id y estado actual."),
            _funcion(
                "controlar_dispositivo",
                "Enciende, apaga o alterna una luz, relay, enchufe o ventilador.",
                {"entity_id": _ENTITY, "accion": {"type": "string", "enum": ["encender", "apagar", "alternar"]}},
                ["entity_id", "accion"],
            ),
            _funcion(
                "controlar_aspiradora",
                "Controla el robot aspiradora.",
                {
                    "entity_id": _ENTITY,
                    "accion": {
                        "type": "string",
                        "enum": ["limpiar", "pausar", "detener", "volver_a_base", "localizar"],
                    },
                },
                ["entity_id", "accion"],
            ),
            _funcion(
                "controlar_musica",
                "Controla la reproducción de música (Spotify u otro reproductor).",
                {
                    "entity_id": _ENTITY,
                    "accion": {
                        "type": "string",
                        "enum": ["reproducir", "pausar", "siguiente", "anterior", "volumen"],
                    },
                    "volumen": {"type": "integer", "description": "0 a 100, solo para accion=volumen"},
                },
                ["entity_id", "accion"],
            ),
        ]
    return defs


def ejecutar(cliente: Groq, nombre: str, argumentos: dict) -> str:
    funciones = {
        "obtener_hora": obtener_hora,
        "clima_actual": clima.resumen,
        "buscar_en_internet": lambda **a: buscar_en_internet(cliente, **a),
        "listar_dispositivos": listar_dispositivos,
        "controlar_dispositivo": controlar_dispositivo,
        "controlar_aspiradora": controlar_aspiradora,
        "controlar_musica": controlar_musica,
    }
    if nombre not in funciones:
        return f"No existe la herramienta {nombre}."
    # A veces el modelo manda parámetros de más o con nombre vacío: solo se pasan los que la herramienta declara
    definicion = next((d["function"] for d in definiciones() if d["function"]["name"] == nombre), None)
    validos = set(definicion["parameters"]["properties"]) if definicion else set()
    argumentos = {k: v for k, v in (argumentos or {}).items() if k in validos}
    try:
        return funciones[nombre](**argumentos)
    except Exception as e:
        return f"Error al ejecutar {nombre}: {e}"
