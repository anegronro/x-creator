"""Las cuentas grandes que vigilamos para responderles.

Los datos de la cuenta de Angel dicen que el 92% de lo que publica ya son
respuestas, pero con mediana de 22 impresiones: no le falta responder, le
falta responder donde hay audiencia. Esta lista es ese "dónde".

Cada entrada declara qué publica la cuenta y qué ángulo del Cerebro encaja,
porque no todas sirven igual: a una cuenta de titulares en vivo se le
responde con niveles y riesgo, no con un DCF.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Cuenta:
    handle: str
    tema: str = ""
    # Ángulo del Cerebro que mejor encaja (ver cerebro.ANGULOS).
    angulo: str = "valuacion"
    activa: bool = True
    # Tope propio de replies al día. 0 = solo manda el tope global.
    # Una cuenta de titulares en vivo publica decenas de posts al día: sin
    # esto, una sola cuenta se come el cupo entero y el resto no se mira.
    tope_diario: int = 0
    notas: str = ""

    def normalizado(self) -> str:
        return self.handle.lstrip("@").lower()


# Semilla: las que sigue Angel. El `angulo` es una hipótesis inicial — se
# corrige midiendo cuáles de nuestras respuestas rinden, no discutiéndolo.
SEMILLA: list[Cuenta] = [
    Cuenta("@unusual_whales", "flujo de opciones y datos de mercado", "riesgo",
           notas="publica datos duros; responde bien a cifras con fuente"),
    Cuenta("@zerohedge", "macro y mercados, tono alarmista", "riesgo",
           notas="mucho alcance y muchas respuestas: hay que aportar o callar"),
    Cuenta("@Deltaone", "titulares de mercado en vivo", "tecnico",
           notas="velocidad; encaja un nivel concreto, no una tesis larga"),
    Cuenta("@FirstSquawk", "titulares en vivo", "tecnico",
           notas="igual que Deltaone: reacción rápida o nada"),
    Cuenta("@Barchart", "gráficos y datos de acciones", "valuacion",
           notas="publica el dato sin interpretarlo; ahí cabe el supuesto"),
    Cuenta("@charliebilello", "series históricas y contexto de largo plazo", "finanzas",
           notas="audiencia numerada; el rigor se nota y se premia"),
    Cuenta("@business", "Bloomberg, noticias generales", "mercado",
           notas="alcance enorme pero poco nicho; la conversión suele ser baja"),
]


@dataclass
class Watchlist:
    path: Path
    cuentas: list[Cuenta] = field(default_factory=list)

    @classmethod
    def cargar(cls, path: Path, *, sembrar: bool = True) -> "Watchlist":
        if path.exists():
            try:
                data = json.loads(path.read_text())
                return cls(path, [Cuenta(**c) for c in data.get("cuentas", [])])
            except (json.JSONDecodeError, OSError, TypeError):
                pass
        wl = cls(path, list(SEMILLA) if sembrar else [])
        if sembrar:
            wl.guardar()
        return wl

    def guardar(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(
            {"cuentas": [asdict(c) for c in self.cuentas]},
            indent=2, ensure_ascii=False))

    def activas(self) -> list[Cuenta]:
        return [c for c in self.cuentas if c.activa]

    def get(self, handle: str) -> Cuenta | None:
        h = handle.lstrip("@").lower()
        return next((c for c in self.cuentas if c.normalizado() == h), None)

    def add(self, handle: str, tema: str = "", angulo: str = "valuacion") -> Cuenta:
        existente = self.get(handle)
        if existente:
            return existente
        c = Cuenta(handle if handle.startswith("@") else f"@{handle}",
                   tema=tema, angulo=angulo)
        self.cuentas.append(c)
        self.guardar()
        return c

    def desactivar(self, handle: str) -> bool:
        """No se borra: una cuenta que no rindió es información, no basura."""
        c = self.get(handle)
        if c is None:
            return False
        c.activa = False
        self.guardar()
        return True
