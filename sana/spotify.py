"""Spotify con la API oficial: buscar y poner música por nombre y controlar la reproducción.

Spotify reproduce en un "dispositivo Spotify Connect": la app abierta en la compu o el celular, o el mini PC
con raspotify/spotifyd. La primera vez hay que autorizar a Sana: python main.py --conectar-spotify
"""
from functools import lru_cache

from . import config

PERMISOS = "user-read-playback-state user-modify-playback-state user-read-currently-playing"
TOKEN = config.RAIZ / "datos" / "spotify_token.json"
TIPOS = {"artista": "artist", "cancion": "track", "album": "album", "playlist": "playlist"}


def configurado() -> bool:
    return bool(config.clave("SPOTIFY_CLIENT_ID") and config.clave("SPOTIFY_CLIENT_SECRET"))


def autorizado() -> bool:
    return configurado() and TOKEN.exists()


def _oauth(abrir_navegador: bool = False):
    from spotipy.cache_handler import CacheFileHandler
    from spotipy.oauth2 import SpotifyOAuth

    TOKEN.parent.mkdir(exist_ok=True)
    return SpotifyOAuth(
        client_id=config.clave("SPOTIFY_CLIENT_ID"),
        client_secret=config.clave("SPOTIFY_CLIENT_SECRET"),
        redirect_uri=config.clave("SPOTIFY_REDIRECT_URI") or "http://127.0.0.1:8888/callback",
        scope=PERMISOS,
        cache_handler=CacheFileHandler(cache_path=str(TOKEN)),
        open_browser=abrir_navegador,
    )


@lru_cache(maxsize=1)
def _cliente():
    import spotipy

    return spotipy.Spotify(auth_manager=_oauth(), requests_timeout=8, retries=1)


def conectar() -> None:
    """Autorización inicial: abre el navegador, el usuario acepta y el token queda guardado en datos/."""
    oauth = _oauth(abrir_navegador=True)
    oauth.get_access_token(as_dict=False)
    print("Spotify conectado. Dispositivos disponibles ahora:")
    for d in _cliente().devices()["devices"]:
        print(f"  - {d['name']} ({d['type']}){' · activo' if d['is_active'] else ''}")


def _dispositivo() -> dict:
    """El dispositivo donde poner música: el que esté sonando, el preferido del .env, o el primero que haya."""
    dispositivos = _cliente().devices()["devices"]
    if not dispositivos:
        raise LookupError("No hay ningún dispositivo de Spotify disponible: abrí Spotify en la compu o el celular")
    preferido = config.clave("SPOTIFY_DISPOSITIVO").lower()
    return (
        next((d for d in dispositivos if d["is_active"]), None)
        or next((d for d in dispositivos if preferido and preferido in d["name"].lower()), None)
        or dispositivos[0]
    )


def poner(busqueda: str, tipo: str = "cualquiera") -> str:
    sp = _cliente()
    tipos = [TIPOS[tipo]] if tipo in TIPOS else ["artist", "track", "playlist", "album"]
    resultados = sp.search(q=busqueda, type=",".join(tipos), limit=5)
    # La API a veces devuelve elementos vacíos (playlists borradas o privadas): se descartan
    encontrados = {t: [x for x in resultados.get(f"{t}s", {}).get("items", []) if x] for t in tipos}

    elegido, clase = None, None
    for t in tipos:  # en el orden pedido; con "cualquiera", prioriza artista > canción > playlist > álbum
        if encontrados[t]:
            elegido, clase = encontrados[t][0], t
            break
    if not elegido:
        return f"No encontré nada en Spotify para '{busqueda}'."

    dispositivo = _dispositivo()
    if clase == "track":
        sp.start_playback(device_id=dispositivo["id"], uris=[elegido["uri"]])
        detalle = f"la canción {elegido['name']} de {elegido['artists'][0]['name']}"
    else:
        sp.start_playback(device_id=dispositivo["id"], context_uri=elegido["uri"])
        nombres = {"artist": "el artista", "playlist": "la playlist", "album": "el álbum"}
        detalle = f"{nombres[clase]} {elegido['name']}"
        if clase == "album":
            detalle += f" de {elegido['artists'][0]['name']}"
    return f"Sonando {detalle} en {dispositivo['name']}."


def controlar(accion: str, volumen: int | None = None) -> str:
    sp = _cliente()
    dispositivo = _dispositivo()
    id_ = dispositivo["id"]
    if accion == "pausar":
        sp.pause_playback(device_id=id_)
    elif accion == "reanudar":
        sp.start_playback(device_id=id_)
    elif accion == "siguiente":
        sp.next_track(device_id=id_)
    elif accion == "anterior":
        sp.previous_track(device_id=id_)
    elif accion == "aleatorio":
        sp.shuffle(True, device_id=id_)
    elif accion in ("volumen", "subir_volumen", "bajar_volumen"):
        actual = dispositivo.get("volume_percent") or 50
        if accion == "subir_volumen":
            volumen = min(100, actual + 15)
        elif accion == "bajar_volumen":
            volumen = max(0, actual - 15)
        if volumen is None:
            return "Falta indicar el volumen (0 a 100)."
        sp.volume(max(0, min(100, int(volumen))), device_id=id_)
        return f"Volumen de Spotify en {volumen}."
    else:
        return f"Acción desconocida: {accion}"
    return f"Listo: {accion.replace('_', ' ')} en {dispositivo['name']}."


def que_suena() -> str:
    actual = _cliente().current_playback()
    if not actual or not actual.get("item"):
        return "No está sonando nada en Spotify."
    tema = actual["item"]
    artistas = ", ".join(a["name"] for a in tema.get("artists", []))
    estado = "sonando" if actual.get("is_playing") else "en pausa"
    return f"{tema['name']} de {artistas}, {estado} en {actual['device']['name']} (volumen {actual['device'].get('volume_percent')})."
