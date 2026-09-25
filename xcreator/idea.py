"""Tus ideas sueltas, escritas con tu voz.

El resto del sistema parte de un dato: un precio, una serie de FRED, un
comunicado de la SEC. Por eso suena a analista. Este módulo es al revés: el
material de partida es una nota tuya, escrita como salga y en el idioma que
salga, y el modelo solo la traduce a un post en inglés con tu voz.

La regla de siempre sigue en pie y aquí es más estricta todavía: las ÚNICAS
cifras permitidas son las que tú escribiste en la nota. El modelo no tiene
brief, no tiene precios y no puede buscar nada, así que cualquier número que
añada sería inventado. Lo mismo con los hechos: puede afilar tu idea, nunca
añadirle una noticia, una fuente o un dato que tú no hayas puesto.

Nace `pendiente`, no `programado`: es tu voz, la apruebas tú.
"""

from __future__ import annotations

from datetime import date

from xcreator.brief import Brief, Fact

# Una nota más corta que esto no es una idea, es un dedazo.
MINIMO_CARACTERES = 15


def es_idea(texto: str) -> bool:
    """True si el mensaje parece una nota y no un comando ni un dedazo."""
    t = (texto or "").strip()
    return len(t) >= MINIMO_CARACTERES and not t.startswith("/")


def brief_idea(nota: str, ticker: str = "") -> Brief:
    """El brief de una nota tuya. Sin facts propios: los pone la nota."""
    from xcreator.replies import _numeros_del_texto

    limpia = " ".join((nota or "").split())
    facts = [Fact("cifra que escribiste en tu nota", v, "num", "tu nota")
             for v in sorted(set(_numeros_del_texto(limpia)))]
    return Brief(
        kind="idea",
        ticker=ticker,
        # `personal` no es un ángulo del Cerebro, y eso es deliberado: así no
        # se carga la metodología del analista, que es justo lo que vuelve
        # formales estos posts.
        angulo="personal",
        angle="Tu idea, dicha como la dirías tú",
        facts=facts,
        context=[
            f"ESTO LO ESCRIBIÓ ANGEL, es su idea y su opinión: \"{limpia}\"",
            "Tu trabajo es decirlo en inglés, con su voz, para que se entienda "
            "suelto en X. No es una traducción literal: puedes afilar la idea, "
            "quitarle paja y darle un cierre. Pero la idea es suya y no se "
            "cambia por otra.",
            "NO AÑADAS NADA QUE NO ESTÉ EN LA NOTA: ni cifras, ni nombres, ni "
            "noticias, ni fuentes, ni fechas. Si la nota no trae números, el "
            "post no lleva ni uno. No tienes datos aquí; lo que inventes se "
            "publica con su nombre.",
            "Si la nota dice algo sobre el pasado de Angel ('yo dije', 'me "
            "equivoqué'), respétalo tal cual: eso lo sabe él, no tú. Lo que "
            "NO puedes es añadir un historial que la nota no menciona.",
            "Sin partidismo, sin consejo de compra o venta, sin links ni "
            "hashtags.",
            "Que se entienda sin contexto: quien lo lea no vio la nota ni "
            "sabe de qué hablabas antes.",
        ],
        as_of=date.today().isoformat(),
    )


def ticker_de_la_nota(nota: str) -> str:
    """El cashtag que la nota menciona, si menciona uno. Vacío si no.

    Sirve para que la regla de las dos formas ($NVDA y NVDA) se aplique
    cuando tú ya nombraste la empresa, y no para ir a buscar datos: aquí no
    hay brief que consultar.
    """
    from xcreator.replies import Mencion

    tickers = sorted(Mencion("", nota or "").tickers())
    return tickers[0] if len(tickers) == 1 else ""
