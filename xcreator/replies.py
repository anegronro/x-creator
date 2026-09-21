"""Asistente de replies: donde de verdad crece una cuenta chica.

Los datos de la cuenta dicen que el cuello de botella es alcance, no
redacción: 6.402 impresiones en un año y 24 replies en total. En FinTwit una
cuenta pequeña no crece por sus propios posts — crece respondiendo a cuentas
grandes, porque ahí es donde la ve gente por primera vez.

**La regla que mantiene esto honesto: saber abstenerse.** Si no tenemos un
dato duro que aporte al post ajeno, no se genera respuesta. Un asistente que
siempre encuentra algo que decir es una máquina de spam, y X penaliza
exactamente eso. Por eso el emparejamiento es determinista (ticker
mencionado ↔ brief que tenemos) y ocurre ANTES de llamar al modelo: si no hay
material, no se gasta ni un token.

El módulo no lee X por su cuenta: recibe el post (a mano o, cuando haya
créditos de la API, desde ella). Así funciona hoy sin depender de eso.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from xcreator.brief import Brief
from xcreator.cripto import ACTIVOS
from xcreator.generate import (
    cifras_mal_formateadas, falta_sujeto, lleva_raya,
    MAX_CHARS, _parece_cortado, es_ingles, falta_ticker, validate_numbers,
)

# Preferencia editorial, no límite: un reply largo rinde peor porque se lee
# en el hilo, no en el timeline. Se le pide al modelo, pero pasarse de aquí
# NO invalida nada — el límite duro es el de X (MAX_CHARS, 280).
LARGO_PREFERIDO = 240

_CASHTAG = re.compile(r"\$([A-Za-z]{1,5})\b")
_SIGLA = re.compile(r"\b([A-Z]{3,5})\b")

# Siglas que aparecen a diario en titulares de mercado y NO son la empresa
# homónima. Sin esta lista, un titular en mayúsculas de zerohedge produce
# "tickers" como AFTER, CALLS, SLOW o KOSPI, y el sistema propone responder
# sobre empresas que nadie mencionó.
_NO_SON_TICKERS = {
    "AFTER", "CALLS", "FALL", "FALLS", "SLOW", "MORE", "THAN", "DOWN", "OVER",
    "INDEX", "KOREA", "SOUTH", "NORTH", "CHINA", "JAPAN", "EURO", "BREAKING",
    "WSJ", "NBC", "CNBC", "CNN", "BBC", "FOX", "CEO", "CEOS", "CFO", "USA",
    "GDP", "CPI", "PPI", "PCE", "FED", "FOMC", "ECB", "BOJ", "BOE", "OPEC",
    "ETF", "ETFS", "IPO", "SEC", "IRS", "FBI", "DOJ", "NYSE", "NASDAQ",
    "BPS", "YOY", "QOQ", "EPS", "GAAP", "EBIT", "WTI", "OAS", "AI", "HY",
    "AND", "THE", "FOR", "WITH", "FROM", "THIS", "THAT", "WILL", "SAYS",
    "NEW", "NOW", "TOP", "BIG", "ALL", "KEY", "WAR", "OIL", "GAS", "JUST",
}


@dataclass
class Mencion:
    """Un post ajeno al que podríamos responder."""

    autor: str
    texto: str
    url: str = ""
    post_id: str = ""

    def tickers(self, nombres: dict[str, str] | None = None) -> set[str]:
        """Tickers mencionados, por orden de fiabilidad.

        1. Cashtags ($NVDA): inequívocos.
        2. Nombres de empresa ("Oracle"), que es como escribe la gente de
           verdad — sin esto se perdían posts sobre empresas que sí cubrimos.
        3. Siglas sueltas en mayúscula, solo si no son de las que salen a
           diario en titulares y no son la empresa.
        """
        encontrados = {m.upper() for m in _CASHTAG.findall(self.texto)}

        if nombres:
            bajo = self.texto.lower()
            for nombre, ticker in nombres.items():
                if re.search(rf"\b{re.escape(nombre)}\b", bajo):
                    encontrados.add(ticker)

        # Los activos digitales se nombran casi siempre por su nombre
        # ("Bitcoin falls under $77,000", "Ripple CEO..."), no por el
        # cashtag. Sin esto, una cuenta de cripto pasa entera por el filtro
        # sin producir un solo reply.
        bajo_texto = self.texto.lower()
        for cfg in ACTIVOS.values():
            if any(re.search(rf"\b{re.escape(a)}\b", bajo_texto)
                   for a in cfg.alias):
                encontrados.add(cfg.ticker)

        for sigla in _SIGLA.findall(self.texto):
            if sigla not in _NO_SON_TICKERS:
                encontrados.add(sigla)
        return encontrados


# Temas sobre los que hay criterio aunque no haya un solo número nuestro.
# La lista es corta a propósito: fuera de esto no es nuestra conversación, y
# opinar de todo es como se pierde una cuenta de nicho.
# Las claves tienen que ser INEQUÍVOCAS. La primera versión llevaba
# "settlement" pensando en la liquidación de operaciones y enganchó con un
# acuerdo judicial de zerohedge; peor aún, ese falso positivo se comió el
# único cupo de opinión del día antes de llegar a la cuenta para la que se
# construyó. Una palabra con dos significados en finanzas no sirve aquí.
_TEMAS_SIN_CIFRAS: dict[str, tuple[str, ...]] = {
    "regulación de cripto": (
        "clarity act", "crypto bill", "crypto tax", "crypto legislation",
        "crypto market structure", "stablecoin bill", "genius act",
        "digital asset", "cryptocurrency exchange", "crypto exchange",
        "crypto regulation", "crypto etf", "bitcoin etf", "spot etf",
        "sec crypto", "crypto custody", "self-custody",
    ),
    "estructura de mercado": (
        "t+1 settlement", "settlement cycle", "payment for order flow",
        "circuit breaker", "short-sale rule", "naked short", "market maker",
        "dark pool", "tick size", "24-hour trading", "extended hours trading",
    ),
    "política monetaria": (
        "rate cut", "rate hike", "quantitative easing",
        "quantitative tightening", "debt ceiling", "yield curve control",
    ),
}


def _tema_sin_cifras(texto: str) -> str:
    # La regulación de cripto se decide en un solo sitio, con la misma regla
    # que usan los posts propios: una lista de frases aquí y otra allí acaba
    # clasificando distinto el mismo titular.
    from xcreator.regulacion import es_regulacion_cripto

    if es_regulacion_cripto(texto):
        return "regulación de cripto"
    # Las frases de la lista siguen valiendo como respaldo en los REPLIES:
    # "Cryptocurrency exchange CoinEx to shut down" no tiene regulador ni
    # señal regulatoria, así que no da para un post propio de regulación,
    # pero sí para un reply con criterio. Los posts propios usan la regla
    # estricta; aquí basta con que sea conversación de nuestro nicho.
    bajo = texto.lower()
    for tema, claves in _TEMAS_SIN_CIFRAS.items():
        if any(k in bajo for k in claves):
            return tema
    return ""


_NUM_EN_TEXTO = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numeros_del_texto(texto: str) -> list[float]:
    """Las cifras que aparecen en el post ajeno, como floats.

    Se añaden a las permitidas: responder citando un dato del post original
    no es inventar, y bloquearlo obliga a escribir replies que no pueden
    referirse a lo que contestan.
    """
    out: list[float] = []
    for m in _NUM_EN_TEXTO.finditer(texto):
        try:
            v = float(m.group(0).replace(",", ""))
        except ValueError:
            continue
        out.extend([v, v / 100])   # "4%" en el post puede citarse como 0.04
    return out


@dataclass
class Relevancia:
    """Por qué (o por qué no) tenemos algo que aportar a un post."""

    brief: Brief | None
    ticker: str = ""
    motivo: str = ""
    # Sin cifras propias, pero el tema es nuestro y hay criterio que aportar.
    # No todo lo que vale la pena decir es una estadística: un proyecto de ley
    # o el cierre de un exchange no tienen brief y siguen siendo la
    # conversación donde está la audiencia.
    solo_opinion: bool = False
    tema: str = ""

    @property
    def aporta(self) -> bool:
        return self.brief is not None or self.solo_opinion


def encontrar_relevancia(mencion: Mencion, briefs: list[Brief],
                         nombres: dict[str, str] | None = None,
                         cripto: Callable[[str], Brief | None] | None = None,
                         macro: Callable[[str], Brief | None] | None = None,
                         ) -> Relevancia:
    """Empareja un post ajeno con un brief nuestro. Determinista y previo al modelo.

    Devolver `Relevancia(None, ...)` es un resultado legítimo y frecuente: la
    mayoría de los posts de otra gente no son sitios donde tengamos nada que
    añadir, y forzar una respuesta ahí es lo que convierte esto en spam.
    """
    if not mencion.texto.strip():
        return Relevancia(None, motivo="el post no trae texto")
    tickers = mencion.tickers(nombres)
    if not tickers:
        # Macro va antes que la opinión: un post sobre tipos o inflación no es
        # "sin cifras propias", es justo donde más tenemos. El filtro miraba
        # acciones y cripto y se saltaba FRED entero.
        if macro is not None:
            b = macro(mencion.texto)
            if b is not None:
                return Relevancia(
                    b, motivo="tenemos el dato de FRED con su fecha y fuente")
        tema = _tema_sin_cifras(mencion.texto)
        if tema:
            return Relevancia(
                None, solo_opinion=True, tema=tema,
                motivo=f"sin cifras propias, pero es {tema}: cabe criterio")
        return Relevancia(
            None, motivo="el post no menciona ninguna empresa que cubramos")
    por_ticker = {b.ticker.upper(): b for b in briefs}
    for t in tickers:
        if t in por_ticker:
            return Relevancia(
                por_ticker[t], ticker=t,
                motivo=f"tenemos análisis propio de {t} con cifras y fuente")
    # Cripto va después de las acciones a propósito: si un post menciona las
    # dos cosas, el análisis de la empresa es más específico. Y se consulta
    # de forma perezosa —solo si el post nombra un activo— para no pedir
    # precios en cada pasada del vigilante.
    if cripto is not None:
        for t in sorted(tickers):
            b = cripto(t)
            if b is not None:
                return Relevancia(
                    b, ticker=t,
                    motivo=f"tenemos datos de precio de {t} con fuente y fecha")
    if macro is not None:
        b = macro(mencion.texto)
        if b is not None:
            return Relevancia(
                b, motivo="tenemos el dato de FRED con su fecha y fuente")
    tema = _tema_sin_cifras(mencion.texto)
    if tema:
        return Relevancia(
            None, solo_opinion=True, tema=tema,
            motivo=f"sin cifras propias, pero es {tema}: cabe criterio")
    return Relevancia(
        None,
        motivo=(f"menciona {', '.join(sorted(tickers))}, que no cubrimos. "
                f"Sin datos propios, responder sería ruido"),
    )


from xcreator.generate import VOZ_PERSONAL  # noqa: E402

_SYSTEM_REPLY = """You write replies on X for a finance account. A reply's only \
job is to add something the original post does not have.

Usually that is a number. Sometimes it isn't, and forcing one in is worse \
than not replying: a post about a bill moving through the Senate, an \
exchange shutting down, or an executive's remark does not get a price \
statistic bolted onto it. Answer what the post is actually about. A sharp \
distinction, a consequence the post skips, or a question that makes the \
claim testable all count as adding something — and on a post with no \
numbers in it, they are the only honest way to reply.

Hard rules:
1. Use ONLY numbers from the brief. Not one other figure. This does not mean \
you must use a number: it means any number you use comes from there.
1c. Match the register of the post you are answering. Reply to a regulatory \
or news post on its own terms; reply to a price post with the price data.
1b. Never cite an internal score or rating: the reader cannot see it or \
verify it. Use prices, multiples, growth assumptions and ranges.
2. Never compliment, never agree without adding something, never say "great \
thread". A reply with no new information is spam, and it is what gets \
accounts throttled.
2b. No dashes as punctuation: no em dash, no en dash, no " - " between \
clauses. A full stop, a comma or a colon instead. Hyphens inside a word are \
fine ("10-year", "high-yield"). Numbers follow English convention: comma for \
thousands, full stop for decimals (79,900 and 10.99).
3. Don't insult the author or dunk on them. You're adding a data point, not \
winning. The best replies make the original author want to answer.
4. Never tell anyone to buy or sell.
5. No links. No hashtags. No emoji.
5b. Mention the ticker or asset BOTH ways: as a cashtag ($NVDA, $BTC) and as \
plain text (NVDA, BTC). X indexes them separately and a small account cannot afford to skip \
half the discovery.
6. Stand alone: someone reading only your reply should learn something \
without opening the parent post.
6b. When the brief is a digital asset, remember there is no valuation model \
behind it — no filings, no cash flow. Never imply a fair value or a target.
7. If the brief genuinely has nothing that bears on this post, say so by \
setting `aporta_algo` to false. Declining is a correct answer and is better \
than a generic reply.

Tone: a peer adding one hard number to the conversation. One or two \
sentences. No preamble, no "actually".""" + "\n\n" + VOZ_PERSONAL


_SYSTEM_OPINION = """You write replies on X for a finance account. This one is \
different from the rest: there is no data behind it.

You are answering a post about markets, policy or the industry where we hold \
no figures of our own. That is not a reason to stay quiet — it means the \
value of this reply is the judgement, not a statistic. Most replies under \
these posts are cheering or booing. A reply that names the mechanism nobody \
is naming is worth more than another number would be.

Hard rules:
1. NO NUMBERS. Not one — unless it already appears in the post you are \
answering. You have no brief here, so any figure you write would be invented.
2. Assert no fact beyond what the post states. You do not know what a bill \
contains, what happened after this post, or what anyone said elsewhere. If \
your point needs a fact you do not have, make a different point.
3. Take a real position: a consequence the post skips, a distinction people \
are collapsing, an incentive nobody named, or what would have to be true for \
the headline to matter. "Interesting" is not a position.
4. No party politics. You may say an incentive is obvious or a rule is \
incoherent; you never take a side between parties, and you never attack a \
person. The account is about markets, not elections.
5. Never tell anyone to buy or sell, and never predict a price.
6. Don't insult the author. No links, no hashtags, no emoji. No dashes as \
punctuation either: no em dash, no en dash, no " - " between clauses. Use a \
full stop, a comma or a colon. Hyphens inside a word are fine ("10-year").
7. If you have nothing worth saying, set aporta_algo to false. Silence is a \
correct answer and is far better than a generic take.

Tone: someone who has watched this cycle before and is unimpressed by the \
headline. One or two sentences, no preamble.""" + "\n\n" + VOZ_PERSONAL


class _ReplyOut:
    """Contrato de salida. Se define con pydantic en `_modelo()` para no
    importarlo si nunca se genera un reply."""


def _modelo():
    from pydantic import BaseModel, Field

    class ReplyOut(BaseModel):
        aporta_algo: bool = Field(
            description="False si el brief no tiene nada que aporte a este post"
        )
        texto: str = Field(description="El reply en inglés, <= 240 caracteres")
        que_aporta: str = Field(
            description="En una frase: qué añade a la conversación (un dato, "
                        "una distinción o una consecuencia que el post omite)"
        )

    return ReplyOut


@dataclass
class ReplyDraft:
    """Un reply listo para revisión, con su auditoría."""

    texto: str
    que_aporta: str
    autor: str
    url: str = ""
    # "reply" o "cita". La cola deriva el tipo de aquí.
    kind: str = "reply"
    ticker: str = ""
    brief_id: str = ""
    model: str = ""
    numeros_no_justificados: list[str] = field(default_factory=list)
    exceso_caracteres: int = 0
    truncado: bool = False
    idioma_incorrecto: bool = False
    tickers_faltantes: list[str] = field(default_factory=list)
    usa_raya: bool = False
    cifras_mal: list[str] = field(default_factory=list)
    sujeto_ausente: bool = False
    # Cuando el modelo decide que no hay nada que aportar.
    declinado: bool = False
    motivo: str = ""

    @property
    def text(self) -> str:
        """Alias de `texto`: la cola guarda posts y replies con el mismo campo."""
        return self.texto

    @property
    def valido(self) -> bool:
        return (
            not self.declinado
            and bool(self.texto.strip())
            and not self.numeros_no_justificados
            and self.exceso_caracteres == 0
            and not self.truncado
            and not self.idioma_incorrecto
            and not self.tickers_faltantes
            and not self.usa_raya
            and not self.cifras_mal
            and not self.sujeto_ausente
        )


def draft_reply(
    mencion: Mencion,
    relevancia: Relevancia,
    settings,
    *,
    client: Any = None,
    model: str | None = None,
    modo: str = "reply",
) -> ReplyDraft:
    """Redacta un reply, o devuelve uno marcado como declinado.

    No llama al modelo si el emparejamiento determinista ya dijo que no hay
    material: abstenerse es gratis y debe serlo.
    """
    from xcreator.generate import MODEL

    modelo_usado = model or MODEL
    if not relevancia.aporta:
        return ReplyDraft(
            texto="", que_aporta="", autor=mencion.autor, url=mencion.url,
            declinado=True, motivo=relevancia.motivo, model=modelo_usado,
        )

    brief = relevancia.brief
    if client is None:
        from xcreator.config import llm_client

        client = llm_client(settings)
        if client is None:
            return ReplyDraft(
                texto="", que_aporta="", autor=mencion.autor, url=mencion.url,
                declinado=True, motivo="sin clave del modelo (XAI_API_KEY o ANTHROPIC_API_KEY)",
                model=modelo_usado,
            )

    if modo == "cita":
        cabecera = (f"POST QUE VAS A CITAR (de {mencion.autor}):\n"
                    f"\"\"\"\n{mencion.texto.strip()}\n\"\"\"\n\n"
                    "Esto NO es un reply: es una CITA. Sale en TU perfil y en "
                    "el feed de tus seguidores, con el post de arriba incrustado "
                    "debajo. Escríbelo como una toma tuya que se entiende sola "
                    "junto al original: no le hables al autor (nada de \"you\"), "
                    "no repitas lo que el post ya dice, di lo que tú ves que él "
                    "no dice.\n\n")
    else:
        cabecera = (f"POST AL QUE RESPONDES (de {mencion.autor}):\n"
                    f"\"\"\"\n{mencion.texto.strip()}\n\"\"\"\n\n")

    if relevancia.solo_opinion:
        # Sin brief no hay metodología del Cerebro que aplicar: el Cerebro
        # analiza empresas, y aquí no hay ninguna. El system va solo.
        sistema = [{"type": "text", "text": _SYSTEM_OPINION}]
        user = (
            f"{cabecera}"
            f"TEMA: {relevancia.tema}. No tenemos cifras propias sobre esto.\n\n"
            f"Escribe UN reply de máximo {LARGO_PREFERIDO} caracteres (nunca "
            f"más de {MAX_CHARS}), en inglés. Sin un solo número que no esté "
            f"ya en el post de arriba. Si no tienes nada que merezca la pena, "
            f"pon aporta_algo=false."
        )
    else:
        from xcreator.cerebro import ANGULOS, metodologia
        from xcreator.generate import _system_blocks

        angulo = ANGULOS.get(brief.angulo) or ANGULOS["valuacion"]
        metodo = metodologia(getattr(settings, "cerebro_dir", None),
                             brief.angulo)
        sistema = _system_blocks(metodo, angulo)
        user = (
            f"{cabecera}"
            f"{brief.render()}\n\n"
            f"Escribe UN reply de máximo {LARGO_PREFERIDO} caracteres (nunca "
            f"más de {MAX_CHARS}), en inglés, que añada un dato duro de arriba "
            f"a esta conversación. Si nada del brief se relaciona de verdad "
            f"con lo que dice el post, pon aporta_algo=false y no escribas "
            f"nada."
        )

    modelo_usado = (model or getattr(client, "modelo_por_defecto", None)
                    or modelo_usado)
    resp = client.messages.parse(
        model=modelo_usado, max_tokens=16000,
        system=sistema,
        messages=[{"role": "user", "content": user}],
        output_format=_modelo(),
    )
    parsed = resp.parsed_output
    if parsed is None:
        return ReplyDraft(
            texto="", que_aporta="", autor=mencion.autor, url=mencion.url,
            declinado=True, motivo="el modelo no devolvió nada usable",
            model=modelo_usado,
        )

    if not parsed.aporta_algo:
        return ReplyDraft(
            texto="", que_aporta=parsed.que_aporta, autor=mencion.autor,
            url=mencion.url, ticker=relevancia.ticker,
            brief_id=brief.brief_id if brief else "",
            declinado=True, model=modelo_usado,
            motivo=("el modelo no encontró nada del brief que aporte a este "
                    "post concreto"),
        )

    texto = parsed.texto.strip()
    # Citar una cifra del post al que respondes es legítimo y verificable:
    # está ahí, a la vista de cualquiera. Lo que no puede es inventarla.
    # Sin brief, lo ÚNICO citable son las cifras del post al que respondes:
    # cualquier otra sería inventada, y esta es la comprobación que lo impide
    # en código en vez de confiar en que el prompt se respete.
    permitidos = (brief.allowed_numbers() if brief else []) \
        + _numeros_del_texto(mencion.texto)
    return ReplyDraft(
        texto=texto,
        kind=modo,
        que_aporta=parsed.que_aporta,
        autor=mencion.autor, url=mencion.url, ticker=relevancia.ticker,
        brief_id=brief.brief_id if brief else "", model=modelo_usado,
        numeros_no_justificados=validate_numbers(texto, permitidos),
        # Contra el límite REAL de X, no contra la preferencia.
        exceso_caracteres=max(0, len(texto) - MAX_CHARS),
        truncado=(getattr(resp, "stop_reason", None) == "max_tokens"
                  or _parece_cortado(texto)),
        idioma_incorrecto=not es_ingles(texto),
        tickers_faltantes=falta_ticker(texto, relevancia.ticker),
        usa_raya=lleva_raya(texto),
        cifras_mal=cifras_mal_formateadas(texto),
        # Un reply también se lee suelto: sin ticker que lo diga, tiene que
        # nombrar el dato. Aplica a macro y cripto, no a los de empresa.
        sujeto_ausente=(not relevancia.ticker
                        and falta_sujeto(texto, getattr(brief, "sujeto", ())
                                         if brief else ())),
    )
