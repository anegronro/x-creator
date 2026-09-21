"""El proveedor del modelo que redacta: xAI (Grok) o Anthropic (Claude).

El 2026-09-21 se acabaron los créditos de Anthropic y no se recargan. El
resto del sistema (generate.py, replies.py) habla con el modelo a través de
dos llamadas del SDK de Anthropic: `messages.parse` con salida estructurada y
`messages.create` con texto libre. Este módulo ofrece esas mismas dos
llamadas sobre la API de xAI, así que el cambio de proveedor no toca ni un
prompt ni una validación: las reglas siguen corriendo en código, que es donde
siempre tuvieron que estar.

La API de xAI es compatible con chat completions: `POST /v1/chat/completions`
con `response_format` de tipo `json_schema` para la salida estructurada.

Cada llamada deja una línea en `Contenido/uso_llm.jsonl` con los tokens y
el costo estimado. Con Anthropic nunca se registró, y el gasto se descubrió
cuando el saldo llegó a cero.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

XAI_URL = "https://api.x.ai/v1/chat/completions"
# El más capaz de xAI a septiembre de 2026. Con posts de 280 caracteres el
# costo por llamada ronda los 3 centavos, así que no compensa bajar de gama.
XAI_MODELO = "grok-4.7"
TIMEOUT = 180.0

# Dólares por millón de tokens (entrada, salida), tramo de menos de 200k de
# contexto, que es donde viven todos nuestros prompts. docs.x.ai/docs/models.
PRECIOS = {
    "grok-4.7": (2.00, 6.00),
    "grok-4.6": (2.00, 6.00),
    "grok-4.5": (2.00, 6.00),
    "grok-4.3": (1.25, 2.50),
}


class LLMError(RuntimeError):
    """Falla de la API del modelo. Nunca se traga en silencio."""


# --- Lo que devuelve, con la forma que el código ya espera del SDK ---------

@dataclass
class _Bloque:
    text: str
    type: str = "text"


@dataclass
class _Respuesta:
    content: list[_Bloque] = field(default_factory=list)
    parsed_output: Any = None
    # "max_tokens" cuando se cortó por el techo, igual que en Anthropic: el
    # detector de truncamiento de generate.py mira exactamente este valor.
    stop_reason: str | None = None


# --- Esquema estricto -------------------------------------------------------

def _inline_refs(schema: dict) -> dict:
    """Sustituye los `$ref` a `$defs` por la definición misma.

    pydantic pone los modelos anidados en `$defs` (`_Variants` contiene
    `_Variant`). Es más seguro mandar el esquema plano que depender de que el
    proveedor resuelva referencias.
    """
    defs = schema.get("$defs", {})

    def resolver(nodo):
        if isinstance(nodo, dict):
            if "$ref" in nodo:
                nombre = nodo["$ref"].split("/")[-1]
                return resolver(copy.deepcopy(defs[nombre]))
            return {k: resolver(v) for k, v in nodo.items() if k != "$defs"}
        if isinstance(nodo, list):
            return [resolver(x) for x in nodo]
        return nodo

    return resolver(schema)


def _estricto(schema: dict) -> dict:
    """Todo objeto cerrado y con todos sus campos obligatorios.

    El modo estricto lo exige. Un campo con valor por defecto en pydantic
    (`thread` vacío) sigue siendo obligatorio aquí: el modelo lo manda vacío.
    """
    if isinstance(schema, dict):
        schema = {k: _estricto(v) for k, v in schema.items()
                  if k not in ("default", "title")}
        if schema.get("type") == "object" and "properties" in schema:
            schema["additionalProperties"] = False
            schema["required"] = list(schema["properties"])
        return schema
    if isinstance(schema, list):
        return [_estricto(x) for x in schema]
    return schema


def esquema_de(modelo) -> dict:
    return _estricto(_inline_refs(modelo.model_json_schema()))


def _texto_de_sistema(system) -> str:
    """El system de Anthropic puede ser texto o una lista de bloques."""
    if not system:
        return ""
    if isinstance(system, str):
        return system
    return "\n\n".join(b.get("text", "") for b in system if isinstance(b, dict))


# --- Cliente ----------------------------------------------------------------

class _Mensajes:
    def __init__(self, cliente: "ClienteXAI"):
        self._c = cliente

    def create(self, *, model: str | None = None, max_tokens: int = 1000,
               messages: list[dict], system=None, **_) -> _Respuesta:
        datos = self._c._llamar(system, messages, max_tokens, None)
        return _Respuesta(content=[_Bloque(datos["texto"])],
                          stop_reason=datos["stop_reason"])

    def parse(self, *, model: str | None = None, max_tokens: int = 1000,
              messages: list[dict], system=None, output_format,
              **_) -> _Respuesta:
        datos = self._c._llamar(system, messages, max_tokens, output_format)
        try:
            parsed = output_format.model_validate_json(datos["texto"])
        except Exception:
            # Igual que el SDK cuando no hay salida usable: el llamador ya
            # sabe tratar `parsed_output is None`.
            parsed = None
        return _Respuesta(content=[_Bloque(datos["texto"])],
                          parsed_output=parsed,
                          stop_reason=datos["stop_reason"])


class ClienteXAI:
    """Imita la parte del SDK de Anthropic que usa este proyecto.

    El `model` que pasa el llamador se ignora: el código de generación trae
    ids de Claude por defecto y mandarlos a xAI sería un 404. Manda el modelo
    de este cliente, y es el que queda registrado en cada borrador.
    """

    def __init__(self, api_key: str, *, modelo: str = XAI_MODELO,
                 registro: Path | None = None, http: Any = None):
        if not api_key:
            raise LLMError("falta XAI_API_KEY")
        self._key = api_key
        self.modelo_por_defecto = modelo
        self._registro = registro
        self._http = http or httpx.Client(timeout=TIMEOUT)
        self.messages = _Mensajes(self)

    def __repr__(self) -> str:
        return f"ClienteXAI(modelo={self.modelo_por_defecto!r})"

    def _llamar(self, system, messages, max_tokens, output_format) -> dict:
        mensajes = []
        texto_sistema = _texto_de_sistema(system)
        if texto_sistema:
            mensajes.append({"role": "system", "content": texto_sistema})
        mensajes += [{"role": m["role"], "content": m["content"]}
                     for m in messages]
        cuerpo: dict[str, Any] = {
            "model": self.modelo_por_defecto,
            "messages": mensajes,
            "max_tokens": max_tokens,
        }
        if output_format is not None:
            cuerpo["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": output_format.__name__.lstrip("_") or "salida",
                    "schema": esquema_de(output_format),
                    "strict": True,
                },
            }
        r = self._http.post(
            XAI_URL, json=cuerpo,
            headers={"Authorization": f"Bearer {self._key}"})
        if r.status_code >= 400:
            # El cuerpo del error de xAI no lleva la clave; el mensaje sí
            # dice por qué (saldo, modelo inexistente, esquema inválido).
            raise LLMError(f"xAI {r.status_code}: {r.text[:300]}")
        d = r.json()
        eleccion = (d.get("choices") or [{}])[0]
        texto = ((eleccion.get("message") or {}).get("content") or "").strip()
        fin = eleccion.get("finish_reason")
        self._anotar(d.get("usage") or {})
        return {"texto": texto,
                "stop_reason": "max_tokens" if fin == "length" else fin}

    def _anotar(self, uso: dict) -> None:
        if self._registro is None:
            return
        entrada = int(uso.get("prompt_tokens") or 0)
        salida = int(uso.get("completion_tokens") or 0)
        p_in, p_out = PRECIOS.get(self.modelo_por_defecto, (0.0, 0.0))
        linea = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "proveedor": "xai",
            "modelo": self.modelo_por_defecto,
            "entrada": entrada,
            "salida": salida,
            "usd": round(entrada / 1e6 * p_in + salida / 1e6 * p_out, 5),
        }
        try:
            self._registro.parent.mkdir(parents=True, exist_ok=True)
            with self._registro.open("a", encoding="utf-8") as f:
                f.write(json.dumps(linea) + "\n")
        except OSError:
            pass  # no poder anotar el gasto no debe tumbar un post


def gasto(registro: Path, dia: str | None = None) -> tuple[int, float]:
    """(llamadas, dólares) del día dado (ISO) o de todo el registro."""
    if not registro.exists():
        return 0, 0.0
    n, usd = 0, 0.0
    for linea in registro.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(linea)
        except json.JSONDecodeError:
            continue
        if dia and not d.get("ts", "").startswith(dia):
            continue
        n += 1
        usd += float(d.get("usd") or 0)
    return n, round(usd, 4)
