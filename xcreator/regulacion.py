"""Posts propios sobre regulación de cripto: Clarity Act, stablecoins, SEC.

Es el tema que mejor le funciona a la cuenta por mediana (120 impresiones
frente a 84 de acciones con datos, semana del 9 al 15 de septiembre), y el
reply que se llevó el 62% del alcance de esa semana era justo esto.

El problema de fondo es de hechos, no de estilo. En un reply, el post ajeno
pone la noticia y nosotros solo el criterio. En un post propio no hay nadie
que ponga la noticia: si el modelo escribe "the Senate passed the Clarity
Act", es una noticia inventada publicada con el nombre de Angel.

Así que cada post se ancla a un TITULAR REAL y reciente de las cuentas de
cripto que ya se vigilan. El titular aporta el hecho, citado como informado
y nunca como verificado; el post aporta el criterio y, si el titular nombra
un activo, sus cifras de precio reales. No se afirma nada que el titular no
diga.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from xcreator.brief import Brief, Fact

# Pasado esto, el titular ya es noticia vieja: el post llegaría tarde a una
# conversación que se movió.
HORAS_MAX_TITULAR = 12

# Partidos y personas de la política partidista. Un post propio que los nombra
# NO sale solo: queda pendiente para que Angel decida. No se prohíbe —a veces
# es imposible explicar la noticia sin decir quién la bloquea—, pero una cuenta
# de mercados no debería tomar partido de forma automática.
_PARTIDISTA = re.compile(
    r"\b(democrats?|democratic|republicans?|gop|dems?|maga|liberals?|"
    r"conservatives?|left-wing|right-wing|trump|biden|harris|vance|"
    r"pelosi|schumer|mcconnell|warren)\b",
    re.IGNORECASE,
)


def menciona_partidismo(texto: str) -> list[str]:
    """Los nombres de partido o político que aparecen. Vacío = neutral."""
    return sorted({m.group(0).lower() for m in _PARTIDISTA.finditer(texto)})


def claves_regulacion() -> tuple[str, ...]:
    """Las frases que marcan un titular de regulación de cripto.

    Salen de las mismas claves que usa el filtro de replies: una sola lista
    para decidir qué es "regulación de cripto" en todo el sistema.
    """
    from xcreator.replies import _TEMAS_SIN_CIFRAS

    return _TEMAS_SIN_CIFRAS["regulación de cripto"]


def sujeto_del_titular(texto: str) -> tuple[str, ...]:
    """Qué nombra el titular, para exigir que el post lo nombre también.

    Si el titular habla del Clarity Act, un post que solo diga "the bill"
    obliga al lector a adivinar. Se exige la misma pieza del titular.
    """
    bajo = texto.lower()
    return tuple(k for k in claves_regulacion() if k in bajo)


@dataclass
class Titular:
    autor: str
    texto: str
    url: str
    post_id: str
    horas: float | None


def elegir_titular(candidatos: list[Titular],
                   usados: set[str]) -> Titular | None:
    """El titular de regulación más fresco que no se haya usado ya.

    Frescura manda: es el mismo criterio que los replies, y por la misma
    razón. Un titular de hace diez horas ya tiene su conversación hecha.
    """
    buenos = [
        t for t in candidatos
        if sujeto_del_titular(t.texto)
        and t.post_id not in usados
        and (t.horas is None or t.horas <= HORAS_MAX_TITULAR)
    ]
    buenos.sort(key=lambda t: t.horas if t.horas is not None else 99)
    return buenos[0] if buenos else None


def _limpiar_titular(texto: str) -> str:
    """Sin el "JUST IN:", sin banderas y sin el enlace acortado."""
    t = re.sub(r"https?://\S+", "", texto)
    t = re.sub(r"^\s*(JUST IN|BREAKING|NEW)\s*:\s*", "", t, flags=re.I)
    t = re.sub(r"[\U0001F1E6-\U0001F1FF]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def brief_regulacion(titular: Titular, fmp_api_key: str | None) -> Brief:
    """El brief para un post propio sobre un titular de regulación.

    Las cifras permitidas son las del propio titular y, si nombra un activo
    que cubrimos, su precio real. Nada más.
    """
    from xcreator.cripto import ACTIVOS, brief_para
    from xcreator.replies import Mencion, _numeros_del_texto

    limpio = _limpiar_titular(titular.texto)
    sujeto = sujeto_del_titular(titular.texto)

    # Si el titular nombra un activo, se toma su brief de precio: el post
    # puede apoyarse en una cifra real en vez de quedarse solo en opinión.
    ticker = ""
    facts: list[Fact] = []
    for t in sorted(Mencion(titular.autor, titular.texto).tickers()):
        if any(a.ticker == t for a in ACTIVOS.values()):
            b = brief_para(t, fmp_api_key)
            if b is not None:
                ticker, facts = t, list(b.facts)
                break

    fuente = f"titular de {titular.autor}"
    for v in sorted(set(_numeros_del_texto(limpio))):
        facts.append(Fact(f"cifra que aparece en el titular", v, "num", fuente))

    return Brief(
        kind="regulacion",
        ticker=ticker,
        sujeto=sujeto,
        angulo="riesgo",
        angle="Qué implica esta noticia de regulación que el titular no dice",
        facts=facts,
        context=[
            f"NOTICIA, tal como la publicó {titular.autor} (sin verificar): "
            f"\"{limpio}\"",
            "Es un titular de una cuenta de noticias rápidas, no un hecho "
            "comprobado. Si lo mencionas, preséntalo como informado "
            "(\"reportedly\", \"per reports\"), nunca como confirmado.",
            "NO afirmes NADA que el titular no diga: ni qué contiene el "
            "proyecto de ley, ni qué votó quién, ni qué pasará después. No lo "
            "sabes. Si tu argumento necesita un hecho que no está arriba, "
            "haz otro argumento.",
            "El valor del post es el CRITERIO: una consecuencia que el titular "
            "se salta, un incentivo que nadie nombra, qué tendría que ser "
            "cierto para que la noticia importe de verdad.",
            "Sin partidismo. Puedes decir que una norma es incoherente o que un "
            "incentivo es obvio; no tomas partido entre partidos ni atacas a "
            "nadie. La cuenta es de mercados.",
            "NO te atribuyas llamadas pasadas: no hay predicciones guardadas "
            "sobre regulación.",
            f"Nombra el tema con todas sus letras ({', '.join(sujeto)}): el "
            "lector no tiene por qué adivinar de qué hablas.",
            "Sin link: el titular original no se enlaza (cuesta 13x y hunde "
            "el alcance).",
        ],
        as_of=date.today().isoformat(),
    )
