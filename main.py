"""Sana: asistente de voz para el hogar.

    python main.py               modo voz: decís "Sana" y tu pedido (manos libres, en segundo plano)
    python main.py --enter       modo voz apretando Enter en lugar de decir "Sana"
    python main.py --texto       modo texto: escribís en la consola
    python main.py --web         interfaz web en http://IP-DE-ESTA-PC:8000
    python main.py --dispositivos  lista micrófonos y parlantes
"""
import argparse
import sys
import threading

from sana import config


def avisador(voz, hablar: bool = True):
    """Devuelve un callback que dice "Dejame fijarme." (una sola vez) cuando Sana usa una herramienta lenta."""
    from sana.herramientas import AVISOS

    avisado = threading.Event()

    def avisar(nombre: str) -> None:
        aviso = AVISOS.get(nombre)
        if aviso and not avisado.is_set():
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


def conversar(cerebro, voz, mic) -> None:
    """Una charla: escucha el pedido, responde, y sigue escuchando un rato por si hay otra pregunta."""
    from sana import oido

    espera = oido.MAX_ESPERA
    while True:
        print("  Escuchando...", flush=True)
        wav = oido.grabar_frase(mic, max_espera=espera)
        if not wav:
            print("  (fin de la charla)\n", flush=True)
            return
        texto = oido.transcribir(cerebro.cliente, wav)
        if not texto:
            print("  (no entendí nada)\n", flush=True)
            return
        print(f"Vos: {texto}", flush=True)
        respuesta = cerebro.responder(texto, avisador(voz))
        print(f"{config.NOMBRE}: {respuesta}", flush=True)
        voz.decir(respuesta)
        mic.descartar()  # lo que el micrófono escuchó mientras Sana hablaba era ella misma
        espera = SEGUIMIENTO


def modo_voz(cerebro, voz, con_enter: bool) -> None:
    from sana import oido

    palabra = None
    if not con_enter:
        if config.MODELO_VOSK.exists():
            palabra = oido.PalabraClave()
        else:
            print(f"(No encontré el modelo de Vosk en {config.MODELO_VOSK}: uso Enter en lugar de la palabra clave.)")

    with oido.Microfono() as mic:
        if palabra:
            print(f'{config.NOMBRE} escuchando. Decí "{palabra.palabra.capitalize()}" y después tu pedido (Ctrl+C para salir).\n', flush=True)
        else:
            print(f"{config.NOMBRE} en modo voz. Apretá Enter y hablá (Ctrl+C para salir).\n")
        while True:
            try:
                if palabra:
                    palabra.esperar(mic)
                    print(f'  ("{palabra.palabra}" detectado)', flush=True)
                else:
                    input("[Enter para hablar]")
                voz.pitido()
                mic.descartar()
                conversar(cerebro, voz, mic)
            except (EOFError, KeyboardInterrupt):
                break


def main() -> None:
    p = argparse.ArgumentParser(description=f"{config.NOMBRE}, asistente de voz para el hogar")
    p.add_argument("--texto", action="store_true", help="conversar escribiendo")
    p.add_argument("--enter", action="store_true", help="modo voz con Enter en lugar de la palabra clave")
    p.add_argument("--mudo", action="store_true", help="en modo texto, no leer las respuestas en voz alta")
    p.add_argument("--web", action="store_true", help="servir la interfaz web en la red local")
    p.add_argument("--puerto", type=int, default=8000, help="puerto de la interfaz web (por defecto 8000)")
    p.add_argument("--dispositivos", action="store_true", help="listar micrófonos y parlantes")
    args = p.parse_args()

    if args.dispositivos:
        import sounddevice as sd

        print(sd.query_devices())
        return

    if not config.GROQ_API_KEY:
        sys.exit("Falta GROQ_API_KEY en el archivo .env (copiá .env.example como .env).")

    if args.web:
        import socket

        import uvicorn

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
        except OSError:
            ip = "localhost"
        print(f"\n  {config.NOMBRE} Home: http://{ip}:{args.puerto}  (desde el celu o cualquier compu de la casa)\n")
        uvicorn.run("sana.web:app", host="0.0.0.0", port=args.puerto, log_level="warning")
        return

    from sana.cerebro import Cerebro
    from sana.voz import Voz

    cerebro = Cerebro()
    voz = Voz()
    if args.texto:
        modo_texto(cerebro, voz, hablar=not args.mudo)
    else:
        modo_voz(cerebro, voz, con_enter=args.enter)


if __name__ == "__main__":
    main()
