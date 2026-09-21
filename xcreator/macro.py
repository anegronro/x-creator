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
    unidad: str         # "pct" (ya en %) | "pp" (puntos) | "count"
    angulo: str         # la pregunta que abre este dato
    decimales: int = 2
    # Las formas en que un redactor puede nombrar este dato. Al menos una
    # tiene que aparecer en el post: sin empresa no hay cashtag que diga de
    # qué se habla, y un porcentaje suelto no lo dice. Nadie es adivino.
    alias: tuple[str, ...] = ()
    # Qué frases de un post AJENO nos hacen tener algo que decir. Va aparte de
    # `alias` a propósito: alias responde a "cómo nombramos esto en NUESTRO
    # texto" y gatillo a "de qué habla el suyo". Mezclarlos deja entrar por la
    # puerta del sujeto frases que no nombran nada.
    gatillos: tuple[str, ...] = ()
    # Si la serie es un ÍNDICE que se publica en nivel (el IPC), se convierte
    # en variación interanual antes de todo lo demás. Ver `interanual()`.
    interanual: bool = False


# Catálogo deliberadamente corto: series que mueven la conversación de
# mercados y que cualquiera puede comprobar en FRED.
SERIES: dict[str, SerieMacro] = {
    "curva": SerieMacro(
        "T10Y2Y", "the 10y-2y Treasury spread", "pp",
        "What does the shape of the curve say that the index doesn't?",
        alias=("curve", "yield curve", "10y-2y", "10s2s", "2s10s", "two-year", "treasury"),
        gatillos=("yield curve", "curve inver", "curve steep", "2s10s", "10y-2y")),
    "tasa10": SerieMacro(
        "DGS10", "the 10-year Treasury yield", "pct",
        "What equity multiple survives this risk-free rate?",
        alias=("10-year", "10 year", "10y", "ten-year", "treasury", "long bond"),
        gatillos=("10-year", "10 year", "10y", "treasury yield", "long bond",
                  "bond market", "yields", "term premium")),
    "desempleo": SerieMacro(
        "UNRATE", "the unemployment rate", "pct",
        "Is the labour market loosening fast enough to matter?", 1,
        alias=("unemployment", "jobless", "labour market", "labor market", "payroll"),
        gatillos=("unemployment", "jobless", "payroll", "labor market",
                  "labour market", "jobs report")),
    "inflacion": SerieMacro(
        # El IPC se publica como un ÍNDICE (334, 333, 323...). Nadie habla de
        # su nivel: se habla de la inflación interanual. Y el nivel casi
        # siempre sube, así que estaba siempre "en máximos" y el puntuador lo
        # leía como un extremo permanente. Se trabaja con la interanual.
        "CPIAUCSL", "CPI inflation, year over year", "pct",
        "Is disinflation still happening, or did it stall?",
        alias=("cpi", "inflation", "consumer price", "disinflation"),
        gatillos=("inflation", "cpi", "consumer price", "disinflation",
                  "price pressure"),
        interanual=True),
    "hipoteca": SerieMacro(
        "MORTGAGE30US", "the 30-year mortgage rate", "pct",
        "What does this do to housing-linked demand?",
        alias=("mortgage", "housing", "homebuy", "30-year fixed"),
        gatillos=("mortgage", "housing market", "homebuy", "home sales")),
    "fed": SerieMacro(
        "DFF", "the effective fed funds rate", "pct",
        "How much room does the Fed actually have?",
        alias=("fed funds", "federal funds", "the fed", "policy rate", "front end"),
        gatillos=("rates on hold", "rate decision", "rate cut", "rate hike",
                  "cut rates", "hike rates", "hold rates", "fomc", "the fed",
                  "fed funds", "policy rate", "powell", "warsh", "dot plot",
                  "easing cycle", "tightening cycle")),
    "highyield": SerieMacro(
        "BAMLH0A0HYM2", "the high-yield credit spread", "pct",
        "Is credit pricing the same risk equities are?",
        alias=("high yield", "high-yield", "credit spread", "junk", "hy spread", "credit market"),
        gatillos=("credit spread", "high yield", "high-yield", "junk bond",
                  "credit market", "spreads widen")),
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


# Cinco años de interanuales: el mismo horizonte que el resto de la lectura
# llama "5a". Sin recortar, 400 observaciones mensuales son 33 años y el
# "rango" del IPC incluiría los 90.
MESES_INTERANUAL = 60


def interanual(serie: list[tuple[str, float]],
               meses: int = MESES_INTERANUAL) -> list[tuple[str, float]]:
    """Índice mensual -> variación interanual en %, los últimos `meses`.

    Cada punto se compara con el MISMO mes del año anterior, no con "hace 365
    días": el IPC se publica con fecha de primero de mes y así no hay que
    adivinar qué observación cae más cerca.
    """
    por_mes = {(int(f[:4]), int(f[5:7])): v for f, v in serie}
    out = []
    for f, v in serie:
        antes = por_mes.get((int(f[:4]) - 1, int(f[5:7])))
        if antes:
            out.append((f, round((v / antes - 1) * 100, 2)))
    return out[-meses:]


def serie_de(cfg: SerieMacro, api_key: str | None) -> list[tuple[str, float]]:
    """La serie tal como hay que leerla. ÚNICO punto de entrada.

    El puntuador, los replies y el gráfico la pedían cada uno por su lado a
    FRED. Si la transformación del IPC viviera solo en uno, los otros seguirían
    leyendo el índice en nivel.
    """
    from xcreator.datos import fred_series

    serie = fred_series(cfg.serie, api_key)
    return interanual(serie) if cfg.interanual else serie


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
    # FRED da las series de tipos YA en porcentaje (5.01 es 5.01%). En el
    # brief eso es "pct_val", no "pct" (que es una fracción).
    u = {"pct": "pct_val", "pp": "pp"}.get(c.unidad, c.unidad)
    facts = [Fact(f"{c.nombre} ahora", lectura.valor, u, fuente)]
    if lectura.hace_un_mes is not None:
        facts.append(Fact(f"{c.nombre} hace un mes", lectura.hace_un_mes,
                          u, fuente))
    if lectura.hace_un_ano is not None:
        facts.append(Fact(f"{c.nombre} hace un año", lectura.hace_un_ano,
                          u, fuente))
    facts.append(Fact(f"mínimo de {c.nombre} en el histórico cargado",
                      lectura.minimo_5a, u, fuente))
    facts.append(Fact(f"máximo de {c.nombre} en el histórico cargado",
                      lectura.maximo_5a, u, fuente))

    donde = ("en la parte alta de su rango histórico" if lectura.percentil_5a >= 0.8
             else "en la parte baja de su rango histórico" if lectura.percentil_5a <= 0.2
             else "en la zona media de su rango histórico")
    return Brief(
        kind="macro",
        ticker="",          # no hay empresa: la regla del cashtag no aplica
        # La serie queda en el item: con dos posts de macro al día, el
        # segundo tiene que saber cuál ya salió para no repetir el dato.
        motivo=f"macro:{c.serie}",
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
            "NO te atribuyas llamadas pasadas. No hay ninguna predicción "
            "guardada sobre esta serie, así que 'hace un año pensé que...' "
            "sería un invento sobre el historial de quien publica.",
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
        l = leer(cfg, serie_de(cfg, api_key))
        if l is not None and l.tension >= minimo:
            lecturas.append(l)
    return sorted(lecturas, key=lambda l: l.tension, reverse=True)


def serie_para_post(texto: str) -> SerieMacro | None:
    """La serie de la que trata un post ajeno. None si no es cosa nuestra.

    Gana la que empareje con la frase más larga: "yield curve" debe ganarle a
    "yields" cuando aparecen las dos, porque es más específica.
    """
    bajo = (texto or "").lower()
    mejor, largo = None, 0
    for cfg in SERIES.values():
        for g in cfg.gatillos:
            if g in bajo and len(g) > largo:
                mejor, largo = cfg, len(g)
    return mejor


def brief_para_post(texto: str, api_key: str | None) -> Brief | None:
    """Brief macro para responderle a un post ajeno, tenga tensión o no.

    Igual que en cripto: para publicar por iniciativa propia hace falta que el
    dato sea noticiable, pero para responder basta con tener el dato.
    """
    from xcreator.datos import fred_series

    cfg = serie_para_post(texto)
    if cfg is None:
        return None
    lec = leer(cfg, serie_de(cfg, api_key))
    return brief_macro(lec) if lec is not None else None
