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
                       destino: Path, *, horizonte_dias: int = 365) -> Path | None:
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
    fig.text(0.065, 0.945, f"{brief.ticker} — 12-month scenarios",
             color=_TINTA, fontsize=18, fontweight="bold", ha="left",
             va="center")
    fig.text(0.065, 0.893, "   ".join(supuestos) or "assumptions unavailable",
             color=_SUAVE, fontsize=11, ha="left", va="center")
    fig.text(0.065, 0.022,
             "Solid: actual price. Dashed: projection under the assumptions "
             "above. Research range, not a recommendation.",
             color=_SUAVE, fontsize=9.5, ha="left")

    ax.grid(color=_REJILLA, lw=0.6, alpha=0.7)
    for lado in ("top", "right", "left"):
        ax.spines[lado].set_visible(False)
    ax.spines["bottom"].set_color(_REJILLA)
    ax.tick_params(colors=_SUAVE, labelsize=10)
    ax.yaxis.set_major_formatter(lambda v, _: f"${v:,.0f}")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
    ax.set_xlim(fechas[0] if fechas else hoy, fin + timedelta(days=62))

    destino.parent.mkdir(parents=True, exist_ok=True)
    fig.subplots_adjust(left=0.065, right=0.855, top=0.835, bottom=0.115)
    fig.savefig(destino, facecolor=_FONDO)
    plt.close(fig)
    return destino
