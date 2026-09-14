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

import httpx

from xcreator.generate import MAX_CHARS, es_ingles, validate_numbers

POST_URL = "https://api.x.com/2/tweets"
COSTO_POST = 0.015
COSTO_POST_CON_LINK = 0.20
_URL = re.compile(r"https?://\S+|\bt\.co/\S+")


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
    if item.estado != "aprobado":
        problemas.append(f"estado '{item.estado}': solo se publica lo aprobado")
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
    if numeros_permitidos is not None:
        malos = validate_numbers("\n".join(piezas), numeros_permitidos)
        if malos:
            problemas.append(f"cifras sin fuente en el texto final: {malos}")
    return problemas


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
                  en_seco: bool = False) -> Publicado:
    """Publica un item ya revisado. Un hilo se encadena con `reply`.

    `en_seco` recorre todo sin llamar a X: sirve para ver qué se enviaría.
    """
    piezas = [item.texto_final, *item.hilo]
    total = costo(piezas)
    if en_seco:
        return Publicado(post_id="(en seco)", url="", costo=total)

    primero: str | None = None
    anterior: str | None = None
    for p in piezas:
        payload: dict = {"text": p}
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
