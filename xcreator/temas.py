"""Qué tickers tienen HOY una historia que contar.

Tener 178 briefs no es lo mismo que tener 178 temas. Un ticker cuyo precio
va dentro del rango, con score medio y múltiplo normal, no da un post: no
hay tensión, y sin tensión no hay replies — que es lo único que monetiza.

Esto puntúa la tensión editorial de cada brief con reglas explícitas. No es
un modelo ni una heurística oculta: cada punto tiene su motivo escrito, y el
reporte los muestra, para que se pueda discutir por qué un tema subió.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from datetime import date, timedelta

from xcreator.brief import Brief

# Días que un ticker "descansa" antes de volver a ser tema. Dos posts
# seguidos del mismo nombre se leen como relleno aunque el ángulo cambie: la
# variedad no es un adorno, es lo que distingue una cuenta de un bot.
VENTANA_DESCANSO = 7
# Cuánto resta haber salido ayer. Calibrado para que supere a la tensión
# típica (2-4 puntos) y saque del ranking a lo recién publicado.
PENALIZACION_MAX = 5.0


@dataclass
class Tema:
    brief: Brief
    puntos: float = 0.0
    razones: list[str] = field(default_factory=list)
    dias_desde_ultimo: int | None = None

    @property
    def ticker(self) -> str:
        return self.brief.ticker

    @property
    def tiene_historia(self) -> bool:
        return self.puntos > 0


def _fact(brief: Brief, etiqueta: str) -> float | None:
    for f in brief.facts:
        if f.label == etiqueta:
            return f.value
    return None


def evaluar(brief: Brief) -> Tema:
    """Puntúa la tensión editorial de un brief.

    La jerarquía sale de qué genera conversación, no de qué es buena
    inversión: un modelo que se equivocó da mejor contenido que uno que
    acertó, porque es raro publicarlo y la gente responde.
    """
    t = Tema(brief)
    precio_hoy = _fact(brief, "precio hoy")
    p0 = _fact(brief, "precio cuando publicamos el análisis")
    bear = _fact(brief, "escenario bajo (12m)")
    bull = _fact(brief, "escenario alto (12m)")
    score = _fact(brief, "score del modelo")
    pe = _fact(brief, "P/E al momento del análisis")
    movimiento = _fact(brief, "movimiento real desde el análisis")

    if precio_hoy is not None and bear is not None and bull is not None:
        if precio_hoy < bear:
            t.puntos += 3
            t.razones.append("el precio cayó POR DEBAJO del escenario bajo: "
                             "la tesis se está rompiendo y decirlo es raro")
        elif precio_hoy > bull:
            t.puntos += 3
            t.razones.append("el precio superó el escenario alto: el modelo "
                             "se quedó corto y admitirlo genera discusión")

    if movimiento is not None and abs(movimiento) >= 0.15:
        t.puntos += 2
        t.razones.append(f"se movió {movimiento:+.0%} desde el análisis: hay "
                         f"marcador que publicar")

    # Un bear case pegado al precio de entrada no es un escenario bajo, es un
    # hueco del modelo. Publicarlo es el tipo de autocrítica que atrae replies.
    if bear is not None and p0 and bear / p0 >= 0.95:
        t.puntos += 2
        t.razones.append("el escenario bajo está pegado al precio de entrada: "
                         "el modelo casi no dibujó caída")

    if score is not None and (score >= 8.0 or score <= 3.0):
        t.puntos += 1
        t.razones.append(f"score extremo ({score:.1f}/10): postura clara")

    if pe is not None and (pe >= 50 or (0 < pe <= 10)):
        t.puntos += 1
        t.razones.append(f"múltiplo extremo ({pe:.1f}x): el supuesto de "
                         f"crecimiento queda a la vista")

    return t


def _penalizar(tema: Tema, ultimo_uso: dict[str, str], hoy: date) -> None:
    """Resta puntos por haber salido hace poco. Decae hasta cero a los 7 días."""
    fecha = ultimo_uso.get(tema.ticker.upper())
    if not fecha:
        return
    try:
        dias = (hoy - date.fromisoformat(fecha)).days
    except ValueError:
        return
    tema.dias_desde_ultimo = dias
    if dias >= VENTANA_DESCANSO:
        return
    castigo = PENALIZACION_MAX * (VENTANA_DESCANSO - dias) / VENTANA_DESCANSO
    tema.puntos -= castigo
    cuando = "hoy" if dias == 0 else ("ayer" if dias == 1 else f"hace {dias} días")
    tema.razones.append(f"PERO ya salió {cuando} (-{castigo:.1f})")


def ranking(briefs: list[Brief], *, minimo: float = 1.0,
            ultimo_uso: dict[str, str] | None = None,
            hoy: date | None = None) -> list[Tema]:
    """Los temas con historia, del más fuerte al más flojo.

    `ultimo_uso` ({ticker: fecha}) hace que el ranking varíe: sin esto, el
    ticker con más tensión gana todos los días y la cuenta publica lo mismo
    una y otra vez.
    """
    hoy = hoy or date.today()
    temas = [evaluar(b) for b in briefs]
    if ultimo_uso:
        for t in temas:
            _penalizar(t, ultimo_uso, hoy)
    con_historia = [t for t in temas if t.puntos >= minimo]
    return sorted(con_historia, key=lambda t: t.puntos, reverse=True)
