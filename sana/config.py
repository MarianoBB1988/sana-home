import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")


def _dispositivo(valor: str) -> int | str | None:
    """Convierte MICROFONO/PARLANTE en índice, nombre parcial o None (predeterminado)."""
    valor = valor.strip()
    if not valor:
        return None
    return int(valor) if valor.isdigit() else valor


def clave(nombre: str) -> str:
    """Una clave opcional del .env (por ejemplo de un servicio del clima)."""
    return os.getenv(nombre, "").strip()


GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODELO = os.getenv("GROQ_MODELO", "openai/gpt-oss-120b")
GROQ_MODELO_BUSQUEDA = os.getenv("GROQ_MODELO_BUSQUEDA", "openai/gpt-oss-20b")
GROQ_MODELO_STT = os.getenv("GROQ_MODELO_STT", "whisper-large-v3-turbo")

NOMBRE = os.getenv("NOMBRE", "Sana")
CIUDAD = os.getenv("CIUDAD", "Montevideo, Uruguay")
ZONA_HORARIA = os.getenv("ZONA_HORARIA", "America/Montevideo")

HA_URL = os.getenv("HA_URL", "").rstrip("/")
HA_TOKEN = os.getenv("HA_TOKEN", "")

MOTOR_VOZ = os.getenv("MOTOR_VOZ", "edge").strip().lower()  # "edge" (nube, Piper de respaldo) o "piper" (local)
VOZ_EDGE = os.getenv("VOZ_EDGE", "es-UY-ValentinaNeural")
VOZ_PIPER = RAIZ / os.getenv("VOZ_PIPER", "voces/es_ES-davefx-medium.onnx")
VOZ_HABLANTE = int(os.getenv("VOZ_HABLANTE") or 0)  # para voces con varios hablantes, como sharvard
PALABRA_CLAVE = os.getenv("PALABRA_CLAVE", "sana").strip().lower()
MODELO_VOSK = RAIZ / os.getenv("MODELO_VOSK", "voces/vosk-model-small-es-0.42")
MICROFONO = _dispositivo(os.getenv("MICROFONO", ""))
PARLANTE = _dispositivo(os.getenv("PARLANTE", ""))
SILENCIO_INICIAL = float(os.getenv("SILENCIO_INICIAL", "0.3"))
