"""Certificado HTTPS propio para la red de la casa: los navegadores solo dejan usar el micrófono con HTTPS.

Es autofirmado: la primera vez el celular muestra "conexión no privada" y hay que aceptar. Se regenera solo si
cambia la IP de la compu (el certificado la incluye).
"""
import datetime
import ipaddress
import json
import socket

from . import config

CARPETA = config.RAIZ / "datos" / "https"
CERTIFICADO = CARPETA / "cert.pem"
CLAVE = CARPETA / "clave.pem"
DIRECCIONES = CARPETA / "direcciones.json"


def ip_local() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def _direcciones() -> list[str]:
    ips = {"127.0.0.1", ip_local()}
    try:
        ips.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith("169.254."))


def asegurar() -> tuple[str, str]:
    """Devuelve (certificado, clave), generándolos si no existen o si cambió la IP."""
    direcciones = _direcciones()
    if CERTIFICADO.exists() and CLAVE.exists() and DIRECCIONES.exists():
        if set(direcciones) <= set(json.loads(DIRECCIONES.read_text())):
            return str(CERTIFICADO), str(CLAVE)

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    clave = ec.generate_private_key(ec.SECP256R1())
    nombre = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "SanaHome")])
    ahora = datetime.datetime.now(datetime.timezone.utc)
    alternativos = [x509.DNSName("localhost"), x509.DNSName(socket.gethostname())]
    alternativos += [x509.IPAddress(ipaddress.ip_address(ip)) for ip in direcciones]
    certificado = (
        x509.CertificateBuilder()
        .subject_name(nombre)
        .issuer_name(nombre)
        .public_key(clave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(ahora - datetime.timedelta(days=1))
        .not_valid_after(ahora + datetime.timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(alternativos), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(clave, hashes.SHA256())
    )
    CARPETA.mkdir(parents=True, exist_ok=True)
    CLAVE.write_bytes(clave.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    CERTIFICADO.write_bytes(certificado.public_bytes(serialization.Encoding.PEM))
    DIRECCIONES.write_text(json.dumps(direcciones))
    return str(CERTIFICADO), str(CLAVE)
