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
