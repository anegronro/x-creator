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
from typing import Any

from xcreator.brief import Brief
from xcreator.generate import MAX_CHARS, _parece_cortado, validate_numbers

# Un reply largo rinde peor: se lee en el hilo, no en el timeline.
MAX_CHARS_REPLY = 240

_CASHTAG = re.compile(r"\$([A-Za-z]{1,5})\b")
# Sin cashtag, el nombre suelto también cuenta si lo tenemos en cartera.
_PALABRA = re.compile(r"\b([A-Z]{2,5})\b")


@dataclass
class Mencion:
    """Un post ajeno al que podríamos responder."""

    autor: str
    texto: str
    url: str = ""
    post_id: str = ""

    def tickers(self) -> set[str]:
        """Tickers mencionados: cashtags, y siglas en mayúscula como respaldo."""
        t = {m.upper() for m in _CASHTAG.findall(self.texto)}
        return t or {m for m in _PALABRA.findall(self.texto)}


@dataclass
class Relevancia:
    """Por qué (o por qué no) tenemos algo que aportar a un post."""

    brief: Brief | None
    ticker: str = ""
    motivo: str = ""

    @property
    def aporta(self) -> bool:
        return self.brief is not None


def encontrar_relevancia(mencion: Mencion, briefs: list[Brief]) -> Relevancia:
    """Empareja un post ajeno con un brief nuestro. Determinista y previo al modelo.

    Devolver `Relevancia(None, ...)` es un resultado legítimo y frecuente: la
    mayoría de los posts de otra gente no son sitios donde tengamos nada que
    añadir, y forzar una respuesta ahí es lo que convierte esto en spam.
    """
    if not mencion.texto.strip():
        return Relevancia(None, motivo="el post no trae texto")
    tickers = mencion.tickers()
    if not tickers:
        return Relevancia(
            None, motivo="el post no menciona ninguna empresa que cubramos")
    por_ticker = {b.ticker.upper(): b for b in briefs}
    for t in tickers:
        if t in por_ticker:
            return Relevancia(
                por_ticker[t], ticker=t,
                motivo=f"tenemos análisis propio de {t} con cifras y fuente")
    return Relevancia(
        None,
        motivo=(f"menciona {', '.join(sorted(tickers))}, que no cubrimos. "
                f"Sin datos propios, responder sería ruido"),
    )


_SYSTEM_REPLY = """You write replies on X for a finance account. A reply's only \
job is to add a fact the original post does not have.

Hard rules:
1. Use ONLY numbers from the brief. Not one other figure.
2. Never compliment, never agree without adding something, never say "great \
thread". A reply with no new information is spam, and it is what gets \
accounts throttled.
3. Don't insult the author or dunk on them. You're adding a data point, not \
winning. The best replies make the original author want to answer.
4. Never tell anyone to buy or sell.
5. No links. No hashtags. No emoji.
6. Stand alone: someone reading only your reply should learn something \
without opening the parent post.
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
            description="En una frase: el dato nuevo que añade a la conversación"
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
        f"Escribe UN reply de máximo {MAX_CHARS_REPLY} caracteres, en inglés, "
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
    return ReplyDraft(
        texto=texto,
        que_aporta=parsed.que_aporta,
        autor=mencion.autor, url=mencion.url, ticker=relevancia.ticker,
        brief_id=brief.brief_id, model=modelo_usado,
        numeros_no_justificados=validate_numbers(texto, brief.allowed_numbers()),
        exceso_caracteres=max(0, len(texto) - MAX_CHARS_REPLY),
        truncado=(getattr(resp, "stop_reason", None) == "max_tokens"
                  or _parece_cortado(texto)),
    )
