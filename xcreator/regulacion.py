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


# Qué es "regulación de cripto" se decide con DOS condiciones y no con una
# lista de frases. La primera versión buscaba frases fijas ("crypto
# regulation") y se saltó "CFTC files new rulemaking to regulate crypto
# transactions": mismo significado, otro orden, y un regulador nombrado que
# la lista no conocía. Hace falta contexto cripto Y una señal regulatoria.
_CONTEXTO_CRIPTO = re.compile(
    r"\b(crypto\w*|bitcoin|btc|ether(eum)?|xrp|ripple|solana|stablecoins?|"
    # "tokens" a secas NO: WatcherGuru también publica de IA ("Anthropic cuts
    # token prices under new EU rules") y eso no es regulación de cripto.
    r"tokeni[sz]ed|digital assets?|defi|blockchain|coinbase|binance|"
    r"kraken|web3)\b", re.IGNORECASE)

# Entidades concretas: reguladores, cámaras y leyes con nombre. Son lo que el
# post tiene que nombrar, porque son lo que el lector reconoce.
_ENTIDADES = re.compile(
    r"\b(sec|cftc|occ|fdic|irs|doj|treasury|congress|senate|house|"
    r"federal reserve|clarity act|genius act|stablecoin bill|"
    r"market structure bill|atkins|lummis)\b", re.IGNORECASE)

_SENAL = re.compile(
    r"\b(regulat\w*|rulemaking|rules?|bill|act|laws?|legislat\w*|"
    r"sanction\w*|bans?|banned|approv\w*|lawsuit|sues?|sued|court|"
    r"enforcement|compliance|framework|oversight|tax(es|ation)?|licen[cs]\w*)\b",
    re.IGNORECASE)


def es_regulacion_cripto(texto: str) -> bool:
    """Contexto cripto y, además, una señal regulatoria o un regulador."""
    return bool(_CONTEXTO_CRIPTO.search(texto)
                and (_SENAL.search(texto) or _ENTIDADES.search(texto)))


def sujeto_del_titular(texto: str) -> tuple[str, ...]:
    """Qué tiene que nombrar el post: la entidad concreta del titular.

    Si el titular habla de la CFTC, un post que solo diga "regulators" obliga
    al lector a adivinar quién. Solo cuentan las entidades con nombre; las
    palabras genéricas ("crypto", "regulate") detectan el tema pero no lo
    nombran. Sin entidad, se cae a la señal regulatoria del titular.
    """
    if not es_regulacion_cripto(texto):
        return ()
    entidades = tuple(dict.fromkeys(m.group(0).lower()
                                    for m in _ENTIDADES.finditer(texto)))
    if entidades:
        return entidades
    return tuple(dict.fromkeys(m.group(0).lower()
                               for m in _SENAL.finditer(texto)))


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
