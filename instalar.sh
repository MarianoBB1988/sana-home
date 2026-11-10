#!/usr/bin/env bash
# Instala (o actualiza) SanaHome en Ubuntu/Debian: dependencias, código, entorno de Python, voz,
# configuración y servicio que arranca solo al prender el equipo.
#
#   curl -fsSL https://raw.githubusercontent.com/MarianoBB1988/sana-home/main/instalar.sh | bash
#
# Volver a correrlo actualiza a la última versión del repositorio sin tocar tu .env ni tus ajustes.
# Sana queda corriendo en segundo plano, escuchando la palabra "Sana" por el micrófono.
# Funciona en un mini PC y en una Raspberry Pi 3 o más nueva (con sistema de 64 bits): en equipos con poca memoria
# entra en "modo liviano" (sin la voz local Piper y con memoria comprimida zram).
# Variables opcionales: SANA_DIR (carpeta, por defecto ~/sana-home), SANA_SIN_SERVICIO=1 (no crear el servicio),
# SANA_WEB=1 (además, servir la página web de Sana en SANA_PUERTO, por defecto 8000),
# SANA_HOME_ASSISTANT=1 o 0 (instalar o no Home Assistant en Docker en este mismo equipo; si no se indica, pregunta),
# SANA_LIVIANO=1 (forzar el modo liviano).
set -euo pipefail

REPO="https://github.com/MarianoBB1988/sana-home.git"
DESTINO="${SANA_DIR:-$HOME/sana-home}"
PUERTO="${SANA_PUERTO:-8000}"
VOZ_PIPER="es_ES-davefx-medium"
MODELO_VOSK="vosk-model-small-es-0.42"
SERVICIO="sana-home"

verde() { printf '\033[32m%s\033[0m\n' "$*"; }
paso() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
error() { printf '\033[31mError: %s\033[0m\n' "$*" >&2; exit 1; }

# Cuando se corre con "curl | bash", la entrada es el script: las preguntas se leen de la terminal.
preguntar() {
  local texto="$1" respuesta=""
  if [ -r /dev/tty ]; then read -r -p "$texto" respuesta < /dev/tty || true; fi
  printf '%s' "$respuesta"
}

[ "$(id -u)" -ne 0 ] || error "corrélo con tu usuario normal, no como root (el script pide sudo cuando lo necesita)."
command -v apt-get >/dev/null || error "este instalador es para Ubuntu, Debian o Raspberry Pi OS (no encontré apt-get)."
case "$(uname -m)" in
  x86_64|aarch64) ;;
  *) error "hace falta un sistema de 64 bits (en Raspberry Pi: Raspberry Pi OS Lite 64-bit). Este es $(uname -m)." ;;
esac

# ¿Qué equipo es? En una Raspberry Pi o con poca memoria se activa el modo liviano.
MODELO="$(tr -d '\0' < /proc/device-tree/model 2>/dev/null || true)"
MEMORIA_MB=$(( $(awk '/MemTotal/ {print $2}' /proc/meminfo) / 1024 ))
ES_RASPBERRY=0; [[ "$MODELO" == Raspberry\ Pi* ]] && ES_RASPBERRY=1
LIVIANO="${SANA_LIVIANO:-0}"; [ "$MEMORIA_MB" -lt 1800 ] && LIVIANO=1
echo "Equipo: ${MODELO:-$(uname -m)} · memoria ${MEMORIA_MB} MB$([ "$LIVIANO" = 1 ] && echo ' · modo liviano')"

INSTALAR_HA="${SANA_HOME_ASSISTANT:-}"
if [ -z "$INSTALAR_HA" ]; then
  respuesta="$(preguntar '¿Instalar también Home Assistant en este equipo (Docker)? [S/n]: ')"
  case "${respuesta,,}" in n|no) INSTALAR_HA=0 ;; *) INSTALAR_HA=1 ;; esac
fi

paso "Instalando paquetes del sistema"
sudo apt-get update -qq
sudo apt-get install -y -qq git curl python3 python3-venv python3-pip libportaudio2 libsndfile1 alsa-utils >/dev/null
# Audio moderno y Bluetooth: si alguno no existe en esta versión, se sigue igual
sudo apt-get install -y -qq pipewire pipewire-pulse pipewire-alsa wireplumber bluez libspa-0.2-bluetooth >/dev/null \
  || echo "Aviso: no se pudieron instalar todos los paquetes de audio/Bluetooth; el micrófono y los parlantes USB igual funcionan."

python3 - <<'EOF' || error "hace falta Python 3.10 o más nuevo."
import sys
sys.exit(0 if sys.version_info >= (3, 10) else 1)
EOF

if [ "$LIVIANO" = 1 ]; then
  paso "Memoria comprimida (zram): más margen en equipos con poca RAM"
  sudo apt-get install -y -qq zram-tools >/dev/null || echo "Aviso: no se pudo instalar zram-tools; se sigue igual."
  if [ -f /etc/default/zramswap ]; then
    printf 'ALGO=zstd\nPERCENT=60\nPRIORITY=100\n' | sudo tee /etc/default/zramswap >/dev/null
    sudo systemctl restart zramswap 2>/dev/null || true
  fi
fi

paso "Descargando SanaHome en $DESTINO"
if [ -d "$DESTINO/.git" ]; then
  git -C "$DESTINO" pull --ff-only
else
  git clone "$REPO" "$DESTINO"
fi
cd "$DESTINO"

paso "Preparando el entorno de Python (puede tardar unos minutos)"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

mkdir -p voces
if [ "$LIVIANO" = 1 ]; then
  echo "Modo liviano: sin la voz local de respaldo (Piper); Sana habla con Edge TTS."
else
  paso "Descargando la voz local de respaldo ($VOZ_PIPER)"
  if [ ! -f "voces/$VOZ_PIPER.onnx" ]; then
    .venv/bin/python -m piper.download_voices --download-dir voces "$VOZ_PIPER"
  else
    echo "Ya estaba descargada."
  fi
fi

paso "Descargando el reconocedor local de la palabra \"Sana\" ($MODELO_VOSK)"
if [ ! -d "voces/$MODELO_VOSK" ]; then
  curl -fsSL -o voces/vosk.zip "https://alphacephei.com/vosk/models/$MODELO_VOSK.zip"
  .venv/bin/python -m zipfile -e voces/vosk.zip voces/
  rm voces/vosk.zip
else
  echo "Ya estaba descargado."
fi

paso "Configuración (.env)"
if [ ! -f .env ]; then
  cp .env.example .env
  sed -i "s|^VOZ_PIPER=.*|VOZ_PIPER=voces/$VOZ_PIPER.onnx|" .env
  clave="$(preguntar 'Pegá tu clave de Groq (https://console.groq.com/keys) o Enter para cargarla después: ')"
  if [ -n "$clave" ]; then
    sed -i "s|^GROQ_API_KEY=.*|GROQ_API_KEY=$clave|" .env
    verde "Clave guardada."
  fi
else
  echo "Ya existe: no lo toco."
fi
chmod 600 .env
# Valores que dependen del equipo (solo si todavía están vacíos o en su valor por defecto)
if [ "$LIVIANO" = 1 ] && grep -q "^VOZ_PIPER=voces/$VOZ_PIPER.onnx" .env; then
  sed -i "s|^VOZ_PIPER=.*|VOZ_PIPER=voces/sin-piper.onnx|" .env  # un archivo que no existe: no carga Piper
fi
if [ "$ES_RASPBERRY" = 1 ] && grep -q '^PARLANTE=$' .env; then
  sed -i 's|^PARLANTE=$|PARLANTE=Headphones|' .env  # el jack de 3,5 mm de la Raspberry Pi
fi
grep -q '^GROQ_API_KEY=.\+' .env || echo "Falta GROQ_API_KEY: editá $DESTINO/.env antes de usar Sana."

if [ "$INSTALAR_HA" = 1 ]; then
  paso "Home Assistant (Docker) en este equipo"
  if ! command -v docker >/dev/null; then
    sudo apt-get install -y -qq docker.io >/dev/null
    sudo systemctl enable --now docker
  fi
  sudo usermod -aG docker "$USER" || true
  ZONA="$(timedatectl show -p Timezone --value 2>/dev/null || echo America/Montevideo)"
  IMAGEN="ghcr.io/home-assistant/home-assistant:stable"
  echo "Descargando Home Assistant (la primera vez tarda varios minutos)..."
  sudo docker pull -q "$IMAGEN" >/dev/null
  # Si ya existe y la imagen es la misma, se deja como está; si hay versión nueva, se recrea (la configuración queda)
  if sudo docker inspect homeassistant >/dev/null 2>&1; then
    if [ "$(sudo docker inspect -f '{{.Image}}' homeassistant)" != "$(sudo docker image inspect -f '{{.Id}}' "$IMAGEN")" ]; then
      sudo docker rm -f homeassistant >/dev/null
    fi
  fi
  if ! sudo docker inspect homeassistant >/dev/null 2>&1; then
    sudo mkdir -p /opt/homeassistant
    sudo docker run -d --name homeassistant --restart=unless-stopped --privileged --network=host \
      -e TZ="$ZONA" -v /opt/homeassistant:/config -v /run/dbus:/run/dbus:ro "$IMAGEN" >/dev/null
  fi
  # Sana habla con este Home Assistant (falta el token: se crea después del primer ingreso)
  grep -q '^HA_URL=$' .env && sed -i 's|^HA_URL=$|HA_URL=http://localhost:8123|' .env
fi

paso "Audio"
# Para que el audio (y el parlante Bluetooth) funcionen aunque nadie inicie sesión en el equipo
sudo loginctl enable-linger "$USER"
sudo usermod -aG audio,bluetooth "$USER" || true
systemctl --user enable --now pipewire pipewire-pulse wireplumber 2>/dev/null || true
echo "Micrófonos y parlantes que ve Sana:"
.venv/bin/python main.py --dispositivos || true

crear_servicio() {  # nombre, descripción, argumentos de main.py
  sudo tee "/etc/systemd/system/$1.service" >/dev/null <<EOF
[Unit]
Description=$2
After=network-online.target sound.target
Wants=network-online.target

[Service]
User=$USER
WorkingDirectory=$DESTINO
Environment=XDG_RUNTIME_DIR=/run/user/$(id -u)
Environment=PYTHONUNBUFFERED=1
ExecStart=$DESTINO/.venv/bin/python main.py $3
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  sudo systemctl daemon-reload
  sudo systemctl enable "$1" >/dev/null 2>&1
  sudo systemctl restart "$1"
}

if [ "${SANA_SIN_SERVICIO:-0}" != "1" ]; then
  paso "Servicio para que Sana arranque sola y escuche en segundo plano"
  crear_servicio "$SERVICIO" "SanaHome, asistente de voz (palabra clave: Sana)" ""
  if [ "${SANA_WEB:-0}" = "1" ]; then
    crear_servicio "$SERVICIO-web" "SanaHome, página web" "--web --puerto $PUERTO"
  elif [ -f "/etc/systemd/system/$SERVICIO-web.service" ]; then
    sudo systemctl disable --now "$SERVICIO-web" >/dev/null 2>&1 || true
  fi
fi

paso "Listo"
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
verde "Sana está escuchando: decí \"Sana\" y tu pedido (por ejemplo: \"Sana, prendé la luz del living\")."
if [ "${SANA_WEB:-0}" = "1" ]; then
  verde "Página web: http://${IP:-localhost}:$PUERTO"
fi
if [ "$INSTALAR_HA" = 1 ]; then
  verde "Home Assistant: http://${IP:-localhost}:8123  (tarda unos minutos en arrancar la primera vez)"
  if ! grep -q '^HA_TOKEN=.\+' .env; then
    cat <<EOF
  Para conectar Sana con Home Assistant:
    1. Entrá a http://${IP:-localhost}:8123 y creá tu usuario.
    2. Tu perfil > Seguridad > Tokens de acceso de larga duración > Crear token.
    3. Pegalo en $DESTINO/.env (HA_TOKEN=...) y: sudo systemctl restart $SERVICIO
EOF
  fi
fi
cat <<EOF

  Configuración:     nano $DESTINO/.env   (después: sudo systemctl restart $SERVICIO)
  Ver qué escucha:   journalctl -u $SERVICIO -f
  Actualizar:        volvé a correr este mismo comando

EOF
