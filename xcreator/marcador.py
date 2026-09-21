"""El marcador semanal: qué acciones se salieron de su rango del modelo.

Es el formato pensado para compartirse. En el algoritmo de X de 2026,
compartir copiando el enlace pesa 20.0 y un like 0.5: el contenido que más
premia es el que alguien quiere mandarle a otra persona. Una lista en una
sola imagen es exactamente eso, y además es la categoría que más replies
atrae: publicar dónde falló el propio modelo, con la predicción guardada
detrás y no inventada.

Solo usa lo que el motor ya dejó escrito: el rango de 12 meses de cada
análisis y el precio de hoy. Aquí no se calcula ningún valor nuevo, solo
cuánto quedó fuera cada precio.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from xcreator.brief import Brief, Fact

# Cuántas por lado. Cinco y cinco caben en una imagen legible en el móvil;
# más convierte el marcador en una tabla que nadie lee entera.
POR_LADO = 5
ETIQUETA = "fuera de su rango"


@dataclass
class Fila:
    ticker: str
    precio: float
    bear: float
    bull: float

    @property
    def fuera(self) -> float:
        """Cuánto quedó fuera del rango, en %. Negativo por abajo, 0 dentro."""
        if self.precio < self.bear:
            return (self.precio - self.bear) / self.bear * 100
        if self.precio > self.bull:
            return (self.precio - self.bull) / self.bull * 100
        return 0.0


def _v(brief: Brief, etiqueta: str) -> float | None:
    return next((f.value for f in brief.facts if f.label == etiqueta), None)


def filas(briefs: list[Brief]) -> list[Fila]:
    """Una fila por acción con precio de hoy y rango completo."""
    out = []
    for b in briefs:
        precio = _v(b, "precio hoy")
        bear = _v(b, "escenario bajo (12m)")
        bull = _v(b, "escenario alto (12m)")
        if precio and bear and bull and bull > bear:
            out.append(Fila(b.ticker.upper(), precio, bear, bull))
    return out


def extremos(todas: list[Fila], n: int = POR_LADO) -> tuple[list[Fila], list[Fila]]:
    """(las más hundidas bajo el bear, las más disparadas sobre el bull)."""
    abajo = sorted((f for f in todas if f.fuera < 0), key=lambda f: f.fuera)[:n]
    arriba = sorted((f for f in todas if f.fuera > 0), key=lambda f: -f.fuera)[:n]
    return abajo, arriba


def brief_marcador(briefs: list[Brief]) -> Brief | None:
    """None si nadie se salió del rango: un marcador vacío no se publica."""
    todas = filas(briefs)
    abajo, arriba = extremos(todas)
    if not abajo and not arriba:
        return None

    facts = [Fact("acciones con precio y rango", float(len(todas)), "num",
                  "motor Warren Buffett Jr, análisis guardados")]
    for f in abajo + arriba:
        facts.append(Fact(f"{f.ticker} {ETIQUETA}", round(f.fuera, 1), "pct_val",
                          "precio de hoy (FMP) contra el rango de 12m del modelo"))
        facts.append(Fact(f"{f.ticker} precio hoy", round(f.precio, 2), "usd", "FMP"))
    fuera_total = sum(1 for f in todas if f.fuera != 0)
    facts.append(Fact("acciones fuera de su rango", float(fuera_total), "num",
                      "calculado sobre los análisis guardados"))

    def lista(fs):
        return ", ".join(f"${f.ticker} ({f.fuera:+.1f}%)" for f in fs) or "ninguna"

    return Brief(
        kind="marcador",
        ticker="",
        sujeto=("range", "model"),
        angulo="valuacion",
        angle="El marcador de la semana: dónde se equivocó el modelo",
        facts=facts,
        context=[
            f"Por DEBAJO del escenario bajo: {lista(abajo)}.",
            f"Por ENCIMA del escenario alto: {lista(arriba)}.",
            "Es el marcador semanal de la cuenta. Lo publica una cuenta que "
            "enseña dónde falló su propio modelo, y eso es lo que lo hace "
            "raro y discutible: dilo de frente.",
            "Estas predicciones SÍ existen y están guardadas: aquí es legítimo "
            "decir 'our model', 'our range'.",
            "La imagen lleva la lista completa: el texto no la repite entera. "
            "Nombra dos o tres casos y di qué tienen en común o qué no "
            "esperaba el modelo, sin inventar la causa.",
            "UN SOLO CASHTAG en todo el post. X rechaza con error cualquier "
            "post con dos o más $TICKER, así que el primero lleva el dólar "
            "($ATAT) y los demás van a secas (COHR, EQIX).",
            "No expliques POR QUÉ se movió una acción: no tienes esa noticia. "
            "Di que se salió del rango y cuánto; la causa, pregúntala.",
        ],
        as_of=date.today().isoformat(),
    )
