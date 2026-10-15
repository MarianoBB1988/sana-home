"""Conversación con el LLM de Groq, con memoria corta y uso de herramientas."""
import json
from collections.abc import Callable

from groq import Groq

from . import ajustes, config, herramientas, homeassistant as ha

MAX_MENSAJES = 20  # historial que se conserva (sin contar el prompt de sistema)
MAX_RONDAS_HERRAMIENTAS = 5


def _prompt_sistema() -> str:
    casa = (
        "Podés controlar la casa con las herramientas. Si no sabés el entity_id de algo, usá listar_dispositivos primero."
        if ha.disponible()
        else "Todavía no hay dispositivos conectados: si te piden controlar algo, explicá que falta configurar Home Assistant."
    )
    return (
        f"Sos {config.NOMBRE}, un asistente de voz para el hogar. {ajustes.contexto()} "
        "Cuando pregunten por el clima, la cotización o noticias sin decir dónde, se refieren a esa ubicación. "
        "Hablás en español rioplatense, cálido y directo. "
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
                respuesta = msg.content or ""
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
