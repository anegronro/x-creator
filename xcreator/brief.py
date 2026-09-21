"""Briefs: el paquete de datos duros del que se redacta un post.

El contrato ("sin evidencia, no hay número") aplica igual a un tweet que a un
reporte. Aquí se resuelve por construcción:

1. El brief precomputa TODOS los números que un post tiene permitido usar,
   incluidos los derivados obvios (upside %, distancia al target).
2. El redactor recibe solo esos números.
3. `generate.validate_numbers` rechaza el borrador si aparece cualquier
   cifra que no esté en la lista.

Así un número inventado no llega a la cola; no depende de que el modelo se
porte bien.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class Fact:
    """Un número con su fuente. Sin fuente no entra."""

    label: str
    value: float
    # "pct"     = FRACCIÓN que se lee como porcentaje: 0.40 es 40%.
    # "pct_val" = valor que YA es un porcentaje: 5.01 es 5.01%.
    # "pp"      = puntos porcentuales (un diferencial de tipos): 0.54 es 0.54 pp.
    # Antes solo existía "pct" y se usaba para las tres cosas. El formato
    # `{:+.0%}` multiplica por 100, así que el brief le decía al modelo que el
    # bono a 10 años estaba al "+501%" y la curva al "+54%". El modelo
    # corregía los absurdos solo, pero el 54% parecía plausible y lo copió.
    unit: str  # "usd" | "pct" | "pct_val" | "pp" | "ratio" | "score" | "count"
    source: str

    def rendered(self) -> str:
        if self.unit == "usd":
            return f"${self.value:,.2f}"
        if self.unit == "pct":
            return f"{self.value:+.0%}"
        if self.unit == "pct_val":
            return f"{self.value:.2f}%"
        if self.unit == "pp":
            return (f"{self.value:+.2f} percentage points "
                    f"({self.value * 100:+.0f} bps)")
        if self.unit == "score":
            return f"{self.value:.1f}/10"
        if self.unit == "count":
            return f"{self.value:,.0f}"
        return f"{self.value:,.2f}"

    def line(self) -> str:
        return f"- {self.label}: {self.rendered()}  [fuente: {self.source}]"


@dataclass
class Brief:
    """Todo lo que el redactor puede saber sobre un post."""

    kind: str          # target_range | thesis_check | conviction
    ticker: str
    angle: str         # el ángulo editorial, en una frase
    facts: list[Fact] = field(default_factory=list)
    context: list[str] = field(default_factory=list)  # prosa, sin números nuevos
    as_of: str = ""
    # Dimensión del Cerebro desde la que se mira el ticker (ver cerebro.py).
    angulo: str = "valuacion"
    # Cómo puede nombrarse el tema cuando no hay empresa. Los briefs de
    # ticker lo dejan vacío: ahí el cashtag ya dice de qué se habla.
    sujeto: tuple[str, ...] = ()
    # La historia que cuenta este brief ("bear_pegado", "movimiento"...). La
    # pone el ranking; viaja hasta la cola para que mañana se sepa qué
    # historia se contó hoy.
    motivo: str = ""
    # De dónde salió el hecho, cuando no es un análisis propio: el titular
    # ajeno en un post de regulación. Se guarda para no escribir dos veces
    # del mismo, no se publica.
    fuente: str = ""
    # Quién publicó el hecho, como lo nombraría un periodista ("SEC",
    # "FRED"). Si no está vacío, el post TIENE que nombrar al menos uno: la
    # credibilidad de la cuenta es que cualquiera pueda ir a la fuente, y sin
    # link (13x de costo) la única forma es nombrarla.
    atribucion: tuple[str, ...] = ()

    @property
    def brief_id(self) -> str:
        return f"{self.ticker}-{self.kind}-{self.angulo}-{self.as_of}"

    def allowed_numbers(self) -> list[float]:
        """Las cifras que el post puede citar, en las formas que admite su unidad.

        La conversión por 100 depende de la unidad y vive AQUÍ, no en el
        validador: una fracción 0.40 se escribe "40%", pero un diferencial de
        0.54 puntos NO se escribe "54%". El validador multiplicaba todo por 100
        y dejó pasar la curva a "+54%".
        """
        out: list[float] = []
        for f in self.facts:
            out.append(f.value)
            if f.unit == "pct":                  # fracción: 0.40 -> 40
                out.append(f.value * 100)
            # "pp" NO se multiplica: el validador no distingue el símbolo, y
            # permitir 54 para que valga "54 bps" dejaba pasar "+54%". No hace
            # falta: "54 bps" es un entero sin símbolo menor que 100 y el
            # validador ya lo trata como texto. "+54%" lleva %, y falla.
        return out

    def render(self) -> str:
        """El brief tal como lo ve el redactor."""
        parts = [
            f"TICKER: {self.ticker}",
            f"ÁNGULO: {self.angle}",
            "",
            "NÚMEROS PERMITIDOS (no puedes usar ningún otro):",
            *[f.line() for f in self.facts],
        ]
        if self.context:
            parts += ["", "CONTEXTO (cualitativo, no inventes cifras de aquí):",
                      *[f"- {c}" for c in self.context]]
        return "\n".join(parts)


def _pct_change(new: float, old: float) -> float | None:
    return (new / old - 1.0) if old else None


def from_prediction(pred: dict, price_now: float | None = None) -> Brief | None:
    """Brief desde un `prediccion.json` del motor de acciones (WBJ).

    La atribución "WBJ analyze <fecha>" que llevan los facts es deliberada:
    dice de dónde salió cada cifra. Es trazabilidad, no una dependencia de
    código — este proyecto solo lee el JSON.

    Con `price_now` el brief se vuelve un chequeo de tesis (lo que dijimos
    vs lo que pasó), que es contenido mucho más fuerte que repetir el
    target: es verificable y admite estar equivocado.
    """
    needed = ("ticker", "date", "price", "bear", "base", "bull")
    if not all(k in pred for k in needed):
        return None

    t = pred["ticker"]
    p0 = float(pred["price"])
    facts = [
        Fact("precio cuando publicamos el análisis", p0, "usd",
             f"WBJ analyze {pred['date']}"),
        Fact("escenario bajo (12m)", float(pred["bear"]), "usd",
             f"WBJ targets {pred['date']}"),
        Fact("escenario base (12m)", float(pred["base"]), "usd",
             f"WBJ targets {pred['date']}"),
        Fact("escenario alto (12m)", float(pred["bull"]), "usd",
             f"WBJ targets {pred['date']}"),
    ]
    # El score NO va en los facts: es una métrica interna que el lector no
    # puede ver ni verificar. Publicar "8.7/10" es pedirle que se fíe de una
    # escala que no conoce, y ocupa caracteres que podrían llevar un dato
    # comprobable. Va como contexto cualitativo, sin cifra: sirve para que el
    # redactor calibre el tono, no para citarlo.
    if pred.get("score10") is not None:
        s10 = float(pred["score10"])
        calidad = ("alta" if s10 >= 7.5 else
                   "media" if s10 >= 5 else "baja")
        context_score = (
            f"Calidad {calidad} según el modelo interno. NO menciones el "
            f"score ni ninguna puntuación: el lector no puede verla."
        )
    else:
        context_score = ""
    if pred.get("pe_now") is not None:
        facts.append(Fact("P/E al momento del análisis", float(pred["pe_now"]),
                          "ratio", f"WBJ analyze {pred['date']}"))
    if pred.get("growth_base") is not None:
        facts.append(Fact("crecimiento asumido en el escenario base",
                          float(pred["growth_base"]), "pct",
                          "supuesto declarado del modelo"))

    # Derivados: se precomputan para que el redactor no tenga que calcular
    # (y para que el validador los reconozca como legítimos).
    up_base = _pct_change(float(pred["base"]), p0)
    if up_base is not None:
        facts.append(Fact("upside al escenario base desde el precio del análisis",
                          up_base, "pct", "calculado: base/precio - 1"))

    kind, angle = "target_range", (
        f"El rango de 12 meses del modelo para {t}, con los supuestos a la vista."
    )
    context = [
        "El rango sale de escenarios con supuestos declarados, no de un precio único.",
        "Es una clasificación de research, nunca una instrucción de compra o venta.",
    ]
    if context_score:
        context.append(context_score)

    if price_now:
        facts.append(Fact("precio hoy", float(price_now), "usd", "FMP quote"))
        moved = _pct_change(float(price_now), p0)
        if moved is not None:
            facts.append(Fact("movimiento real desde el análisis", moved, "pct",
                              "calculado: precio hoy/precio análisis - 1"))
        dentro = float(pred["bear"]) <= float(price_now) <= float(pred["bull"])
        kind = "thesis_check"
        angle = (
            f"Qué dijo el modelo sobre {t} el {pred['date']} y qué pasó realmente. "
            f"El precio hoy está {'DENTRO' if dentro else 'FUERA'} del rango bear-bull."
        )
        context = [
            f"El precio de hoy está {'dentro' if dentro else 'fuera'} del rango proyectado.",
            "Publicar el marcador — acierto o error — es el punto: la mayoría"
            " de cuentas solo publica los aciertos.",
            "El horizonte del target es 12 meses; aún no está maduro si han"
            " pasado menos.",
        ]
        if context_score:
            context.append(context_score)

    return Brief(
        kind=kind, ticker=t, angle=angle, facts=facts, context=context,
        as_of=date.today().isoformat(),
    )


def load_briefs(
    reports_dir: Path | None,
    price_fn=None,
    *,
    limit: int = 10,
) -> list[Brief]:
    """Un brief por cada predicción guardada, la más reciente por ticker.

    `reports_dir` es una RUTA a los JSON que el motor de acciones ya escribe:
    este proyecto los lee, no importa su código. Si la ruta no existe, se
    devuelve [] y el resto del sistema sigue funcionando con otras fuentes.

    `price_fn(ticker) -> float | None` es inyectable: sin ella los briefs se
    arman igual, solo que sin el chequeo contra la realidad.
    """
    from xcreator.datos import load_predictions

    preds = load_predictions(reports_dir)
    latest: dict[str, dict] = {}
    for p in preds:  # load_predictions viene ordenado del más viejo al más nuevo
        latest[p["ticker"]] = p

    briefs: list[Brief] = []
    for pred in sorted(latest.values(), key=lambda p: p["date"], reverse=True)[:limit]:
        price = None
        if price_fn is not None:
            try:
                price = price_fn(pred["ticker"])
            except Exception:
                price = None  # sin precio el brief sigue sirviendo, solo sin marcador
        b = from_prediction(pred, price)
        if b:
            briefs.append(b)
    return briefs


def load_brief_file(path: Path) -> Brief:
    """Brief desde un JSON a mano — para contenido que no sale del motor."""
    d = json.loads(path.read_text())
    return Brief(
        kind=d.get("kind", "custom"),
        ticker=d.get("ticker", ""),
        angle=d["angle"],
        facts=[Fact(**f) for f in d.get("facts", [])],
        context=d.get("context", []),
        as_of=d.get("as_of", date.today().isoformat()),
    )


def con_precio(reports_dir, brief: Brief, price_fn) -> Brief:
    """El mismo brief, ahora con su precio de hoy. Para cuando solo hace falta
    uno de los 153.

    El vigilante pedía el precio de las 153 empresas cada 15 minutos para
    luego responder, como mucho, sobre una o dos: unas 5,000 llamadas diarias
    a FMP, a un ritmo que roza el límite por minuto del plan. Emparejar no
    necesita el precio; redactar sí, y solo el de la empresa elegida.
    """
    from xcreator.datos import load_predictions

    if brief.kind not in ("target_range", "thesis_check", "conviction"):
        return brief                      # macro, cripto: ya traen su dato
    ultima = None
    for p in load_predictions(reports_dir):
        if p["ticker"].upper() == brief.ticker.upper():
            ultima = p
    if ultima is None:
        return brief
    try:
        precio = price_fn(brief.ticker)
    except Exception:
        precio = None
    nuevo = from_prediction(ultima, precio)
    if nuevo is None:
        return brief
    nuevo.angulo = brief.angulo
    return nuevo
