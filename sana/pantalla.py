"""Pantalla completa con la animación de Sana: se mueve cuando está activa y queda quieta cuando está en pausa.

Sana sirve una página local y abre el navegador en modo kiosco (Edge en Windows, Chromium en Linux). El estado
le llega a la página al instante por Server-Sent Events.
"""
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config

ESTATICOS = Path(__file__).parent / "static"
PAGINA = ESTATICOS / "pantalla.html"
TIPOS = {
    ".svg": "image/svg+xml", ".lottie": "application/zip", ".json": "application/json",
    ".js": "text/javascript", ".wasm": "application/wasm", ".woff2": "font/woff2",
}


class Pantalla:
    def __init__(self, puerto: int = 8001):
        self.puerto = puerto
        self._estado = "pausa"
        self._cambio = threading.Condition()
        self._navegador: subprocess.Popen | None = None
        pantalla = self

        class Manejador(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                animacion = config.ANIMACION
                extension = animacion.suffix.lower()
                ruta_pedida = self.path.split("?")[0]
                if ruta_pedida in ("/", "/index.html"):
                    self._archivo(PAGINA, "text/html; charset=utf-8")
                elif ruta_pedida == f"/animacion{extension}":
                    self._archivo(animacion, TIPOS.get(extension, "application/octet-stream"))
                elif ruta_pedida == "/animacion-info":
                    tipo = "svg" if extension == ".svg" else "lottie"
                    self._enviar(f'{{"tipo": "{tipo}", "url": "/animacion{extension}"}}'.encode(), "application/json")
                elif ruta_pedida.startswith(("/vendor/", "/fuentes/")) and ".." not in ruta_pedida:
                    ruta = ESTATICOS / ruta_pedida.lstrip("/")
                    self._archivo(ruta, TIPOS.get(ruta.suffix, "application/octet-stream"))
                elif ruta_pedida == "/estado":
                    self._eventos()
                else:
                    self.send_error(404)

            def _enviar(self, datos: bytes, tipo: str):
                self.send_response(200)
                self.send_header("Content-Type", tipo)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(datos)

            def _archivo(self, ruta: Path, tipo: str):
                try:
                    datos = ruta.read_bytes()
                except OSError:
                    self.send_error(404)
                    return
                self._enviar(datos, tipo)

            def _eventos(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                ultimo = None
                try:
                    while True:
                        with pantalla._cambio:
                            pantalla._cambio.wait_for(lambda: pantalla._estado != ultimo, timeout=15)
                            actual = pantalla._estado
                        # sin cambios en 15 s: un comentario para mantener viva la conexión
                        self.wfile.write(f"data: {actual}\n\n".encode() if actual != ultimo else b": ping\n\n")
                        self.wfile.flush()
                        ultimo = actual
                except OSError:
                    pass  # el navegador se cerró o recargó

        self._servidor = ThreadingHTTPServer(("127.0.0.1", puerto), Manejador)
        self._servidor.daemon_threads = True
        threading.Thread(target=self._servidor.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://localhost:{self.puerto}/"

    def estado(self, nombre: str) -> None:
        """pausa, escuchando, pensando o hablando."""
        with self._cambio:
            self._estado = nombre
            self._cambio.notify_all()

    def abrir(self) -> None:
        """Abre el navegador a pantalla completa, con un perfil propio para no mezclarse con tu navegador."""
        perfil = config.RAIZ / "datos" / "pantalla-navegador"
        if sys.platform == "win32":
            candidatos = [
                Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
                Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
                Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            ]
            ejecutable = next((str(c) for c in candidatos if c.exists()), None)
        else:
            ejecutable = next(
                (shutil.which(n) for n in ("chromium", "chromium-browser", "google-chrome", "microsoft-edge") if shutil.which(n)),
                None,
            )
        if not ejecutable:
            print(f"(No encontré Edge ni Chromium: abrí {self.url} a mano en pantalla completa.)", flush=True)
            return
        argumentos = [
            ejecutable, f"--user-data-dir={perfil}", "--kiosk", self.url, "--edge-kiosk-type=fullscreen",
            "--no-first-run", "--noerrdialogs", "--disable-infobars", "--disable-session-crashed-bubble",
            "--autoplay-policy=no-user-gesture-required",
        ]
        self._navegador = subprocess.Popen(argumentos, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def cerrar(self) -> None:
        if self._navegador and self._navegador.poll() is None:
            self._navegador.terminate()
        self._servidor.shutdown()
