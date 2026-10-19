# Sana — asistente de voz para el hogar

Sana escucha, entiende con Groq (Whisper + LLM), busca en internet y controla la casa a través de Home Assistant.
Habla con una voz uruguaya de Edge TTS (`es-UY-ValentinaNeural`); si Edge falla, usa Piper, que corre local.
Se elige en `.env` con `MOTOR_VOZ` y `VOZ_EDGE`.

```
Micrófono → Whisper (Groq) → LLM gpt-oss (Groq) ─┬─ hora (local)
                                                  ├─ clima_actual (Open-Meteo, gratis y sin clave)
                                                  ├─ buscar_en_internet (Groq browser_search): clima, noticias, cotización…
                                                  └─ Home Assistant: relays, aspiradora, Spotify
                                     → Edge TTS (Piper de respaldo) → parlante
```

La interfaz gráfica para prender y apagar dispositivos es el panel de **Home Assistant** (web y app del celular). Sana es la interfaz de voz sobre esa misma casa.

## 1. Probar en esta PC (Windows)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m piper.download_voices --download-dir voces es_ES-davefx-medium
copy .env.example .env      # y poné tu GROQ_API_KEY (https://console.groq.com/keys)

python main.py               # manos libres: decís "Sana" y tu pedido (así corre en el mini PC)
python main.py --pantalla    # igual, con una animación a pantalla completa (Lottie .lottie/.json o SVG, ver ANIMACION
                             # en .env): se mueve cuando Sana está activa y queda quieta en pausa (salir: Alt+F4 o Ctrl+C)
python main.py --enter       # igual, pero apretando Enter en lugar de decir "Sana"
python main.py --texto       # conversar escribiendo en la consola
python main.py --web         # página web opcional: chat, clima y ajustes
python main.py --web --https # además, Sana para el celular en https://IP:8000/movil: se toca la esfera y se habla
                             # (HTTPS hace falta para el micrófono; la 1.ª vez aceptá el aviso del certificado)
python main.py --dispositivos  # ver micrófonos y parlantes; elegilos en .env (MICROFONO / PARLANTE)
```

### Interfaz web

`python main.py --web` muestra la dirección (por ejemplo `http://192.168.1.50:8000`). Abrila desde el celular o cualquier compu
conectada al mismo Wi-Fi. En el celular: menú del navegador → *Agregar a la pantalla de inicio* y queda como una app.

- **Charla:** escribile a Sana. Las respuestas pueden escucharse en el mismo celular ("Voz acá") o en el parlante de la casa.
- **Casa:** prender y apagar relays y luces, mandar a limpiar la aspiradora, pausar la música. Se actualiza sola cada 10 segundos.
  Para abrir directo en esta pestaña: `http://IP:8000/#casa`.
- **Micrófono del navegador:** botón 🎤 Hablar; corta solo cuando hacés una pausa. Los navegadores solo permiten el micrófono
  en `localhost` o con HTTPS: desde la misma PC funciona; desde el celular por ahora se usa escribiendo.
- **Windows:** la primera vez el firewall pregunta si permitir Python en redes privadas: aceptá para que entre el celular.

Sin Home Assistant ya funcionan: conversación, hora, clima, noticias, cotización y cualquier búsqueda.
En **Ajustes** (botón arriba a la derecha) se guardan la ubicación, la fuente del clima y las cotizaciones de interés.

## 2. Mini PC (i3, 8 GB)

1. Instalar **Ubuntu Server 24.04** o **Debian 12**.
2. Instalar SanaHome con un solo comando:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/MarianoBB1988/sana-home/main/instalar.sh | bash
   ```
   Instala las dependencias, descarga el código en `~/sana-home`, prepara Python y la voz, te pide la clave de Groq
   y deja Sana **escuchando en segundo plano** al prender el equipo: decís "Sana", suena un aviso, y le hablás.
   La palabra "Sana" se reconoce en el equipo (Vosk): lo que se habla antes no sale a internet.
   Después de responder, durante 5 segundos podés seguir hablando sin volver a decir "Sana".
   Con `SANA_WEB=1` antes del comando también queda la página web.
   **Para actualizar**, se vuelve a correr el mismo comando (no toca tu `.env` ni tus ajustes).
   - Mensajes del servicio: `journalctl -u sana-home -f` · Reiniciar: `sudo systemctl restart sana-home`
   - Emparejar el parlante Bluetooth: `bluetoothctl` → `scan on`, `pair XX:XX…`, `trust XX:XX…`, `connect XX:XX…`.
3. Home Assistant en Docker:
   ```bash
   docker run -d --name homeassistant --restart=unless-stopped --network=host \
     -e TZ=America/Montevideo -v /opt/homeassistant:/config \
     ghcr.io/home-assistant/home-assistant:stable
   ```
   Abrir `http://IP-DEL-MINI-PC:8123` y crear el usuario.
4. En `~/sana-home/.env` completar `HA_URL` y `HA_TOKEN`
   (Home Assistant → tu perfil → Seguridad → *Tokens de acceso de larga duración*) y `sudo systemctl restart sana-home`.

## 3. Conectar los dispositivos a Home Assistant

**Relays de Temu.** Configuralos con la app **Smart Life** (casi todos los genéricos son Tuya). Si la app no los reconoce, probá **eWeLink**.
Después, en Home Assistant: *Ajustes → Dispositivos → Añadir integración → Tuya*, y escaneá el QR con Smart Life.
Ponele nombres claros a cada relay ("luz del living"): Sana los usa para entender qué querés prender.

**Aspiradora Xiaomi.** Configurala con la app **Xiaomi Home** (o Mi Home). En Home Assistant: integración **Xiaomi Home**
(la oficial de Xiaomi, se instala desde HACS) o **Xiaomi Miio**. Según el modelo puede convenir otra integración (Roborock, Dreame).

**Spotify.** Integración **Spotify** en Home Assistant (necesita Premium para controlar la reproducción). Para que el mini PC
sea un parlante Spotify Connect, instalá `raspotify` o `spotifyd`.

Con eso Sana ya puede: "prendé la luz del living", "mandá a limpiar la aspiradora", "pausá la música", "subí el volumen a 40".

## Próximos pasos

- Poner un tema, artista o playlist por nombre en Spotify.
- HTTPS en la red local, para usar el micrófono del celular desde la web.
- Cámaras: "¿dónde está Felipe?" y avisos con Frigate + un modelo con visión.
