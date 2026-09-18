"""Gráficos para acompañar un post. Las reglas de visualización mandan.

Son las del CLAUDE.md de Warren Buffett Jr, y aquí pesan más que en un
reporte: una imagen en X se comparte fuera de contexto, sin el texto que la
acompañaba.

1. **Nunca una sola línea.** Se dibuja la banda bear-base-bull. Un target
   único miente con confianza.
2. **Los supuestos, rotulados EN la imagen.** Si el gráfico circula solo, el
   "+40% de crecimiento" tiene que viajar con él.
3. **El pasado no se proyecta.** Histórico en línea sólida, proyección
   punteada. Siempre.
4. **El gráfico ilustra, no decide.** Aquí no se calcula nada: se dibujan los
   números que ya vienen del brief.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # sin pantalla: esto corre en un VPS
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from xcreator.brief import Brief  # noqa: E402

# Oscuro: X se lee mayormente en modo noche y en móvil.
_FONDO = "#15181c"
_TINTA = "#e7e9ea"
_SUAVE = "#8b98a5"
_BASE = "#1d9bf0"
_BULL = "#00ba7c"
_BEAR = "#f4212e"
_REJILLA = "#2f3336"


def _firmar(fig, firma: str, fuente: str) -> None:
    """Handle, fecha y fuente, en la propia imagen.

    Una gráfica se comparte sin el post que la acompañaba: sin el handle no
    trae a nadie de vuelta a la cuenta, y sin fecha no se sabe de cuándo es.
    Compartir copiando el enlace es lo que más pesa en el algoritmo de X
    (20.0, contra 0.5 de un like): que la imagen viaje sola es el objetivo.
    """
    fig.text(0.065, 0.022, fuente, color=_SUAVE, fontsize=9.5, ha="left")
    marca = f"@{firma.lstrip('@')}  ·  {date.today():%b %-d, %Y}" if firma \
        else f"{date.today():%b %-d, %Y}"
    fig.text(0.985, 0.022, marca, color=_TINTA, fontsize=10.5,
             fontweight="bold", ha="right", alpha=0.85)


def _ejes(ax) -> None:
    ax.grid(color=_REJILLA, lw=0.6, alpha=0.7)
    for lado in ("top", "right", "left"):
        ax.spines[lado].set_visible(False)
    ax.spines["bottom"].set_color(_REJILLA)
    ax.tick_params(colors=_SUAVE, labelsize=10)


def _fact(brief: Brief, etiqueta: str) -> float | None:
    for f in brief.facts:
        if f.label == etiqueta:
            return f.value
    return None


def puede_graficar(brief: Brief) -> bool:
    """Sin los tres escenarios no hay banda que dibujar, y una línea sola no
    se publica."""
    return all(_fact(brief, k) is not None for k in (
        "escenario bajo (12m)", "escenario base (12m)", "escenario alto (12m)"))


def grafico_escenarios(brief: Brief, historico: list[tuple[str, float]],
                       destino: Path, *, horizonte_dias: int = 365,
                       firma: str = "") -> Path | None:
    """Dibuja histórico + banda de escenarios. None si no hay con qué."""
    if not puede_graficar(brief):
        return None

    bear = _fact(brief, "escenario bajo (12m)")
    base = _fact(brief, "escenario base (12m)")
    bull = _fact(brief, "escenario alto (12m)")
    hoy_precio = _fact(brief, "precio hoy") or _fact(
        brief, "precio cuando publicamos el análisis")
    crecimiento = _fact(brief, "crecimiento asumido en el escenario base")
    pe = _fact(brief, "P/E al momento del análisis")
    if hoy_precio is None:
        return None

    fechas = [datetime.strptime(f, "%Y-%m-%d").date() for f, _ in historico]
    cierres = [c for _, c in historico]
    hoy = fechas[-1] if fechas else date.today()
    fin = hoy + timedelta(days=horizonte_dias)

    fig, ax = plt.subplots(figsize=(12, 6.75), dpi=135)  # 1620x911, buen móvil
    fig.patch.set_facecolor(_FONDO)
    ax.set_facecolor(_FONDO)

    # --- El pasado: línea sólida ---
    if fechas:
        ax.plot(fechas, cierres, color=_TINTA, lw=2.0, zorder=3)
        # Arriba y a la izquierda del último punto: a la derecha choca con la
        # etiqueta del escenario bajo cuando el bear queda cerca del precio.
        # Con recuadro del color del fondo: la serie de precios es densa y
        # el texto encima se vuelve ilegible.
        ax.annotate(f"${cierres[-1]:,.2f}", (fechas[-1], cierres[-1]),
                    textcoords="offset points", xytext=(-8, 26),
                    ha="right", color=_TINTA, fontsize=11,
                    fontweight="bold", zorder=5,
                    bbox={"facecolor": _FONDO, "edgecolor": "none",
                          "pad": 2.0})

    # --- El futuro: punteado, y siempre una banda ---
    puntos = [hoy, fin]
    ax.fill_between(puntos, [hoy_precio, bear], [hoy_precio, bull],
                    color=_BASE, alpha=0.10, zorder=1)
    for valor, color, nombre in ((bull, _BULL, "Bull"), (base, _BASE, "Base"),
                                 (bear, _BEAR, "Bear")):
        ax.plot(puntos, [hoy_precio, valor], color=color, lw=2.0,
                ls=(0, (5, 4)), zorder=2)
        ax.annotate(f"{nombre}  ${valor:,.2f}", (fin, valor),
                    textcoords="offset points", xytext=(8, -4),
                    color=color, fontsize=11, fontweight="bold", zorder=4)

    ax.axvline(hoy, color=_SUAVE, lw=1, ls=":", alpha=0.6, zorder=1)

    # --- Los supuestos viajan CON la imagen ---
    # El texto del gráfico va en INGLÉS: la cuenta es en inglés y una imagen
    # se comparte sin el post que la acompañaba.
    supuestos = []
    if crecimiento is not None:
        supuestos.append(f"base case assumes {crecimiento:+.0%} growth")
    if pe is not None:
        supuestos.append(f"P/E at analysis: {pe:.1f}x")
    # Título y supuestos como textos de figura en alturas separadas:
    # set_title + fig.text se pisan en cuanto el título crece.
    # Sin raya: el título también es texto publicado, y la regla vale igual.
    fig.text(0.065, 0.945, f"{brief.ticker} · 12-month scenarios",
             color=_TINTA, fontsize=18, fontweight="bold", ha="left",
             va="center")
    fig.text(0.065, 0.893, "   ".join(supuestos) or "assumptions unavailable",
             color=_SUAVE, fontsize=11, ha="left", va="center")
    _firmar(fig, firma, "Solid: actual price. Dashed: projection under the "
                        "assumptions above. Research range, not a recommendation.")
    _ejes(ax)
    ax.yaxis.set_major_formatter(lambda v, _: f"${v:,.0f}")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
    ax.set_xlim(fechas[0] if fechas else hoy, fin + timedelta(days=62))

    destino.parent.mkdir(parents=True, exist_ok=True)
    fig.subplots_adjust(left=0.065, right=0.855, top=0.835, bottom=0.115)
    fig.savefig(destino, facecolor=_FONDO)
    plt.close(fig)
    return destino


def grafico_rango(serie: list[tuple[str, float]], destino: Path, *,
                  titulo: str, subtitulo: str, fuente: str,
                  formato: str = "usd", firma: str = "") -> Path | None:
    """Dónde está un valor dentro de su propio recorrido. Solo pasado.

    Para cripto y macro no hay modelo que proyecte nada, así que no se dibuja
    futuro: dibujar una proyección sin modelo sería inventarla. La regla de
    "nunca una sola línea" se cumple con la BANDA entre el mínimo y el máximo
    del histórico cargado: el valor de hoy se lee contra su propio rango.
    """
    if len(serie) < 20:
        return None
    fechas = [datetime.strptime(f, "%Y-%m-%d").date() for f, _ in serie]
    valores = [v for _, v in serie]
    lo, hi, hoy = min(valores), max(valores), valores[-1]

    def fmt(v: float) -> str:
        if formato == "pct":
            return f"{v:.2f}%"
        if formato == "num":               # un índice, como el IPC: sin "$"
            return f"{v:,.1f}"
        return f"${v:,.4f}" if v < 10 else f"${v:,.2f}"

    fig, ax = plt.subplots(figsize=(12, 6.75), dpi=135)
    fig.patch.set_facecolor(_FONDO)
    ax.set_facecolor(_FONDO)

    from matplotlib.transforms import blended_transform_factory

    ax.axhspan(lo, hi, color=_BASE, alpha=0.07, zorder=0)
    # Los extremos van en gris y no en verde/rojo: colorear el máximo de verde
    # opina. Para el rendimiento del bono, subir no es "bueno"; el gráfico
    # ilustra y el post es el que argumenta.
    borde = blended_transform_factory(ax.transAxes, ax.transData)
    for nivel, nombre, va, dy in ((hi, "High", "bottom", 5), (lo, "Low", "top", -5)):
        ax.axhline(nivel, color=_SUAVE, lw=1.3, ls=(0, (5, 4)), zorder=1)
        # Al borde derecho y FUERA de la línea (encima del máximo, debajo del
        # mínimo): pegada a ella, la punteada la tachaba.
        ax.annotate(f"{nombre}  {fmt(nivel)}", (1.0, nivel), xycoords=borde,
                    textcoords="offset points", xytext=(0, dy), ha="right",
                    va=va, color=_SUAVE, fontsize=11, fontweight="bold",
                    zorder=6)
    ax.plot(fechas, valores, color=_TINTA, lw=2.0, zorder=3)
    ax.scatter([fechas[-1]], [hoy], color=_BASE, s=46, zorder=4)
    # Si hoy está pegado al máximo, la etiqueta va debajo: encima chocaba con
    # la del "High", que es justo el caso del bono a 10 años en su récord.
    cerca_del_techo = (hi - hoy) <= (hi - lo) * 0.12
    ax.annotate(f"{fmt(hoy)}", (fechas[-1], hoy), textcoords="offset points",
                xytext=(-12, -22 if cerca_del_techo else 16), ha="right",
                color=_TINTA, fontsize=12, fontweight="bold", zorder=5,
                bbox={"facecolor": _FONDO, "edgecolor": "none", "pad": 2.0})

    fig.text(0.065, 0.945, titulo, color=_TINTA, fontsize=18,
             fontweight="bold", ha="left", va="center")
    fig.text(0.065, 0.893, subtitulo, color=_SUAVE, fontsize=11,
             ha="left", va="center")
    _firmar(fig, firma, fuente)
    _ejes(ax)
    if formato == "pct":
        ax.yaxis.set_major_formatter(lambda v, _: f"{v:.1f}%")
    elif formato == "num":
        ax.yaxis.set_major_formatter(lambda v, _: f"{v:,.0f}")
    else:
        ax.yaxis.set_major_formatter(
            lambda v, _: f"${v:,.2f}" if hi < 10 else f"${v:,.0f}")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
    ax.set_xlim(fechas[0], fechas[-1] + timedelta(days=len(fechas) // 6))

    destino.parent.mkdir(parents=True, exist_ok=True)
    fig.subplots_adjust(left=0.065, right=0.87, top=0.835, bottom=0.115)
    fig.savefig(destino, facecolor=_FONDO)
    plt.close(fig)
    return destino


def grafico_marcador(abajo: list, arriba: list, total: int, destino: Path, *,
                     firma: str = "") -> Path | None:
    """Barras de cuánto quedó cada acción fuera de su rango del modelo.

    Aquí el rojo y el verde SÍ significan algo: dirección, no juicio. Por
    debajo del escenario bajo es caída, por encima del alto es subida. Es la
    convención de cualquier pantalla de mercado, y el lector la lee sin
    leyenda.
    """
    filas = list(reversed(arriba)) + list(abajo)   # de arriba abajo en la imagen
    if not filas:
        return None
    fig, ax = plt.subplots(figsize=(12, 6.75), dpi=135)
    fig.patch.set_facecolor(_FONDO)
    ax.set_facecolor(_FONDO)

    nombres = [f"${f.ticker}" for f in filas]
    valores = [f.fuera for f in filas]
    colores = [_BULL if v > 0 else _BEAR for v in valores]
    y = list(range(len(filas)))
    ax.barh(y, valores, color=colores, height=0.62, zorder=3)
    ax.axvline(0, color=_SUAVE, lw=1.0, zorder=2)
    ax.set_yticks(y, nombres)
    ax.tick_params(axis="y", colors=_TINTA, labelsize=12, length=0)
    ax.invert_yaxis()

    ancho = max(abs(v) for v in valores)
    for yi, v, f in zip(y, valores, filas):
        ax.annotate(f"{v:+.1f}%", (v, yi), textcoords="offset points",
                    xytext=(7 if v > 0 else -7, 0), ha="left" if v > 0 else "right",
                    va="center", color=_TINTA, fontsize=11, fontweight="bold")
    ax.set_xlim(-ancho * 1.35 if any(v < 0 for v in valores) else -ancho * 0.1,
                ancho * 1.35 if any(v > 0 for v in valores) else ancho * 0.1)

    fig.text(0.065, 0.945, "Outside the model's 12-month range",
             color=_TINTA, fontsize=18, fontweight="bold", ha="left", va="center")
    fig.text(0.065, 0.893,
             f"price today vs the low and high scenarios · {total} stocks tracked",
             color=_SUAVE, fontsize=11, ha="left", va="center")
    _firmar(fig, firma, "Red: below the low scenario. Green: above the high "
                        "scenario. Research ranges, not recommendations.")
    ax.grid(axis="x", color=_REJILLA, lw=0.6, alpha=0.7, zorder=0)
    for lado in ("top", "right", "left", "bottom"):
        ax.spines[lado].set_visible(False)
    ax.tick_params(axis="x", colors=_SUAVE, labelsize=10)
    # Las marcas tienen que caer en ENTEROS. Con el localizador por defecto
    # quedaban cada 2.5 y el formato las redondeaba: la marca "+2%" estaba en
    # 2.5, y la barra de +2.3% terminaba antes de ella. Se leía como menos de
    # 2% un valor de 2.3%.
    from matplotlib.ticker import MaxNLocator

    ax.xaxis.set_major_locator(MaxNLocator(nbins=10, integer=True))
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:+.0f}%")

    destino.parent.mkdir(parents=True, exist_ok=True)
    fig.subplots_adjust(left=0.10, right=0.96, top=0.835, bottom=0.115)
    fig.savefig(destino, facecolor=_FONDO)
    plt.close(fig)
    return destino
