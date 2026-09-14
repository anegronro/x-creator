"""Contenido de mercado y economía, no atado a una empresa.

Complementa a los posts de tickers, no los sustituye: amplía el repertorio
para los días en que ninguna empresa tiene tensión, y llega a gente que sigue
macro pero no sigue nombres concretos.

Mismo contrato que el resto: cada cifra sale de FRED con su fecha, y lo que
hace noticiable a un dato se calcula —cuánto se movió, dónde está respecto a
su propia historia— en vez de afirmarse.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, datetime

from xcreator.brief import Brief, Fact


@dataclass(frozen=True)
class SerieMacro:
    serie: str          # id en FRED
    nombre: str         # cómo se llama en el post, en inglés
    unidad: str         # "pct" | "ratio" | "count"
    angulo: str         # la pregunta que abre este dato
    decimales: int = 2
    # Las formas en que un redactor puede nombrar este dato. Al menos una
    # tiene que aparecer en el post: sin empresa no hay cashtag que diga de
    # qué se habla, y un porcentaje suelto no lo dice. Nadie es adivino.
    alias: tuple[str, ...] = ()


# Catálogo deliberadamente corto: series que mueven la conversación de
# mercados y que cualquiera puede comprobar en FRED.
SERIES: dict[str, SerieMacro] = {
    "curva": SerieMacro(
        "T10Y2Y", "the 10y-2y Treasury spread", "pct",
        "What does the shape of the curve say that the index doesn't?",
        alias=("curve", "yield curve", "10y-2y", "10s2s", "2s10s", "two-year", "treasury")),
    "tasa10": SerieMacro(
        "DGS10", "the 10-year Treasury yield", "pct",
        "What equity multiple survives this risk-free rate?",
        alias=("10-year", "10 year", "10y", "ten-year", "treasury", "long bond")),
    "desempleo": SerieMacro(
        "UNRATE", "the unemployment rate", "pct",
        "Is the labour market loosening fast enough to matter?", 1,
        alias=("unemployment", "jobless", "labour market", "labor market", "payroll")),
    "inflacion": SerieMacro(
        "CPIAUCSL", "CPI", "count",
        "Is disinflation still happening, or did it stall?",
        alias=("cpi", "inflation", "consumer price", "disinflation")),
    "hipoteca": SerieMacro(
        "MORTGAGE30US", "the 30-year mortgage rate", "pct",
        "What does this do to housing-linked demand?",
        alias=("mortgage", "housing", "homebuy", "30-year fixed")),
    "fed": SerieMacro(
        "DFF", "the effective fed funds rate", "pct",
        "How much room does the Fed actually have?",
        alias=("fed funds", "federal funds", "the fed", "policy rate", "front end")),
    "highyield": SerieMacro(
        "BAMLH0A0HYM2", "the high-yield credit spread", "pct",
        "Is credit pricing the same risk equities are?",
        alias=("high yield", "high-yield", "credit spread", "junk", "hy spread", "credit market")),
}


@dataclass
class Lectura:
    """Un dato macro con su contexto histórico, todo calculado."""

    cfg: SerieMacro
    fecha: str
    valor: float
    hace_un_mes: float | None
    hace_un_ano: float | None
    minimo_5a: float
    maximo_5a: float
    percentil_5a: float

    @property
    def cambio_anual(self) -> float | None:
        if self.hace_un_ano is None:
            return None
        return self.valor - self.hace_un_ano

    @property
    def plana(self) -> bool:
        """True si la serie apenas se ha movido en términos de su propio nivel.

        Sin esto, una serie que oscila entre 4.00 y 4.02 puntúa como extremo
        histórico: el percentil y el recorrido son relativos, así que con un
        rango minúsculo cualquier variación parece enorme. Un movimiento de
        dos centésimas en el bono a 10 años no es noticia.
        """
        escala = max(abs(self.valor), 1e-9)
        return (self.maximo_5a - self.minimo_5a) / escala < 0.05

    @property
    def tension(self) -> float:
        """Cuán noticiable es. Un dato en un extremo histórico o que se movió
        mucho da conversación; uno en su media, no."""
        if self.plana:
            return 0.0
        puntos = 0.0
        if self.percentil_5a >= 0.92 or self.percentil_5a <= 0.08:
            puntos += 3
        elif self.percentil_5a >= 0.80 or self.percentil_5a <= 0.20:
            puntos += 1
        if self.cambio_anual is not None and self.maximo_5a != self.minimo_5a:
            recorrido = abs(self.cambio_anual) / (self.maximo_5a - self.minimo_5a)
            if recorrido >= 0.30:
                puntos += 2
            elif recorrido >= 0.15:
                puntos += 1
        return puntos


def _cerca_de(serie: list[tuple[str, float]], dias: int) -> float | None:
    """El valor de hace `dias`, tomando el dato más cercano hacia atrás."""
    if not serie:
        return None
    objetivo = datetime.strptime(serie[-1][0], "%Y-%m-%d").date()
    objetivo = objetivo.replace(year=objetivo.year - 1) if dias >= 365 else None
    if objetivo is None:
        from datetime import timedelta

        objetivo = (datetime.strptime(serie[-1][0], "%Y-%m-%d").date()
                    - timedelta(days=dias))
    previos = [v for f, v in serie
               if datetime.strptime(f, "%Y-%m-%d").date() <= objetivo]
    return previos[-1] if previos else None


def leer(cfg: SerieMacro, serie: list[tuple[str, float]]) -> Lectura | None:
    """Convierte la serie cruda en un dato con contexto. None si no alcanza."""
    if len(serie) < 20:
        return None
    valores = [v for _, v in serie]
    actual = valores[-1]
    lo, hi = min(valores), max(valores)
    # Percentil del valor actual dentro de su propia historia reciente.
    pct = sum(1 for v in valores if v <= actual) / len(valores)
    return Lectura(
        cfg=cfg, fecha=serie[-1][0], valor=actual,
        hace_un_mes=_cerca_de(serie, 30), hace_un_ano=_cerca_de(serie, 365),
        minimo_5a=lo, maximo_5a=hi, percentil_5a=pct,
    )


def brief_macro(lectura: Lectura) -> Brief:
    """Brief publicable a partir de una lectura macro."""
    c = lectura.cfg
    fuente = f"FRED {c.serie}, dato del {lectura.fecha}"
    facts = [Fact(f"{c.nombre} ahora", lectura.valor, c.unidad, fuente)]
    if lectura.hace_un_mes is not None:
        facts.append(Fact(f"{c.nombre} hace un mes", lectura.hace_un_mes,
                          c.unidad, fuente))
    if lectura.hace_un_ano is not None:
        facts.append(Fact(f"{c.nombre} hace un año", lectura.hace_un_ano,
                          c.unidad, fuente))
    facts.append(Fact(f"mínimo de {c.nombre} en el histórico cargado",
                      lectura.minimo_5a, c.unidad, fuente))
    facts.append(Fact(f"máximo de {c.nombre} en el histórico cargado",
                      lectura.maximo_5a, c.unidad, fuente))

    donde = ("en la parte alta de su rango histórico" if lectura.percentil_5a >= 0.8
             else "en la parte baja de su rango histórico" if lectura.percentil_5a <= 0.2
             else "en la zona media de su rango histórico")
    return Brief(
        kind="macro",
        ticker="",          # no hay empresa: la regla del cashtag no aplica
        sujeto=c.alias,     # ...así que el sujeto se exige por aquí
        angulo="mercado",
        angle=c.angulo,
        facts=facts,
        context=[
            f"El dato está {donde}.",
            "Es un dato observable de FRED, no una previsión.",
            "No hay empresa: no uses cashtags ni hables de un ticker.",
            f"DI SIEMPRE de qué hablas: el post tiene que nombrar "
            f"{c.nombre} con todas sus letras. Un porcentaje suelto no dice "
            f"nada — el lector no tiene por qué adivinar qué mide ese número.",
            "Conecta el dato con lo que implica para los múltiplos o el "
            "apetito de riesgo, que es lo que le importa a la audiencia.",
        ],
        as_of=date.today().isoformat(),
    )


def mejores_temas(api_key: str | None, *, minimo: float = 1.0) -> list[Lectura]:
    """Las series con algo que contar hoy, de más a menos tensión."""
    from xcreator.datos import fred_series

    lecturas = []
    for cfg in SERIES.values():
        l = leer(cfg, fred_series(cfg.serie, api_key))
        if l is not None and l.tension >= minimo:
            lecturas.append(l)
    return sorted(lecturas, key=lambda l: l.tension, reverse=True)
