# Guía de despliegue — N, Uzi y su casa 3D

Todo lo que armamos en Termux ahora también corre en la nube. Esta guía
junta en un solo lugar los pasos para dejarlo funcionando 24/7 gratis.

## Parte 1 — Los dos bots en Render (nivel gratis)

Vas a crear **dos servicios separados** en Render, uno por bot (necesitan
estar siempre corriendo por separado porque cada uno es su propia
aplicación de Discord).

### Por cada bot (repite esto dos veces: una para N, una para Uzi)

1. Sube el proyecto a un repo de GitHub (puede ser el mismo repo con los
   dos archivos `discord_bot_N.py` y `discord_bot_Uzi.py`, o dos repos
   separados - como prefieras).
2. En [render.com](https://render.com) → **New** → **Web Service**
   (NO "Background Worker" - ese no tiene nivel gratis).
3. Conecta tu repo.
4. Configura:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python discord_bot_N.py` (o `discord_bot_Uzi.py`
     para el otro servicio)
   - **Instance Type:** Free
5. En **Environment** agrega estas variables (así no dejas el token
   escrito en el código, que es lo seguro):
   - `DISCORD_TOKEN` = el token de esa aplicación de bot en Discord
   - `GROQ_API_KEY` = tu API key de Groq (puede ser la misma en ambos)
6. Dale **Create Web Service**. Cuando termine el deploy, copia la URL
   pública que te da Render (algo como `https://n-bot-xxxx.onrender.com`)
   - la vas a necesitar para el paso 3 (la página 3D) y el paso 2 (evitar
     que se duerma).

### Evitar que Render lo duerma (nivel gratis)

Los Web Services gratis se duermen a los 15 min sin tráfico. Regístrate
gratis en [UptimeRobot](https://uptimerobot.com) y crea un monitor tipo
"HTTP(s)" que le pegue a `https://TU-SERVICIO.onrender.com/` cada 5-10
minutos, por cada uno de los dos servicios. Con eso se mantienen despiertos.

> Nota: aun con el ping, puede haber cortes breves (reinicios de Render,
> mantenimiento, etc.) - para 100% de uptime real, la opción es pasar a
> "Starter" ($7/mes por servicio), pero eso ya no es gratis.

### Sobre la memoria persistente

En el nivel gratis, el sistema de archivos de Render es efímero: si el
servicio se reinicia o redeploya, `n_memoria.json` / `uzi_memoria.json` y
los diarios de experimentos **se pierden**. Si en algún momento quieres que
sobrevivan, se agrega un "Disk" persistente en Render (Settings → Disks,
$0.25/GB al mes) montado en la carpeta del proyecto.

## Parte 2 — Invitar los bots a tu servidor

Si aún no lo hiciste con estos, en el Developer Portal de cada aplicación:
**OAuth2 → URL Generator** → marca `bot` → marca los permisos que
necesites (Send Messages, Read Message History, Attach Files, Add
Reactions, Connect, Speak, View Channels) → copia la URL generada y ábrela
para invitarlo a tu servidor. Y no olvides activar **Message Content
Intent** y **Server Members Intent** en la pestaña "Bot" de cada
aplicación (esto ya lo vimos antes - si no, tira `PrivilegedIntentsRequired`).

## Parte 3 — La página 3D en Vercel o Netlify

1. Consigue los modelos de Sketchfab y ponlos en `web3d/assets/` (ver
   `web3d/README.md` para las instrucciones completas de licencias).
2. En `web3d/index.html`, pon las URLs reales de tus dos servicios de
   Render + `/estado_3d` en `BACKEND_N` y `BACKEND_UZI`.
3. Publica la carpeta `web3d/`:
   - **Vercel:** `npx vercel deploy` desde dentro de `web3d/`, o conecta
     el repo y elige `web3d` como "Root Directory" del proyecto.
   - **Netlify:** arrastra la carpeta `web3d/` a
     [app.netlify.com/drop](https://app.netlify.com/drop), o conecta el
     repo con "Publish directory" = `web3d`.
4. Abre la URL que te dan - deberías ver el cuarto y, si los bots están
   despiertos en Render, sus acciones/emociones actualizándose solas.

## Checklist rápido

- [ ] Bot de N desplegado en Render, con `DISCORD_TOKEN`/`GROQ_API_KEY` en
      Environment (no en el código)
- [ ] Bot de Uzi desplegado en Render, con SU PROPIO `DISCORD_TOKEN`
- [ ] UptimeRobot pingueando ambas URLs cada 5-10 min
- [ ] Ambos bots invitados al servidor, con los Privileged Intents activos
- [ ] Modelos de Sketchfab descargados con licencia revisada, en
      `web3d/assets/`
- [ ] URLs de `/estado_3d` puestas en `index.html`
- [ ] `web3d/` publicada en Vercel o Netlify
