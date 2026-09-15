"""Contenido de activos digitales: BTC, XRP y compañía.

Esto NO es el motor de acciones aplicado a cripto, y la diferencia es el
punto entero del módulo. Una acción tiene filings, beneficios y flujo de
caja, así que se le puede calcular un rango de valor con supuestos
declarados. Bitcoin no tiene nada de eso: no hay 10-K, no hay márgenes, no
hay crecimiento que descontar. Un precio objetivo de XRP sería exactamente
el tipo de número sin fórmula que el resto del sistema existe para impedir.

Así que se sigue el patrón de `macro.py`: hechos observables —precio, su
propio recorrido, caída desde máximos, volatilidad realizada— calculados
aquí, con su fuente y su fecha, y la conversación se construye sobre lo que
esos hechos implican. El redactor tiene prohibido inventar un objetivo.

El cashtag sí aplica: en X, $BTC y $XRP son símbolos indexados igual que los
de una empresa, así que la regla de las dos formas protege el sujeto.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from xcreator.brief import Brief, Fact

# Días de histórico que se cargan. Algo más de un año, para poder comparar
# contra el mismo mes del año pasado sin quedarse corto por fines de semana.
DIAS_HISTORICO = 400
# Por debajo de esto no hay histórico suficiente para hablar de rango.
MINIMO_DATOS = 60


@dataclass(frozen=True)
class Activo:
    simbolo: str        # símbolo en FMP, p.ej. BTCUSD
    ticker: str         # cashtag en X, p.ej. BTC
    nombre: str         # cómo se llama en el post, en inglés
    angulo: str         # la pregunta que abre este activo
    decimales: int = 2
    # Igual que en macro: el post tiene que nombrar el activo, no dejar al
    # lector deducirlo de un precio suelto.
    alias: tuple[str, ...] = ()


# Catálogo corto a propósito: los que de verdad mueven conversación y tienen
# histórico limpio. Añadir uno es una línea.
ACTIVOS: dict[str, Activo] = {
    "btc": Activo(
        "BTCUSD", "BTC", "Bitcoin",
        "What has to be true for this price to be the right one?",
        alias=("bitcoin", "btc")),
    "xrp": Activo(
        "XRPUSD", "XRP", "XRP",
        "How much of this price is regulatory outcome rather than usage?",
        decimales=4, alias=("xrp", "ripple")),
    "eth": Activo(
        "ETHUSD", "ETH", "Ether",
        "Is this priced as infrastructure or as a beta trade?",
        alias=("ether", "ethereum", "eth")),
    "sol": Activo(
        "SOLUSD", "SOL", "Solana",
        "What premium is the fastest chain actually earning?",
        alias=("solana", "sol")),
}


@dataclass
class LecturaCripto:
    """Un activo digital con su contexto, todo calculado."""

    cfg: Activo
    fecha: str
    precio: float
    hace_30d: float | None
    hace_90d: float | None
    hace_un_ano: float | None
    minimo: float
    maximo: float
    percentil: float
    volatilidad: float          # anualizada, en %

    @property
    def caida_desde_maximo(self) -> float:
        """Cuánto ha caído desde el máximo del histórico cargado, en %."""
        if self.maximo <= 0:
            return 0.0
        return (self.maximo - self.precio) / self.maximo * 100

    def cambio_pct(self, desde: float | None) -> float | None:
        if desde is None or desde <= 0:
            return None
        return (self.precio - desde) / desde * 100

    @property
    def plana(self) -> bool:
        """True si el precio apenas se ha movido frente a su propio nivel.

        El percentil es relativo: con un recorrido minúsculo, cualquier
        variación parece un extremo histórico. A macro ya le pasó —una serie
        entre 4.00 y 4.02 puntuaba como récord— y el mismo fallo aquí es más
        grave, porque un activo con 60-80% de volatilidad anual que no se
        mueve en más de un año significa que el histórico está roto, no que
        haya noticia.
        """
        escala = max(abs(self.precio), 1e-9)
        return (self.maximo - self.minimo) / escala < 0.10

    @property
    def tension(self) -> float:
        """Cuán discutible está hoy. Un activo en mitad de su rango y sin
        movimiento no da post: publicar por publicar es peor que callarse."""
        if self.plana:
            return 0.0
        puntos = 0.0
        if self.percentil >= 0.92 or self.percentil <= 0.08:
            puntos += 3
        elif self.percentil >= 0.80 or self.percentil <= 0.20:
            puntos += 1
        caida = self.caida_desde_maximo
        if caida >= 40:
            puntos += 2
        elif caida >= 20:
            puntos += 1
        c90 = self.cambio_pct(self.hace_90d)
        if c90 is not None and abs(c90) >= 30:
            puntos += 2
        elif c90 is not None and abs(c90) >= 15:
            puntos += 1
        return puntos


def _cerca_de(serie: list[tuple[str, float]], dias: int) -> float | None:
    """El cierre de hace `dias`, tomando el dato más cercano hacia atrás."""
    if not serie:
        return None
    ultimo = datetime.strptime(serie[-1][0], "%Y-%m-%d").date()
    objetivo = ultimo - timedelta(days=dias)
    previos = [v for f, v in serie
               if datetime.strptime(f, "%Y-%m-%d").date() <= objetivo]
    return previos[-1] if previos else None


def _volatilidad_anualizada(valores: list[float]) -> float:
    """Volatilidad realizada en %, de los retornos diarios.

    Cripto cotiza los siete días, así que se anualiza con 365 y no con 252.
    Usar el calendario bursátil aquí infravaloraría la cifra un 20%.
    """
    retornos = [(b - a) / a for a, b in zip(valores, valores[1:]) if a > 0]
    if len(retornos) < 20:
        return 0.0
    return statistics.stdev(retornos) * (365 ** 0.5) * 100


def leer(cfg: Activo, serie: list[tuple[str, float]]) -> LecturaCripto | None:
    """Convierte el histórico crudo en una lectura. None si no alcanza."""
    if len(serie) < MINIMO_DATOS:
        return None
    valores = [v for _, v in serie]
    actual = valores[-1]
    if actual <= 0:
        return None
    return LecturaCripto(
        cfg=cfg, fecha=serie[-1][0], precio=actual,
        hace_30d=_cerca_de(serie, 30),
        hace_90d=_cerca_de(serie, 90),
        hace_un_ano=_cerca_de(serie, 365),
        minimo=min(valores), maximo=max(valores),
        percentil=sum(1 for v in valores if v <= actual) / len(valores),
        volatilidad=_volatilidad_anualizada(valores),
    )


def _r(x: float, d: int) -> float:
    return round(x, d)


def brief_cripto(lectura: LecturaCripto,
                 tasa10: tuple[str, float] | None = None) -> Brief:
    """Brief publicable a partir de una lectura de cripto.

    `tasa10` es opcional: el bono a 10 años como contexto permite el único
    argumento cruzado que casi nadie hace en este nicho —qué tasa libre de
    riesgo tiene que batir un activo sin flujo de caja— en vez de repetir
    otro comentario de precio.
    """
    c = lectura.cfg
    fuente = f"FMP {c.simbolo}, cierre del {lectura.fecha}"
    d = c.decimales
    facts = [
        Fact(f"{c.nombre} ahora", _r(lectura.precio, d), "usd", fuente),
        Fact(f"máximo de {c.nombre} en el histórico cargado",
             _r(lectura.maximo, d), "usd", fuente),
        Fact(f"mínimo de {c.nombre} en el histórico cargado",
             _r(lectura.minimo, d), "usd", fuente),
        Fact(f"caída de {c.nombre} desde ese máximo",
             _r(lectura.caida_desde_maximo, 1), "pct", fuente),
        Fact(f"volatilidad anualizada de {c.nombre}",
             _r(lectura.volatilidad, 0), "pct",
             f"calculada sobre los cierres diarios de {c.simbolo}"),
    ]
    for etiqueta, valor in (("hace 30 días", lectura.hace_30d),
                            ("hace 90 días", lectura.hace_90d),
                            ("hace un año", lectura.hace_un_ano)):
        if valor is not None:
            facts.append(Fact(f"{c.nombre} {etiqueta}", _r(valor, d), "usd",
                              fuente))
    if tasa10 is not None:
        facts.append(Fact("el bono del Tesoro a 10 años", _r(tasa10[1], 2),
                          "pct", f"FRED DGS10, dato del {tasa10[0]}"))

    donde = ("en la parte alta de su rango" if lectura.percentil >= 0.8
             else "en la parte baja de su rango" if lectura.percentil <= 0.2
             else "en la zona media de su rango")
    return Brief(
        kind="cripto",
        ticker=c.ticker,        # $BTC y BTC: la regla del cashtag sí aplica
        sujeto=c.alias,
        angulo="mercado",
        angle=c.angulo,
        facts=facts,
        context=[
            f"{c.nombre} está {donde} del histórico cargado.",
            "AQUÍ NO HAY MODELO DE VALOR. No hay filings, ni beneficios, ni "
            "flujo de caja que descontar, así que NO tienes un rango objetivo "
            "y no puedes inventarlo. Prohibido dar un precio objetivo, un "
            "'fair value' o una previsión.",
            "Lo que tienes son hechos de precio observables y comprobables "
            "por cualquiera. Construye el argumento sobre lo que esos hechos "
            "IMPLICAN, y sobre qué tendría que ser cierto para justificar el "
            "precio de hoy.",
            "No es una empresa: no hables de márgenes, múltiplos ni "
            "resultados trimestrales.",
            f"DI SIEMPRE de qué hablas: nombra {c.nombre} con todas sus "
            "letras. Un precio suelto no dice nada.",
            "NO te atribuyas llamadas pasadas. No hay ninguna predicción "
            "guardada sobre este activo, así que 'me equivoqué', 'yo dije' o "
            "'mi objetivo era' serían inventos sobre el historial de quien "
            "publica. Los hechos del brief son de precio, no de opiniones.",
        ],
        as_of=date.today().isoformat(),
    )


def mejores_temas(api_key: str | None, *, minimo: float = 1.0
                  ) -> list[LecturaCripto]:
    """Los activos con algo que contar hoy, de más a menos tensión."""
    from xcreator.datos import price_history

    lecturas = []
    for cfg in ACTIVOS.values():
        serie = price_history(cfg.simbolo, api_key, dias=DIAS_HISTORICO)
        lec = leer(cfg, serie)
        if lec is not None and lec.tension >= minimo:
            lecturas.append(lec)
    return sorted(lecturas, key=lambda l: l.tension, reverse=True)


def activo_por_ticker(ticker: str) -> Activo | None:
    """El activo cuyo cashtag coincide. None si no lo cubrimos."""
    t = (ticker or "").upper().lstrip("$")
    return next((a for a in ACTIVOS.values() if a.ticker == t), None)


def brief_para(ticker: str, api_key: str | None,
               tasa10: tuple[str, float] | None = None) -> Brief | None:
    """Brief de un activo concreto, tenga o no tensión hoy.

    `mejores_temas` filtra por tensión porque decide sobre QUÉ publicar por
    iniciativa propia. Para responderle a alguien la pregunta es otra: si
    menciona Bitcoin, lo que hace falta es tener datos de Bitcoin, aunque hoy
    no sea el tema más jugoso.
    """
    from xcreator.datos import price_history

    cfg = activo_por_ticker(ticker)
    if cfg is None:
        return None
    lec = leer(cfg, price_history(cfg.simbolo, api_key, dias=DIAS_HISTORICO))
    return brief_cripto(lec, tasa10) if lec is not None else None
