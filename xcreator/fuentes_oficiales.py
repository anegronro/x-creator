"""Comunicados oficiales de regulación: SEC, CFTC, Fed, OCC y Federal Register.

La cuenta quiere funcionar como un periodista: la noticia sale de la fuente
primaria y se atribuye con nombre. Antes, los posts de regulación salían de
titulares de cuentas de noticias rápidas (@WatcherGuru) y tenían que decir
"reportedly", porque nadie había verificado nada. Un comunicado de la SEC no
es un rumor: es el hecho, publicado por quien lo produce.

Las tres fuentes son gratis y sin clave. Costaban $0.075 por pasada en
lecturas de X; aquí cuestan cero.

- SEC: RSS de comunicados de prensa. Exige un User-Agent que identifique al
  que pide (política de acceso justo de EDGAR).
- CFTC: RSS de comunicados de prensa.
- Federal Register: API pública, búsqueda por términos de cripto. Es donde
  sale el texto de las reglas, de cualquier agencia.

Si una fuente falla, se avisa por la salida de error y se sigue con las
demás. Nunca en silencio: un 403 tragado ya dejó al sistema días sin precios.
"""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

SEC_RSS = "https://www.sec.gov/news/pressreleases.rss"
CFTC_RSS = "https://www.cftc.gov/RSS/RSSGP/rssgp.xml"
# (agencia, url, cómo se llama el documento en el post). Añadidas el
# 2026-09-21 para tener más volumen sin salir de la fuente primaria: los
# comisionados de la SEC y los gobernadores de la Fed hablan de cripto mucho
# más a menudo de lo que sus agencias emiten comunicados. Tesoro y FDIC no
# tienen RSS (404); sus reglas llegan por el Federal Register.
FUENTES_RSS = (
    ("SEC", SEC_RSS, ""),
    ("SEC", "https://www.sec.gov/news/speeches-statements.rss",
     "SEC statement"),
    ("CFTC", CFTC_RSS, "CFTC press release"),
    ("Federal Reserve", "https://www.federalreserve.gov/feeds/press_all.xml",
     "Federal Reserve press release"),
    ("Federal Reserve", "https://www.federalreserve.gov/feeds/speeches.xml",
     "Federal Reserve speech"),
    ("OCC", "https://www.occ.gov/rss/occ_news.xml", "OCC news release"),
)
FEDREG_API = "https://www.federalregister.gov/api/v1/documents.json"

# La SEC pide identificarse. Va el nombre del proyecto, no un correo: el
# correo del usuario no se manda a servicios de terceros sin que lo pida.
USER_AGENT = "x-creator research bot (github.com/anegronro/x-creator)"
TIMEOUT = 20.0

# Un comunicado oficial se sigue citando días después (la gente lo busca, lo
# enlaza, lo discute), así que la ventana es más larga que la de un titular
# de X. 72 horas cubren el fin de semana: lo del viernes sigue vivo el lunes.
HORAS_MAX_OFICIAL = 72

# Nombre completo de la agencia -> cómo se la nombra en un post. El post
# tiene que atribuir con un nombre que el lector reconozca.
_CORTO = {
    "securities and exchange commission": "SEC",
    "commodity futures trading commission": "CFTC",
    "federal deposit insurance corporation": "FDIC",
    "comptroller of the currency": "OCC",
    "federal reserve system": "Federal Reserve",
    "treasury department": "Treasury",
    "internal revenue service": "IRS",
    "financial crimes enforcement network": "FinCEN",
    "national credit union administration": "NCUA",
}


# La cuenta oficial en X de cada agencia, comprobada el 2026-09-21 con la
# API de X: todas con verificación de gobierno salvo @FedRegister (real, sin
# la marca). Por eso un documento del Federal Register se atribuye a la
# agencia que lo emite, no al Federal Register.
HANDLES = {
    "SEC": "@SECGov",
    "CFTC": "@CFTC",
    "FDIC": "@FDICgov",
    "OCC": "@USOCC",
    "Federal Reserve": "@federalreserve",
    "Treasury": "@USTreasury",
    "IRS": "@IRSnews",
    "FinCEN": "@FinCENnews",
    "NCUA": "@TheNCUA",
}


@dataclass
class Comunicado:
    agencia: str        # "SEC", como se nombra en el post
    titulo: str
    resumen: str
    url: str
    fecha: datetime | None
    documento: str      # "SEC press release 2026-90", "Federal Register rule"

    @property
    def horas(self) -> float | None:
        if self.fecha is None:
            return None
        return (datetime.now(timezone.utc) - self.fecha).total_seconds() / 3600

    @property
    def handle(self) -> str:
        """La @ de la agencia en X, o "" si no la tenemos comprobada."""
        return HANDLES.get(self.agencia, "")

    @property
    def clave(self) -> str:
        """Identificador estable: el último tramo de la URL."""
        return self.url.rstrip("/").split("/")[-1]


def _limpio(t: str | None) -> str:
    return re.sub(r"\s+", " ", t or "").strip()


def _fecha_rss(t: str | None) -> datetime | None:
    try:
        f = parsedate_to_datetime(t or "")
    except (TypeError, ValueError):
        return None
    if f.tzinfo is None:
        f = f.replace(tzinfo=timezone.utc)
    return f.astimezone(timezone.utc)


def _documento_sec(url: str) -> str:
    """La SEC numera sus comunicados en la URL: 2026-90-sec-issues-...

    Con el número, cualquiera lo encuentra sin link: "SEC press release
    2026-90" es una cita comprobable.
    """
    m = re.search(r"/(\d{4}-\d+)-", url)
    return f"SEC press release {m.group(1)}" if m else "SEC press release"


def parse_rss(xml: str, agencia: str, documento: str = "") -> list[Comunicado]:
    try:
        raiz = ET.fromstring(xml)
    except ET.ParseError as e:
        print(f"{agencia}: RSS ilegible ({e})", file=sys.stderr)
        return []
    out = []
    for item in raiz.iter("item"):
        url = _limpio(item.findtext("link"))
        titulo = _limpio(item.findtext("title"))
        if not url or not titulo:
            continue
        doc = documento or (_documento_sec(url) if agencia == "SEC"
                            else f"{agencia} press release")
        out.append(Comunicado(
            agencia=agencia, titulo=titulo,
            resumen=_limpio(item.findtext("description")), url=url,
            fecha=_fecha_rss(item.findtext("pubDate")), documento=doc))
    return out


def parse_federal_register(datos: dict) -> list[Comunicado]:
    out = []
    for d in datos.get("results") or []:
        agencias = d.get("agencies") or []
        nombre = (agencias[0].get("name") or "") if agencias else ""
        corto = next((v for k, v in _CORTO.items() if k in nombre.lower()),
                     nombre or "Federal Register")
        try:
            f = datetime.fromisoformat(d.get("publication_date", "")).replace(
                tzinfo=timezone.utc)
        except ValueError:
            f = None
        tipo = (d.get("type") or "document").lower()
        out.append(Comunicado(
            agencia=corto, titulo=_limpio(d.get("title")),
            resumen=_limpio(d.get("abstract"))[:400],
            url=d.get("html_url") or "", fecha=f,
            documento=f"Federal Register {tipo}"))
    return [c for c in out if c.titulo and c.url]


def leer_todos(http=None) -> list[Comunicado]:
    """Los comunicados recientes de las tres fuentes. Nunca revienta."""
    import httpx

    cliente = http or httpx.Client(timeout=TIMEOUT,
                                   headers={"User-Agent": USER_AGENT})
    out: list[Comunicado] = []
    for agencia, url, documento in FUENTES_RSS:
        try:
            r = cliente.get(url)
            if r.status_code >= 400:
                print(f"{agencia} ({url}): HTTP {r.status_code}", file=sys.stderr)
                continue
            out += parse_rss(r.text, agencia, documento)
        except Exception as e:
            print(f"{agencia}: {type(e).__name__}: {e}", file=sys.stderr)
    try:
        r = cliente.get(FEDREG_API, params={
            "per_page": 20, "order": "newest",
            "conditions[term]": ("crypto OR stablecoin OR \"digital asset\" "
                                 "OR tokenized OR blockchain"),
        })
        if r.status_code >= 400:
            print(f"Federal Register: HTTP {r.status_code}", file=sys.stderr)
        else:
            out += parse_federal_register(r.json())
    except Exception as e:
        print(f"Federal Register: {type(e).__name__}: {e}", file=sys.stderr)
    # La SEC publica lo mismo en dos feeds a veces: una sola vez por URL.
    return list({c.url: c for c in out}.values())


def a_titular(c: Comunicado):
    """Un comunicado con la forma que usa el resto del pipeline de regulación.

    El texto empieza por la agencia: así el detector de regulación y el de
    sujeto la ven aunque el título no la nombre (los del Federal Register
    casi nunca lo hacen).
    """
    from xcreator.regulacion import Titular

    texto = f"{c.agencia}: {c.titulo}."
    if c.resumen:
        texto += f" {c.resumen}"
    return Titular(autor=c.agencia, texto=texto, url=c.url,
                   post_id=c.clave, horas=c.horas)
