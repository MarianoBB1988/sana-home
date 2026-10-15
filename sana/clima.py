"""Clima actual desde varias fuentes, elegibles en Ajustes.

Open-Meteo siempre da la base completa (estado del cielo, máxima, mínima, amanecer...). La fuente elegida
pisa los datos que tenga (temperatura, humedad, viento, estado); lo que no tenga queda de Open-Meteo.
Si la fuente elegida falla, se usa Open-Meteo solo.
"""
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor

import requests

from . import ajustes, config

# Códigos WMO de Open-Meteo -> (categoría para el fondo, descripción)
CODIGOS = {
    0: ("despejado", "Despejado"),
    1: ("parcial", "Mayormente despejado"),
    2: ("parcial", "Parcialmente nublado"),
    3: ("nublado", "Nublado"),
    45: ("niebla", "Niebla"),
    48: ("niebla", "Niebla con escarcha"),
    51: ("llovizna", "Llovizna débil"),
    53: ("llovizna", "Llovizna"),
    55: ("llovizna", "Llovizna intensa"),
    56: ("llovizna", "Llovizna helada"),
    57: ("llovizna", "Llovizna helada intensa"),
    61: ("lluvia", "Lluvia débil"),
    63: ("lluvia", "Lluvia"),
    65: ("lluvia", "Lluvia intensa"),
    66: ("lluvia", "Lluvia helada"),
    67: ("lluvia", "Lluvia helada intensa"),
    71: ("nieve", "Nevada débil"),
    73: ("nieve", "Nevada"),
    75: ("nieve", "Nevada intensa"),
    77: ("nieve", "Granizo fino"),
    80: ("lluvia", "Chaparrones débiles"),
    81: ("lluvia", "Chaparrones"),
    82: ("lluvia", "Chaparrones fuertes"),
    85: ("nieve", "Chaparrones de nieve"),
    86: ("nieve", "Chaparrones de nieve fuertes"),
    95: ("tormenta", "Tormenta"),
    96: ("tormenta", "Tormenta con granizo"),
    99: ("tormenta", "Tormenta fuerte con granizo"),
}
DESCRIPCION = {
    "despejado": "Despejado", "parcial": "Parcialmente nublado", "nublado": "Nublado", "niebla": "Niebla",
    "llovizna": "Llovizna", "lluvia": "Lluvia", "tormenta": "Tormenta", "nieve": "Nieve",
}

MODELOS_OPEN_METEO = {
    "best_match": "automático",
    "ecmwf_ifs025": "europeo (ECMWF)",
    "gfs_seamless": "estadounidense (GFS)",
    "icon_seamless": "alemán (ICON)",
    "meteofrance_seamless": "francés (Météo-France)",
    "ukmo_seamless": "británico (UK Met Office)",
    "jma_seamless": "japonés (JMA)",
}

# id -> (nombre, variable de .env con la clave o None, minutos de caché)
FUENTES = {
    **{f"open-meteo:{m}": (f"Open-Meteo, modelo {n}", None, 10) for m, n in MODELOS_OPEN_METEO.items()},
    "met-norway": ("MET Norway (yr.no)", None, 10),
    "openweathermap": ("OpenWeatherMap", "OPENWEATHER_API_KEY", 10),
    "weatherapi": ("WeatherAPI.com", "WEATHERAPI_KEY", 10),
    "google": ("Google Weather", "GOOGLE_WEATHER_API_KEY", 15),
    "accuweather": ("AccuWeather", "ACCUWEATHER_API_KEY", 30),  # el plan gratis da ~50 consultas por día
}
POR_DEFECTO = "open-meteo:best_match"

_coordenadas: dict[str, tuple[float, float, str]] = {}
_cache: dict[str, tuple[float, dict]] = {}
_bloqueo = threading.Lock()


# ---------------------------------------------------------------- utilidades

def _normal(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return sin_tildes.lower().replace("departamento de", "").replace("provincia de", "").strip()


def _clave(fuente: str) -> str:
    variable = FUENTES[fuente][1]
    return config.clave(variable) if variable else ""


def _cacheado(clave: str, minutos: int, obtener):
    with _bloqueo:
        if clave in _cache and time.time() - _cache[clave][0] < minutos * 60:
            return _cache[clave][1]
    valor = obtener()
    with _bloqueo:
        _cache[clave] = (time.time(), valor)
    return valor


def _ubicar(datos: dict) -> tuple[float, float, str]:
    clave = ajustes.ubicacion(datos)
    if clave in _coordenadas:
        return _coordenadas[clave]
    r = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": datos["ciudad"], "count": 20, "language": "es", "format": "json"},
        timeout=10,
    )
    r.raise_for_status()
    resultados = r.json().get("results") or []
    if not resultados:
        raise LookupError(f"No encontré la ciudad {datos['ciudad']}")

    def puntaje(x: dict) -> int:
        p = 0
        if datos["pais"] and _normal(datos["pais"]) in (_normal(x.get("country", "")), _normal(x.get("country_code", ""))):
            p += 2
        if datos["region"] and _normal(datos["region"]) in _normal(x.get("admin1", "")):
            p += 1
        return p

    mejor = max(resultados, key=puntaje)  # ante empate gana el primero (el más poblado)
    lugar = ", ".join(filter(None, [mejor.get("name"), mejor.get("admin1"), mejor.get("country")]))
    _coordenadas[clave] = (mejor["latitude"], mejor["longitude"], lugar)
    return _coordenadas[clave]


# ---------------------------------------------------------------- fuentes
# Cada una devuelve solo los datos que tiene; lo demás lo completa Open-Meteo.

def _open_meteo(lat: float, lon: float, zona: str, modelo: str) -> dict:
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,is_day,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset",
            "timezone": zona,
            "forecast_days": 1,
            "models": modelo,
        },
        timeout=10,
    )
    r.raise_for_status()
    j = r.json()
    ahora, hoy = j["current"], j["daily"]
    categoria, descripcion = CODIGOS.get(ahora["weather_code"], ("nublado", "Sin datos"))
    return {
        "categoria": categoria,
        "descripcion": descripcion,
        "es_de_dia": bool(ahora["is_day"]),
        "temperatura": ahora["temperature_2m"],
        "sensacion": ahora["apparent_temperature"],
        "humedad": ahora["relative_humidity_2m"],
        "viento": ahora["wind_speed_10m"],
        "maxima": hoy["temperature_2m_max"][0],
        "minima": hoy["temperature_2m_min"][0],
        "lluvia_probabilidad": (hoy.get("precipitation_probability_max") or [None])[0],
        "amanecer": hoy["sunrise"][0][-5:],
        "atardecer": hoy["sunset"][0][-5:],
    }


def _met_categoria(base: str) -> str | None:
    """Símbolos de MET Norway: clearsky, fair, partlycloudy, cloudy, fog, lightrain, rainshowers, snow, ...thunder"""
    if "thunder" in base:
        return "tormenta"
    if "snow" in base or "sleet" in base:
        return "nieve"
    if "rain" in base:
        return "llovizna" if base.startswith("light") else "lluvia"
    return {"fog": "niebla", "cloudy": "nublado", "partlycloudy": "parcial", "fair": "parcial", "clearsky": "despejado"}.get(base)


def _met_norway(lat: float, lon: float) -> dict:
    r = requests.get(
        "https://api.met.no/weatherapi/locationforecast/2.0/compact",
        params={"lat": round(lat, 4), "lon": round(lon, 4)},
        headers={"User-Agent": "SanaHome/1.0 (asistente de hogar personal)"},
        timeout=10,
    )
    r.raise_for_status()
    serie = r.json()["properties"]["timeseries"][0]["data"]
    ahora = serie["instant"]["details"]
    simbolo = (serie.get("next_1_hours") or serie.get("next_6_hours") or {}).get("summary", {}).get("symbol_code", "")
    categoria = _met_categoria(simbolo.split("_")[0])
    datos = {
        "temperatura": ahora["air_temperature"],
        "humedad": ahora.get("relative_humidity"),
        "viento": ahora.get("wind_speed", 0) * 3.6,
    }
    if categoria:
        datos.update(categoria=categoria, descripcion=DESCRIPCION[categoria])
    if simbolo.endswith("_day") or simbolo.endswith("_night"):
        datos["es_de_dia"] = simbolo.endswith("_day")
    return datos


def _openweathermap(lat: float, lon: float, clave: str) -> dict:
    r = requests.get(
        "https://api.openweathermap.org/data/2.5/weather",
        params={"lat": lat, "lon": lon, "appid": clave, "units": "metric", "lang": "es"},
        timeout=10,
    )
    r.raise_for_status()
    j = r.json()
    w = j["weather"][0]
    i = w["id"]
    categoria = ("tormenta" if i < 300 else "llovizna" if i < 400 else "lluvia" if i < 600 else "nieve" if i < 700
                 else "niebla" if i < 800 else "despejado" if i == 800 else "parcial" if i <= 802 else "nublado")
    return {
        "categoria": categoria,
        "descripcion": w["description"].capitalize(),
        "es_de_dia": w["icon"].endswith("d"),
        "temperatura": j["main"]["temp"],
        "sensacion": j["main"]["feels_like"],
        "humedad": j["main"]["humidity"],
        "viento": j["wind"]["speed"] * 3.6,
    }


_WEATHERAPI = {
    "despejado": {1000}, "parcial": {1003}, "nublado": {1006, 1009}, "niebla": {1030, 1135, 1147},
    "llovizna": {1150, 1153, 1168, 1171, 1063, 1180, 1183},
    "tormenta": {1087, 1273, 1276, 1279, 1282},
    "nieve": {1066, 1069, 1072, 1114, 1117, 1204, 1207, 1210, 1213, 1216, 1219, 1222, 1225, 1237, 1249, 1252, 1255, 1258, 1261, 1264},
}


def _weatherapi(lat: float, lon: float, clave: str) -> dict:
    r = requests.get(
        "https://api.weatherapi.com/v1/forecast.json",
        params={"key": clave, "q": f"{lat},{lon}", "days": 1, "lang": "es"},
        timeout=10,
    )
    r.raise_for_status()
    j = r.json()
    ahora, dia = j["current"], j["forecast"]["forecastday"][0]["day"]
    codigo = ahora["condition"]["code"]
    categoria = next((c for c, codigos in _WEATHERAPI.items() if codigo in codigos), "lluvia")
    return {
        "categoria": categoria,
        "descripcion": ahora["condition"]["text"].strip().capitalize(),
        "es_de_dia": bool(ahora["is_day"]),
        "temperatura": ahora["temp_c"],
        "sensacion": ahora["feelslike_c"],
        "humedad": ahora["humidity"],
        "viento": ahora["wind_kph"],
        "maxima": dia["maxtemp_c"],
        "minima": dia["mintemp_c"],
        "lluvia_probabilidad": dia.get("daily_chance_of_rain"),
    }


_GOOGLE = {
    "CLEAR": ("despejado", "Despejado"), "MOSTLY_CLEAR": ("parcial", "Mayormente despejado"),
    "PARTLY_CLOUDY": ("parcial", "Parcialmente nublado"), "MOSTLY_CLOUDY": ("nublado", "Mayormente nublado"),
    "CLOUDY": ("nublado", "Nublado"), "WINDY": ("parcial", "Ventoso"),
}


def _google(lat: float, lon: float, clave: str) -> dict:
    r = requests.get(
        "https://weather.googleapis.com/v1/currentConditions:lookup",
        params={"key": clave, "location.latitude": lat, "location.longitude": lon},
        timeout=10,
    )
    r.raise_for_status()
    j = r.json()
    tipo = j.get("weatherCondition", {}).get("type", "")
    if tipo in _GOOGLE:
        categoria, descripcion = _GOOGLE[tipo]
    else:
        categoria = ("tormenta" if "THUNDER" in tipo else "nieve" if any(x in tipo for x in ("SNOW", "HAIL")) else
                     "llovizna" if tipo in ("LIGHT_RAIN", "LIGHT_RAIN_SHOWERS", "CHANCE_OF_SHOWERS") else "lluvia")
        descripcion = DESCRIPCION[categoria]
    datos = {
        "categoria": categoria,
        "descripcion": descripcion,
        "es_de_dia": bool(j.get("isDaytime", True)),
        "temperatura": j["temperature"]["degrees"],
        "sensacion": j.get("feelsLikeTemperature", {}).get("degrees"),
        "humedad": j.get("relativeHumidity"),
        "viento": j.get("wind", {}).get("speed", {}).get("value"),
    }
    return {k: v for k, v in datos.items() if v is not None}


def _accuweather_categoria(icono: int) -> str:
    if icono in (1, 2, 30, 31, 32, 33, 34):
        return "despejado" if icono in (1, 33) else "parcial"
    if icono in (3, 4, 5, 35, 36, 37):
        return "parcial"
    if icono in (6, 7, 8, 38):
        return "nublado"
    if icono == 11:
        return "niebla"
    if icono in (15, 16, 17, 41, 42):
        return "tormenta"
    if icono in (19, 20, 21, 22, 23, 24, 25, 26, 29, 43, 44):
        return "nieve"
    return "lluvia"


def _accuweather(lat: float, lon: float, clave: str) -> dict:
    base = "https://dataservice.accuweather.com"

    def ubicacion():
        r = requests.get(f"{base}/locations/v1/cities/geoposition/search",
                         params={"apikey": clave, "q": f"{lat},{lon}"}, timeout=10)
        r.raise_for_status()
        return r.json()["Key"]

    lugar = _cacheado(f"accuweather:lugar:{lat},{lon}", 60 * 24 * 30, ubicacion)  # la ubicación casi no cambia
    r = requests.get(f"{base}/currentconditions/v1/{lugar}",
                     params={"apikey": clave, "details": "true", "language": "es-ar"}, timeout=10)
    r.raise_for_status()
    j = r.json()[0]
    datos = {
        "categoria": _accuweather_categoria(j["WeatherIcon"]),
        "descripcion": j["WeatherText"],
        "es_de_dia": bool(j["IsDayTime"]),
        "temperatura": j["Temperature"]["Metric"]["Value"],
        "sensacion": j.get("RealFeelTemperature", {}).get("Metric", {}).get("Value"),
        "humedad": j.get("RelativeHumidity"),
        "viento": j.get("Wind", {}).get("Speed", {}).get("Metric", {}).get("Value"),
    }
    return {k: v for k, v in datos.items() if v is not None}


def _consultar(fuente: str, lat: float, lon: float, datos: dict) -> dict:
    if fuente.startswith("open-meteo:"):
        return _open_meteo(lat, lon, datos["zona_horaria"], fuente.split(":", 1)[1])
    if fuente == "met-norway":
        return _met_norway(lat, lon)
    clave = _clave(fuente)
    if not clave:
        raise LookupError(f"Falta {FUENTES[fuente][1]} en el archivo .env")
    return {"openweathermap": _openweathermap, "weatherapi": _weatherapi,
            "google": _google, "accuweather": _accuweather}[fuente](lat, lon, clave)


# ---------------------------------------------------------------- interfaz pública

def fuentes() -> list[dict]:
    """Las fuentes para el selector de Ajustes, con si se pueden usar y por qué no."""
    lista = []
    for id_, (nombre, variable, _) in FUENTES.items():
        motivo = f"falta {variable} en .env" if variable and not config.clave(variable) else ""
        grupo = "Con clave" if variable else "Sin clave"
        lista.append({"id": id_, "nombre": nombre, "grupo": grupo, "disponible": not motivo, "motivo": motivo})
    return lista


def validar(datos: dict) -> None:
    fuente = datos.get("clima_fuente") or POR_DEFECTO
    if fuente not in FUENTES:
        raise ValueError(f"Fuente de clima desconocida: {fuente}")


def _redondear(c: dict) -> dict:
    for k in ("temperatura", "sensacion", "maxima", "minima", "viento", "humedad"):
        if isinstance(c.get(k), (int, float)):
            c[k] = round(c[k])
    return c


def actual() -> dict:
    datos = ajustes.leer()
    fuente = datos.get("clima_fuente") or POR_DEFECTO
    if fuente not in FUENTES:
        fuente = POR_DEFECTO
    lat, lon, lugar = _ubicar(datos)
    minutos = FUENTES[fuente][2]

    modelo_base = fuente.split(":", 1)[1] if fuente.startswith("open-meteo:") else "best_match"
    clima = dict(_cacheado(f"open-meteo:{modelo_base}:{lat},{lon}", 10,
                           lambda: _open_meteo(lat, lon, datos["zona_horaria"], modelo_base)))
    clima.update(lugar=lugar, fuente=FUENTES[f"open-meteo:{modelo_base}"][0], aviso="")

    if not fuente.startswith("open-meteo:"):
        try:
            propio = _cacheado(f"{fuente}:{lat},{lon}", minutos, lambda: _consultar(fuente, lat, lon, datos))
            clima.update(propio)
            clima["fuente"] = FUENTES[fuente][0].split(" (")[0]
        except Exception as e:
            clima["aviso"] = f"{FUENTES[fuente][0]} no respondió ({e}); muestro Open-Meteo."
    return _redondear(clima)


def comparar() -> list[dict]:
    """Temperatura y estado según cada fuente disponible, consultadas en paralelo (sin caché)."""
    datos = ajustes.leer()
    lat, lon, _ = _ubicar(datos)
    disponibles = [f for f in fuentes() if f["disponible"]]

    def una(f: dict) -> dict:
        try:
            c = _consultar(f["id"], lat, lon, datos)
            return {"id": f["id"], "nombre": f["nombre"], "temperatura": round(c["temperatura"], 1),
                    "descripcion": c.get("descripcion", ""), "error": ""}
        except Exception as e:
            return {"id": f["id"], "nombre": f["nombre"], "error": str(e)[:160]}

    # Open-Meteo rechaza muchos pedidos simultáneos: sus modelos van de a uno, en un solo hilo; el resto en paralelo.
    modelos = [f for f in disponibles if f["id"].startswith("open-meteo:")]
    otras = [f for f in disponibles if not f["id"].startswith("open-meteo:")]
    with ThreadPoolExecutor(max_workers=6) as pool:
        tanda_modelos = pool.submit(lambda: [una(f) for f in modelos])
        resultados_otras = list(pool.map(una, otras))
        return tanda_modelos.result() + resultados_otras


def resumen() -> str:
    """Texto para el LLM."""
    c = actual()
    return (
        f"{c['lugar']} (fuente: {c['fuente']}): {c['descripcion'].lower()}, {c['temperatura']} °C "
        f"(sensación {c['sensacion']} °C), humedad {c['humedad']} %, viento {c['viento']} km/h. "
        f"Hoy: máxima {c['maxima']} °C, mínima {c['minima']} °C, probabilidad de lluvia {c['lluvia_probabilidad']} %. "
        f"Es de {'día' if c['es_de_dia'] else 'noche'}; amanecer {c['amanecer']}, atardecer {c['atardecer']}."
    )
