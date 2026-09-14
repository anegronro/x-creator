"""OAuth 2.0 (PKCE) para publicar como el usuario.

Dos credenciales distintas y fáciles de confundir:

- El **bearer token** de `xapi.py` es app-only: lee datos públicos y no puede
  publicar nada.
- Esto de aquí es **user context**: Angel autoriza la app en su navegador y a
  cambio se obtiene un access token que publica EN SU NOMBRE. Por eso el
  login lo hace él, en su navegador, y aquí nunca se ve ni se pide una
  contraseña.

El access token dura ~2 horas; con el scope `offline.access` viene un refresh
token que lo renueva sin volver a molestar al usuario. Los tokens se guardan
en `Contenido/` (ignorado por git) con permisos 600.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx

AUTORIZAR = "https://x.com/i/oauth2/authorize"
TOKEN = "https://api.x.com/2/oauth2/token"
# `offline.access` es el que da refresh token: sin él hay que reautorizar a
# mano cada dos horas, que en un proceso por cron es inviable.
SCOPES = ["tweet.read", "tweet.write", "users.read", "offline.access"]
PUERTO_CALLBACK = 8788
CALLBACK = f"http://localhost:{PUERTO_CALLBACK}/callback"
# Margen para no usar un token que caduca mientras vuela la petición.
MARGEN_REFRESH = 120


class AuthError(RuntimeError):
    """Falla de autorización. Nunca se traga en silencio."""


def _pkce() -> tuple[str, str]:
    """(verifier, challenge) para PKCE."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


@dataclass
class Tokens:
    access_token: str
    refresh_token: str = ""
    expira_en: float = 0.0   # epoch

    @property
    def vencido(self) -> bool:
        return time.time() >= self.expira_en - MARGEN_REFRESH

    def to_dict(self) -> dict:
        return {"access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "expira_en": self.expira_en}


class AlmacenTokens:
    """Tokens en disco, con permisos restringidos."""

    def __init__(self, path: Path):
        self.path = path

    def cargar(self) -> Tokens | None:
        try:
            d = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        if not d.get("access_token"):
            return None
        return Tokens(d["access_token"], d.get("refresh_token", ""),
                      float(d.get("expira_en", 0)))

    def guardar(self, t: Tokens) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(t.to_dict(), indent=2))
        self.path.chmod(0o600)


class _Handler(BaseHTTPRequestHandler):
    """Recibe el redirect de X y se calla. Un solo uso."""

    code: str | None = None
    state: str | None = None

    def do_GET(self):  # noqa: N802
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _Handler.code = (q.get("code") or [None])[0]
        _Handler.state = (q.get("state") or [None])[0]
        ok = _Handler.code is not None
        self.send_response(200 if ok else 400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            ("<h2>Listo, ya puedes cerrar esta pestaña.</h2>" if ok
             else "<h2>No llegó el código de autorización.</h2>").encode())

    def log_message(self, *a):  # silenciar el log del servidor
        pass


def autorizar(client_id: str, almacen: AlmacenTokens,
              *, client_secret: str = "", abrir_navegador: bool = True,
              timeout: float = 300.0) -> Tokens:
    """Flujo completo: abre el navegador, espera el callback, guarda tokens.

    El usuario autoriza en SU navegador, con SU sesión. Aquí no se pide ni se
    escribe una contraseña en ningún momento.
    """
    if not client_id:
        raise AuthError(
            "Falta X_CLIENT_ID en API/.env. Se saca creando una app en "
            "developer.x.com con OAuth 2.0 activado y callback "
            f"{CALLBACK}"
        )
    verifier, challenge = _pkce()
    estado = secrets.token_urlsafe(16)
    url = AUTORIZAR + "?" + urllib.parse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": CALLBACK,
        "scope": " ".join(SCOPES),
        "state": estado,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })

    _Handler.code = _Handler.state = None
    servidor = HTTPServer(("localhost", PUERTO_CALLBACK), _Handler)
    servidor.timeout = timeout
    print(f"Abre esta URL y autoriza:\n\n{url}\n")
    if abrir_navegador:
        webbrowser.open(url)
    servidor.handle_request()
    servidor.server_close()

    if not _Handler.code:
        raise AuthError("No llegó el código de autorización (¿se canceló?).")
    if _Handler.state != estado:
        # Defensa contra CSRF: el state de vuelta tiene que ser el que mandamos.
        raise AuthError("El `state` no coincide: se descarta por seguridad.")

    return _intercambiar(
        client_id, client_secret, almacen,
        {"grant_type": "authorization_code", "code": _Handler.code,
         "redirect_uri": CALLBACK, "code_verifier": verifier},
    )


def _intercambiar(client_id: str, client_secret: str, almacen: AlmacenTokens,
                  datos: dict) -> Tokens:
    datos = {**datos, "client_id": client_id}
    auth = (client_id, client_secret) if client_secret else None
    try:
        r = httpx.post(TOKEN, data=datos, auth=auth, timeout=30.0)
    except httpx.HTTPError as e:
        raise AuthError(f"token endpoint: sin conexión ({type(e).__name__})") from e
    if r.status_code >= 400:
        raise AuthError(f"token endpoint: HTTP {r.status_code} — {r.text[:200]}")
    d = r.json()
    if "access_token" not in d:
        raise AuthError(f"respuesta sin access_token: {str(d)[:200]}")
    t = Tokens(
        access_token=d["access_token"],
        # X no siempre devuelve refresh nuevo: se conserva el que había.
        refresh_token=d.get("refresh_token", "")
        or (almacen.cargar().refresh_token if almacen.cargar() else ""),
        expira_en=time.time() + float(d.get("expires_in", 7200)),
    )
    almacen.guardar(t)
    return t


def token_vigente(client_id: str, almacen: AlmacenTokens,
                  *, client_secret: str = "") -> Tokens:
    """El token de acceso, renovándolo si hace falta.

    Lanza AuthError si nunca se autorizó: mejor decirlo que fallar luego con
    un 401 críptico a mitad de una publicación.
    """
    t = almacen.cargar()
    if t is None:
        raise AuthError("Sin autorizar todavía. Corre `xc x-auth`.")
    if not t.vencido:
        return t
    if not t.refresh_token:
        raise AuthError("El token venció y no hay refresh token. Corre "
                        "`xc x-auth` otra vez (con scope offline.access).")
    return _intercambiar(
        client_id, client_secret, almacen,
        {"grant_type": "refresh_token", "refresh_token": t.refresh_token},
    )
