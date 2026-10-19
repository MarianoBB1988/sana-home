"""Conversación con el LLM de Groq, con memoria corta y uso de herramientas."""
import json
import re
from collections.abc import Callable

from groq import Groq

from . import ajustes, config, herramientas, homeassistant as ha

MAX_MENSAJES = 20  # historial que se conserva (sin contar el prompt de sistema)
MAX_RONDAS_HERRAMIENTAS = 5


def _casa() -> str:
    """Los dispositivos van en el prompt: así Sana actúa en un solo paso, sin consultar la lista antes."""
    if not ha.disponible():
        return "Todavía no hay dispositivos conectados: si te piden controlar algo, explicá que falta configurar Home Assistant."
    try:
        lista = "; ".join(f"{d['nombre']} ({d['entity_id']}): {d['estado']}" for d in ha.dispositivos())
    except Exception:
        return ("Home Assistant no responde en este momento: si piden controlar algo de la casa, decí en una frase "
                "que ahora no te podés conectar con la casa, sin usar herramientas de la casa.")
    return (
        f"Dispositivos de la casa ahora (nombre, entity_id y estado): {lista or 'ninguno'}. "
        "Para prender o apagar usá directamente controlar_dispositivo con ese entity_id; "
        "si piden algo que no está en la lista, decilo."
    )


def _prompt_sistema() -> str:
    casa = _casa()
    return (
        f"Sos {config.NOMBRE}, un asistente de voz para el hogar. {ajustes.contexto()} "
        "Cuando pregunten por el clima, la cotización o noticias sin decir dónde, se refieren a esa ubicación. "
        "Hablás en español rioplatense, cálido y directo, siempre con frases completas y solo en español. "
        "Tus respuestas se leen en voz alta: sé breve (una a tres oraciones), sin markdown, listas, emojis ni URLs. "
        "Escribí los números y unidades como se dicen. "
        "Para el clima de hoy en casa usá clima_actual. Para noticias, cotizaciones o cualquier otro dato actual usá "
        "buscar_en_internet; nunca inventes datos. "
        f"{casa}"
    )


class Cerebro:
    def __init__(self):
        self.cliente = Groq(api_key=config.GROQ_API_KEY)
        self.historial: list[dict] = []

    def responder(self, texto: str, al_usar_herramienta: Callable[[str], None] | None = None) -> str:
        """al_usar_herramienta(nombre) se llama antes de cada herramienta: sirve para avisar "dejame fijarme"."""
        self.historial.append({"role": "user", "content": texto})
        mensajes = [{"role": "system", "content": _prompt_sistema()}] + self.historial[-MAX_MENSAJES:]

        for _ in range(MAX_RONDAS_HERRAMIENTAS):
            r = self.cliente.chat.completions.create(
                model=config.GROQ_MODELO,
                messages=mensajes,
                tools=herramientas.definiciones(),
                reasoning_effort="low",
            )
            msg = r.choices[0].message
            if not msg.tool_calls:
                respuesta = (msg.content or "").strip()
                if not respuesta:  # a veces el modelo devuelve vacío: se le pide que conteste
                    mensajes.append({"role": "user", "content": "Respondé la pregunta anterior en una o dos oraciones."})
                    continue
                # "…por ciento.¿Te ayudo…" -> con espacio, así la voz hace la pausa entre oraciones
                respuesta = re.sub(r"([.!?])(?=[¿¡A-ZÁÉÍÓÚÑ])", r"\1 ", respuesta)
                self.historial.append({"role": "assistant", "content": respuesta})
                return respuesta

            mensajes.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {"id": t.id, "type": "function", "function": {"name": t.function.name, "arguments": t.function.arguments}}
                        for t in msg.tool_calls
                    ],
                }
            )
            for t in msg.tool_calls:
                args = json.loads(t.function.arguments or "{}")
                print(f"  [herramienta] {t.function.name} {args}")
                if al_usar_herramienta:
                    al_usar_herramienta(t.function.name)
                resultado = herramientas.ejecutar(self.cliente, t.function.name, args)
                mensajes.append({"role": "tool", "tool_call_id": t.id, "content": resultado})

        return "Perdón, me trabé intentando resolver eso."
