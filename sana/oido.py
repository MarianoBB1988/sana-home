"""Micrófono siempre abierto: espera la palabra de activación (local, con Vosk), graba el pedido hasta un
silencio y lo transcribe con Whisper en Groq. Lo que se habla antes de "Sana" nunca sale del equipo."""
import io
import json
import queue
import re
import wave
from collections import deque

import numpy as np
import sounddevice as sd
from groq import Groq

from . import config

FRECUENCIA = 16000
BLOQUE = 1600  # 100 ms
SILENCIO_FINAL = 0.9  # segundos de silencio que cierran la frase
MAX_ESPERA = 6.0  # segundos esperando que empiece a hablar
MAX_FRASE = 20.0
PREVIO = 3  # bloques de antes de detectar la voz que se agregan al inicio (para no cortar la primera sílaba)
INICIO_VOZ = 2  # bloques seguidos con sonido para considerar que empezó a hablar (un golpe o un pitido no alcanzan)
ULTIMA_FRASE = config.RAIZ / "datos" / "ultima_frase.wav"  # el último audio enviado a Whisper, para diagnosticar
# Palabras de uso diario parecidas a "sana" que no tienen que activarla aunque se digan solas
PALABRAS_COMUNES = {"sala", "sara", "saga", "sapa", "rana", "lana", "cana", "mana", "nana", "gana", "pana", "sama"}
CONFIANZA_MINIMA = -0.45  # avg_logprob de Whisper: por debajo es ruido que Whisper "transcribió" igual

# Frases que Whisper inventa cuando solo hay ruido
ALUCINACIONES = re.compile(
    r"^(gracias( por ver( el video)?)?|subt[ií]tulos.*|amara\.org.*|suscr[ií]bete.*|\.+|…"
    r"|[\[(]?(m[uú]sica|aplausos|risas|silencio|ruido)[\])]?)$",
    re.I,
)


def _rms(bloque: np.ndarray) -> float:
    return float(np.sqrt(np.mean(bloque.astype(np.float32) ** 2)))


class Microfono:
    """Stream continuo en bloques de 100 ms. Se usa con `with Microfono() as mic:`."""

    def __init__(self, dispositivo=None):
        self._cola: queue.Queue = queue.Queue()
        self._stream = sd.InputStream(
            samplerate=FRECUENCIA, channels=1, dtype="int16", blocksize=BLOQUE,
            device=dispositivo if dispositivo is not None else config.MICROFONO,
            callback=lambda datos, *_: self._cola.put(datos[:, 0].copy()),
        )
        self.ruido = 150.0  # nivel del ruido ambiente, se ajusta solo mientras espera

    def __enter__(self):
        self._stream.start()
        return self

    def __exit__(self, *_):
        self._stream.stop()
        self._stream.close()

    def leer(self) -> np.ndarray:
        return self._cola.get()

    def descartar(self) -> None:
        """Tira lo acumulado (por ejemplo lo que se escuchó mientras Sana hablaba)."""
        while not self._cola.empty():
            self._cola.get_nowait()

    def actualizar_ruido(self, bloque: np.ndarray) -> None:
        """Aprende el ruido de fondo solo con bloques tranquilos: si contara la voz (por ejemplo al decir
        "Hola Sana"), el umbral subiría y después no detectaría el pedido."""
        nivel = _rms(bloque)
        if nivel < self.ruido * 2:
            self.ruido = 0.95 * self.ruido + 0.05 * nivel


class PalabraClave:
    """Detecta la palabra de activación con un modelo de Vosk que corre en el equipo.

    Usa el vocabulario completo (y no una gramática cerrada "sana o nada", que se activa con cualquier frase):
    en las pruebas no tuvo falsos positivos con "banana", "campana", "Santiago", "semana", etc.
    """

    def __init__(self, palabra: str = "", modelo=None):
        import vosk

        vosk.SetLogLevel(-1)
        self.palabra = (palabra or config.PALABRA_CLAVE).lower()
        self.modelo = vosk.Model(str(modelo or config.MODELO_VOSK))
        p = re.escape(self.palabra)
        # Dicho de corrido, "Sana prendé…" se oye "san aprende…": por eso también vale "san a…" al empezar la frase
        corrido = rf"|^{re.escape(self.palabra[:-1])} {re.escape(self.palabra[-1])}" if len(self.palabra) > 3 else ""
        self._patron = re.compile(rf"\b{p}\b{corrido}")
        self._vosk = vosk

    def _parecida(self, texto: str) -> bool:
        """Una frase cortita (1 o 2 palabras) con una palabra a una letra de distancia: "ana", "sano", "zana"...
        Así no hace falta repetir "Sana" si Vosk la entendió mal, sin activarse con frases normales."""
        palabras = texto.split()
        return 0 < len(palabras) <= 2 and any(
            len(p) >= 3 and p not in PALABRAS_COMUNES and _distancia(p, self.palabra) <= 1 for p in palabras
        )

    def esperar(self, mic: Microfono) -> None:
        reconocedor = self._vosk.KaldiRecognizer(self.modelo, FRECUENCIA)
        while True:
            bloque = mic.leer()
            mic.actualizar_ruido(bloque)
            if reconocedor.AcceptWaveform(bloque.tobytes()):
                texto = json.loads(reconocedor.Result()).get("text", "")
                if self._patron.search(texto) or self._parecida(texto):
                    return
                if texto:
                    print(f"  (oí: {texto!r})", flush=True)
            elif self._patron.search(json.loads(reconocedor.PartialResult()).get("partial", "")):
                return


def _distancia(a: str, b: str) -> int:
    """Cantidad mínima de letras a cambiar, agregar o sacar para pasar de a a b (Levenshtein)."""
    previa = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        actual = [i]
        for j, cb in enumerate(b, 1):
            actual.append(min(previa[j] + 1, actual[j - 1] + 1, previa[j - 1] + (ca != cb)))
        previa = actual
    return previa[-1]


def grabar_frase(mic: Microfono, max_espera: float = MAX_ESPERA) -> bytes | None:
    """Graba desde que se detecta voz hasta un silencio. Devuelve un WAV, o None si nadie habló."""
    umbral = max(mic.ruido * 3, 300)
    previos: deque = deque(maxlen=PREVIO + INICIO_VOZ)
    bloques, hablando, silencio, t, seguidos = [], False, 0.0, 0.0, 0
    while True:
        bloque = mic.leer()
        t += 0.1
        fuerte = _rms(bloque) > umbral
        if not hablando:
            previos.append(bloque)
            seguidos = seguidos + 1 if fuerte else 0
            if seguidos >= INICIO_VOZ:
                hablando = True
                bloques = list(previos)
            elif t > max_espera:
                return None
            continue
        bloques.append(bloque)
        silencio = 0.0 if fuerte else silencio + 0.1
        if silencio >= SILENCIO_FINAL or len(bloques) * 0.1 >= MAX_FRASE:
            break

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(FRECUENCIA)
        w.writeframes(np.concatenate(bloques).tobytes())
    try:
        ULTIMA_FRASE.parent.mkdir(exist_ok=True)
        ULTIMA_FRASE.write_bytes(buf.getvalue())
    except OSError:
        pass
    return buf.getvalue()


def transcribir(cliente: Groq, audio: bytes, nombre_archivo: str = "frase.wav") -> str:
    """Pasa audio a texto. Whisper acepta wav, webm, ogg, mp3, m4a, etc. (lo deduce de la extensión)."""
    r = cliente.audio.transcriptions.create(
        file=(nombre_archivo, audio),
        model=config.GROQ_MODELO_STT,
        language="es",
        response_format="verbose_json",
    )
    texto = r.text.strip()
    # Con ruido (ventilador, pitidos, golpes) Whisper inventa palabras con poca confianza (~-0.55 o menos);
    # con voz real, aun bajita, da ~-0.2/-0.3
    confianzas = [s["avg_logprob"] for s in (r.segments or []) if "avg_logprob" in s]
    confianza = sum(confianzas) / len(confianzas) if confianzas else 0.0
    if not texto or ALUCINACIONES.match(texto.strip(" .!¡¿?")) or confianza < CONFIANZA_MINIMA:
        print(f"  (solo ruido: Whisper oyó {texto!r} con confianza {confianza:.2f})", flush=True)
        return ""
    return texto
