"""Sana: asistente de voz para el hogar.

    python main.py               modo voz: decís "Sana" y tu pedido (manos libres, en segundo plano)
    python main.py --pantalla    igual, con la animación de Sana a pantalla completa (se mueve cuando está activa)
    python main.py --enter       modo voz apretando Enter en lugar de decir "Sana"
    python main.py --texto       modo texto: escribís en la consola
    python main.py --web         interfaz web en http://IP-DE-ESTA-PC:8000
    python main.py --dispositivos  lista micrófonos y parlantes
"""
import argparse
import random
import sys
import threading
import time

from sana import config


def avisador(voz, hablar: bool = True):
    """Devuelve un callback que dice una frase de espera ("Dejame fijarme", "Aguardá un segundo"...), una sola vez
    por pregunta, cuando Sana usa una herramienta lenta."""
    from sana import herramientas

    avisado = threading.Event()

    def avisar(nombre: str) -> None:
        aviso = herramientas.aviso(nombre) if not avisado.is_set() else None
        if aviso:
            avisado.set()
            print(f"{config.NOMBRE}: {aviso}")
            if hablar:
                threading.Thread(target=voz.decir, args=(aviso,), daemon=True).start()

    return avisar


def modo_texto(cerebro, voz, hablar: bool) -> None:
    print(f"{config.NOMBRE} en modo texto. Escribí 'salir' para terminar.\n")
    while True:
        try:
            texto = input("Vos: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if texto.lower() in ("salir", "chau"):
            break
        if texto:
            respuesta = cerebro.responder(texto, avisador(voz, hablar))
            print(f"{config.NOMBRE}: {respuesta}\n")
            if hablar:
                voz.decir(respuesta)


SEGUIMIENTO = 5.0  # segundos en que se puede seguir hablando sin repetir la palabra clave

# Lo que dice Sana al llamarla, rotando. Se generan al arrancar para que suenen al instante.
SALUDOS = [
    "¿Sí? Decime.",
    "Te escucho.",
    "¿En qué te puedo ayudar?",
    "Acá estoy.",
    "¿Qué necesitás?",
    "Decime.",
    "¿Sí?",
]


class Saludos:
    def __init__(self, voz):
        self.voz = voz
        self.listos: list[str] = []
        self.ultimo = ""
        threading.Thread(target=self._preparar, daemon=True).start()

    def _preparar(self) -> None:
        from sana.herramientas import AVISOS

        for saludo in SALUDOS:
            try:
                if self.voz.preparar(saludo):
                    self.listos.append(saludo)
            except Exception:
                pass
        for frase in (f for lista in AVISOS.values() for f in lista):  # "Dejame fijarme", "Aguardá"...
            try:
                self.voz.preparar(frase)
            except Exception:
                pass

    def decir(self) -> None:
        """Un saludo distinto al anterior; si todavía no hay ninguno listo, el pitido."""
        opciones = [f for f in self.listos if f != self.ultimo] or self.listos
        if not opciones:
            self.voz.pitido()
            return
        self.ultimo = random.choice(opciones)
        print(f"{config.NOMBRE}: {self.ultimo}", flush=True)
        self.voz.decir(self.ultimo)


def _sin_pantalla(_estado: str) -> None:
    pass


def conversar(cerebro, voz, mic, marcar=_sin_pantalla) -> None:
    """Una charla: escucha el pedido, responde, y sigue escuchando un rato por si hay otra pregunta.
    marcar(estado) avisa a la pantalla: escuchando, pensando o hablando."""
    from sana import oido

    espera = oido.MAX_ESPERA
    ruidos = 0
    while True:
        marcar("escuchando")
        print(f"  Escuchando... ({espera:.0f} s)", flush=True)
        wav = oido.grabar_frase(mic, max_espera=espera)
        if not wav:
            return
        marcar("pensando")
        texto = oido.transcribir(cerebro.cliente, wav)
        if not texto:  # era ruido: una sola oportunidad más, para no quedar dando vueltas con un ruido constante
            ruidos += 1
            if ruidos > 1:
                return
            espera = SEGUIMIENTO
            continue
        ruidos = 0
        print(f"Vos: {texto}", flush=True)
        respuesta = cerebro.responder(texto, avisador(voz))
        print(f"{config.NOMBRE}: {respuesta}", flush=True)
        marcar("hablando")
        voz.decir(respuesta)
        time.sleep(0.3)
        mic.descartar()  # lo que el micrófono escuchó mientras Sana hablaba era ella misma
        espera = SEGUIMIENTO


def restaurar_musica(bajando: threading.Thread | None) -> None:
    """Devuelve la música a su volumen, esperando primero a que haya terminado de bajarla (si no, quedaría baja)."""
    from sana import spotify

    if bajando:
        bajando.join(timeout=10)
    spotify.atenuador.restaurar()


def modo_voz(cerebro, voz, con_enter: bool, pantalla=None) -> None:
    from sana import oido, spotify

    marcar = pantalla.estado if pantalla else _sin_pantalla

    palabra = None
    if not con_enter:
        if config.MODELO_VOSK.exists():
            palabra = oido.PalabraClave()
        else:
            print(f"(No encontré el modelo de Vosk en {config.MODELO_VOSK}: uso Enter en lugar de la palabra clave.)")

    saludos = Saludos(voz)
    bajando = None
    with oido.Microfono() as mic:
        if palabra:
            print(f'{config.NOMBRE} escuchando. Decí "{palabra.palabra.capitalize()}" y después tu pedido (Ctrl+C para salir).\n', flush=True)
        else:
            print(f"{config.NOMBRE} en modo voz. Apretá Enter y hablá (Ctrl+C para salir).\n")
        while True:
            try:
                marcar("pausa")
                if palabra:
                    print(f'En pausa. Decí "{palabra.palabra.capitalize()}" para hablar.', flush=True)
                    palabra.esperar(mic)
                else:
                    input("[Enter para hablar]")
                # La música baja mientras Sana escucha (en paralelo al saludo, para no demorarlo)
                bajando = threading.Thread(target=spotify.atenuador.bajar, daemon=True)
                bajando.start()
                marcar("hablando")
                saludos.decir()
                time.sleep(0.3)  # el parlante sigue sonando un instante después de terminar
                mic.descartar()  # que el saludo no se tome como el comienzo del pedido
                conversar(cerebro, voz, mic, marcar)
            except (EOFError, KeyboardInterrupt):
                restaurar_musica(bajando)
                break
            except Exception as e:  # un error en una charla (internet, Groq...) no apaga a Sana
                print(f"  (error: {e})", flush=True)
                try:
                    voz.decir("Perdón, tuve un problema. Probá de nuevo en un momento.")
                except Exception:
                    pass
            restaurar_musica(bajando)
            marcar("pausa")
            try:
                voz.sonido_apagado()  # "me quedo en pausa"
            except Exception as e:
                print(f"  (no pude reproducir el aviso: {e})", flush=True)
            mic.descartar()
            print(flush=True)


def probar_microfono(segundos: float = 8.0) -> None:
    """Medidor en vivo: muestra si el micrófono capta lo suficiente y qué entiende Vosk."""
    import json

    import numpy as np

    from sana import oido

    print(f'Durante {segundos:.0f} segundos: quedate en silencio un momento y después decí "Sana, ¿qué hora es?" '
          "como le hablarías normalmente, desde donde vas a estar.\n")
    niveles, bloques = [], []
    with oido.Microfono() as mic:
        for i in range(int(segundos * 10)):
            bloque = mic.leer()
            bloques.append(bloque)
            nivel = float(np.sqrt(np.mean(bloque.astype(np.float32) ** 2)))
            niveles.append(nivel)
            barra = "█" * min(50, int(nivel / 100))
            print(f"\r  nivel {nivel:6.0f} |{barra:<50}|", end="", flush=True)
    audio = np.concatenate(bloques)
    fondo, voz, pico = np.percentile(niveles, 10), np.percentile(niveles, 95), int(np.abs(audio).max())
    print(f"\n\n  ruido de fondo ~{fondo:.0f} · tu voz ~{voz:.0f} · pico {pico} de 32767")

    if config.MODELO_VOSK.exists():
        import vosk

        vosk.SetLogLevel(-1)
        rec = vosk.KaldiRecognizer(vosk.Model(str(config.MODELO_VOSK)), oido.FRECUENCIA)
        rec.AcceptWaveform(audio.tobytes())
        print(f"  Vosk entendió: {json.loads(rec.FinalResult())['text']!r}")

    if pico < 4000 or voz < fondo * 4:
        print("\n  ⚠ El micrófono capta muy bajo. Subilo en Windows: Configuración > Sistema > Sonido > tu micrófono >"
              " Volumen de entrada al 100 %. Si existe, activá también 'Aumento del micrófono' (Panel de control >"
              " Sonido > Grabar > Propiedades > Niveles). Después volvé a probar.")
    else:
        print("\n  ✓ El nivel del micrófono está bien.")


def main() -> None:
    p = argparse.ArgumentParser(description=f"{config.NOMBRE}, asistente de voz para el hogar")
    p.add_argument("--texto", action="store_true", help="conversar escribiendo")
    p.add_argument("--enter", action="store_true", help="modo voz con Enter en lugar de la palabra clave")
    p.add_argument("--pantalla", action="store_true", help="mostrar la animación de Sana a pantalla completa")
    p.add_argument("--mudo", action="store_true", help="en modo texto, no leer las respuestas en voz alta")
    p.add_argument("--web", action="store_true", help="servir la interfaz web en la red local")
    p.add_argument("--puerto", type=int, default=8000, help="puerto de la interfaz web (por defecto 8000)")
    p.add_argument("--https", action="store_true", help="con --web: HTTPS para poder usar el micrófono del celular")
    p.add_argument("--dispositivos", action="store_true", help="listar micrófonos y parlantes")
    p.add_argument("--probar-microfono", action="store_true", help="medir si el micrófono capta lo suficiente")
    p.add_argument("--conectar-spotify", action="store_true", help="autorizar a Sana a usar tu Spotify (una sola vez)")
    args = p.parse_args()

    if args.conectar_spotify:
        from sana import spotify

        if not spotify.configurado():
            sys.exit("Faltan SPOTIFY_CLIENT_ID y SPOTIFY_CLIENT_SECRET en el .env.")
        spotify.conectar()
        return

    if args.dispositivos:
        import sounddevice as sd

        print(sd.query_devices())
        return
    if args.probar_microfono:
        probar_microfono()
        return

    if not config.GROQ_API_KEY:
        sys.exit("Falta GROQ_API_KEY en el archivo .env (copiá .env.example como .env).")

    if args.web:
        import uvicorn

        from sana import certificado

        ip = certificado.ip_local()
        tls = {}
        if args.https:
            cert, clave = certificado.asegurar()
            tls = {"ssl_certfile": cert, "ssl_keyfile": clave}
        esquema = "https" if args.https else "http"
        print(f"\n  {config.NOMBRE} en el celular: {esquema}://{ip}:{args.puerto}/movil"
              f"\n  Panel completo:      {esquema}://{ip}:{args.puerto}/")
        if args.https:
            print("  (la primera vez el navegador avisa 'conexión no privada': tocá Avanzado > Continuar)")
        else:
            print("  (para usar el micrófono del celular, arrancá con --https)")
        print()
        uvicorn.run("sana.web:app", host="0.0.0.0", port=args.puerto, log_level="warning", **tls)
        return

    from sana.cerebro import Cerebro
    from sana.voz import Voz

    cerebro = Cerebro()
    voz = Voz()
    if args.texto:
        modo_texto(cerebro, voz, hablar=not args.mudo)
        return

    pantalla = None
    if args.pantalla:
        from sana.pantalla import Pantalla

        pantalla = Pantalla()
        pantalla.abrir()
    try:
        modo_voz(cerebro, voz, con_enter=args.enter, pantalla=pantalla)
    finally:
        if pantalla:
            pantalla.cerrar()


if __name__ == "__main__":
    main()
