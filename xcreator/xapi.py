"""Lectura de la API de X. Solo lectura: publicar es otra cosa y otro permiso.

Precios pay-per-use (feb 2026): $0.005 por post leído y $0.010 por usuario
leído. De ahí dos decisiones:

- Los user_id se cachean en disco. Un handle SIEMPRE resuelve al mismo id, así
  que pagarlo en cada corrida sería tirar dinero: 7 cuentas vigiladas cuatro
  veces al día son $0.28 diarios solo en resolver nombres que ya conocíamos.
- Cada llamada estima su costo antes de hacerla, y `presupuesto_diario` corta.
  Un bucle con un bug no puede gastarse los créditos en una tarde.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import httpx

BASE = "https://api.x.com/2"
COSTO_POST_LEIDO = 0.005
COSTO_USUARIO_LEIDO = 0.010


class XAPIError(RuntimeError):
    """Falla de la API o de configuración. Nunca se traga en silencio."""


@dataclass
class PostAjeno:
    post_id: str
    autor: str
    texto: str
    creado: str = ""

    @property
    def url(self) -> str:
        return f"https://x.com/{self.autor.lstrip('@')}/status/{self.post_id}"


class ClienteX:
    """Cliente mínimo de lectura. Nunca imprime el bearer token."""

    def __init__(self, bearer: str, cache_path: Path,
                 *, presupuesto_diario: float = 1.0, timeout: float = 20.0):
        if not bearer:
            raise XAPIError(
                "Falta X_BEARER_TOKEN en API/.env. Se saca en console.x.com "
                "(el proyecto y su app), y hay que cargar créditos: leer un "
                "post cuesta $0.005."
            )
        self.bearer = bearer
        self.cache_path = cache_path
        self.presupuesto_diario = presupuesto_diario
        self.timeout = timeout
        self.gastado = 0.0

    # --- caché de ids ---
    def _cache(self) -> dict:
        try:
            return json.loads(self.cache_path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}

    def _guardar_cache(self, d: dict) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(d, indent=2))

    def _cobrar(self, monto: float) -> None:
        if self.gastado + monto > self.presupuesto_diario:
            raise XAPIError(
                f"Presupuesto agotado: llevas ${self.gastado:.3f} de "
                f"${self.presupuesto_diario:.2f}. Sube el tope a conciencia."
            )
        self.gastado += monto

    def _get(self, ruta: str, **params) -> dict:
        try:
            r = httpx.get(f"{BASE}{ruta}",
                          headers={"Authorization": f"Bearer {self.bearer}"},
                          params=params, timeout=self.timeout)
        except httpx.HTTPError as e:
            raise XAPIError(f"{ruta}: sin conexión ({type(e).__name__})") from e
        if r.status_code == 401:
            raise XAPIError("El bearer token no sirve (401).")
        if r.status_code == 429:
            raise XAPIError("Rate limit de X (429). Espera antes de reintentar.")
        if r.status_code >= 400:
            raise XAPIError(f"{ruta}: HTTP {r.status_code} — {r.text[:200]}")
        try:
            return r.json()
        except ValueError:
            raise XAPIError(f"{ruta}: respuesta no-JSON")

    def user_id(self, handle: str) -> str:
        """Id del handle, cacheado en disco (un handle no cambia de id)."""
        h = handle.lstrip("@").lower()
        cache = self._cache()
        if h in cache:
            return cache[h]
        self._cobrar(COSTO_USUARIO_LEIDO)
        data = self._get(f"/users/by/username/{h}")
        uid = (data.get("data") or {}).get("id")
        if not uid:
            raise XAPIError(f"No encontré el usuario @{h}")
        cache[h] = uid
        self._guardar_cache(cache)
        return uid

    def posts_recientes(self, handle: str, *, limite: int = 5,
                        desde_id: str | None = None) -> list[PostAjeno]:
        """Últimos posts de una cuenta, excluyendo respuestas y reposts.

        `desde_id` evita releer (y repagar) lo que ya se vio en la corrida
        anterior, que es la mitad del ahorro cuando esto corre por cron.
        """
        uid = self.user_id(handle)
        limite = max(5, min(limite, 100))  # la API exige 5..100
        # Se RESERVA el máximo antes de llamar (así la guarda de presupuesto
        # protege aunque la respuesta venga llena) y se ajusta a la baja con
        # lo realmente devuelto: con `since_id`, muchas pasadas traen cero.
        reserva = COSTO_POST_LEIDO * limite
        self._cobrar(reserva)
        params = {
            "max_results": limite,
            "exclude": "replies,retweets",
            "tweet.fields": "created_at",
        }
        if desde_id:
            params["since_id"] = desde_id
        try:
            data = self._get(f"/users/{uid}/tweets", **params)
        except XAPIError:
            self.gastado -= reserva  # la llamada falló: no se leyó nada
            raise
        devueltos = data.get("data") or []
        self.gastado -= reserva - COSTO_POST_LEIDO * len(devueltos)
        return [
            PostAjeno(post_id=t["id"], autor=handle, texto=t.get("text", ""),
                      creado=t.get("created_at", ""))
            for t in devueltos
        ]


def costo_estimado(n_cuentas: int, posts_por_cuenta: int,
                   *, ids_en_cache: bool = True) -> float:
    """Lo que costaría una pasada. Para decidir la frecuencia del cron."""
    costo = n_cuentas * posts_por_cuenta * COSTO_POST_LEIDO
    if not ids_en_cache:
        costo += n_cuentas * COSTO_USUARIO_LEIDO
    return costo
