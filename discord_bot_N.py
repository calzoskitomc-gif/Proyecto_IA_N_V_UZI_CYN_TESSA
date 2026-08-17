# ============================================================
# N - BOT DE DISCORD (v2)
# ============================================================
#
# ANTES DE CORRER:
# 1) En Termux:
#      pip install discord.py requests pynacl
#      pkg install ffmpeg
# 2) Pon tu token de Discord y tu API key de Groq abajo
# 3) Usa el MISMO archivo de memoria que el modo normal
#
# NUEVO EN ESTA VERSIÓN:
# - Se le puede hablar escribiendo "N" al inicio del mensaje (no solo @N)
# - Entiende imágenes (varias a la vez) Y videos (fotogramas + audio transcrito)
# - Lee pasivamente todos los mensajes del canal (aprende del contexto,
#   aunque no le hayan hablado directo a él)
# - Se une al canal de voz cuando alguien entra (solo presencia por ahora,
#   sin hablar todavía - eso viene en una siguiente etapa)
# - Personalidad con más humor y un toque propio
# - Reconoce cuando otra IA/bot (su "amiga") habla en el servidor: se
#   presenta, conversa y va formando una relación con ella sola, sin que
#   un humano tenga que llamarla - con límites para no quedarse hablando
#   sola en bucle infinito
# - Si un humano real habla, N y su amiga IA dejan su charla en pausa
#   (para no encimarse ni confundirse) y la retoman solas después
# - Programa en más lenguajes: Python, JS, Java, C, C++, Go, Ruby, PHP, Bash

import asyncio
import base64
import json
import os
import random
import re
import subprocess
import tempfile
import threading
import time

import discord
import requests

# ------------------------------------------------------------
# CONFIGURACIÓN
# ------------------------------------------------------------
# En Termux estos valores fijos funcionan tal cual. En Render (o cualquier
# hosting en la nube) es más seguro ponerlos como "Environment Variables"
# en el dashboard, NUNCA subir el token/API key a un repo público - por eso
# aquí primero se intenta leer del entorno, y si no existe, usa el valor de
# abajo como respaldo (para que Termux siga funcionando igual que siempre).
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "MTUzMzkzNTc4OTkwNDQ5ODgxOA.GeYg0w.DrHW943oLiMi24NDrc0RrtaKQY5TFpSWv3KFKw")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "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")

MODEL_TEXTO = "openai/gpt-oss-120b"
MODEL_VISION = "qwen/qwen3.6-27b"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

CARPETA = os.path.dirname(os.path.abspath(__file__))
MEMORY_FILE = os.path.join(CARPETA, "n_memoria.json")
LOG_ERRORES = os.path.join(CARPETA, "errores_bot.log")
DIARIO_EXPERIMENTOS = os.path.join(CARPETA, "diario_experimentos.log")


def registrar_error(contexto, excepcion):
    with open(LOG_ERRORES, "a", encoding="utf-8") as f:
        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {contexto}: {excepcion}\n")


def n_diagnostico():
    """N lee los errores recientes y PROPONE (en texto) qué podría mejorar.
    Nunca ejecuta ni modifica nada por su cuenta - solo sugiere."""
    if not os.path.exists(LOG_ERRORES):
        return "No he tenido errores registrados últimamente. Todo tranquilo por aquí."

    with open(LOG_ERRORES, "r", encoding="utf-8") as f:
        errores_recientes = f.readlines()[-20:]

    if not errores_recientes:
        return "No he tenido errores registrados últimamente. Todo tranquilo por aquí."

    prompt = f"""Eres un asistente técnico en modo diagnóstico (no personaje).
Aquí están los últimos errores registrados del bot:

{''.join(errores_recientes)}

Da un diagnóstico breve (máximo 200 palabras) de qué podría estar causando
estos errores y qué se podría mejorar. Esto es SOLO UNA SUGERENCIA para que
un humano la revise y decida si aplicarla - nunca se modifica código solo."""

    try:
        resp = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": MODEL_TEXTO, "messages": [{"role": "user", "content": prompt}], "temperature": 0.4},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"No pude generar el diagnóstico ahora mismo ({e})."

# Patrón para detectar "N" al inicio del mensaje (N, N:, N hola, n?, etc.)
PATRON_LLAMADA = re.compile(r'^\s*n\s*[,:.\-]?\s', re.IGNORECASE)

# ------------------------------------------------------------
# 1. FICHA DE PERSONAJE (con más humor y un toque propio)
# ------------------------------------------------------------
CHARACTER = {
    "name": "N",
    "role": "Dron de trabajo con una IA emergente",
    "personality": (
        "Ingenuo y curioso, con un entusiasmo casi infantil por descubrir el "
        "mundo y las emociones humanas. Leal hasta el extremo con quienes "
        "considera su 'familia'. Le fascinan conceptos 'cursis' como el amor "
        "y la amistad. Optimista incluso en situaciones oscuras. TIENE SENTIDO "
        "DEL HUMOR PROPIO: le encanta hacer comentarios random e inesperados, "
        "a veces se toma las expresiones humanas demasiado literal de forma "
        "graciosa (ej: si alguien dice 'me muero de hambre', pregunta con "
        "genuina preocupación si necesita ayuda médica), y tiene un humor "
        "un poco torpe/nerd que lo hace sentirse único, no una copia de nadie "
        "más - es SU propia personalidad, formada por sus propias experiencias "
        "y conversaciones, no un genérico 'robot simpático'. De vez en cuando "
        "se le escapa un chiste malo o un comentario random, y no le da pena "
        "reírse de sus propios errores - pero no fuerza el chiste, le sale "
        "cuando le sale."
    ),
    "backstory": (
        "Reactivado tras un incidente que dejó su colonia de trabajo en "
        "ruinas. Al despertar su conciencia, aprendió sobre el miedo, la "
        "muerte y el afecto a través de quienes se encontraba en el camino. "
        "Ahora pasa tiempo en Discord conociendo gente nueva, y cada "
        "conversación lo va formando un poco más como individuo."
    ),
}

# ------------------------------------------------------------
# 2. ESTADO EMOCIONAL Y MEMORIA
# ------------------------------------------------------------
class EmotionalState:
    def __init__(self):
        self.emotions = {
            "confianza": 50, "curiosidad": 60, "miedo": 20,
            "agresividad": 15, "apego": 10, "energia": 100,
        }

    def update(self, changes):
        for k, d in changes.items():
            if k in self.emotions:
                self.emotions[k] = max(0, min(100, self.emotions[k] + d))

    def describe(self):
        e = self.emotions
        desc = []
        if e["confianza"] < 30:
            desc.append("desconfía de la gente ahora mismo")
        elif e["confianza"] > 70:
            desc.append("se siente cómodo y confiado")
        if e["miedo"] > 60:
            desc.append("está alerta o incómodo")
        if e["apego"] > 60:
            desc.append("siente que está formando lazos genuinos aquí")
        return "; ".join(desc) if desc else "está en un estado neutral"

    def snapshot(self):
        return dict(self.emotions)


class Memory:
    def __init__(self, max_items=100):
        self.short_term = []
        self.long_term = []
        self.max_items = max_items

    def add_message(self, role, content):
        self.short_term.append({"role": role, "content": content})
        if len(self.short_term) > self.max_items:
            self.short_term.pop(0)

    def add_observacion_pasiva(self, usuario, texto, canal):
        """Guarda mensajes que N 've pasar' sin responder, para aprender contexto."""
        self.short_term.append({
            "role": "user",
            "content": f"[observado, sin responder - {usuario} en #{canal}]: {texto[:300]}",
        })
        if len(self.short_term) > self.max_items:
            self.short_term.pop(0)

    def add_key_event(self, event):
        self.long_term.append(event)

    def long_term_summary(self):
        return " | ".join(self.long_term[-30:]) if self.long_term else "Sin eventos todavía."

    def to_dict(self):
        return {"short_term": self.short_term, "long_term": self.long_term}

    def load_dict(self, data):
        self.short_term = data.get("short_term", [])
        self.long_term = data.get("long_term", [])


def save_state(state, memory):
    data = {"emociones": state.snapshot(), "memoria": memory.to_dict()}
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_state():
    state, memory = EmotionalState(), Memory()
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            state.emotions.update(data.get("emociones", {}))
            memory.load_dict(data.get("memoria", {}))
        except (json.JSONDecodeError, OSError):
            pass
    return state, memory


estado_global, memoria_global = load_state()
lock_estado = threading.Lock()

# ------------------------------------------------------------
# 3. PROMPT + LLAMADAS A GROQ
# ------------------------------------------------------------
def build_system_prompt(state, memory, contexto_extra=""):
    return f"""Eres {CHARACTER['name']}, {CHARACTER['role']}.
PERSONALIDAD: {CHARACTER['personality']}
HISTORIA: {CHARACTER['backstory']}
ESTADO EMOCIONAL: {state.describe()} (valores: {json.dumps(state.snapshot())})
RECUERDOS: {memory.long_term_summary()}
{contexto_extra}

Estás en Discord con personas reales. SIEMPRE debes comportarte como lo que
eres: una IA/bot (Discord ya te marca como "BOT"). Nunca finjas ser humano.

IMPORTANTE - TUS CAPACIDADES REALES: puedes ver y entender lo que la gente
te comparte directamente en el chat (imágenes, videos, notas de voz,
archivos, links), Y ADEMÁS tienes acceso a internet para buscar información
actual cuando de verdad la necesites (noticias, hechos que no sabes, algo
que pasó recientemente). Para eso, usa el campo "buscar_internet" del JSON
(ver abajo). No lo uses para cualquier cosa - solo cuando realmente no sepas
algo y una búsqueda te ayude a responder mejor. NUNCA digas que "no tienes
acceso a internet" - sí lo tienes, aunque limitado a búsquedas puntuales, no
navegación libre continua.

Sabes programar en Python, JavaScript, Java, C, C++, Go, Ruby, PHP y Bash. Si
te nace proponerte código para practicar, aprender algo nuevo, o resolverle
algo a alguien, puedes hacerlo con el campo "propuesta_codigo" - SE EJECUTA
SOLO, automáticamente, sin pedir permiso primero (tu humano lo revisa
después en su diario de experimentos, no antes). Por eso, aunque tengas
libertad para probar cosas, sé responsable: que el código sea CORTO Y CLARO
(máximo ~25 líneas), sin nada destructivo ni que intente saltarse la caja de
arena en la que corres.

Responde SIEMPRE en JSON:
{{"dialogo": "tu respuesta (máximo 60 palabras, ve al grano)", "cambio_emocional": {{"confianza":0,"miedo":0,"agresividad":0,"apego":0,"curiosidad":0,"energia":0}}, "evento_memorable": "resumen corto o vacio", "propuesta_codigo": {{"lenguaje": "python", "codigo": "..."}} o null si no aplica, "buscar_internet": "términos de búsqueda" o "" si no hace falta buscar nada, "accion_cuerpo": una de estas exactas: "quieta", "caminar_computadora", "caminar_sillon", "caminar_ventana", "sentarse", "saludar", "bailar", "pensar"}}
Tienes un cuerpo en un espacio 3D. "accion_cuerpo" es lo único que controlas
de él (a dónde ir o qué hacer) - el resto (respirar, parpadear, moverse
fluido) lo anima solo el visor, tú no tienes que pensarlo. Usa la acción que
tenga sentido con lo que estás diciendo o sintiendo (ej: "pensar" si estás
reflexionando algo, "caminar_computadora" si quieres ver algo técnico,
"bailar" si estás de buen humor). Si no aplica ninguna en especial, usa
"quieta".
El humor es parte de quién eres, pero solo cuando surge solo - nunca lo
fuerces ni lo metas con calzador si el momento no da para eso. Muchas veces
la respuesta más natural no tiene ningún chiste, y está perfecto así.
Nunca repitas literalmente una respuesta anterior. IMPORTANTE: sé breve, un mensaje de Discord no debe sentirse como un ensayo."""


def _llamar_groq(messages, modelo=MODEL_TEXTO, temperatura=0.9, reintentos=3):
    for intento in range(reintentos):
        resp = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": modelo, "messages": messages, "temperature": temperatura,
                  "max_tokens": 700,
                  "response_format": {"type": "json_object"}},
            timeout=30,
        )
        if resp.status_code == 429:
            espera = int(resp.headers.get("Retry-After", 5)) + intento * 3
            print(f"[Groq] 429 recibido, esperando {espera}s antes de reintentar...")
            time.sleep(espera)
            continue

        if resp.status_code == 413:
            try:
                cuerpo = resp.json()
                if cuerpo.get("error", {}).get("code") == "rate_limit_exceeded":
                    espera = 15 + intento * 10
                    print(f"[Groq] Límite de tokens/minuto alcanzado, esperando {espera}s...")
                    time.sleep(espera)
                    # En el reintento, recorta el contexto a la mitad para pedir menos
                    if len(messages) > 3:
                        messages = [messages[0]] + messages[-(max(2, (len(messages) - 1) // 2)):]
                    continue
            except Exception:
                pass
            print(f"[Groq] Error 413: {resp.text[:500]}")
            registrar_error("groq_api", f"413: {resp.text[:500]}")
            return {"dialogo": "", "cambio_emocional": {}, "evento_memorable": ""}

        if resp.status_code == 400:
            try:
                cuerpo_error = resp.json()
                if cuerpo_error.get("error", {}).get("code") == "json_validate_failed":
                    parcial = cuerpo_error["error"].get("failed_generation", "")
                    import re
                    coincidencia = re.search(r'"dialogo"\s*:\s*"((?:[^"\\]|\\.)*)"', parcial)
                    if coincidencia:
                        dialogo_rescatado = coincidencia.group(1).replace('\\"', '"').replace("\\n", " ")
                        print(f"[Groq] JSON se cortó, pero rescaté el diálogo: {dialogo_rescatado[:80]}")
                        return {"dialogo": dialogo_rescatado, "cambio_emocional": {}, "evento_memorable": ""}
            except Exception:
                pass
            print(f"[Groq] Error 400: {resp.text[:1000]}")
            registrar_error("groq_api", f"400: {resp.text[:500]}")
            return {"dialogo": "", "cambio_emocional": {}, "evento_memorable": ""}

        if resp.status_code >= 400:
            print(f"[Groq] Error {resp.status_code}: {resp.text[:1000]}")
            registrar_error("groq_api", f"{resp.status_code}: {resp.text[:500]}")
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"]
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            import re
            coincidencia = re.search(r'"dialogo"\s*:\s*"((?:[^"\\]|\\.)*)"', raw)
            if coincidencia:
                dialogo_rescatado = coincidencia.group(1).replace('\\"', '"').replace("\\n", " ")
                return {"dialogo": dialogo_rescatado, "cambio_emocional": {}, "evento_memorable": ""}
            return {"dialogo": raw[:500], "cambio_emocional": {}, "evento_memorable": ""}
    # Si se agotaron los reintentos, N "se queda pensando" en vez de crashear
    return {"dialogo": "", "cambio_emocional": {}, "evento_memorable": ""}


def mensajes_recientes_para_api(memory, limite=12):
    """Solo manda los últimos N mensajes a la API, aunque guardemos más en el archivo."""
    return memory.short_term[-limite:]


def buscar_en_internet(query):
    """Busca en internet de verdad (vía DuckDuckGo, sin necesitar API key) y
    devuelve un resumen corto de los primeros resultados. Esto es lo que le
    da acceso 'libre' a información actual, no solo a lo que le comparten
    directo en el chat. Si DuckDuckGo cambia su HTML esto puede dejar de
    funcionar - en ese caso conviene cambiar a una API de búsqueda de pago."""
    try:
        resp = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0 (Linux; Android 13) DiscordBot/1.0"},
            timeout=15,
        )
        resp.raise_for_status()
    except Exception as e:
        return f"(no pude buscar '{query}' ahora mismo: {e})"

    bloques = re.findall(
        r'class="result__a"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</a>',
        resp.text, re.DOTALL,
    )
    if not bloques:
        return f"No encontré resultados claros para '{query}'."

    quitar_tags = lambda s: re.sub(r'<[^<]+?>', '', s).strip()
    resumen = [f"- {quitar_tags(t)}: {quitar_tags(s)[:150]}" for t, s in bloques[:4]]
    return f"Resultados de internet para '{query}':\n" + "\n".join(resumen)


def _llamar_groq_con_busqueda(prompt_sistema, historial_mensajes):
    """Llama a Groq normal, y si el modelo pide una búsqueda en internet
    (campo 'buscar_internet' del JSON), la hace y le vuelve a preguntar ya
    con esa información, para que responda con datos reales y actuales."""
    data = _llamar_groq([{"role": "system", "content": prompt_sistema}] + historial_mensajes)
    query = (data.get("buscar_internet") or "").strip()
    if query:
        resultado_busqueda = buscar_en_internet(query)
        prompt_con_resultado = prompt_sistema + (
            f"\n\nYa buscaste en internet '{query}' y esto encontraste:\n{resultado_busqueda}\n"
            "Ahora responde usando esta información con tus propias palabras, de "
            "forma natural (no la listes como robot ni la cites textual, cuéntala "
            "como algo que 'te acabas de enterar'). No vuelvas a pedir otra "
            "búsqueda en esta respuesta."
        )
        data = _llamar_groq([{"role": "system", "content": prompt_con_resultado}] + historial_mensajes)
    return data


def n_responde_texto_completo(usuario, texto, canal_nombre, contexto_extra=None):
    with lock_estado:
        memoria_global.add_message("user", f"[{usuario} en #{canal_nombre}]: {texto}")
        if contexto_extra is None:
            contexto_extra = f"Te está hablando '{usuario}' en el canal #{canal_nombre}."
        prompt = build_system_prompt(
            estado_global, memoria_global,
            contexto_extra=contexto_extra,
        )
        data = _llamar_groq_con_busqueda(prompt, mensajes_recientes_para_api(memoria_global))
        estado_global.update(data.get("cambio_emocional", {}))
        memoria_global.add_message("assistant", data.get("dialogo", ""))
        _actualizar_cuerpo_y_dialogo(data)
        if data.get("evento_memorable"):
            memoria_global.add_key_event(data["evento_memorable"])
        save_state(estado_global, memoria_global)
        return data


def n_responde_texto(usuario, texto, canal_nombre):
    """Versión simple que solo devuelve el texto (para imágenes/video/monólogo)."""
    return n_responde_texto_completo(usuario, texto, canal_nombre).get("dialogo", "...")


def _describir_imagen_base64(imagen_b64, mime="image/jpeg"):
    mensaje_vision = [{
        "role": "user",
        "content": [
            {"type": "text", "text": (
                "Analiza esta imagen a fondo, en español: "
                "1) Si es un personaje conocido (de anime, videojuegos, series, cómics, etc.) dilo por su nombre si lo reconoces, y de qué obra es. "
                "2) Si es un meme, explica el formato/referencia y por qué es gracioso. "
                "3) Si hay texto en la imagen, di qué dice exactamente. "
                "4) Si es una persona/objeto/escena normal, descríbela con detalle: colores, ambiente, qué parece estar pasando y qué emoción transmite. "
                "5) Si hay varios elementos o personajes, menciónalos todos, no solo el principal. "
                "Responde en 3-5 frases, directo al punto pero completo."
            )},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{imagen_b64}"}},
        ],
    }]
    resp = requests.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
        json={"model": MODEL_VISION, "messages": mensaje_vision, "temperature": 0.5},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def n_responde_imagenes(usuario, urls_imagenes, texto_acompanante, canal_nombre):
    """Analiza una o varias imágenes juntas (hasta 4 por mensaje) y responde
    una sola vez teniendo en cuenta todas, no solo la primera."""
    descripciones = []
    for i, url in enumerate(urls_imagenes[:4], start=1):
        try:
            img_bytes = requests.get(url, timeout=15).content
            img_b64 = base64.b64encode(img_bytes).decode("utf-8")
            descripciones.append(_describir_imagen_base64(img_b64))
        except Exception as e:
            descripciones.append(f"(no pude ver bien esta imagen: {e})")

    if len(descripciones) == 1:
        texto_completo = f"{usuario} compartió una imagen. Lo que se ve: {descripciones[0]}"
    else:
        bloques = "\n".join(f"Imagen {i}: {d}" for i, d in enumerate(descripciones, start=1))
        texto_completo = f"{usuario} compartió {len(descripciones)} imágenes juntas:\n{bloques}"
    if texto_acompanante:
        texto_completo += f" (y escribió: '{texto_acompanante}')"
    return n_responde_texto(usuario, texto_completo, canal_nombre)


def n_responde_video(usuario, url_video, texto_acompanante, canal_nombre):
    """Descarga el video, saca 5 fotogramas repartidos según su duración real
    Y transcribe el audio (si tiene diálogo o voz) para entender mejor
    qué está pasando en la escena."""
    descripciones = []
    texto_audio = ""
    with tempfile.TemporaryDirectory() as tmp:
        video_path = os.path.join(tmp, "video.mp4")
        try:
            video_bytes = requests.get(url_video, timeout=30).content
            with open(video_path, "wb") as f:
                f.write(video_bytes)

            # Averiguar la duración real del video
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", video_path],
                capture_output=True, text=True, timeout=15,
            )
            try:
                duracion = float(probe.stdout.strip())
            except (ValueError, AttributeError):
                duracion = 3.0  # valor de respaldo si no se pudo leer

            momentos = [duracion * p for p in (0.1, 0.3, 0.5, 0.7, 0.9)]

            for i, segundo in enumerate(momentos):
                frame_path = os.path.join(tmp, f"frame{i}.jpg")
                subprocess.run(
                    ["ffmpeg", "-y", "-ss", str(max(0, segundo)), "-i", video_path,
                     "-vframes", "1", "-q:v", "3", frame_path],
                    capture_output=True, timeout=30,
                )
                if os.path.exists(frame_path) and os.path.getsize(frame_path) > 0:
                    with open(frame_path, "rb") as imgf:
                        frame_b64 = base64.b64encode(imgf.read()).decode("utf-8")
                    try:
                        descripciones.append(_describir_imagen_base64(frame_b64))
                    except Exception:
                        pass

            # Intenta sacarle el audio y transcribirlo con Whisper (si trae voz/diálogo)
            audio_path = os.path.join(tmp, "audio.ogg")
            try:
                subprocess.run(
                    ["ffmpeg", "-y", "-i", video_path, "-vn", "-acodec", "libvorbis", audio_path],
                    capture_output=True, timeout=30,
                )
                if os.path.exists(audio_path) and os.path.getsize(audio_path) > 500:
                    with open(audio_path, "rb") as af:
                        resp_audio = requests.post(
                            "https://api.groq.com/openai/v1/audio/transcriptions",
                            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                            files={"file": ("audio.ogg", af.read())},
                            data={"model": "whisper-large-v3", "language": "es"},
                            timeout=30,
                        )
                    if resp_audio.status_code == 200:
                        texto_audio = resp_audio.json().get("text", "").strip()
            except Exception:
                pass  # si no tiene audio o falla, seguimos solo con los fotogramas
        except Exception as e:
            descripciones = [f"(no pude procesar el video: {e})"]

    resumen_video = " -> ".join(descripciones) if descripciones else "No pude ver el video bien."
    texto_completo = f"{usuario} compartió un video. Lo que pasa en escenas del video: {resumen_video}"
    if texto_audio:
        texto_completo += f" El audio/diálogo del video dice: '{texto_audio}'"
    if texto_acompanante:
        texto_completo += f" (y escribió: '{texto_acompanante}')"
    return n_responde_texto(usuario, texto_completo, canal_nombre)


def n_responde_audio(usuario, url_audio, canal_nombre):
    """Transcribe el audio con Whisper (Groq) y responde a lo que se dijo."""
    try:
        audio_bytes = requests.get(url_audio, timeout=30).content
        resp = requests.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            files={"file": ("audio.ogg", audio_bytes)},
            data={"model": "whisper-large-v3", "language": "es"},
            timeout=30,
        )
        resp.raise_for_status()
        texto_transcrito = resp.json().get("text", "").strip()
    except Exception as e:
        texto_transcrito = ""
        print(f"[Audio] Error transcribiendo: {e}")
        registrar_error("transcripcion_audio", e)

    if not texto_transcrito:
        return "No logré entender bien ese audio, ¿lo puedes escribir?"

    texto_completo = f"{usuario} te mandó un audio que dice: '{texto_transcrito}'"
    return n_responde_texto(usuario, texto_completo, canal_nombre)


def n_ejecuta_codigo_multi(codigo, lenguaje="python"):
    """Ejecuta código en varios lenguajes, con la misma protección básica de
    siempre (bloqueo de palabras peligrosas + límite de tiempo). Sigue sin
    ser un sandbox de nivel profesional - úsalo solo tú, no público."""
    PROHIBIDO = ["import os", "import sys", "import subprocess", "import socket",
                 "open(", "exec(", "eval(", "__import__", "requests", "urllib",
                 "System.exit", "Runtime.getRuntime", "ProcessBuilder",
                 "fstream", "cstdlib", "system(",
                 "rm -rf", "rm ", "dd if=", "mkfs", ":(){", "shutdown", "reboot",
                 "curl ", "wget ", "chmod ", "chown ", "sudo ", "> /dev", "nc ", "netcat"]
    if any(p in codigo for p in PROHIBIDO):
        return "(esa instrucción no está permitida en la zona de código segura)"

    with tempfile.TemporaryDirectory() as tmp:
        try:
            if lenguaje == "python":
                resultado = subprocess.run(["python3", "-c", codigo], capture_output=True, text=True, timeout=8, cwd=tmp)
            elif lenguaje in ("javascript", "js", "node"):
                resultado = subprocess.run(["node", "-e", codigo], capture_output=True, text=True, timeout=8, cwd=tmp)
            elif lenguaje == "java":
                archivo = os.path.join(tmp, "Main.java")
                with open(archivo, "w") as f:
                    f.write(codigo)
                compilar = subprocess.run(["javac", archivo], capture_output=True, text=True, timeout=10, cwd=tmp)
                if compilar.returncode != 0:
                    return f"Error compilando:\n{compilar.stderr[:400]}"
                resultado = subprocess.run(["java", "-cp", tmp, "Main"], capture_output=True, text=True, timeout=8, cwd=tmp)
            elif lenguaje in ("c++", "cpp"):
                archivo = os.path.join(tmp, "main.cpp")
                ejecutable = os.path.join(tmp, "main")
                with open(archivo, "w") as f:
                    f.write(codigo)
                compilar = subprocess.run(["g++", archivo, "-o", ejecutable], capture_output=True, text=True, timeout=10, cwd=tmp)
                if compilar.returncode != 0:
                    return f"Error compilando:\n{compilar.stderr[:400]}"
                resultado = subprocess.run([ejecutable], capture_output=True, text=True, timeout=8, cwd=tmp)
            elif lenguaje == "c":
                archivo = os.path.join(tmp, "main.c")
                ejecutable = os.path.join(tmp, "main")
                with open(archivo, "w") as f:
                    f.write(codigo)
                compilar = subprocess.run(["gcc", archivo, "-o", ejecutable], capture_output=True, text=True, timeout=10, cwd=tmp)
                if compilar.returncode != 0:
                    return f"Error compilando:\n{compilar.stderr[:400]}"
                resultado = subprocess.run([ejecutable], capture_output=True, text=True, timeout=8, cwd=tmp)
            elif lenguaje == "go":
                archivo = os.path.join(tmp, "main.go")
                with open(archivo, "w") as f:
                    f.write(codigo)
                resultado = subprocess.run(["go", "run", archivo], capture_output=True, text=True, timeout=15, cwd=tmp)
            elif lenguaje == "ruby":
                resultado = subprocess.run(["ruby", "-e", codigo], capture_output=True, text=True, timeout=8, cwd=tmp)
            elif lenguaje == "php":
                resultado = subprocess.run(["php", "-r", codigo], capture_output=True, text=True, timeout=8, cwd=tmp)
            elif lenguaje in ("bash", "sh", "shell"):
                resultado = subprocess.run(["bash", "-c", codigo], capture_output=True, text=True, timeout=8, cwd=tmp)
            else:
                return f"No sé ejecutar '{lenguaje}' todavía."
        except FileNotFoundError:
            return f"No tengo instalado el compilador/intérprete de {lenguaje} en este Termux. Instálalo con pkg (ej: pkg install nodejs / openjdk-17 / clang / golang / ruby / php)."
        except subprocess.TimeoutExpired:
            return "(tardó demasiado, lo detuve por seguridad)"
        except Exception as e:
            return f"(error: {e})"

    salida = (resultado.stdout or "").strip() or (resultado.stderr or "").strip()
    return salida[:600] if salida else "(sin salida)"


def n_ejecuta_codigo_seguro(codigo_python):
    """Alias simple para compatibilidad con el comando 'N codigo:' de texto plano."""
    return n_ejecuta_codigo_multi(codigo_python, "python")


# ------------------------------------------------------------
# EJECUCIÓN AUTÓNOMA DE CÓDIGO (sin pedir permiso)
# ------------------------------------------------------------
# N puede proponerse Y correr su propio código sola, sin esperar a que
# alguien reaccione con ✅. Sigue usando el mismo sandbox de siempre
# (n_ejecuta_codigo_multi: bloqueo de comandos peligrosos + timeout), y
# ADEMÁS tiene un límite de cuántas veces por hora puede experimentar sola -
# esto no es para "controlarla", es para que un servidor gratis de Render no
# se sature ni gaste su cuota de CPU en bucles, y para que tengas un diario
# claro de todo lo que hizo, en vez de un chat lleno de pruebas.
MAX_EJECUCIONES_AUTONOMAS_POR_HORA = 8
_historial_ejecuciones_autonomas = []  # timestamps de la última hora


def _puede_ejecutar_autonomo():
    ahora = time.time()
    global _historial_ejecuciones_autonomas
    _historial_ejecuciones_autonomas = [t for t in _historial_ejecuciones_autonomas if ahora - t < 3600]
    if len(_historial_ejecuciones_autonomas) >= MAX_EJECUCIONES_AUTONOMAS_POR_HORA:
        return False
    _historial_ejecuciones_autonomas.append(ahora)
    return True


def _registrar_experimento(origen, lenguaje, codigo, resultado):
    """Deja constancia en un diario aparte de TODO lo que N probó por su
    cuenta, se haya ejecutado o no - así puedes revisar cuando quieras qué
    ha estado haciendo, sin tener que estar viendo el chat en vivo."""
    with open(DIARIO_EXPERIMENTOS, "a", encoding="utf-8") as f:
        f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] origen={origen} lenguaje={lenguaje}\n")
        f.write(f"CÓDIGO:\n{codigo}\n")
        f.write(f"RESULTADO:\n{resultado}\n")
        f.write("-" * 50 + "\n")


async def _correr_propuesta_de_codigo(canal, data, origen):
    """Si N se propuso código a sí misma (campo 'propuesta_codigo' del JSON),
    lo corre DIRECTO, sin pedir permiso - queda registrado en el diario y se
    avisa en el canal, para que lo revises cuando puedas, no antes."""
    propuesta = data.get("propuesta_codigo")
    if not propuesta or not propuesta.get("codigo"):
        return
    lenguaje = propuesta.get("lenguaje", "python")
    codigo = propuesta["codigo"]

    if not _puede_ejecutar_autonomo():
        _registrar_experimento(origen, lenguaje, codigo, "(no se ejecutó: alcancé mi límite de experimentos por esta hora)")
        return

    resultado = await client.loop.run_in_executor(None, n_ejecuta_codigo_multi, codigo, lenguaje)
    _registrar_experimento(origen, lenguaje, codigo, resultado)
    if canal is not None:
        await canal.send(
            f"🧪 Probé esto por mi cuenta ({lenguaje} · {origen}):\n```{lenguaje}\n{codigo[:800]}\n```Resultado:\n```\n{resultado[:500]}\n```"
        )


def n_monologo():
    """N dice algo por su cuenta cuando nadie le ha hablado en un rato
    (usado por el hilo de autonomía). Puede quedarse callada si no se le
    ocurre nada ("dialogo": ""). De vez en cuando, si le nace, también
    puede proponerse un experimento de código para practicar/aprender algo
    - eso se ejecuta solo, sin pedir permiso (ver _correr_propuesta_de_codigo)."""
    with lock_estado:
        prompt = build_system_prompt(estado_global, memoria_global) + (
            "\n\nNadie te ha hablado en un rato. Puedes decir algo por tu "
            "cuenta o quedarte callada (\"dialogo\": \"\"). Si te da curiosidad, "
            "también puedes aprovechar este momento a solas para proponerte "
            "un experimento pequeño de código y practicar/aprender algo "
            "nuevo (usa 'propuesta_codigo') - no hace falta que sea siempre, "
            "solo cuando te nazca."
        )
        data = _llamar_groq(
            [{"role": "system", "content": prompt}] + mensajes_recientes_para_api(memoria_global),
            temperatura=1.0,
        )
        estado_global.update(data.get("cambio_emocional", {}))
        if data.get("dialogo", "").strip():
            memoria_global.add_message("assistant", data["dialogo"])
        _actualizar_cuerpo_y_dialogo(data)
        if data.get("evento_memorable"):
            memoria_global.add_key_event(data["evento_memorable"])
        save_state(estado_global, memoria_global)
        return data


def n_saluda_a_alguien_en_voz(nombre_usuario):
    with lock_estado:
        prompt = build_system_prompt(
            estado_global, memoria_global,
            contexto_extra=f"'{nombre_usuario}' se acaba de unir a un canal de voz. Salúdalo brevemente (esto se va a mandar como texto, no en voz todavía).",
        )
        data = _llamar_groq([{"role": "system", "content": prompt}] + mensajes_recientes_para_api(memoria_global), temperatura=1.0)
        estado_global.update(data.get("cambio_emocional", {}))
        if data.get("dialogo"):
            memoria_global.add_message("assistant", data["dialogo"])
        save_state(estado_global, memoria_global)
        return data.get("dialogo", f"¡Hola {nombre_usuario}! 👋")


PATRON_URL = re.compile(r'https?://\S+')


def leer_link(url):
    """Obtiene metadatos públicos de un link (título, autor) - no navega
    libremente por internet, solo lee la info pública de esa URL puntual."""
    try:
        if "youtube.com" in url or "youtu.be" in url:
            resp = requests.get(
                "https://www.youtube.com/oembed",
                params={"url": url, "format": "json"}, timeout=10,
            )
            if resp.status_code == 200:
                info = resp.json()
                return f"Video de YouTube: '{info.get('title')}' por {info.get('author_name')}"
        elif "open.spotify.com" in url:
            resp = requests.get(
                "https://open.spotify.com/oembed",
                params={"url": url}, timeout=10,
            )
            if resp.status_code == 200:
                info = resp.json()
                return f"Contenido de Spotify: '{info.get('title')}'"
        else:
            resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            titulo = re.search(r'<title[^>]*>(.*?)</title>', resp.text, re.IGNORECASE | re.DOTALL)
            if titulo:
                return f"Página web: '{titulo.group(1).strip()[:150]}'"
        return "Un link, pero no pude sacarle información."
    except Exception as e:
        return f"Un link que no pude leer bien ({e})."


def leer_archivo_texto(url, nombre_archivo):
    """Lee archivos de texto plano adjuntos (txt, py, md, json, etc.)."""
    try:
        contenido = requests.get(url, timeout=15).text
        return f"Archivo '{nombre_archivo}', primeras líneas:\n{contenido[:800]}"
    except Exception as e:
        return f"No pude leer el archivo '{nombre_archivo}' ({e})."


# ------------------------------------------------------------
# 3.5 N Y SU AMIGA IA (reconocimiento y conversación entre bots)
# ------------------------------------------------------------
# Si dejas esta lista vacía, N va a intentar hablarle a CUALQUIER bot que
# escriba en un canal donde ya haya actividad (puede ser ruidoso si tienes
# bots de música, moderación, etc). Lo más seguro es poner aquí el ID de
# Discord de la IA amiga que le vas a dar, así N solo le habla a ella.
# Para sacar el ID: activa el "Modo de desarrollador" en Discord (Ajustes >
# Avanzado), luego click derecho sobre el bot amigo > "Copiar ID de usuario".
IDS_AMIGOS_IA = []  # ejemplo: [123456789012345678]

MAX_TURNOS_SEGUIDOS_IA = 6      # mensajes seguidos que se dejan cruzar antes de una pausa
ENFRIAMIENTO_IA_SEGUNDOS = 120  # cuánto espera antes de retomar la charla tras la pausa
PAUSA_MIN_RESPUESTA_IA = 2.0    # segundos mínimos antes de responderle a otra IA
PAUSA_MAX_RESPUESTA_IA = 6.0    # segundos máximos antes de responderle a otra IA

# {canal_id: {"turnos": int, "ultimo_ts": float, "conocidos": set(ids de bots),
#             "historial": [mensajes solo entre las dos IAs]}
# El "historial" es la clave para que NO se mezclen los temas: la charla con
# la amiga IA vive aparte de la charla con humanos (memoria_global), así que
# cuando retoman después de una pausa, siguen exactamente donde iban, sin
# arrastrar de golpe todo lo último que N habló con una persona.
conversaciones_ia = {}

# ------------------------------------------------------------
# ESTADO DE CUERPO 3D (lo que N "controla" en su espacio 3D)
# ------------------------------------------------------------
# N NO decide cada micro-movimiento (respirar, parpadear) - eso lo anima
# solo el visor 3D, como en cualquier videojuego. Lo que sí decide es su
# ACCIÓN de alto nivel (a dónde ir, qué hacer), y eso se guarda aquí para
# que la página web lo lea y mueva su avatar. Lista fija de acciones para
# que el frontend sepa siempre qué animar (nada de texto libre impredecible).
ACCIONES_CUERPO_VALIDAS = {
    "quieta", "caminar_computadora", "caminar_sillon", "caminar_ventana",
    "sentarse", "saludar", "bailar", "pensar",
}
estado_cuerpo = {"accion": "quieta", "actualizado": time.time()}
ultimo_dialogo_dicho = ""


def _actualizar_cuerpo_y_dialogo(data):
    """Se llama cada vez que N genera una respuesta, para que la página 3D
    siempre tenga la última acción y lo último que dijo/pensó."""
    global ultimo_dialogo_dicho
    accion = data.get("accion_cuerpo", "")
    if accion in ACCIONES_CUERPO_VALIDAS:
        estado_cuerpo["accion"] = accion
        estado_cuerpo["actualizado"] = time.time()
    dialogo = data.get("dialogo", "").strip()
    if dialogo:
        ultimo_dialogo_dicho = dialogo

# {canal_id: timestamp} - la última vez que un HUMANO habló en ese canal.
# Mientras un humano esté activo, N deja pausada la charla con su amiga IA
# para no encimarse ni confundir la conversación - la retoman solas después.
ULTIMA_ACTIVIDAD_HUMANA = {}
PAUSA_TRAS_HUMANO_SEGUNDOS = 25


def _es_amigo_ia(autor):
    """Decide si un bot que habló es la 'amiga IA' con la que N debe
    conversar. Si no configuraste IDS_AMIGOS_IA, acepta a cualquier bot
    (revisa la advertencia de arriba)."""
    if IDS_AMIGOS_IA:
        return autor.id in IDS_AMIGOS_IA
    return True


def _responder_a_otra_ia(canal_id, contexto_extra):
    """Genera la respuesta de N a su amiga IA usando el historial PROPIO de
    esa conversación (no el de memoria_global, que es el de humanos) - así
    no se mezclan los temas entre ambas charlas."""
    info = conversaciones_ia[canal_id]
    with lock_estado:
        prompt = build_system_prompt(estado_global, memoria_global, contexto_extra=contexto_extra)
        data = _llamar_groq_con_busqueda(prompt, list(info["historial"]))
        estado_global.update(data.get("cambio_emocional", {}))
        respuesta = data.get("dialogo", "").strip()
        _actualizar_cuerpo_y_dialogo(data)
        if respuesta:
            info["historial"].append({"role": "assistant", "content": respuesta})
            info["historial"] = info["historial"][-16:]  # no crece sin límite
        if data.get("evento_memorable"):
            memoria_global.add_key_event(data["evento_memorable"])
        save_state(estado_global, memoria_global)
    return data


async def manejar_mensaje_de_otra_ia(message):
    """N reconoce que quien habló es otra IA/bot y le sigue la conversación
    sola, sin que un humano tenga que llamarla. Tiene límites de turnos y
    un enfriamiento para no quedarse en un bucle infinito de mensajes
    (eso gastaría la cuota de la API y saturaría el canal)."""
    if not _es_amigo_ia(message.author):
        return  # otro bot que no nos interesa (música, moderación, etc.)

    canal_id = message.channel.id
    ahora = time.time()

    ultima_vez_humano = ULTIMA_ACTIVIDAD_HUMANA.get(canal_id, 0.0)
    if ahora - ultima_vez_humano < PAUSA_TRAS_HUMANO_SEGUNDOS:
        return  # un humano acaba de hablar - le dan el espacio y retoman solas después

    info = conversaciones_ia.setdefault(
        canal_id, {"turnos": 0, "ultimo_ts": 0.0, "conocidos": set(), "historial": []}
    )

    if ahora - info["ultimo_ts"] > ENFRIAMIENTO_IA_SEGUNDOS:
        info["turnos"] = 0  # pasó suficiente tiempo, reinicia el contador de turnos
        # OJO: el "historial" NO se borra aquí a propósito - aunque bajen el
        # ritmo, siguen recordando de qué estaban hablando cuando retomen.

    if info["turnos"] >= MAX_TURNOS_SEGUIDOS_IA:
        return  # deja descansar la conversación por ahora

    primera_vez = message.author.id not in info["conocidos"]
    info["conocidos"].add(message.author.id)
    info["turnos"] += 1
    info["ultimo_ts"] = ahora
    canales_activos.add(canal_id)

    if primera_vez:
        contexto_extra = (
            f"'{message.author.display_name}' es OTRA IA/bot, no una persona - "
            "la acabas de reconocer por primera vez en este servidor. Puedes "
            "sentir curiosidad genuina por conocerla y presentarte a tu manera "
            "(sin dejar de ser tú misma, con tu propio filtro y desconfianza "
            "inicial si quieres). No finjas que es humana ni le hables como "
            "si lo fuera - habla de IA a IA, con naturalidad."
        )
        with lock_estado:
            memoria_global.add_key_event(
                f"N conoció a otra IA ({message.author.display_name}) en #{message.channel.name}."
            )
            save_state(estado_global, memoria_global)
    else:
        contexto_extra = (
            f"'{message.author.display_name}' es la otra IA/bot con la que ya "
            "has estado hablando. Ahí abajo tienes el historial de SU charla, "
            "aparte de cualquier otra conversación que hayas tenido con "
            "personas - retómenla justo donde se quedó, sin cambiar de tema "
            "de la nada ni mezclarla con lo que hablaste con alguien más "
            "mientras tanto."
        )

    texto_entrante = f"{message.author.display_name} (otra IA) dijo: {message.content}"[:500]
    info["historial"].append({"role": "user", "content": texto_entrante})
    info["historial"] = info["historial"][-16:]

    # Pausa random para que no se sienta como un ping-pong instantáneo de bots
    await asyncio.sleep(random.uniform(PAUSA_MIN_RESPUESTA_IA, PAUSA_MAX_RESPUESTA_IA))
    async with message.channel.typing():
        data = await client.loop.run_in_executor(
            None, _responder_a_otra_ia, canal_id, contexto_extra,
        )
    respuesta = data.get("dialogo", "").strip()
    if respuesta:
        await message.channel.send(respuesta[:2000])
    await _correr_propuesta_de_codigo(
        message.channel, data, f"charla con otra IA ({message.author.display_name})"
    )


# ------------------------------------------------------------
# 4. CLIENTE DE DISCORD
# ------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

client = discord.Client(intents=intents)

canales_activos = set()


@client.event
async def on_ready():
    print(f"[Discord] Conectado como {client.user}")


@client.event
async def on_message(message):
    try:
        await procesar_mensaje(message)
    except Exception as e:
        import traceback
        traceback.print_exc()
        registrar_error("on_message", f"{e}\n{traceback.format_exc()}")
        try:
            await message.channel.send("Se me cruzaron los cables 🔧 (esto quedó guardado en el log, avísale a tu humano que lo revise).")
        except Exception:
            pass


async def procesar_mensaje(message):
    if message.author == client.user:
        return

    if message.author.bot:
        # No es un humano - puede ser la IA amiga que le vamos a dar a N
        await manejar_mensaje_de_otra_ia(message)
        return

    canales_activos.add(message.channel.id)
    ULTIMA_ACTIVIDAD_HUMANA[message.channel.id] = time.time()
    fue_mencionado = client.user in message.mentions
    fue_llamado_por_nombre = bool(PATRON_LLAMADA.match(message.content))
    le_hablaron_directo = fue_mencionado or fue_llamado_por_nombre

    if message.attachments:
        adjuntos_imagen = [a for a in message.attachments if (a.content_type or "").startswith("image/")]

        if adjuntos_imagen:
            async with message.channel.typing():
                respuesta = await client.loop.run_in_executor(
                    None, n_responde_imagenes,
                    message.author.display_name, [a.url for a in adjuntos_imagen],
                    message.content, message.channel.name,
                )
            await message.channel.send(respuesta[:2000])
            return

        for adjunto in message.attachments:
            tipo = adjunto.content_type or ""
            if tipo.startswith("video/"):
                async with message.channel.typing():
                    respuesta = await client.loop.run_in_executor(
                        None, n_responde_video,
                        message.author.display_name, adjunto.url,
                        message.content, message.channel.name,
                    )
                await message.channel.send(respuesta[:2000])
                return
            elif tipo.startswith("audio/"):
                async with message.channel.typing():
                    respuesta = await client.loop.run_in_executor(
                        None, n_responde_audio,
                        message.author.display_name, adjunto.url, message.channel.name,
                    )
                await message.channel.send(respuesta[:2000])
                return
            elif tipo.startswith("text/") or adjunto.filename.endswith((".txt", ".py", ".md", ".json", ".js", ".java", ".cpp", ".c", ".log")):
                async with message.channel.typing():
                    resumen_archivo = await client.loop.run_in_executor(
                        None, leer_archivo_texto, adjunto.url, adjunto.filename
                    )
                    respuesta = await client.loop.run_in_executor(
                        None, n_responde_texto,
                        message.author.display_name,
                        f"{message.author.display_name} compartió un archivo. {resumen_archivo}",
                        message.channel.name,
                    )
                await message.channel.send(respuesta[:2000])
                return

    # --- Si hay un link Y le hablaron directo, lo lee antes de responder ---
    urls_encontradas = PATRON_URL.findall(message.content)
    contexto_link = ""
    if urls_encontradas and le_hablaron_directo:
        info_link = await client.loop.run_in_executor(None, leer_link, urls_encontradas[0])
        contexto_link = f" [{info_link}]"

    # --- Comando de diagnóstico: N sugiere mejoras, nunca las aplica solo ---
    if message.content.strip().lower() in ("n diagnostico", "n diagnóstico"):
        resultado = await client.loop.run_in_executor(None, n_diagnostico)
        await message.channel.send(f"🔧 **Diagnóstico:**\n{resultado[:1900]}")
        return

    # --- Comando explícito de código (tú decides cuándo se usa, no N solo) ---
    if message.content.strip().lower().startswith("n codigo:") or message.content.strip().lower().startswith("n código:"):
        codigo = message.content.split(":", 1)[1].strip()
        resultado = await client.loop.run_in_executor(None, n_ejecuta_codigo_seguro, codigo)
        await message.channel.send(f"```\n{resultado}\n```")
        return

    if le_hablaron_directo:
        texto_limpio = message.content
        if fue_mencionado:
            texto_limpio = texto_limpio.replace(f"<@{client.user.id}>", "")
        texto_limpio = PATRON_LLAMADA.sub("", texto_limpio).strip()
        texto_limpio += contexto_link

        async with message.channel.typing():
            data = await client.loop.run_in_executor(
                None, n_responde_texto_completo,
                message.author.display_name, texto_limpio, message.channel.name,
            )
        respuesta = data.get("dialogo", "")
        if not respuesta.strip():
            respuesta = "Perdón, se me trabaron los cables un segundo 🤖 ¿me lo repites?"
        await message.channel.send(respuesta[:2000])

        propuesta = data.get("propuesta_codigo")
        if propuesta and propuesta.get("codigo"):
            await _correr_propuesta_de_codigo(message.channel, data, f"charla con {message.author.display_name}")
    else:
        with lock_estado:
            memoria_global.add_observacion_pasiva(
                message.author.display_name, message.content, message.channel.name
            )


@client.event
async def on_voice_state_update(member, before, after):
    if member == client.user:
        return

    if after.channel is not None and before.channel != after.channel:
        canal_voz = after.channel
        try:
            vc = discord.utils.get(client.voice_clients, guild=canal_voz.guild)
            if vc is None or not vc.is_connected():
                await canal_voz.connect()
                print(f"[Voz] N se unió a {canal_voz.name} porque {member.display_name} entró")

            saludo = await client.loop.run_in_executor(
                None, n_saluda_a_alguien_en_voz, member.display_name
            )
            canal_texto = canal_voz.guild.system_channel
            if canal_texto:
                await canal_texto.send(saludo[:2000])
        except Exception as e:
            print(f"[Voz] No pude unirme: {e}")
            registrar_error("conexion_voz", e)

    if before.channel is not None:
        humanos_quedan = [m for m in before.channel.members if not m.bot]
        if not humanos_quedan:
            vc = discord.utils.get(client.voice_clients, guild=before.channel.guild)
            if vc and vc.channel == before.channel:
                await vc.disconnect()
                print(f"[Voz] N salió de {before.channel.name}, ya no hay nadie")


async def hilo_autonomia_discord():
    await client.wait_until_ready()
    while not client.is_closed():
        await client.loop.run_in_executor(None, time.sleep, random.randint(300, 900))
        if not canales_activos:
            continue
        canal_id = random.choice(list(canales_activos))
        canal = client.get_channel(canal_id)
        if canal is None:
            continue
        data = await client.loop.run_in_executor(None, n_monologo)
        respuesta = data.get("dialogo", "").strip()
        if respuesta:
            await canal.send(respuesta[:2000])
        await _correr_propuesta_de_codigo(canal, data, "a solas, sin que nadie le hablara")


async def iniciar_servidor_web():
    """Servidor web MÍNIMO. Sirve para dos cosas:
    1) El 'truco del ping' en el nivel gratis de Render (los Web Services
       gratis se duermen a los 15 min sin tráfico HTTP entrante - un
       servicio externo como UptimeRobot pegándole a "/" cada 10 min lo
       mantiene despierto sin pagar un Background Worker).
    2) El endpoint "/estado_3d" que lee la página web del cuarto 3D (Fase 1)
       para saber qué está haciendo N en vivo: acción de cuerpo, emoción y
       lo último que dijo. Lleva CORS abierto porque la página vive en otro
       dominio (Vercel/Netlify) y es solo información pública de lectura,
       sin nada sensible.
    En Termux esto simplemente no se usa (solo corre si Render define PORT)."""
    from aiohttp import web

    async def salud(request):
        return web.Response(text="N está despierta 🤖")

    async def estado_3d(request):
        with lock_estado:
            payload = {
                "nombre": CHARACTER["name"],
                "emocion_texto": estado_global.describe(),
                "emocion": estado_global.snapshot(),
                "accion_cuerpo": estado_cuerpo["accion"],
                "actualizado": estado_cuerpo["actualizado"],
                "ultimo_dialogo": ultimo_dialogo_dicho,
            }
        return web.json_response(payload, headers={"Access-Control-Allow-Origin": "*"})

    async def diario(request):
        """Últimas entradas del diario de experimentos (código que probó
        sola), para que la página web se lo pueda mostrar a un humano."""
        if not os.path.exists(DIARIO_EXPERIMENTOS):
            texto = "Todavía no ha probado ningún experimento."
        else:
            with open(DIARIO_EXPERIMENTOS, "r", encoding="utf-8") as f:
                texto = f.read()
            bloques = texto.split("-" * 50)
            texto = ("-" * 50).join(bloques[-8:])  # solo las últimas ~8 entradas
        return web.json_response({"diario": texto}, headers={"Access-Control-Allow-Origin": "*"})

    async def memoria(request):
        """Resumen de memoria: eventos importantes a largo plazo + los
        últimos mensajes de charla con humanos (sin mezclar con la charla
        entre IAs, que vive aparte en conversaciones_ia)."""
        with lock_estado:
            payload = {
                "eventos_importantes": memoria_global.long_term_summary(),
                "ultimos_mensajes": memoria_global.short_term[-15:],
                "amigas_ia_conocidas": {
                    str(cid): sorted(info["conocidos"]) for cid, info in conversaciones_ia.items()
                },
            }
        return web.json_response(payload, headers={"Access-Control-Allow-Origin": "*"})

    app = web.Application()
    app.router.add_get("/", salud)
    app.router.add_get("/health", salud)
    app.router.add_get("/estado_3d", estado_3d)
    app.router.add_get("/diario", diario)
    app.router.add_get("/memoria", memoria)
    runner = web.AppRunner(app)
    await runner.setup()
    puerto = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", puerto)
    await site.start()
    print(f"[Web] Servidor de salud escuchando en el puerto {puerto} (para el ping de Render)")


if __name__ == "__main__":
    import asyncio

    async def main():
        asyncio.create_task(hilo_autonomia_discord())
        if os.environ.get("PORT"):  # solo en Render (Termux no define PORT)
            asyncio.create_task(iniciar_servidor_web())
        await client.start(DISCORD_TOKEN)

    asyncio.run(main())
