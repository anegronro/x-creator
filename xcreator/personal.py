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
    # De fin de semana: familia, fe, gratitud, descanso. Sábado y domingo la
    # cuenta no publica datos —"para que mis seguidores descansen", dijo
    # Angel el 2026-09-25— y solo salen estas.
    finde: bool = False


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
    Semilla("bitcoin_largo", "holding bitcoin through boring stretches",
            "What does conviction look like when nothing is happening?"),
    Semilla("pagos", "moving money across borders without asking permission",
            "Who benefits first when sending money gets cheap?"),
    Semilla("tokenizacion", "putting real assets on rails that never close",
            "What changes when a market stops having closing hours?"),
    Semilla("ia_trabajo", "AI doing the boring half of the work",
            "What did you stop doing by hand this year?"),
    Semilla("claridad", "clearer rules being good news for builders",
            "Why do good rules help the honest projects most?"),
    Semilla("empezar", "starting small with the money you actually have",
            "What is the smallest first step that still counts?"),
    Semilla("riesgo", "sizing positions so you can sleep",
            "What does a position size say about your confidence?"),
    Semilla("errores", "publishing your own misses on purpose",
            "Why is admitting the miss better business than hiding it?"),
    Semilla("proceso", "the checklist that saves you from yourself",
            "Which rule of yours has paid for itself the most?"),
    Semilla("ruido", "ignoring the timeline on a loud day",
            "What did you ignore today that will not matter next month?"),
    Semilla("curiosidad", "reading the thing everyone is arguing about",
            "When did reading the primary source change your mind?"),
    Semilla("salud", "sleep, food and screens as part of the job",
            "What off-screen habit made you better at this?"),
    Semilla("mananas", "the first hour of the day before the noise starts",
            "What do you get done before the market opens?"),
    Semilla("interes_compuesto", "small things repeated for years",
            "What are you doing today that only pays off in years?"),
    Semilla("construir", "building your own tools instead of buying signals",
            "What did you learn by building the thing yourself?"),
    Semilla("puerto_rico", "doing this from outside the usual places",
            "What is an advantage of not being where everyone else is?"),
    Semilla("ensenar", "explaining something until it is simple",
            "What did teaching it teach you?"),
    Semilla("volatilidad", "volatility as the price of admission",
            "What would you be giving up if prices never moved?"),
    # --- Fin de semana: la persona, no el mercado ---------------------------
    Semilla("fe", "faith as the thing that keeps you steady",
            "What keeps you steady when the week goes sideways?", finde=True),
    Semilla("gracias_dios", "thanking God for the ordinary days",
            "What ordinary thing are you grateful for today?", finde=True),
    Semilla("familia_finde", "weekends with the people you work for",
            "Who are you actually doing all this for?", finde=True),
    Semilla("descanso", "resting on purpose and coming back sharper",
            "When did stepping away make you better at this?", finde=True),
    Semilla("servir", "helping someone with no upside for you",
            "Who helped you when there was nothing in it for them?",
            finde=True),
    Semilla("esperanza", "expecting good things and working for them",
            "What are you hopeful about that has nothing to do with price?",
            finde=True),
    Semilla("amistad", "friends who tell you the truth",
            "Who tells you the truth even when you don't want it?",
            finde=True),
    Semilla("proposito", "why you started doing this in the first place",
            "What would you still do if nobody were watching?", finde=True),
    Semilla("humildad", "staying small while things go well",
            "What keeps you humble on a good week?", finde=True),
)


# Puerto Rico es UTC-4 todo el año (no cambia la hora). El servidor corre en
# UTC, así que sin esta cuenta un post de las 9 PM del viernes se generaría
# "en sábado" y saldría con semilla de fin de semana.
HORAS_AST = 4


def es_finde(dia: date | None = None) -> bool:
    """True si en Puerto Rico es sábado o domingo."""
    if dia is not None:
        return dia.weekday() >= 5
    from datetime import datetime, timedelta, timezone

    local = datetime.now(timezone.utc) - timedelta(hours=HORAS_AST)
    return local.weekday() >= 5


def elegir_semilla(ultimo_uso: dict[str, str], hoy: date | None = None,
                   finde: bool | None = None) -> Semilla | None:
    """La semilla más descansada. None si todas salieron hace muy poco.

    Callar es una salida válida: con tres posts al día, forzar una semilla
    repetida es la forma más rápida de sonar a bot con calendario.
    """
    hoy = hoy or date.today()
    finde = es_finde(hoy) if finde is None else finde
    corte = (hoy - timedelta(days=DESCANSO_DIAS)).isoformat()

    def usada(s: Semilla) -> str:
        return ultimo_uso.get(f"personal:{s.clave}", "")

    # El fin de semana solo las de familia, fe y descanso. Entre semana, solo
    # las otras: guardarlas para el finde es lo que hace que el sábado se
    # note distinto.
    candidatas = [s for s in SEMILLAS if s.finde == finde]
    libres = [s for s in candidatas if usada(s) <= corte]
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
            *(["ES SÁBADO O DOMINGO: este post no va de mercados. Va de la "
               "vida de Angel: su familia, su fe, lo que agradece, el "
               "descanso. No menciones precios, ni activos, ni la economía, "
               "ni el trabajo de analizar.",
               "Si hablas de Dios o de la fe, hazlo como algo suyo y en "
               "primera persona, con sencillez. Nada de sermones, nada de "
               "citar versículos, nada de decirle a nadie lo que tiene que "
               "creer ni juzgar a quien crea otra cosa.",
               "Cálido y agradecido, nunca cursi. Una frase honesta vale más "
               "que una bonita."] if semilla.finde else []),
        ],
        as_of=date.today().isoformat(),
    )
