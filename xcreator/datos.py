"""Lectura de las fuentes de datos. Solo lectura, sin importar otros motores.

Hoy la fuente son los `prediccion.json` que escribe warren-buffett-jr y los
precios de FMP. Cuando el contenido deje de ser solo de acciones, aquí es
donde se enchufan las fuentes nuevas — nada más del proyecto lo nota.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

_CAMPOS = ("ticker", "date", "price", "bear", "base", "bull")


def load_predictions(reportes_dir: Path | None) -> list[dict]:
    """Todas las predicciones guardadas, de la más vieja a la más nueva.

    Tolera JSON corrupto y directorios ausentes: una fuente rota no puede
    tumbar la generación de contenido, solo dejarla sin material.
    """
    if not reportes_dir or not reportes_dir.exists():
        return []
    out: list[dict] = []
    for p in sorted(reportes_dir.glob("*/*/prediccion.json")):
        try:
            rec = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if all(k in rec for k in _CAMPOS):
            out.append(rec)
    return out


def live_price(ticker: str, api_key: str | None, *, timeout: float = 10.0
               ) -> float | None:
    """Último precio por FMP. None si no hay clave o la llamada falla.

    Sin precio, un brief sigue sirviendo (pierde el marcador contra la
    realidad, no el resto), así que aquí no se lanza nunca.
    """
    if not api_key:
        return None
    try:
        r = httpx.get(
            f"https://financialmodelingprep.com/api/v3/quote-short/{ticker}",
            params={"apikey": api_key}, timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()
    except (httpx.HTTPError, ValueError):
        return None
    if isinstance(data, list) and data and isinstance(data[0], dict):
        precio = data[0].get("price")
        return float(precio) if isinstance(precio, (int, float)) else None
    return None
