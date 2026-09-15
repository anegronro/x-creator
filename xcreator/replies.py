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

    @property
    def aporta(self) -> bool:
        return self.brief is not None


def encontrar_relevancia(mencion: Mencion, briefs: list[Brief],
                         nombres: dict[str, str] | None = None,
                         cripto: Callable[[str], Brief | None] | None = None,
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
    return Relevancia(
        None,
        motivo=(f"menciona {', '.join(sorted(tickers))}, que no cubrimos. "
                f"Sin datos propios, responder sería ruido"),
    )


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
sentences. No preamble, no "actually"."""


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
    ticker: str = ""
    brief_id: str = ""
    model: str = ""
    numeros_no_justificados: list[str] = field(default_factory=list)
    exceso_caracteres: int = 0
    truncado: bool = False
    idioma_incorrecto: bool = False
    tickers_faltantes: list[str] = field(default_factory=list)
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
        )


def draft_reply(
    mencion: Mencion,
    relevancia: Relevancia,
    settings,
    *,
    client: Any = None,
    model: str | None = None,
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
        from xcreator.config import anthropic_client

        client = anthropic_client(settings)
        if client is None:
            return ReplyDraft(
                texto="", que_aporta="", autor=mencion.autor, url=mencion.url,
                declinado=True, motivo="sin ANTHROPIC_API_KEY o sin SDK",
                model=modelo_usado,
            )

    from xcreator.cerebro import ANGULOS, metodologia
    from xcreator.generate import _system_blocks

    angulo = ANGULOS.get(brief.angulo) or ANGULOS["valuacion"]
    metodo = metodologia(getattr(settings, "cerebro_dir", None), brief.angulo)

    user = (
        f"POST AL QUE RESPONDES (de {mencion.autor}):\n"
        f"\"\"\"\n{mencion.texto.strip()}\n\"\"\"\n\n"
        f"{brief.render()}\n\n"
        f"Escribe UN reply de máximo {LARGO_PREFERIDO} caracteres (nunca más "
        f"de {MAX_CHARS}), en inglés, "
        f"que añada un dato duro de arriba a esta conversación. Si nada del "
        f"brief se relaciona de verdad con lo que dice el post, pon "
        f"aporta_algo=false y no escribas nada."
    )

    resp = client.messages.parse(
        model=modelo_usado, max_tokens=16000,
        system=_system_blocks(metodo, angulo),
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
            url=mencion.url, ticker=relevancia.ticker, brief_id=brief.brief_id,
            declinado=True, model=modelo_usado,
            motivo=("el modelo no encontró nada del brief que aporte a este "
                    "post concreto"),
        )

    texto = parsed.texto.strip()
    # Citar una cifra del post al que respondes es legítimo y verificable:
    # está ahí, a la vista de cualquiera. Lo que no puede es inventarla.
    permitidos = brief.allowed_numbers() + _numeros_del_texto(mencion.texto)
    return ReplyDraft(
        texto=texto,
        que_aporta=parsed.que_aporta,
        autor=mencion.autor, url=mencion.url, ticker=relevancia.ticker,
        brief_id=brief.brief_id, model=modelo_usado,
        numeros_no_justificados=validate_numbers(texto, permitidos),
        # Contra el límite REAL de X, no contra la preferencia.
        exceso_caracteres=max(0, len(texto) - MAX_CHARS),
        truncado=(getattr(resp, "stop_reason", None) == "max_tokens"
                  or _parece_cortado(texto)),
        idioma_incorrecto=not es_ingles(texto),
        tickers_faltantes=falta_ticker(texto, relevancia.ticker),
    )
