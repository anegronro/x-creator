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
from dataclasses import dataclass, field
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
    # like_count, reply_count, retweet_count, quote_count... Pedirlas no
    # cuesta más: X cobra por post leído, no por campo.
    metricas: dict = field(default_factory=dict)
    # Id del post al que responde este, si es un reply. Vacío si no lo es.
    responde_a: str = ""
    # Autor del post al que responde ("@handle"), cuando la API lo expande.
    responde_a_autor: str = ""

    @property
    def impresiones(self) -> int:
        return int((self.metricas or {}).get("impression_count", 0) or 0)

    @property
    def conversacion(self) -> int:
        """Replies + citas + reposts: lo que dice que el post está VIVO.

        Los likes no cuentan: pesan 0.5 en el algoritmo y no traen a nadie a
        la conversación, que es donde una cita se deja ver.
        """
        m = self.metricas or {}
        return (m.get("reply_count", 0) + m.get("quote_count", 0)
                + m.get("retweet_count", 0))

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
        if r.status_code == 402:
            # 402 no es un fallo de credenciales: el token está bien y la
            # cuenta se quedó sin saldo. Distinguirlo del 401 ahorra una
            # persecución inútil del token.
            raise XAPIError(
                "Sin créditos en X (402). El token es válido; hay que "
                "recargar en console.x.com. Leer un post cuesta $0.005."
            )
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
            "tweet.fields": "created_at,public_metrics",
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
                      creado=t.get("created_at", ""),
                      metricas=t.get("public_metrics") or {})
            for t in devueltos
        ]


    def _leer_con_reserva(self, ruta: str, limite: int, **params) -> dict:
        """GET que reserva el máximo antes y devuelve lo no usado después.

        X cobra por post devuelto, incluidos los que vienen en `includes`
        (los padres expandidos). Se reserva el peor caso para que la guarda
        de presupuesto proteja aunque la respuesta venga llena.
        """
        reserva = COSTO_POST_LEIDO * limite * 2
        self._cobrar(reserva)
        try:
            data = self._get(ruta, **params)
        except XAPIError:
            self.gastado -= reserva
            raise
        n = len(data.get("data") or []) + len(
            (data.get("includes") or {}).get("tweets") or [])
        self.gastado -= reserva - COSTO_POST_LEIDO * n
        return data

    def menciones(self, handle: str, *, desde_id: str | None = None,
                  limite: int = 20) -> list[tuple[PostAjeno, PostAjeno | None]]:
        """Replies y menciones a `handle`, cada uno con el post al que responde.

        Con `desde_id` solo llega lo nuevo, y X solo cobra lo que devuelve:
        una cuenta pequeña recibe pocas respuestas al día, así que mirar cada
        media hora cuesta centavos al mes.
        """
        uid = self.user_id(handle)
        limite = max(5, min(limite, 100))
        params = {
            "max_results": limite,
            "tweet.fields": "created_at,public_metrics,referenced_tweets,author_id",
            "expansions": "author_id,referenced_tweets.id,referenced_tweets.id.author_id",
            "user.fields": "username",
        }
        if desde_id:
            params["since_id"] = desde_id
        data = self._leer_con_reserva(f"/users/{uid}/mentions", limite, **params)
        return _con_padres(data)

    def mis_replies(self, handle: str, *, horas: int = 24,
                    limite: int = 50) -> list[tuple[PostAjeno, None]]:
        """Los replies de `handle` de las últimas `horas`, SIN su post padre.

        Se busca `from:x is:reply` en vez de leer el timeline entero: el
        timeline trae también los posts propios, y pagarlos para descartarlos
        duplicaba el costo. Y el padre NO se expande aquí: la primera versión
        lo hacía y pagaba 100 posts ($0.50) para usar 2. El padre se pide con
        `post()` solo para los que de verdad se reciclan.
        """
        from datetime import datetime, timedelta, timezone

        h = handle.lstrip("@")
        desde = (datetime.now(timezone.utc) - timedelta(hours=horas)).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        limite = max(10, min(limite, 100))
        data = self._leer_con_reserva(
            "/tweets/search/recent", limite,
            query=f"from:{h} is:reply", start_time=desde, max_results=limite,
            **{"tweet.fields": "created_at,public_metrics,referenced_tweets"})
        return [(PostAjeno(post_id=t["id"], autor="@" + h,
                           texto=t.get("text", ""),
                           creado=t.get("created_at", ""),
                           metricas=t.get("public_metrics") or {},
                           responde_a=_padre(t)), None)
                for t in data.get("data") or []]

    def post(self, post_id: str) -> PostAjeno | None:
        """Un post suelto con su autor. Para el padre de un reply reciclado."""
        self._cobrar(COSTO_POST_LEIDO + COSTO_USUARIO_LEIDO)
        try:
            data = self._get(f"/tweets/{post_id}", expansions="author_id",
                             **{"user.fields": "username",
                                "tweet.fields": "created_at,public_metrics"})
        except XAPIError:
            self.gastado -= COSTO_POST_LEIDO + COSTO_USUARIO_LEIDO
            raise
        t = data.get("data")
        if not t:
            return None
        usuarios = {u["id"]: "@" + u.get("username", "")
                    for u in (data.get("includes") or {}).get("users") or []}
        return PostAjeno(post_id=t["id"], autor=usuarios.get(t.get("author_id", ""), ""),
                         texto=t.get("text", ""), creado=t.get("created_at", ""),
                         metricas=t.get("public_metrics") or {})

def _con_padres(data: dict) -> list[tuple[PostAjeno, PostAjeno | None]]:
    """Empareja cada post de `data` con su padre de `includes`."""
    usuarios = {u["id"]: "@" + u.get("username", "")
                for u in (data.get("includes") or {}).get("users") or []}
    padres = {t["id"]: t for t in (data.get("includes") or {}).get("tweets") or []}

    def a_post(t: dict) -> PostAjeno:
        padre_id = _padre(t)
        padre = padres.get(padre_id) or {}
        return PostAjeno(
            post_id=t["id"], autor=usuarios.get(t.get("author_id", ""), ""),
            texto=t.get("text", ""), creado=t.get("created_at", ""),
            metricas=t.get("public_metrics") or {}, responde_a=padre_id,
            responde_a_autor=usuarios.get(padre.get("author_id", ""), ""))

    out = []
    for t in data.get("data") or []:
        p = a_post(t)
        padre = padres.get(p.responde_a)
        out.append((p, a_post(padre) if padre else None))
    return out


def _padre(t: dict) -> str:
    """El id del post al que responde `t`, o "" si no es un reply."""
    for r in t.get("referenced_tweets") or []:
        if r.get("type") == "replied_to":
            return r.get("id", "")
    return ""


def costo_estimado(n_cuentas: int, posts_por_cuenta: int,
                   *, ids_en_cache: bool = True) -> float:
    """Lo que costaría una pasada. Para decidir la frecuencia del cron."""
    costo = n_cuentas * posts_por_cuenta * COSTO_POST_LEIDO
    if not ids_en_cache:
        costo += n_cuentas * COSTO_USUARIO_LEIDO
    return costo
