"""Publicación en X. El último paso, y el único irreversible.

Reglas que no dependen de que nadie se acuerde:

1. **Solo se publica lo aprobado.** Un borrador en `pendiente` o `rechazado`
   no se publica ni por error de tipeo: se comprueba el estado aquí, no en
   el CLI.
2. **Se revalida justo antes de publicar.** Entre la aprobación y el envío
   pudo editarse el texto; las cifras sin fuente, el largo y el idioma se
   comprueban otra vez sobre el texto FINAL.
3. **Los links cuestan 13x** ($0.20 vs $0.015) y hunden el alcance, así que
   publicar uno exige decirlo explícitamente.
4. **Idempotencia.** Un item ya publicado no se vuelve a publicar aunque se
   corra el comando dos veces: duplicar un post en X es caro y feo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import httpx

from xcreator.generate import (
    MAX_CHARS, SIN_HISTORIAL, afirma_llamada_propia, cifras_mal_formateadas,
    es_ingles, falta_sujeto, falta_ticker, lleva_raya, validate_numbers,
)

POST_URL = "https://api.x.com/2/tweets"
MEDIA_URL = "https://api.x.com/2/media/upload"
# X rechaza imágenes por encima de esto; los gráficos pesan ~100 KB.
MAX_BYTES_IMAGEN = 5 * 1024 * 1024
COSTO_POST = 0.015
COSTO_POST_CON_LINK = 0.20
_URL = re.compile(r"https?://\S+|\bt\.co/\S+")

# Época de los IDs de X (snowflake): el timestamp va codificado en el propio
# id, así que se puede saber la edad de un post sin gastar una lectura.
_EPOCA_X_MS = 1288834974657
# Pasado esto, un reply llega a una conversación que ya terminó: cuesta lo
# mismo y no lo ve nadie.
HORAS_MAX_PARA_RESPONDER = 12


def edad_horas(post_id: str) -> float | None:
    """Horas desde que se publicó el post, deducidas de su id. None si no aplica."""
    from datetime import datetime, timezone

    if not post_id or not post_id.isdigit():
        return None
    ms = (int(post_id) >> 22) + _EPOCA_X_MS
    creado = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return (datetime.now(timezone.utc) - creado).total_seconds() / 3600


class PublicarError(RuntimeError):
    """No se publicó. Nunca se traga en silencio."""


@dataclass
class Publicado:
    post_id: str
    url: str
    costo: float


def tiene_link(texto: str) -> bool:
    return bool(_URL.search(texto))


def costo(textos: list[str]) -> float:
    return sum(COSTO_POST_CON_LINK if tiene_link(t) else COSTO_POST
               for t in textos)


def revisar_antes_de_publicar(item, *, permitir_link: bool = False,
                              numeros_permitidos: list[float] | None = None
                              ) -> list[str]:
    """Problemas que impiden publicar. Lista vacía = adelante.

    Se corre sobre el texto FINAL (la edición de Angel gana), no sobre el
    original: aprobar y editar son dos cosas y lo que sale es lo editado.
    """
    problemas: list[str] = []
    if item.estado not in ("aprobado", "programado"):
        problemas.append(
            f"estado '{item.estado}': solo se publica lo aprobado o programado")
    piezas = [item.texto_final, *item.hilo]
    for i, p in enumerate(piezas, 1):
        if not p.strip():
            problemas.append(f"pieza {i} vacía")
        if len(p) > MAX_CHARS:
            problemas.append(f"pieza {i} se pasa por {len(p) - MAX_CHARS} caracteres")
        if not es_ingles(p):
            problemas.append(f"pieza {i} no está en inglés")
        if tiene_link(p) and not permitir_link:
            problemas.append(
                f"pieza {i} lleva un link (cuesta ${COSTO_POST_CON_LINK} en vez "
                f"de ${COSTO_POST} y baja el alcance). Usa --permitir-link si "
                f"de verdad lo quieres")
    # El ticker se revisa AQUÍ y no solo al generar. Tres posts salieron sin
    # cashtag porque se redactaron 43 minutos antes de que la regla llegara al
    # VPS: el campo no existía en el borrador viejo, se guardó vacío y nadie
    # lo volvió a mirar. Una regla que solo corre en generación no protege a
    # lo que ya está en la cola.
    if item.ticker:
        faltan = falta_ticker("\n".join(piezas), item.ticker)
        if faltan:
            problemas.append(
                f"falta el ticker en el texto final: {', '.join(faltan)}")
    # Estilo, revisado sobre el texto FINAL porque la edición de Angel también
    # puede meterlo: la raya larga delata texto generado, y las cifras van en
    # convención inglesa (79,900 y 10.99).
    entero = "\n".join(piezas)
    if lleva_raya(entero):
        problemas.append("usa una raya como puntuación: va punto, coma o dos puntos")
    malas = cifras_mal_formateadas(entero)
    if malas:
        problemas.append(f"cifras mal formateadas {malas}: coma para los miles "
                         f"y punto para los decimales")
    # Macro y cripto no tienen predicciones guardadas, así que atribuirse una
    # llamada pasada es inventar el historial de Angel y publicarlo con su
    # nombre. Las cifras pueden ser correctas y la frase seguir siendo falsa.
    if item.kind in SIN_HISTORIAL:
        inventadas = afirma_llamada_propia("\n".join(piezas))
        if inventadas:
            problemas.append(
                f"se atribuye una predicción que no existe ({', '.join(inventadas)}): "
                f"en {item.kind} no hay historial guardado que respalde eso")
    # Un post de macro no tiene cashtag que diga de qué habla, así que aquí
    # se exige que nombre algún sujeto reconocible. La comprobación es más
    # gruesa que la de generación —el item no guarda de qué serie salió— pero
    # caza el fallo que importa: un post que solo encadena porcentajes y deja
    # al lector adivinando.
    if item.kind == "macro" and not item.ticker:
        from xcreator.macro import SERIES

        todos = tuple(a for c in SERIES.values() for a in c.alias)
        if falta_sujeto("\n".join(piezas), todos):
            problemas.append(
                "el texto no dice de qué habla: no nombra ningún dato macro "
                "reconocible, solo cifras sueltas")
    # X bloqueó los replies programáticos el 2026-02-23 para frenar el spam
    # de replies generados con LLM: POST /2/tweets solo admite responder si el
    # autor original te menciona o te cita. Aplica a todos los planes salvo
    # Enterprise. No es un fallo de configuración y no hay forma de sortearlo
    # por API — intentarlo solo devuelve un 403 y gasta la llamada.
    if item.kind == "reply" and item.url_origen:
        problemas.append(
            "los replies a otras cuentas no se pueden publicar por API "
            "(restricción de X desde feb 2026): cópialo y pégalo a mano")
    # Un reply a una conversación muerta es dinero tirado.
    if item.url_origen:
        origen = item.url_origen.rstrip("/").split("/")[-1]
        horas = edad_horas(origen)
        if horas is not None and horas > HORAS_MAX_PARA_RESPONDER:
            problemas.append(
                f"el post al que responde tiene {horas:.0f} horas (límite "
                f"{HORAS_MAX_PARA_RESPONDER}): la conversación ya pasó")
    if numeros_permitidos is not None:
        malos = validate_numbers("\n".join(piezas), numeros_permitidos)
        if malos:
            problemas.append(f"cifras sin fuente en el texto final: {malos}")
    return problemas


def subir_media(token: str, imagen: Path, *, timeout: float = 60.0) -> str:
    """Sube una imagen y devuelve su media_id.

    Adjuntar media no cuesta aparte: un post con imagen vale lo mismo que uno
    de texto ($0.015). Lo que sí hace falta es el scope `media.write`, y sin
    él la API responde un 403 escueto que no lo menciona.
    """
    if not imagen.exists():
        raise PublicarError(f"no existe la imagen {imagen}")
    peso = imagen.stat().st_size
    if peso > MAX_BYTES_IMAGEN:
        raise PublicarError(
            f"la imagen pesa {peso/1024/1024:.1f} MB, por encima del límite "
            f"de {MAX_BYTES_IMAGEN/1024/1024:.0f} MB de X")
    try:
        with imagen.open("rb") as fh:
            r = httpx.post(
                MEDIA_URL, headers={"Authorization": f"Bearer {token}"},
                files={"media": (imagen.name, fh, "image/png")},
                data={"media_category": "tweet_image"}, timeout=timeout)
    except httpx.HTTPError as e:
        raise PublicarError(f"subida de media: sin conexión ({type(e).__name__})") from e
    if r.status_code == 403:
        raise PublicarError(
            "403 al subir la imagen: al token le falta el scope `media.write`. "
            "Corre `xc x-auth` otra vez para reautorizar con el scope nuevo.")
    if r.status_code == 402:
        raise PublicarError("Sin créditos en X (402) al subir la imagen.")
    if r.status_code >= 400:
        raise PublicarError(f"subida de media: HTTP {r.status_code} — {r.text[:200]}")
    d = r.json().get("data") or r.json()
    media_id = d.get("id") or d.get("media_id_string") or d.get("media_key")
    if not media_id:
        raise PublicarError(f"subida sin id: {str(r.json())[:200]}")
    return str(media_id)


def _post(token: str, payload: dict, timeout: float = 30.0) -> dict:
    try:
        r = httpx.post(POST_URL, json=payload, timeout=timeout,
                       headers={"Authorization": f"Bearer {token}",
                                "Content-Type": "application/json"})
    except httpx.HTTPError as e:
        raise PublicarError(f"sin conexión ({type(e).__name__})") from e
    if r.status_code == 401:
        raise PublicarError("401: el token no autoriza a publicar. ¿Falta el "
                            "scope tweet.write? Corre `xc x-auth`.")
    if r.status_code == 403:
        raise PublicarError(f"403: X rechazó el post — {r.text[:200]}")
    if r.status_code == 402:
        raise PublicarError(
            "Sin créditos en X (402). La autorización está bien; falta "
            f"recargar en console.x.com. Publicar un post cuesta "
            f"${COSTO_POST}."
        )
    if r.status_code == 429:
        raise PublicarError("429: límite de publicación alcanzado.")
    if r.status_code >= 400:
        raise PublicarError(f"HTTP {r.status_code} — {r.text[:200]}")
    d = r.json().get("data") or {}
    if not d.get("id"):
        raise PublicarError(f"respuesta sin id: {str(r.json())[:200]}")
    return d


def publicar_item(item, token: str, *, handle: str = "",
                  imagen: Path | None = None,
                  en_seco: bool = False) -> Publicado:
    """Publica un item ya revisado. Un hilo se encadena con `reply`.

    `imagen` se adjunta SOLO a la primera pieza: repetir el gráfico en cada
    post del hilo es ruido, y el que abre es el que se ve en el timeline.

    `en_seco` recorre todo sin llamar a X: sirve para ver qué se enviaría.
    """
    piezas = [item.texto_final, *item.hilo]
    total = costo(piezas)
    if en_seco:
        return Publicado(post_id="(en seco)", url="", costo=total)

    media_id = subir_media(token, imagen) if imagen else None

    primero: str | None = None
    anterior: str | None = None
    for p in piezas:
        payload: dict = {"text": p}
        if media_id and primero is None:
            payload["media"] = {"media_ids": [media_id]}
        if anterior:
            payload["reply"] = {"in_reply_to_tweet_id": anterior}
        elif item.url_origen:
            # Es una respuesta a otra cuenta: cuelga del post original.
            origen = item.url_origen.rstrip("/").split("/")[-1]
            if origen.isdigit():
                payload["reply"] = {"in_reply_to_tweet_id": origen}
        d = _post(token, payload)
        anterior = d["id"]
        primero = primero or d["id"]

    return Publicado(
        post_id=primero or "",
        url=f"https://x.com/{handle.lstrip('@') or 'i'}/status/{primero}",
        costo=total,
    )
