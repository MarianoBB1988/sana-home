"""Captura de audio del micrófono y transcripción con Whisper en Groq."""
import io
import wave

import numpy as np
import sounddevice as sd
from groq import Groq

from . import config

FRECUENCIA = 16000
BLOQUE = 1600  # 100 ms
SILENCIO_FINAL = 1.2  # segundos de silencio que cierran la frase
MAX_ESPERA = 8.0  # segundos esperando que empiece a hablar
MAX_FRASE = 20.0


def _rms(bloque: np.ndarray) -> float:
    return float(np.sqrt(np.mean(bloque.astype(np.float32) ** 2)))


def grabar_frase() -> bytes | None:
    """Graba desde que se detecta voz hasta un silencio. Devuelve un WAV, o None si nadie habló."""
    with sd.InputStream(samplerate=FRECUENCIA, channels=1, dtype="int16", device=config.MICROFONO, blocksize=BLOQUE) as s:
        # Medir el ruido ambiente durante medio segundo para fijar el umbral.
        ruido = np.mean([_rms(s.read(BLOQUE)[0]) for _ in range(5)])
        umbral = max(ruido * 3, 300)

        bloques, hablando, silencio, t = [], False, 0.0, 0.0
        while True:
            bloque = s.read(BLOQUE)[0]
            t += 0.1
            fuerte = _rms(bloque) > umbral
            if not hablando:
                if fuerte:
                    hablando = True
                    bloques.append(bloque)
                elif t > MAX_ESPERA:
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
    return buf.getvalue()


def transcribir(cliente: Groq, audio: bytes, nombre_archivo: str = "frase.wav") -> str:
    """Pasa audio a texto. Whisper acepta wav, webm, ogg, mp3, m4a, etc. (lo deduce de la extensión)."""
    r = cliente.audio.transcriptions.create(
        file=(nombre_archivo, audio),
        model=config.GROQ_MODELO_STT,
        language="es",
    )
    return r.text.strip()
