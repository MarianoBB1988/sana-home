import socket

# Solo IPv4: en muchas redes hogareñas el IPv6 está a medio configurar y cada conexión nueva espera ~15 s
# hasta caer a IPv4 (Groq, la voz de Edge...). IPv4 funciona en todas, así que se usa directamente.
_getaddrinfo_original = socket.getaddrinfo


def _solo_ipv4(host, puerto, familia=0, *args, **kwargs):
    resultados = _getaddrinfo_original(host, puerto, familia, *args, **kwargs)
    ipv4 = [r for r in resultados if r[0] == socket.AF_INET]
    return ipv4 or resultados


socket.getaddrinfo = _solo_ipv4
