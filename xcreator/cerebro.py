"""El Cerebro de Warren Buffett Jr como metodología para el contenido.

Se leen sus markdown por ruta (`WBJ_CEREBRO_DIR`); no se importa su código.
Son 83 documentos y ~180KB: volcarlos enteros en cada prompt sería caro y
además peor — un modelo con 45K tokens de metodología genérica escribe más
vago, no más agudo. Se carga solo la dimensión del ángulo que toca.

Qué aporta cada pieza al contenido:
- `AGENT.md` trae "Mission" y sobre todo "Boundaries", que son las reglas de
  rigor ("no declares un moat por lenguaje de marca; exige efectos económicos
  medibles"). Eso es exactamente lo que separa un post con criterio de una
  opinión con cashtag.
- `DECISION_RULES.md` trae los umbrales concretos, que dan sustancia
  verificable en vez de adjetivos.

Las seis dimensiones son también seis ángulos distintos sobre el mismo
ticker: multiplican la variedad del contenido sin repetir la idea.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Angulo:
    """Una dimensión del Cerebro vista como ángulo editorial."""

    clave: str
    carpeta: str
    titulo: str
    pregunta: str  # la pregunta que este ángulo le hace a la empresa


ANGULOS: dict[str, Angulo] = {
    "negocio": Angulo(
        "negocio", "01_business_analysis", "Calidad del negocio",
        "¿Es un negocio durable que crea valor, antes de mirar el precio?"),
    "finanzas": Angulo(
        "finanzas", "02_financial_analysis", "Salud financiera",
        "¿Los márgenes y el flujo de caja sostienen lo que promete la acción?"),
    "mercado": Angulo(
        "mercado", "03_market_analysis", "Mercado y crecimiento",
        "¿El mercado que persigue es tan grande como dice el consenso?"),
    "tecnico": Angulo(
        "tecnico", "04_technical_momentum", "Niveles y momentum",
        "¿Dónde están los niveles que invalidarían o confirmarían la tesis?"),
    "riesgo": Angulo(
        "riesgo", "05_risk_analysis", "Riesgo y resiliencia",
        "¿Qué tendría que pasar para que esto se rompa de verdad?"),
    "valuacion": Angulo(
        "valuacion", "06_valuation_analysis", "Valuación",
        "¿Qué crecimiento hay que creerse para justificar el precio de hoy?"),
}

# Por dimensión: los límites del analista y los umbrales. Nada de schemas de
# output ni tests de validación — eso es plomería del motor, no criterio.
_DOCS = ("AGENT.md", "DECISION_RULES.md")

# Tope de seguridad: si el Cerebro creciera, el prompt no se dispara solo.
MAX_CHARS_CONTEXTO = 24_000


def _leer(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


@lru_cache(maxsize=32)
def _cargar(cerebro_dir: str, carpeta: str) -> str:
    base = Path(cerebro_dir) / carpeta
    partes = []
    for doc in _DOCS:
        texto = _leer(base / doc).strip()
        if texto:
            partes.append(f"--- {carpeta}/{doc} ---\n{texto}")
    return "\n\n".join(partes)[:MAX_CHARS_CONTEXTO]


def disponible(cerebro_dir: Path | None) -> bool:
    return bool(cerebro_dir) and (Path(cerebro_dir) / "README.md").exists()


def metodologia(cerebro_dir: Path | None, angulo: str) -> str:
    """La metodología del ángulo, o "" si el Cerebro no está a mano.

    Devolver "" y seguir es deliberado: sin Cerebro el contenido sale más
    genérico, pero el sistema no se cae ni inventa metodología.
    """
    a = ANGULOS.get(angulo)
    if not a or not disponible(cerebro_dir):
        return ""
    return _cargar(str(cerebro_dir), a.carpeta)


def angulos_disponibles(cerebro_dir: Path | None) -> list[Angulo]:
    if not disponible(cerebro_dir):
        return []
    return [a for a in ANGULOS.values()
            if (Path(cerebro_dir) / a.carpeta).is_dir()]
