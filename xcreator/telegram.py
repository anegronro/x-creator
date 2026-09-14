"""Cola de aprobación por Telegram: cada borrador llega con botones.

Bot PROPIO de este proyecto. No hay fallback a ningún `TELEGRAM_BOT_TOKEN`
genérico a propósito: un fallback silencioso mandaría estos posts al chat de
otro agente (forex, opciones), que es justo el cruce que hay que evitar.

No hay webhook ni proceso permanente: se usa long-polling con `getUpdates` y
un offset persistido, así corre por cron igual que el resto de la infra.

Flujo:
- `enviar_pendientes` manda cada borrador con ✅ / ✏️ / ❌.
- `procesar_updates` lee los toques y mueve el estado en la cola.
- Editar: el bot pide el texto con `force_reply`; tu respuesta se guarda
  como texto editado Y aprueba el borrador de una vez.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

API = "https://api.telegram.org/bot{token}/{method}"
TIMEOUT = 30.0


class TelegramError(RuntimeError):
    """Falla de configuración o de la API. Nunca se traga en silencio."""


@dataclass
class Bot:
    """Cliente mínimo de la Bot API. Nunca imprime el token."""

    token: str
    chat_id: str

    def _call(self, method: str, **payload) -> dict:
        try:
            r = httpx.post(
                API.format(token=self.token, method=method),
                json=payload, timeout=TIMEOUT,
            )
        except httpx.HTTPError as e:
            raise TelegramError(f"{method}: sin conexión ({type(e).__name__})") from e
        try:
            data = r.json()
        except ValueError:
            raise TelegramError(f"{method}: respuesta no-JSON (HTTP {r.status_code})")
        if not data.get("ok"):
            # El mensaje de Telegram puede traer el token en la URL, nunca en
            # el cuerpo — este texto es seguro de mostrar.
            raise TelegramError(
                f"{method}: {data.get('description', 'error desconocido')} "
                f"(HTTP {r.status_code})"
            )
        return data.get("result", {})

    def me(self) -> dict:
        return self._call("getMe")

    def send(self, texto: str, *, botones: list | None = None,
             force_reply: bool = False) -> dict:
        payload: dict[str, Any] = {"chat_id": self.chat_id, "text": texto,
                                   "disable_web_page_preview": True}
        if botones:
            payload["reply_markup"] = {"inline_keyboard": botones}
        elif force_reply:
            payload["reply_markup"] = {"force_reply": True, "selective": True}
        return self._call("sendMessage", **payload)

    def send_photo(self, imagen: Path, texto: str,
                   *, botones: list | None = None) -> dict:
        """Manda una foto con pie y botones. El pie de Telegram va hasta 1024
        caracteres: lo que sobra se recorta, porque el texto completo ya está
        en la cola y lo que importa aquí es decidir con la imagen delante."""
        import json as _json

        datos: dict[str, Any] = {"chat_id": self.chat_id,
                                 "caption": texto[:1024]}
        if botones:
            datos["reply_markup"] = _json.dumps({"inline_keyboard": botones})
        try:
            with imagen.open("rb") as fh:
                r = httpx.post(
                    API.format(token=self.token, method="sendPhoto"),
                    data=datos, files={"photo": (imagen.name, fh, "image/png")},
                    timeout=TIMEOUT)
        except httpx.HTTPError as e:
            raise TelegramError(f"sendPhoto: sin conexión ({type(e).__name__})") from e
        try:
            d = r.json()
        except ValueError:
            raise TelegramError(f"sendPhoto: respuesta no-JSON (HTTP {r.status_code})")
        if not d.get("ok"):
            raise TelegramError(f"sendPhoto: {d.get('description', 'error')}")
        return d.get("result", {})

    def answer_callback(self, callback_id: str, texto: str = "") -> None:
        """Quita el "cargando" del botón. Cosmético, y caduca en segundos.

        El ciclo corre por cron cada 5 minutos, así que que este acuse llegue
        tarde es lo NORMAL. Fallar aquí no puede costar una aprobación.
        """
        try:
            self._call("answerCallbackQuery", callback_query_id=callback_id,
                       text=texto)
        except TelegramError:
            pass

    def quitar_botones(self, message_id: int, nuevo_texto: str | None = None) -> None:
        """Deja el mensaje sin botones para que no se pueda votar dos veces."""
        try:
            if nuevo_texto is not None:
                self._call("editMessageText", chat_id=self.chat_id,
                           message_id=message_id, text=nuevo_texto,
                           disable_web_page_preview=True)
            else:
                self._call("editMessageReplyMarkup", chat_id=self.chat_id,
                           message_id=message_id)
        except TelegramError:
            pass  # cosmético: si falla, el estado en la cola ya es correcto

    def updates(self, offset: int | None = None) -> list[dict]:
        p: dict[str, Any] = {"timeout": 0,
                             "allowed_updates": ["callback_query", "message"]}
        if offset is not None:
            p["offset"] = offset
        res = self._call("getUpdates", **p)
        return res if isinstance(res, list) else []


# Un token de bot es "<id numérico>:<hash>". Pegar solo el hash, o pegar el
# id del bot en el campo del chat, son los dos errores de copiado habituales
# y ambos fallan después con un mensaje inútil de la API.
_TOKEN_RE = re.compile(r"\d{6,15}:[A-Za-z0-9_-]{30,}")


def revisar_credenciales(settings) -> list[str]:
    """Problemas de FORMATO detectables sin llamar a la API."""
    avisos = []
    t = (settings.telegram_bot_token or "").strip()
    if t and not _TOKEN_RE.fullmatch(t):
        if t.isdigit():
            avisos.append(
                "TELEGRAM_X_BOT_TOKEN son solo dígitos: eso es el id del bot, "
                "no el token. El token completo es '<id>:<hash>'."
            )
        elif ":" not in t:
            avisos.append(
                f"TELEGRAM_X_BOT_TOKEN ({len(t)} caracteres) no lleva el "
                f"prefijo '<id>:'. Parece que se copió solo la segunda mitad."
            )
        else:
            avisos.append("TELEGRAM_X_BOT_TOKEN no tiene forma de token.")
    c = str(settings.telegram_chat_id or "").strip()
    if c and not (c.lstrip("-").isdigit() or c.startswith("@")):
        avisos.append("TELEGRAM_X_CHAT_ID debería ser numérico (o @canal).")
    return avisos


def bot_desde(settings) -> Bot:
    """Construye el bot o explica exactamente qué falta."""
    problemas = revisar_credenciales(settings)
    if problemas:
        raise TelegramError(" | ".join(problemas))
    if not settings.telegram_bot_token:
        raise TelegramError(
            "Falta TELEGRAM_X_BOT_TOKEN en API/.env. Créalo con @BotFather "
            "(/newbot) — tiene que ser un bot NUEVO, propio de este proyecto."
        )
    if not settings.telegram_chat_id:
        raise TelegramError(
            "Falta TELEGRAM_X_CHAT_ID (o TELEGRAM_CHAT_ID) en API/.env. "
            "Escríbele algo al bot y corre `xc telegram setup`."
        )
    return Bot(settings.telegram_bot_token, str(settings.telegram_chat_id))


# --- estado del polling ---------------------------------------------------

@dataclass
class Estado:
    """Offset de `getUpdates` y ediciones en curso, en disco."""

    path: Path

    def load(self) -> dict:
        if not self.path.exists():
            return {"offset": None, "esperando_edicion": {}}
        try:
            d = json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return {"offset": None, "esperando_edicion": {}}
        d.setdefault("esperando_edicion", {})
        return d

    def save(self, d: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(d, indent=2))


# --- render ---------------------------------------------------------------

def _texto_item(item) -> str:
    piezas = [item.texto, *item.hilo]
    cuerpo = "\n\n".join(
        (f"{n}/ {p}" if len(piezas) > 1 else p) for n, p in enumerate(piezas, 1)
    )
    cab = f"{item.ticker} · {item.kind} · {len(item.texto)}c"
    if item.responde_a:
        cab = f"RESPUESTA a {item.responde_a} · " + cab
    if len(piezas) > 1:
        cab += f" · hilo de {len(piezas)}"
    partes = [cab, "", cuerpo]
    partes += ["", "— lo de arriba es lo que se publica; lo de abajo son notas —"]
    if item.approach:
        partes += [f"ángulo: {item.approach}"]
    if item.reply_hook:
        partes += [f"gancho: {item.reply_hook}"]
    avisos = []
    if item.numeros_no_justificados:
        avisos.append(f"CIFRAS SIN FUENTE: {', '.join(item.numeros_no_justificados)}")
    if getattr(item, "truncado", False):
        avisos.append("TEXTO CORTADO a media frase")
    if getattr(item, "idioma_incorrecto", False):
        avisos.append("NO ESTÁ EN INGLÉS")
    if getattr(item, "tickers_faltantes", None):
        avisos.append(f"FALTA EL TICKER: {', '.join(item.tickers_faltantes)}")
    if avisos:
        partes += ["", "⚠️ " + " | ".join(avisos)]
    return "\n".join(partes)


def _botones(item_id: str) -> list:
    return [[
        {"text": "✅ Aprobar", "callback_data": f"ok:{item_id}"},
        {"text": "✏️ Editar", "callback_data": f"ed:{item_id}"},
        {"text": "❌ Descartar", "callback_data": f"no:{item_id}"},
    ]]


# --- acciones -------------------------------------------------------------

def enviar_pendientes(queue, bot: Bot, *, limite: int = 10) -> int:
    """Manda los pendientes que aún no se enviaron. Devuelve cuántos.

    El filtro va ANTES del límite: al revés, si los primeros de la cola ya
    estaban en el teléfono, el límite se consumía con ellos y los borradores
    nuevos no salían nunca.
    """
    sin_enviar = [i for i in queue.pendientes()
                  if not i.metricas.get("telegram_message_id")]
    n = 0
    for item in sin_enviar[:limite]:
        imagen = Path(item.imagen) if item.imagen else None
        if imagen is not None and imagen.exists():
            # Con gráfico se manda la foto: aprobar una imagen sin verla es
            # aprobar a ciegas.
            res = bot.send_photo(imagen, _texto_item(item),
                                 botones=_botones(item.id))
        else:
            res = bot.send(_texto_item(item), botones=_botones(item.id))
        queue.update(item.id, metricas={**item.metricas,
                                        "telegram_message_id": res.get("message_id")})
        n += 1
    return n


def procesar_updates(queue, bot: Bot, estado: Estado) -> list[str]:
    """Aplica los toques de botón y las ediciones. Devuelve un log legible."""
    st = estado.load()
    log: list[str] = []
    updates = bot.updates(st.get("offset"))

    for up in updates:
        st["offset"] = up["update_id"] + 1
        # Un update que falle no puede llevarse por delante los que vienen
        # detrás en la misma tanda. El offset ya avanzó, así que tampoco se
        # reprocesa en bucle.
        try:
            _procesar_uno(up, queue, bot, st, log)
        except Exception as e:  # noqa: BLE001 - robustez deliberada
            log.append(f"update {up.get('update_id')} falló: {e}")

    estado.save(st)
    return log


def _procesar_uno(up: dict, queue, bot: Bot, st: dict, log: list[str]) -> None:
    """Aplica UN update. Aislado para que su fallo no contamine la tanda."""
    if True:
        cb = up.get("callback_query")
        if cb:
            data = cb.get("data", "")
            accion, _, item_id = data.partition(":")
            item = queue.get(item_id)
            if item is None:
                bot.answer_callback(cb["id"], "Ese borrador ya no existe.")
                return
            msg_id = (cb.get("message") or {}).get("message_id")

            if accion == "ok":
                queue.aprobar(item_id)
                bot.answer_callback(cb["id"], "Aprobado")
                bot.quitar_botones(msg_id, _texto_item(item) + "\n\n✅ APROBADO")
                log.append(f"{item_id} aprobado")
            elif accion == "no":
                queue.rechazar(item_id, motivo="descartado desde Telegram")
                bot.answer_callback(cb["id"], "Descartado")
                bot.quitar_botones(msg_id, _texto_item(item) + "\n\n❌ DESCARTADO")
                log.append(f"{item_id} descartado")
            elif accion == "ed":
                bot.answer_callback(cb["id"], "Respóndeme con el texto nuevo")
                pedido = bot.send(
                    f"Responde a ESTE mensaje con el texto corregido de "
                    f"{item.ticker} ({item_id}).", force_reply=True,
                )
                st["esperando_edicion"][str(pedido["message_id"])] = item_id
                log.append(f"{item_id} esperando edición")
            return

        msg = up.get("message")
        if msg and msg.get("reply_to_message"):
            origen = str(msg["reply_to_message"].get("message_id"))
            item_id = st["esperando_edicion"].pop(origen, None)
            if item_id:
                nuevo = (msg.get("text") or "").strip()
                if nuevo:
                    # Editar es aprobar: si te tomaste el trabajo de
                    # reescribirlo, lo quieres publicado.
                    queue.aprobar(item_id, texto_editado=nuevo)
                    bot.send(f"✅ {item_id} actualizado y aprobado ({len(nuevo)}c).")
                    log.append(f"{item_id} editado y aprobado")
                else:
                    bot.send("No entendí el texto. El borrador sigue pendiente.")
