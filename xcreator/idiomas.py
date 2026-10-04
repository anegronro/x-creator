"""En qué idioma sale cada post. Ni el modelo ni el azar lo deciden.

Angel es de Puerto Rico y hasta el 2026-10-03 la cuenta publicaba siempre en
inglés. Eso tiene una razón de alcance (el mercado en inglés es mucho mayor)
y un costo que no habíamos contado: una cuenta que nunca se sale de un
registro suena a plantilla, y la plantilla es justo lo que X acaba de
etiquetar como manipulación de plataforma.

La mezcla se calcula, no se sortea: se mira qué se ha publicado hoy y se
elige el idioma que falta para llegar a la proporción. Así nunca salen cinco
seguidos en español ni se olvida el español durante una semana, que es lo
que pasa cuando esto se deja a un `random`.
"""

from __future__ import annotations

# Proporción objetivo de posts en español. Un tercio: suficiente para que la
# cuenta suene a una persona bilingüe y no tanto como para perder al público
# en inglés, que es donde está el tamaño.
PROPORCION_ESPANOL = 1 / 3


def elegir(idiomas_de_hoy: list[str],
           proporcion: float = PROPORCION_ESPANOL) -> str:
    """El idioma del próximo post: "es" o "en".

    `idiomas_de_hoy` son los idiomas de lo que ya se escribió hoy, en orden.
    Si el español va por debajo de su cuota contando este post, toca español.
    """
    total = len(idiomas_de_hoy) + 1
    en_espanol = sum(1 for i in idiomas_de_hoy if i == "es")
    return "es" if (en_espanol + 1) <= total * proporcion else "en"


def idiomas_de_hoy(items, hoy: str) -> list[str]:
    """Los idiomas de los posts propios creados hoy, en orden.

    Los replies y las citas no cuentan: su idioma lo manda el post al que
    responden, no esta proporción.
    """
    return [getattr(i, "idioma", "en") or "en" for i in items
            if i.kind not in ("reply", "cita")
            and (i.creado or "")[:10] == hoy
            and i.estado != "rechazado"]
