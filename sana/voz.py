"""Texto a voz: Edge TTS (voz uruguaya, en la nube) con Piper (local) de respaldo."""
import asyncio
import io
import queue
import re
import threading
import wave
from functools import lru_cache

import numpy as np
import sounddevice as sd

from . import config


def frases(texto: str) -> list[str]:
    return [f for f in re.split(r"(?<=[.!?…:;])\s+", texto.strip()) if f]


class Voz:
    def __init__(self):
        self.piper = None
        self.ajustes = None
        self._parlante = threading.Lock()  # una sola respuesta a la vez en el parlante
        self._piper_listo = threading.Event()
        if config.VOZ_PIPER.exists():
            # Con Edge, Piper es solo respaldo: se carga en segundo plano para no demorar el arranque.
            if config.MOTOR_VOZ == "edge":
                threading.Thread(target=self._cargar_piper, daemon=True).start()
            else:
                self._cargar_piper()
        else:
            self._piper_listo.set()
            if config.MOTOR_VOZ != "edge":
                print(f"(Sin voz: no existe {config.VOZ_PIPER}. Solo se mostrará texto.)")

    @property
    def disponible(self) -> bool:
        return config.MOTOR_VOZ == "edge" or self.piper is not None

    def _cargar_piper(self) -> None:
        from piper import PiperVoice, SynthesisConfig

        piper = PiperVoice.load(config.VOZ_PIPER)
        varios = piper.config.num_speakers > 1
        self.ajustes = SynthesisConfig(speaker_id=config.VOZ_HABLANTE if varios else None)
        # La primera síntesis es bastante más lenta: la hacemos ahora y no en la primera respuesta.
        list(piper.synthesize("Hola.", syn_config=self.ajustes))
        self.piper = piper
        self._piper_listo.set()

    # --- Motores ---

    def _edge(self, texto: str) -> bytes:
        import edge_tts

        async def sintetizar() -> bytes:
            datos = bytearray()
            async for parte in edge_tts.Communicate(texto, config.VOZ_EDGE).stream():
                if parte["type"] == "audio":
                    datos += parte["data"]
            return bytes(datos)

        datos = asyncio.run(sintetizar())
        if not datos:
            raise RuntimeError("Edge TTS no devolvió audio")
        return datos

    def _piper_wav(self, texto: str) -> bytes | None:
        self._piper_listo.wait(timeout=30)
        if not self.piper:
            return None
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            self.piper.synthesize_wav(texto, w, syn_config=self.ajustes)
        return buf.getvalue()

    @lru_cache(maxsize=32)  # frases repetidas ("Dejame fijarme…") salen al instante
    def audio(self, texto: str) -> tuple[bytes, str] | None:
        """La frase como archivo de audio: (datos, tipo MIME). Para el navegador y el parlante."""
        if not texto:
            return None
        if config.MOTOR_VOZ == "edge":
            try:
                return self._edge(texto), "audio/mpeg"
            except Exception as e:
                print(f"(Edge TTS falló, uso Piper: {e})")
        datos = self._piper_wav(texto)
        return (datos, "audio/wav") if datos else None

    # --- Parlante de la casa ---

    def sonido_apagado(self) -> None:
        """Notificación de "me pongo en pausa": tres notas descendentes suaves que se apagan."""
        frecuencia = 24000
        notas = (659.3, 523.3, 392.0)  # mi, do, sol
        duracion = 0.22
        t = np.arange(int(frecuencia * duracion)) / frecuencia
        envolvente = np.exp(-t * 9) * np.minimum(1, t * 400)  # ataque corto y caída como una campanita
        partes = [
            (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(4 * np.pi * f * t)) * envolvente * 0.2 for f in notas
        ]
        audio = (np.concatenate(partes + [np.zeros(int(frecuencia * 0.1))]) * 32767).astype(np.int16)
        with self._parlante:
            sd.play(audio, frecuencia, device=config.PARLANTE)
            sd.wait()

    def pitido(self, subiendo: bool = True) -> None:
        """Dos tonos cortos: subiendo es "te escucho"; bajando, "me quedo en pausa"."""
        frecuencia = 24000
        partes = []
        for nota in (880, 1320) if subiendo else (1100, 740):
            t = np.arange(int(frecuencia * 0.08)) / frecuencia
            envolvente = np.minimum(1, np.minimum(t, t[::-1]) * 200)  # sin chasquidos al empezar y terminar
            partes.append(np.sin(2 * np.pi * nota * t) * envolvente * 0.25)
        audio = (np.concatenate(partes) * 32767).astype(np.int16)
        with self._parlante:
            sd.play(audio, frecuencia, device=config.PARLANTE)
            sd.wait()

    def decir(self, texto: str) -> None:
        """Reproduce en el parlante de la casa. Genera la frase siguiente mientras suena la actual."""
        import soundfile as sf

        cola: queue.Queue = queue.Queue(maxsize=2)

        def producir():
            for f in frases(texto):
                resultado = self.audio(f)
                if resultado:
                    cola.put(sf.read(io.BytesIO(resultado[0]), dtype="int16"))
            cola.put(None)

        threading.Thread(target=producir, daemon=True).start()
        with self._parlante:
            salida = None
            try:
                while (item := cola.get()) is not None:
                    audio, frecuencia = item
                    if salida is None or salida.samplerate != frecuencia:
                        if salida:
                            salida.close()
                        salida = sd.OutputStream(samplerate=frecuencia, channels=1, dtype="int16", device=config.PARLANTE)
                        salida.start()
                        salida.write(np.zeros(int(frecuencia * config.SILENCIO_INICIAL), dtype=np.int16))
                    salida.write(audio)
            finally:
                if salida:
                    salida.stop()
                    salida.close()
