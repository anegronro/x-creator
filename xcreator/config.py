"""Configuración propia. Este proyecto NO comparte .env con otros agentes.

Deliberadamente independiente de warren-buffett-jr: la única atadura es una
RUTA a los reportes que ese motor ya escribe. Se leen sus JSON; no se importa
su código. Si aquel cambia por dentro, aquí no se rompe nada — y si un día el
contenido deja de ser de acciones, esta ruta simplemente sobra.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


@dataclass(repr=False)
class Settings:
    """Nunca hace repr de un secreto."""

    anthropic_api_key: str | None = None
    anthropic_workspace_id: str | None = None
    # xAI (Grok). Desde el 2026-09-21 es el proveedor por defecto: los
    # créditos de Anthropic se acabaron y no se recargan. Con la clave
    # puesta, redacta Grok; sin ella, se cae a Claude si hay clave.
    xai_api_key: str | None = None
    xai_modelo: str = "grok-4.7"
    # "xai" o "anthropic". Vacío = xai si hay XAI_API_KEY, si no anthropic.
    llm_proveedor: str = ""
    # Fuentes de datos de mercado (solo lectura). Nada de ejecución.
    fmp_api_key: str | None = None
    finnhub_api_key: str | None = None
    fred_api_key: str | None = None
    census_api_key: str | None = None
    oanda_token: str | None = None
    oanda_account_id: str | None = None
    # Lectura de la API de X (app-only: NO puede publicar).
    x_bearer_token: str | None = None
    # Publicación en nombre del usuario (OAuth 2.0 user context). El login lo
    # hace Angel en su navegador; aquí nunca se ve una contraseña.
    x_client_id: str | None = None
    x_client_secret: str | None = None
    x_handle: str | None = None
    # Por si la app registró otro callback: tiene que coincidir EXACTAMENTE
    # con el de developer.x.com, y el servidor local escucha en su puerto.
    x_callback: str | None = None
    # Tope de gasto por pasada. Un bucle con un bug no puede vaciar los
    # créditos en una tarde.
    x_presupuesto_pasada: float = 0.50
    # Replies al día. Cada uno cuesta tres toques manuales (X no deja
    # publicarlos por API), así que el límite no es el dinero: es el tiempo
    # de Angel. Pocos y buenos vale más que muchos y tibios.
    # Subido de 3 a 6 el 2026-09-15. El 3 lo elegí yo, sin medir nada, y la
    # evidencia apunta al otro lado: el reply a @zerohedge sobre PLTR hizo 584
    # impresiones el mismo día en que los posts propios hicieron entre 33 y
    # 62. Racionar los replies era racionar justo donde está el alcance. El
    # tope sigue existiendo porque cada reply es trabajo manual de Angel (X
    # bloqueó publicarlos por API) y porque al agotarse corta las lecturas de
    # X antes de gastarlas. Seis son unos diez minutos suyos al día.
    replies_por_dia: int = 6
    # De esos, cuántos pueden ser de opinión (sin cifras propias). Los de
    # datos son lo que diferencia la cuenta; los de opinión son más fáciles
    # de producir y hay muchos más posts candidatos, así que sin este
    # sub-tope se comerían el cupo entero y el diferencial se perdería.
    # Vuelve a 1 (lo había subido a 2 por iniciativa propia). La semana del
    # 9 al 15 de septiembre dice que los replies SIN cashtag tienen mediana 22
    # frente a 104 los que llevan datos (n=8/40, p=0.003). El cuello no es el
    # cupo sino los tickers: solo hubo 8 posts ajenos emparejables en 7 días,
    # así que subir la opinión solo fabrica más de la categoría más floja.
    replies_opinion_por_dia: int = 1
    # Y solo a posts recientes: a las tres horas la conversación ya se movió.
    horas_frescura_reply: float = 3.0
    # Solo UNA máquina puede hablar con Telegram. Dos instancias con el mismo
    # bot se roban los updates (el primero que llega los consume) y cada una
    # busca el borrador en SU cola: aprobar en el teléfono un borrador de la
    # otra da "ese borrador ya no existe". El VPS es el dueño porque corre
    # 24/7; la Mac queda para desarrollar.
    telegram_activo: bool = True
    # Bot PROPIO. Sin fallback a ningún TELEGRAM_BOT_TOKEN genérico: un
    # fallback silencioso mandaría estos posts al chat de otro agente.
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    # Fuentes del motor de acciones: solo lectura, por ruta.
    reportes_dir: Path | None = None
    cerebro_dir: Path | None = None
    root: Path = field(default_factory=_root)

    @property
    def x_tokens_path(self) -> Path:
        return self.root / "Contenido" / "x_tokens.json"

    @property
    def watchlist_path(self) -> Path:
        return self.root / "Contenido" / "watchlist.json"

    @property
    def x_cache_path(self) -> Path:
        return self.root / "Contenido" / "x_ids.json"

    @property
    def x_estado_path(self) -> Path:
        return self.root / "Contenido" / "x_ultimos.json"

    @property
    def uso_llm_path(self) -> Path:
        return self.root / "Contenido" / "uso_llm.jsonl"

    @property
    def cola_path(self) -> Path:
        return self.root / "Contenido" / "cola.jsonl"

    @property
    def estado_telegram_path(self) -> Path:
        return self.root / "Contenido" / "telegram_estado.json"

    def __repr__(self) -> str:
        def m(v):
            return "********" if v else None

        return (
            f"Settings(anthropic_api_key={m(self.anthropic_api_key)}, "
            f"xai_api_key={m(self.xai_api_key)}, "
            f"fmp_api_key={m(self.fmp_api_key)}, "
            f"telegram_bot_token={m(self.telegram_bot_token)}, "
            f"reportes_dir={self.reportes_dir}, root={self.root})"
        )


def load_settings(env_file: Path | None = None) -> Settings:
    root = _root()
    env_file = env_file or root / "API" / ".env"
    env = dotenv_values(env_file) if env_file.exists() else {}

    def get(name: str) -> str | None:
        return env.get(name) or os.environ.get(name) or None

    reportes = get("WBJ_REPORTES_DIR")
    cerebro = get("WBJ_CEREBRO_DIR")
    return Settings(
        anthropic_api_key=get("ANTHROPIC_API_KEY"),
        anthropic_workspace_id=get("ANTHROPIC_WORKSPACE_ID"),
        xai_api_key=get("XAI_API_KEY"),
        xai_modelo=get("XAI_MODELO") or "grok-4.7",
        llm_proveedor=(get("LLM_PROVEEDOR") or "").lower(),
        fmp_api_key=get("FMP_API_KEY"),
        finnhub_api_key=get("FINNHUB_API_KEY"),
        fred_api_key=get("FRED_API_KEY"),
        census_api_key=get("CENSUS_API_KEY"),
        oanda_token=get("OANDA_TOKEN"),
        oanda_account_id=get("OANDA_ACCOUNT_ID"),
        x_bearer_token=get("X_BEARER_TOKEN"),
        x_client_id=get("X_CLIENT_ID"),
        x_client_secret=get("X_CLIENT_SECRET"),
        x_handle=get("X_HANDLE"),
        x_callback=get("X_CALLBACK_URL"),
        x_presupuesto_pasada=float(get("X_PRESUPUESTO_PASADA") or 0.50),
        replies_por_dia=int(get("REPLIES_POR_DIA") or 6),
        replies_opinion_por_dia=int(get("REPLIES_OPINION_POR_DIA") or 1),
        horas_frescura_reply=float(get("HORAS_FRESCURA_REPLY") or 3),
        telegram_activo=(get("TELEGRAM_ACTIVO") or "true").lower()
        not in ("false", "0", "no"),
        telegram_bot_token=get("TELEGRAM_X_BOT_TOKEN"),
        telegram_chat_id=get("TELEGRAM_X_CHAT_ID"),
        reportes_dir=Path(reportes).expanduser() if reportes else None,
        cerebro_dir=Path(cerebro).expanduser() if cerebro else None,
        root=root,
    )


def anthropic_client(settings: Settings):
    """Cliente listo, o None si falta la clave o el SDK. Nunca revienta."""
    if not settings.anthropic_api_key:
        return None
    try:
        import anthropic
    except ImportError:
        return None
    headers = (
        {"anthropic-workspace-id": settings.anthropic_workspace_id}
        if settings.anthropic_workspace_id
        else None
    )
    return anthropic.Anthropic(
        api_key=settings.anthropic_api_key, default_headers=headers
    )


def proveedor(settings: Settings) -> str:
    """Qué modelo redacta: el elegido a mano, o xAI si hay clave."""
    if settings.llm_proveedor in ("xai", "anthropic"):
        return settings.llm_proveedor
    return "xai" if settings.xai_api_key else "anthropic"


def llm_client(settings: Settings):
    """El cliente del modelo que redacta, o None si falta su clave.

    Devuelve algo con la interfaz `messages.parse` / `messages.create` del
    SDK de Anthropic, sea cual sea el proveedor: el resto del código no
    necesita saber quién escribe.
    """
    if proveedor(settings) == "xai":
        if not settings.xai_api_key:
            return None
        from xcreator.llm import ClienteXAI

        return ClienteXAI(settings.xai_api_key, modelo=settings.xai_modelo,
                          registro=settings.uso_llm_path)
    return anthropic_client(settings)
