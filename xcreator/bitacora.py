"""Construir en público: qué hizo el sistema esta semana y qué costó.

Es el otro tipo de contenido humano, y el único que puede hablar de Angel sin
que él tenga que escribir nada: los hechos existen y son comprobables. Salen
de tres sitios, todos propios:

- `CAMBIOS.txt`: el historial de git, que el despliegue deja en el VPS (allí
  no hay repo, solo el código copiado).
- `Contenido/uso_llm.jsonl`: lo que costó el modelo, llamada a llamada.
- La cola: cuántos posts salieron de verdad.

Nada de esto se estima. Si un dato falta, ese hecho no entra en el post.

Lo que NUNCA sale de aquí: direcciones de servidores, rutas, claves ni
nombres de archivos internos. Se publica lo que se hizo y lo que costó, no
cómo entrar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from xcreator.brief import Brief, Fact

DIAS = 7
# Prefijos de Conventional Commits y qué son en cristiano.
_TIPO = {"feat": "mejora", "fix": "arreglo", "docs": "documentación",
         "refactor": "limpieza", "test": "pruebas", "chore": "mantenimiento"}


@dataclass
class Cambio:
    fecha: str
    tipo: str        # feat | fix | docs...
    asunto: str      # el mensaje, ya sin el prefijo

    @property
    def es_arreglo(self) -> bool:
        return self.tipo == "fix"


def leer_cambios(ruta: Path, dias: int = DIAS,
                 hoy: date | None = None) -> list[Cambio]:
    """Los cambios de los últimos `dias` desde el CAMBIOS.txt del despliegue.

    Formato de cada línea: `hash|YYYY-MM-DD|asunto`. Un archivo que no está
    (desarrollo local, despliegue viejo) devuelve lista vacía, no revienta:
    sin cambios que contar, no hay post.
    """
    if not ruta.exists():
        return []
    corte = (hoy or date.today()) - timedelta(days=dias)
    out: list[Cambio] = []
    for linea in ruta.read_text(encoding="utf-8", errors="ignore").splitlines():
        partes = linea.split("|", 2)
        if len(partes) != 3:
            continue
        _, fecha, asunto = partes
        try:
            f = date.fromisoformat(fecha.strip())
        except ValueError:
            continue
        if f < corte:
            continue
        m = re.match(r"^(\w+)(\([^)]*\))?:\s*(.+)$", asunto.strip())
        tipo = (m.group(1) if m else "").lower()
        out.append(Cambio(fecha=fecha.strip(),
                          tipo=tipo if tipo in _TIPO else "",
                          asunto=(m.group(3) if m else asunto).strip()))
    return out


def gasto_semanal(registro: Path, dias: int = DIAS,
                  ahora: datetime | None = None) -> tuple[int, float]:
    """(llamadas, dólares) del modelo en los últimos `dias`."""
    from xcreator.llm import gasto

    ahora = ahora or datetime.now(timezone.utc)
    n_total, usd_total = 0, 0.0
    for k in range(dias):
        dia = (ahora - timedelta(days=k)).date().isoformat()
        n, usd = gasto(registro, dia)
        n_total += n
        usd_total += usd
    return n_total, round(usd_total, 4)


def publicados_semana(items, dias: int = DIAS,
                      hoy: date | None = None) -> tuple[int, int]:
    """(posts propios publicados, replies propuestos) en la ventana."""
    corte = ((hoy or date.today()) - timedelta(days=dias)).isoformat()
    propios = sum(1 for i in items
                  if i.estado == "publicado" and i.kind not in ("reply", "cita")
                  and (i.publicado_en or "")[:10] >= corte)
    replies = sum(1 for i in items
                  if i.kind == "reply" and (i.creado or "")[:10] >= corte)
    return propios, replies


def brief_bitacora(cambios: list[Cambio], llamadas: int, usd: float,
                   propios: int, replies: int) -> Brief | None:
    """Brief del post semanal. None si no hubo nada que contar.

    Sin cambios en el código no hay bitácora: publicar "esta semana no toqué
    nada" es relleno, y el relleno es lo que hace que una cuenta parezca un
    bot con calendario.
    """
    if not cambios or propios <= 0:
        return None

    arreglos = [c for c in cambios if c.es_arreglo]
    fuente_repo = "historial de cambios del propio repositorio"
    facts = [
        Fact("cambios al sistema esta semana", float(len(cambios)), "num",
             fuente_repo),
        Fact("de esos, arreglos de fallos", float(len(arreglos)), "num",
             fuente_repo),
        Fact("posts propios publicados esta semana", float(propios), "num",
             "la cola del agente"),
        Fact("replies propuestos esta semana", float(replies), "num",
             "la cola del agente"),
        Fact("lo que costó el modelo esta semana", round(usd, 2), "usd",
             "registro de uso del modelo, llamada a llamada"),
        Fact("llamadas al modelo esta semana", float(llamadas), "num",
             "registro de uso del modelo"),
    ]
    if llamadas:
        facts.append(Fact("coste medio por llamada al modelo",
                          round(usd / llamadas, 4), "usd", "calculado"))
    if propios:
        facts.append(Fact("coste del modelo por post publicado",
                          round(usd / propios, 3), "usd", "calculado"))

    lista = "; ".join(f"{c.asunto}" for c in cambios[:6])
    lista_arreglos = "; ".join(c.asunto for c in arreglos[:4]) or "ninguno"
    return Brief(
        kind="sistema",
        ticker="",
        sujeto=("my system", "the agent", "this account", "my bot"),
        angulo="personal",
        angle="Qué cambié esta semana en el sistema que escribe esta cuenta",
        facts=facts,
        context=[
            "Esto es construir en público: la cuenta cuenta cómo se hace a sí "
            "misma. Habla en primera persona de lo que TÚ montaste.",
            f"CAMBIOS DE ESTA SEMANA (reales, del repositorio): {lista}.",
            f"FALLOS QUE ARREGLASTE: {lista_arreglos}.",
            "Elige UNA cosa de esa lista y cuéntala. Un post no es un "
            "changelog: el changelog aburre, el fallo concreto y lo que "
            "enseñó, no. Si arreglaste algo que estuvo roto, ESO es el post: "
            "lo que se rompió, cómo te diste cuenta y qué cambiaste.",
            "Puedes usar las cifras de arriba porque son tuyas y las tienes "
            "medidas. Dos como mucho, y las que apoyen la historia.",
            "NO expliques cómo está montado por dentro: nada de servidores, "
            "direcciones, rutas, nombres de archivos ni proveedores de "
            "claves. Se cuenta QUÉ hace y qué costó, no cómo entrar.",
            "NO prometas resultados de la cuenta ni digas que esto es un "
            "negocio que funciona: todavía no monetiza, y decir lo contrario "
            "sería mentir.",
            "Sin consejo de inversión, sin links, sin hashtags.",
        ],
        as_of=date.today().isoformat(),
    )
