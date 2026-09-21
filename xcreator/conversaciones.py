"""Dos cosas que convierten el alcance de los replies en algo que cuenta.

El programa de monetización de X solo cuenta impresiones verificadas de posts
ORIGINALES; los replies no suman. Y el 86% del alcance de la cuenta (8 al 21
de septiembre de 2026) venía justo de replies de Angel. Su mejor reply hizo
11,048 impresiones y para el programa valió cero.

1. De reply a post: cuando un reply tuyo funciona, su idea ya está probada.
   Se reescribe como post original, que sí cuenta, y se entiende solo.
2. Responder a quien te responde: una respuesta en tu post es la acción que
   más pesa del algoritmo después de compartir (5.0 frente a 0.5 de un like),
   y contestarla mantiene la conversación viva dentro de TU post original.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone

from xcreator.brief import Brief, Fact

# Impresiones a partir de las cuales un reply ya demostró su idea. La mediana
# de los replies de la cuenta es ~50 y la de los posts propios 36: 500 es
# diez veces lo normal, un reply que claramente conectó.
UMBRAL_REPLY_A_POST = 500
# Cuántos replies se reciclan al día como mucho. Son ideas probadas, pero un
# perfil lleno de reciclajes se nota.
POSTS_DESDE_REPLIES_POR_DIA = 2
# Borradores de respuesta en tus posts al día. Van aparte del cupo de 6 de
# los replies a otras cuentas: son conversaciones que ya empezaron, y dejar
# a alguien sin contestar en tu propio post es lo más caro que hay.
CONVERSACIONES_POR_DIA = 8
# Pasado esto la conversación ya se enfrió.
HORAS_MAX_CONVERSACION = 12

# Vocabulario de mercados. Filtra los replies personales ("The kind of dad I
# aspire to be", 3,783 impresiones) que no tienen sitio en el perfil de la
# cuenta como post. Cashtag o una palabra de aquí, en el reply o en su padre.
_MERCADOS = re.compile(
    r"\$[a-z]{1,5}\b|\b(stocks?|shares?|markets?|fed|rates?|yields?|bonds?|"
    r"treasur\w*|inflation|cpi|jobs|recession|economy|gdp|tariffs?|dollar|"
    r"oil|gold|earnings|revenue|valuation|ipo|etf|sec|cftc|crypto\w*|bitcoin|"
    r"btc|ether\w*|eth|xrp|ripple|solana|stablecoins?|clarity act|genius act|"
    r"bank\w*|nasdaq|s&p|dow|nvidia|tesla|apple|ai|capex|debt|deficit)\b",
    re.IGNORECASE)


def es_de_mercados(*textos: str) -> bool:
    return any(_MERCADOS.search(t or "") for t in textos)


def _horas(creado: str) -> float | None:
    try:
        f = datetime.fromisoformat((creado or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - f).total_seconds() / 3600


def _sin_menciones_iniciales(texto: str) -> str:
    """Quita los @usuario del principio que X añade a todo reply."""
    return re.sub(r"^(\s*@\w+)+\s*", "", texto or "").strip()


# --- 1. De reply a post -------------------------------------------------------

def candidatos_reply_a_post(pares, usados: set[str], *,
                            umbral: int = UMBRAL_REPLY_A_POST):
    """Tus replies que ya funcionaron, de más a menos impresiones.

    `pares` es lo que devuelve `ClienteX.mis_replies`: (tu reply, su padre).
    `usados` son los ids de replies ya reciclados, para no hacerlo dos veces.
    """
    # El filtro de mercados mira el reply y, si viene, su padre. Sin padre
    # (lo normal, para no pagarlo), basta el reply: si ni tu propio texto
    # habla de mercados, no es un post para esta cuenta.
    buenos = [
        (r, p) for r, p in pares
        if r.impresiones >= umbral
        and r.post_id not in usados
        and es_de_mercados(r.texto, p.texto if p else "")
    ]
    return sorted(buenos, key=lambda rp: -rp[0].impresiones)


def brief_desde_reply(reply, padre) -> Brief:
    """El brief para reescribir un reply tuyo como post original."""
    from xcreator.replies import _numeros_del_texto

    tuyo = _sin_menciones_iniciales(reply.texto)
    contexto_padre = (f"Respondías a {padre.autor or 'otra cuenta'}: "
                      f"\"{padre.texto.strip()}\"") if padre else (
        "No tenemos el post al que respondías.")
    facts = []
    for fuente, texto in (("tu reply", tuyo), ("el post al que respondías",
                                                padre.texto if padre else "")):
        for v in sorted(set(_numeros_del_texto(texto))):
            facts.append(Fact(f"cifra que aparece en {fuente}", v, "num", fuente))

    return Brief(
        kind="desde_reply",
        ticker="",
        angulo="mercado",
        angle="Una idea tuya que ya funcionó como reply, ahora como post propio",
        facts=facts,
        motivo=f"reply:{reply.post_id}",
        context=[
            f"ESTE REPLY TUYO FUNCIONÓ ({reply.impresiones:,} impresiones): "
            f"\"{tuyo}\"",
            contexto_padre,
            "Reescríbelo como POST ORIGINAL que se entienda solo, para "
            "alguien que nunca vio el post de arriba: en pocas palabras di de "
            "qué va (qué pasó o qué se dijo) y luego tu toma.",
            "Conserva la idea y el tono del reply. Funcionó por algo: no la "
            "diluyas, no la vuelvas formal, no la alargues más de la cuenta.",
            "NO menciones al autor del otro post ni empieces con @: esto es "
            "tuyo, no una respuesta.",
            "No afirmes nada que no digan los dos textos de arriba. Es tu "
            "opinión sobre algo que ya pasó, no una noticia nueva.",
            "NO te atribuyas llamadas pasadas: no hay predicciones guardadas "
            "sobre esto.",
        ],
        as_of=date.today().isoformat(),
    )


# --- 2. Responder a quien te responde -----------------------------------------

def respuestas_por_contestar(pares, mi_handle: str, ya_respondido,
                             *, horas_max: float = HORAS_MAX_CONVERSACION):
    """Respuestas a posts TUYOS, frescas y sin contestar.

    `pares` es lo que devuelve `ClienteX.menciones`. Una mención no basta: X
    menciona a todos los que están en un hilo, y alguien que le responde a un
    tercero en una conversación donde tú estabas también te "menciona". Solo
    cuenta si el post al que responde es tuyo.
    """
    yo = "@" + mi_handle.lstrip("@").lower()
    out = []
    for m, padre in pares:
        if (m.autor or "").lower() == yo:
            continue
        if not padre or (padre.autor or "").lower() != yo:
            continue
        h = _horas(m.creado)
        if h is not None and h > horas_max:
            continue
        if ya_respondido(m.url):
            continue
        if not _sin_menciones_iniciales(m.texto):
            continue  # solo etiquetas, nada que contestar
        out.append((m, padre))
    return out
