"""Sana: asistente de voz para el hogar.

    python main.py               modo voz: Enter para hablar
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


def modo_voz(cerebro, voz) -> None:
    from sana import oido

    print(f"{config.NOMBRE} en modo voz. Apretá Enter y hablá (Ctrl+C para salir).\n")
    while True:
        try:
            input("[Enter para hablar]")
        except (EOFError, KeyboardInterrupt):
            break
        print("  Escuchando...")
        wav = oido.grabar_frase()
        if not wav:
            print("  (no escuché nada)")
            continue
        texto = oido.transcribir(cerebro.cliente, wav)
        print(f"Vos: {texto}")
        if not texto:
            continue
        respuesta = cerebro.responder(texto, avisador(voz))
        print(f"{config.NOMBRE}: {respuesta}\n")
        voz.decir(respuesta)


def main() -> None:
    p = argparse.ArgumentParser(description=f"{config.NOMBRE}, asistente de voz para el hogar")
    p.add_argument("--texto", action="store_true", help="conversar escribiendo")
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
        modo_voz(cerebro, voz)


if __name__ == "__main__":
    main()
