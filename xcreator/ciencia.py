"""Ciencia y tecnología: el nicho que más interacción tiene en X.

Por qué existe este módulo, con los números delante:

- Medido en la propia cuenta el 2026-09-26: los posts personales de fin de
  semana hicieron mediana de 9 impresiones (n=26), frente a 52 de los de
  empresa. No es que estuvieran mal escritos.
- La causa es cómo reparte X: pasa cada post por un modelo, lo asigna a uno
  de sus grupos temáticos y se lo enseña a la gente de ese grupo. La cuenta
  vive en el grupo de finanzas y cripto. Un post sobre la fe o la familia
  cae en otro grupo donde la cuenta no tiene a nadie.
- Y tecnología (1.74%) y cripto (1.62%) son los nichos con más interacción
  de 2026, por encima de la mediana de la plataforma (1.11%).

Así que el contenido de fin de semana deja de ser solo personal y entra
ciencia y tecnología, que es vecino del grupo temático donde la cuenta sí
tiene audiencia. Mismo patrón que `regulacion.py`: titular real de fuente
oficial, atribuido con su cuenta de X, sin enlace y sin inventar nada.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date

from xcreator.brief import Brief, Fact

# (nombre, url del RSS, cuenta de X comprobada el 2026-09-26, qué publica)
FUENTES = (
    ("NASA", "https://www.nasa.gov/news-release/feed/", "@NASA",
     "space missions and hardware"),
    ("Nature", "https://www.nature.com/nature.rss", "@nature",
     "peer reviewed research"),
    ("ScienceDaily", "https://www.sciencedaily.com/rss/top/science.xml",
     "@ScienceDaily", "research summaries across fields"),
    ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/technology-lab",
     "@arstechnica", "technology and computing"),
)

# Pasadas 48 horas, la conversación ya ocurrió. Es la misma ventana que usa
# el propio filtro de edad de X.
HORAS_MAX = 48

# Temas que conectan con la audiencia que YA tiene la cuenta. Un titular de
# biología marina es ciencia, pero no habla al grupo temático de mercados.
_RELEVANTE = (
    "ai", "artificial intelligence", "machine learning", "chip", "chips",
    "semiconductor", "quantum", "compute", "computing", "data center",
    "energy", "battery", "nuclear", "fusion", "solar", "grid", "robot",
    "robotics", "satellite", "space", "launch", "rocket", "orbit", "mars",
    "moon", "telescope", "encryption", "cryptography", "network", "internet",
    "chipmaker", "supercomputer", "algorithm", "model", "materials",
    "manufacturing", "automation", "drone", "biotech", "genome", "vaccine",
    "climate", "storage", "hydrogen",
)


@dataclass
class Titular:
    fuente: str
    handle: str
    titulo: str
    resumen: str
    url: str
    horas: float | None

    @property
    def clave(self) -> str:
        return self.url.rstrip("/").split("/")[-1]


def es_relevante(texto: str) -> bool:
    """True si el titular toca algo que le interesa a esta audiencia."""
    t = f" {(texto or '').lower()} "
    return any(f" {p} " in t or f" {p}s " in t or f"{p}," in t
               for p in _RELEVANTE)


def leer(http=None) -> list[Titular]:
    """Titulares recientes de las cuatro fuentes. Nunca revienta."""
    import httpx

    from xcreator.fuentes_oficiales import USER_AGENT, parse_rss

    cliente = http or httpx.Client(timeout=20.0,
                                   headers={"User-Agent": USER_AGENT})
    out: list[Titular] = []
    for nombre, url, handle, _ in FUENTES:
        try:
            r = cliente.get(url)
            if r.status_code >= 400:
                print(f"{nombre}: HTTP {r.status_code}", file=sys.stderr)
                continue
            for c in parse_rss(r.text, nombre):
                out.append(Titular(fuente=nombre, handle=handle,
                                   titulo=c.titulo, resumen=c.resumen,
                                   url=c.url, horas=c.horas))
        except Exception as e:  # noqa: BLE001 - una fuente caída no tumba el resto
            print(f"{nombre}: {type(e).__name__}: {e}", file=sys.stderr)
    return out


def elegir(titulares: list[Titular], usados: set[str]) -> Titular | None:
    """El titular relevante más fresco que no se haya usado ya."""
    buenos = [t for t in titulares
              if t.clave not in usados
              and es_relevante(f"{t.titulo} {t.resumen}")
              and (t.horas is None or t.horas <= HORAS_MAX)]
    buenos.sort(key=lambda t: t.horas if t.horas is not None else 999)
    return buenos[0] if buenos else None


def brief_ciencia(t: Titular) -> Brief:
    """Brief de un post de ciencia o tecnología, atribuido a su fuente."""
    from xcreator.replies import _numeros_del_texto

    texto = f"{t.titulo}. {t.resumen}".strip()
    facts = [Fact("cifra que aparece en el titular", v, "num",
                  f"{t.fuente}, titular original")
             for v in sorted(set(_numeros_del_texto(texto)))]
    return Brief(
        kind="ciencia",
        ticker="",
        sujeto=(),
        atribucion=(t.handle,),
        angulo="personal",   # fuera del Cerebro: aquí no hay empresa que analizar
        angle="Qué significa este avance para quien invierte y construye",
        facts=facts,
        context=[
            f"NOTICIA, publicada por {t.fuente} ({t.handle}): \"{texto[:600]}\"",
            f"ATRIBÚYELA: nombra a {t.handle} dentro de una frase, nunca como "
            f"primera palabra del post (X esconde los posts que empiezan por "
            f"@ como si fueran respuestas).",
            "NO afirmes nada que el titular no diga. No sabes qué más "
            "contiene el estudio ni qué pasará después. Las únicas cifras "
            "permitidas son las que aparecen arriba.",
            "El valor del post es el PUENTE: qué significa esto para alguien "
            "que invierte o que construye. Qué se abarata, qué se acelera, "
            "qué deja de ser un cuello de botella. Ese puente es tuyo y es "
            "opinión: no lo presentes como parte de la noticia.",
            "EN POSITIVO, que es como escribe esta cuenta: lo que esto "
            "habilita, no lo que amenaza. Sin catastrofismo y sin hype "
            "hueco tampoco.",
            "Nada de consejo de compra o venta, ningún precio objetivo, "
            "ninguna empresa concreta como recomendación.",
            "Sin links, sin hashtags. Corto: una o dos frases.",
        ],
        as_of=date.today().isoformat(),
    )
