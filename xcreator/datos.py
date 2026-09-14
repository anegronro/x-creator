"""Lectura de las fuentes de datos. Solo lectura, sin importar otros motores.

Hoy la fuente son los `prediccion.json` que escribe warren-buffett-jr y los
precios de FMP. Cuando el contenido deje de ser solo de acciones, aquí es
donde se enchufan las fuentes nuevas — nada más del proyecto lo nota.
"""

from __future__ import annotations

import json
import re
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


# Sufijos societarios: "Apple Inc." y "Apple" son la misma empresa en un post.
_SUFIJOS = re.compile(
    r"\b(inc|corp|corporation|company|co|ltd|limited|plc|holdings?|group|"
    r"technologies|technology|systems|international|sa|nv|ag|the)\b\.?",
    re.IGNORECASE,
)


def nombre_corto(entidad: str) -> str:
    """'Apple Inc.' -> 'apple'. Lo que un post escribiría de verdad."""
    s = _SUFIJOS.sub(" ", entidad or "")
    s = re.sub(r"[^\w\s&]", " ", s)
    return " ".join(s.split()).strip().lower()


def load_company_names(reportes_dir: Path | None) -> dict[str, str]:
    """{nombre de empresa en minúsculas: ticker}, desde los scores.json.

    Sin esto, un post que dice "Oracle canceled his plan to sell shares" se
    descarta aunque tengamos ORCL analizado, porque no lleva cashtag. Los
    nombres ya los escribió el motor de acciones: aquí solo se leen.
    """
    if not reportes_dir or not reportes_dir.exists():
        return {}
    nombres: dict[str, str] = {}
    for p in sorted(reportes_dir.glob("*/*/scores.json")):
        try:
            d = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        ticker, entidad = d.get("ticker"), d.get("entity")
        if not ticker or not entidad:
            continue
        corto = nombre_corto(entidad)
        # Un nombre de una sola letra o dos caracteres da falsos positivos.
        if len(corto) >= 3:
            nombres[corto] = ticker.upper()
    return nombres


def price_history(ticker: str, api_key: str | None, *, dias: int = 180,
                  timeout: float = 20.0) -> list[tuple[str, float]]:
    """[(fecha ISO, cierre)] de los últimos `dias`, del más viejo al más nuevo.

    Devuelve [] si no hay clave o la llamada falla: un gráfico sin histórico
    no se dibuja, pero el post de texto sigue saliendo.
    """
    if not api_key:
        return []
    from datetime import date, timedelta

    hoy = date.today()
    try:
        # El endpoint /api/v3/historical-price-full está retirado (403
        # "Legacy Endpoint"): el vivo es /stable/historical-price-eod/full.
        r = httpx.get(
            "https://financialmodelingprep.com/stable/historical-price-eod/full",
            params={"symbol": ticker, "apikey": api_key,
                    "from": str(hoy - timedelta(days=dias)), "to": str(hoy)},
            timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()
    except (httpx.HTTPError, ValueError):
        return []
    filas = data if isinstance(data, list) else data.get("historical")
    if not filas:
        return []
    out = []
    for f in filas:
        fecha, cierre = f.get("date"), f.get("close")
        if fecha and isinstance(cierre, (int, float)):
            out.append((fecha, float(cierre)))
    return sorted(out)


def fred_series(serie: str, api_key: str | None, *, limite: int = 400,
                timeout: float = 20.0) -> list[tuple[str, float]]:
    """[(fecha, valor)] de una serie de FRED, de la más vieja a la más nueva.

    Devuelve [] si falla: sin macro se sigue publicando de empresas.
    """
    if not api_key:
        return []
    try:
        r = httpx.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={"series_id": serie, "api_key": api_key,
                    "file_type": "json", "sort_order": "desc",
                    "limit": limite},
            timeout=timeout,
        )
        r.raise_for_status()
        obs = r.json().get("observations", [])
    except (httpx.HTTPError, ValueError):
        return []
    out = []
    for o in obs:
        # FRED marca los huecos con "." — son días sin dato, no ceros.
        if o.get("value") in (None, ".", ""):
            continue
        try:
            out.append((o["date"], float(o["value"])))
        except (KeyError, ValueError):
            continue
    return sorted(out)
