"""Posts de opinión: la voz de Angel, sin una sola cifra.

El resto del sistema parte de un dato. Este parte de lo que Angel piensa, y
sale solo. La evidencia está a favor: en las dos semanas del 12 al 25 de
septiembre sus tres posts con más alcance no llevaban ningún número ("We are
about to watch a lot of green candles unfold", 2,359 impresiones), mientras
que el mejor post con datos del sistema hizo 673.

Qué lo hace distinto de `idea.py`: allí el material es una nota que Angel
escribe. Aquí no hay nota. El material es su postura, que está escrita en
`PERFIL`, y una semilla temática que rota para que no se repita. Por eso
estos SÍ salen solos.

Dos guardas de fondo, porque un post sin datos es el más fácil de estropear:

1. **Cero cifras.** El brief no trae ni un `Fact`, así que la lista de
   números permitidos está vacía y el validador marca cualquiera que
   aparezca. Una opinión con un número inventado es una mentira con aspecto
   de análisis.
2. **Nada de negatividad ni de política.** Angel lo pidió explícitamente y
   además es lo que le funciona: las tres frases suyas que más volaron son
   optimistas. El detector de partidismo que ya existe sigue aplicando.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from xcreator.brief import Brief

# Quién es la cuenta. Esto NO es una invención del modelo: son las posturas
# que Angel declaró el 2026-09-25. Si cambian, se cambian aquí.
PERFIL = """Angel: trader minorista de Puerto Rico, optimista por convicción.
- Le gustan las stablecoins y cree que son infraestructura de pago, no un
  casino.
- Es alcista en cripto y en la economía: ve la adopción avanzando, no
  retrocediendo.
- Busca el lado bueno de las cosas: donde otros ven el fin de ciclo, él ve la
  parte que se está construyendo.
- Trabaja sus propios análisis y publica también sus errores.
- No es un gurú ni vende señales. Habla como alguien que está en la trinchera
  y disfruta el proceso."""

# Cada cuánto puede repetirse una misma semilla, en días. Con doce semillas y
# tres posts diarios, cuatro días reparte el catálogo sin que se note el
# turno.
DESCANSO_DIAS = 4


@dataclass(frozen=True)
class Semilla:
    clave: str
    tema: str        # de qué habla, en una frase (para el prompt)
    apertura: str    # qué pregunta abre, para que no todos suenen igual


# El catálogo. Corto a propósito: cada una tiene que dar un post que Angel
# firmaría. Añadir una es una línea.
SEMILLAS: tuple[Semilla, ...] = (
    Semilla("stablecoins", "stablecoins as payment rails that already work",
            "What do people get wrong about stablecoins being boring?"),
    Semilla("adopcion", "crypto adoption moving forward quietly",
            "What is being built right now that nobody is clapping for?"),
    Semilla("optimismo_mercado", "why you stay constructive on markets",
            "Why does staying constructive beat being clever about the top?"),
    Semilla("paciencia", "the boring part of investing: waiting well",
            "What does patience actually look like on a red day?"),
    Semilla("aprender", "learning in public and getting things wrong",
            "What did being wrong teach you that being right never did?"),
    Semilla("trabajo", "the work nobody sees behind a good call",
            "What part of the work would people skip if they could?"),
    Semilla("gratitud", "gratitude for the chance to do this at all",
            "What is easy to take for granted in this job?"),
    Semilla("familia", "life outside the screen: family, health, sleep",
            "What keeps you sane when the market does not cooperate?"),
    Semilla("tecnologia", "technology making things cheaper and faster",
            "Which change is already here that people still call the future?"),
    Semilla("largo_plazo", "thinking in years while the timeline thinks in hours",
            "What looks like noise today and will look like nothing in a year?"),
    Semilla("oportunidad", "opportunity for people starting from zero",
            "What would you tell someone starting today with no edge?"),
    Semilla("comunidad", "the people who correct you and make you better",
            "Who made you better by disagreeing with you?"),
)


def elegir_semilla(ultimo_uso: dict[str, str],
                   hoy: date | None = None) -> Semilla | None:
    """La semilla más descansada. None si todas salieron hace muy poco.

    Callar es una salida válida: con tres posts al día, forzar una semilla
    repetida es la forma más rápida de sonar a bot con calendario.
    """
    hoy = hoy or date.today()
    corte = (hoy - timedelta(days=DESCANSO_DIAS)).isoformat()

    def usada(s: Semilla) -> str:
        return ultimo_uso.get(f"personal:{s.clave}", "")

    libres = [s for s in SEMILLAS if usada(s) <= corte]
    if not libres:
        return None
    # La que lleva más tiempo sin salir; a igualdad, el orden del catálogo.
    return min(libres, key=lambda s: (usada(s), SEMILLAS.index(s)))


def brief_personal(semilla: Semilla) -> Brief:
    """Brief de un post de opinión. Sin facts: aquí no hay cifras que citar."""
    return Brief(
        kind="personal",
        ticker="",
        sujeto=(),
        angulo="personal",   # fuera del Cerebro: nada de metodología aquí
        angle=semilla.apertura,
        facts=[],            # y por tanto: cero números permitidos
        motivo=f"personal:{semilla.clave}",
        context=[
            "Este post NO lleva datos. Es una opinión de Angel, en su voz.",
            f"QUIÉN ES ANGEL:\n{PERFIL}",
            f"DE QUÉ VA ESTE POST: {semilla.tema}.",
            f"LA PREGUNTA QUE LO ABRE (no la copies literal): {semilla.apertura}",
            "CERO CIFRAS. Ni precios, ni porcentajes, ni fechas, ni "
            "estadísticas, ni 'el 90% de la gente'. No tienes ningún dato "
            "delante, así que cualquier número sería inventado. Si el post "
            "necesita un número para sostenerse, es que el post es otro.",
            "TODO EN POSITIVO. Angel busca el lado bueno: qué se está "
            "construyendo, qué mejora, qué agradece. Nada de catastrofismo, "
            "nada de atacar a nadie, nada de burlarse de quien se equivocó. "
            "Se puede discrepar sin despreciar.",
            "Que sea discutible, no un cartel motivacional. Una postura "
            "concreta que alguien pueda contestar vale mucho más que una "
            "frase bonita que nadie responde. Nada de 'stay positive' ni de "
            "sermones.",
            "Nada de consejo de compra o venta, nada de precios objetivo, "
            "nada de política de partidos.",
            "Puede hablar de la vida, no solo de mercados: el trabajo, la "
            "familia, dormir bien, empezar de cero. Ese es su lado humano y "
            "es lo que hace que la cuenta no parezca un bot.",
            "Corto. Una o dos frases. Como se lo dirías a un amigo.",
        ],
        as_of=date.today().isoformat(),
    )
