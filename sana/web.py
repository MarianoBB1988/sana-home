"""Interfaz web de Sana: chat y panel de dispositivos, accesible desde la red de la casa."""
import json
import queue
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from groq import Groq
from pydantic import BaseModel

from . import ajustes, clima, config, herramientas, homeassistant as ha, oido
from .cerebro import Cerebro
from .voz import Voz

ESTATICOS = Path(__file__).parent / "static"

# Botones del panel: acción -> (dominio, servicio) de Home Assistant.
ACCIONES = {
    "alternar": ("homeassistant", "toggle"),
    "limpiar": ("vacuum", "start"),
    "pausar_aspiradora": ("vacuum", "pause"),
    "volver_a_base": ("vacuum", "return_to_base"),
    "play_pausa": ("media_player", "media_play_pause"),
    "siguiente": ("media_player", "media_next_track"),
}

app = FastAPI(title=config.NOMBRE)
groq = Groq(api_key=config.GROQ_API_KEY)
voz = Voz()
# Los avisos ("Dejame fijarme", "Aguardá"...) se preparan desde el arranque, así suenan al instante.
threading.Thread(
    target=lambda: [voz.preparar(f) for lista in herramientas.AVISOS.values() for f in lista], daemon=True
).start()
conversaciones: dict[str, Cerebro] = {}  # una por navegador


class Mensaje(BaseModel):
    sesion: str
    texto: str
    voz_en_casa: bool = False  # leer la respuesta en el parlante del mini PC


class Texto(BaseModel):
    texto: str


class Accion(BaseModel):
    entity_id: str
    accion: str


def _cerebro(sesion: str) -> Cerebro:
    if sesion not in conversaciones:
        conversaciones[sesion] = Cerebro()
    return conversaciones[sesion]


@app.get("/api/estado")
def estado():
    return {"nombre": config.NOMBRE, "home_assistant": ha.disponible(), "voz": voz.disponible}


def _decir_en_casa(texto: str) -> None:
    threading.Thread(target=voz.decir, args=(texto,), daemon=True).start()


@app.post("/api/chat")
def chat(m: Mensaje):
    """Responde en líneas JSON: un "aviso" si va a tardar (búsqueda en internet) y después la "respuesta"."""
    eventos: queue.Queue = queue.Queue()

    def al_usar_herramienta(nombre: str) -> None:
        aviso = herramientas.aviso(nombre) if not avisado.is_set() else None
        if aviso:
            avisado.set()
            eventos.put({"tipo": "aviso", "texto": aviso})
            if m.voz_en_casa:
                _decir_en_casa(aviso)

    def pensar() -> None:
        try:
            respuesta = _cerebro(m.sesion).responder(m.texto, al_usar_herramienta)
            eventos.put({"tipo": "respuesta", "texto": respuesta})
            if m.voz_en_casa:
                _decir_en_casa(respuesta)
        except Exception as e:
            eventos.put({"tipo": "error", "texto": f"Falló la consulta a Groq ({type(e).__name__}). Revisá la clave y la conexión."})

    def lineas():
        while True:
            evento = eventos.get()
            yield json.dumps(evento, ensure_ascii=False) + "\n"
            if evento["tipo"] != "aviso":
                return

    avisado = threading.Event()
    threading.Thread(target=pensar, daemon=True).start()
    return StreamingResponse(lineas(), media_type="application/x-ndjson")


@app.post("/api/nueva")
def nueva(m: Mensaje):
    conversaciones.pop(m.sesion, None)
    return {"ok": True}


@app.post("/api/voz")
def sintetizar(t: Texto):
    resultado = voz.audio(t.texto)
    if resultado is None:
        raise HTTPException(503, "No hay voz disponible")
    datos, tipo = resultado
    return Response(datos, media_type=tipo)


@app.post("/api/transcribir")
async def transcribir(audio: UploadFile):
    datos = await audio.read()
    return {"texto": oido.transcribir(groq, datos, audio.filename or "audio.webm")}


@app.get("/api/ajustes")
def leer_ajustes():
    return ajustes.leer()


@app.put("/api/ajustes")
def guardar_ajustes(datos: dict):
    try:
        clima.validar(datos)
        return ajustes.guardar(datos)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/clima")
def clima_actual():
    try:
        return clima.actual()
    except Exception as e:
        raise HTTPException(502, f"No pude obtener el clima: {e}")


@app.get("/api/clima/fuentes")
def clima_fuentes():
    return clima.fuentes()


@app.get("/api/clima/comparar")
def clima_comparar():
    try:
        return clima.comparar()
    except Exception as e:
        raise HTTPException(502, f"No pude comparar las fuentes: {e}")


@app.get("/api/dispositivos")
def dispositivos():
    if not ha.disponible():
        return {"configurado": False, "dispositivos": []}
    try:
        return {"configurado": True, "dispositivos": ha.dispositivos()}
    except Exception as e:
        raise HTTPException(502, f"No pude hablar con Home Assistant: {e}")


@app.post("/api/dispositivos/accion")
def accion(a: Accion):
    if a.accion not in ACCIONES:
        raise HTTPException(400, "Acción desconocida")
    dominio, servicio = ACCIONES[a.accion]
    try:
        ha.servicio(dominio, servicio, {"entity_id": a.entity_id})
    except Exception as e:
        raise HTTPException(502, f"No pude hablar con Home Assistant: {e}")
    return {"ok": True}


@app.get("/")
def inicio():
    return FileResponse(ESTATICOS / "index.html")


@app.get("/movil")
def movil():
    """Sana para el celular: la esfera animada; se toca para hablar (instalable en la pantalla de inicio)."""
    return FileResponse(ESTATICOS / "movil.html")


@app.get("/animacion-info")
def animacion_info():
    extension = config.ANIMACION.suffix.lower()
    return {"tipo": "svg" if extension == ".svg" else "lottie", "url": f"/animacion{extension}"}


@app.get("/animacion{extension}")
def animacion(extension: str):
    if extension.lower() != config.ANIMACION.suffix.lower() or not config.ANIMACION.exists():
        raise HTTPException(404)
    tipos = {".svg": "image/svg+xml", ".lottie": "application/zip", ".json": "application/json"}
    return FileResponse(config.ANIMACION, media_type=tipos.get(extension.lower(), "application/octet-stream"))


app.mount("/", StaticFiles(directory=ESTATICOS), name="estaticos")
