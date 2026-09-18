"""Analizador de engagement de X: qué funciona en TU cuenta, con evidencia.

Fuente: el CSV que exportas de analytics.x.com (Posts -> export). No usa la
API, así que no cuesta nada y no depende de créditos.

La métrica que manda aquí NO es likes. El programa de Ads Revenue Sharing
paga por impresiones de usuarios verificados en la sección de REPLIES de tus
posts: un post que se lee y nadie responde no monetiza. Por eso el ranking
primario es `reply_rate = replies / impressions`, y los likes son contexto.

Honestidad estadística (la razón de ser de este módulo):
- Mediana, no media. Las distribuciones de engagement son long-tail; una
  sola publicación viral mueve la media y te hace creer un patrón falso.
- Todo hallazgo trae n de cada grupo y un p-value (Mann-Whitney U, no
  paramétrico: no asume normalidad, que aquí no se cumple).
- Con muestra chica el hallazgo se marca INSUFICIENTE y no se usa para
  decidir nada. Un lift de +40% con n=4 es ruido, no una lección.
"""

from __future__ import annotations

import csv
import re
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Un post con puñado de impresiones produce ratios absurdos (1 reply / 3
# impresiones = 33%). Se excluyen del análisis de patrones.
MIN_IMPRESSIONS = 200

# Por debajo de esto, un grupo no sostiene una conclusión.
MIN_GROUP = 8

# Umbral de significancia. No es sagrado, pero hay que declararlo.
ALPHA = 0.05


# --- Lectura del CSV ------------------------------------------------------

def _norm(name: str) -> str:
    """'Post text ' -> 'posttext'. El export de X cambia mayúsculas y espacios."""
    return re.sub(r"[^a-z0-9]", "", name.strip().lower())


# Alias por columna: X ha renombrado estas cabeceras varias veces y el export
# nuevo no coincide con el viejo. Se prueba en orden.
_ALIASES: dict[str, tuple[str, ...]] = {
    "post_id": ("postid", "tweetid", "id"),
    "text": ("posttext", "tweettext", "text", "post"),
    "created": ("date", "time", "createdat", "datetime"),
    "impressions": ("impressions", "views", "impression"),
    "likes": ("likes", "like"),
    "replies": ("replies", "reply", "comments"),
    "reposts": ("reposts", "retweets", "repost", "retweet"),
    "bookmarks": ("bookmarks", "bookmark"),
    "engagements": ("engagements", "engagement"),
    "profile_visits": ("profilevisits", "userprofileclicks", "profileclicks"),
    "follows": ("follows", "newfollows", "newfollowers"),
    "url_clicks": ("urlclicks", "linkclicks"),
    "media_views": ("mediaviews",),
}

# Sin esto no hay análisis posible.
_REQUIRED = ("impressions", "replies")


class AnalyticsError(ValueError):
    """El CSV no sirve. Se lanza fuerte: un análisis a medias miente."""


def _resolve_columns(header: list[str]) -> dict[str, str]:
    """Mapea nombre canónico -> nombre real de la columna en el CSV."""
    present = {_norm(h): h for h in header}
    found: dict[str, str] = {}
    for canon, aliases in _ALIASES.items():
        for alias in aliases:
            if alias in present:
                found[canon] = present[alias]
                break
    missing = [c for c in _REQUIRED if c not in found]
    if missing:
        raise AnalyticsError(
            f"El CSV no trae columna(s) {missing}. Cabeceras encontradas: "
            f"{sorted(present.values())}. ¿Es el export de posts de "
            f"analytics.x.com?"
        )
    return found


def _num(raw: str | None) -> float:
    """'1,234' / '12.3%' / '' -> float. Devuelve 0.0 si no es número."""
    if raw is None:
        return 0.0
    s = raw.strip().replace(",", "").replace("%", "").replace("$", "")
    if not s or s in {"-", "—", "N/A", "n/a"}:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


_DATE_FORMATS = (
    "%Y-%m-%d %H:%M %z", "%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%d", "%m/%d/%Y %H:%M", "%m/%d/%Y",
)


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    s = raw.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


@dataclass
class Post:
    """Un post con sus métricas y las features que se van a correlacionar."""

    post_id: str
    text: str
    created: datetime | None
    impressions: float
    likes: float
    replies: float
    reposts: float
    bookmarks: float
    profile_visits: float
    follows: float

    @property
    def reply_rate(self) -> float:
        """La métrica que paga: conversación por impresión."""
        return self.replies / self.impressions if self.impressions else 0.0

    @property
    def engagement_rate(self) -> float:
        total = self.likes + self.replies + self.reposts + self.bookmarks
        return total / self.impressions if self.impressions else 0.0

    @property
    def amplification_rate(self) -> float:
        """Reposts: lo que te lleva a audiencias nuevas."""
        return self.reposts / self.impressions if self.impressions else 0.0

    @property
    def follow_rate(self) -> float:
        return self.follows / self.impressions if self.impressions else 0.0


def load_posts(csv_path: Path) -> list[Post]:
    """Lee el export de X Analytics. Lanza AnalyticsError si el CSV no sirve."""
    if not csv_path.exists():
        raise AnalyticsError(f"No existe {csv_path}")
    with csv_path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise AnalyticsError(f"{csv_path} está vacío o no es un CSV.")
        cols = _resolve_columns(list(reader.fieldnames))
        posts: list[Post] = []
        for row in reader:
            def g(canon: str) -> str | None:
                col = cols.get(canon)
                return row.get(col) if col else None

            posts.append(
                Post(
                    post_id=(g("post_id") or "").strip(),
                    text=(g("text") or "").strip(),
                    created=_parse_date(g("created")),
                    impressions=_num(g("impressions")),
                    likes=_num(g("likes")),
                    replies=_num(g("replies")),
                    reposts=_num(g("reposts")),
                    bookmarks=_num(g("bookmarks")),
                    profile_visits=_num(g("profile_visits")),
                    follows=_num(g("follows")),
                )
            )
    if not posts:
        raise AnalyticsError(f"{csv_path} no tiene filas de datos.")
    return posts


# --- Features del texto ---------------------------------------------------

_URL = re.compile(r"https?://\S+|\bt\.co/\S+")
_CASHTAG = re.compile(r"\$[A-Z]{1,5}\b")
_NUMBER = re.compile(r"\d")
_THREAD = re.compile(r"(^|\s)(1/\d*|🧵|thread\b)", re.IGNORECASE)
# Marcadores de postura: el contenido que provoca replies casi siempre
# contradice algo. Lista deliberadamente corta y en inglés (la cuenta es en
# inglés); ampliarla sin medir sería inventar un patrón.
_STANCE = re.compile(
    r"\b(but|actually|wrong|nobody|everyone|myth|isn't|aren't|won't|"
    r"stop|forget|unpopular|contrarian|truth)\b",
    re.IGNORECASE,
)


def features(post: Post) -> dict[str, bool]:
    """Features booleanas de un post, para el análisis de lift."""
    t = post.text
    lines = [ln for ln in t.splitlines() if ln.strip()]
    return {
        "tiene_link": bool(_URL.search(t)),
        "tiene_pregunta": "?" in t,
        "tiene_cashtag": bool(_CASHTAG.search(t)),
        "tiene_numero": bool(_NUMBER.search(t)),
        "es_hilo": bool(_THREAD.search(t)),
        "postura_fuerte": bool(_STANCE.search(t)),
        "multilinea": len(lines) >= 3,
        "texto_largo": len(t) >= 200,
    }


def _hour_bucket(post: Post) -> str | None:
    if post.created is None:
        return None
    h = post.created.hour
    if 5 <= h < 9:
        return "05-09 (premarket)"
    if 9 <= h < 12:
        return "09-12 (apertura)"
    if 12 <= h < 16:
        return "12-16 (sesión)"
    if 16 <= h < 20:
        return "16-20 (cierre/tarde)"
    return "20-05 (noche)"


# --- Análisis de patrones -------------------------------------------------

@dataclass
class Finding:
    """Un patrón medido. `suficiente=False` significa: no concluyas nada."""

    feature: str
    n_con: int
    n_sin: int
    mediana_con: float
    mediana_sin: float
    lift: float | None          # cambio relativo de la mediana, con vs sin
    p_value: float | None
    suficiente: bool
    metric: str = "reply_rate"
    # Lo pone `_benjamini_hochberg` sobre el conjunto completo de findings:
    # un p-value aislado no basta cuando se corren 8 tests a la vez.
    pasa_correccion: bool = False

    @property
    def significativo(self) -> bool:
        return self.suficiente and self.pasa_correccion

    @property
    def veredicto(self) -> str:
        if not self.suficiente:
            return f"INSUFICIENTE (n={self.n_con}/{self.n_sin}, mínimo {MIN_GROUP})"
        if self.p_value is None:
            return "SIN TEST"
        if not self.pasa_correccion:
            if self.p_value < ALPHA:
                # El caso traicionero: p<0.05 aislado, pero con 8 tests
                # simultáneos un falso positivo así es lo ESPERADO.
                return (f"descartado por comparaciones múltiples "
                        f"(p={self.p_value:.3f}, no sobrevive Benjamini-Hochberg)")
            return f"no distinguible del ruido (p={self.p_value:.2f})"
        direccion = "SUBE" if (self.lift or 0) > 0 else "BAJA"
        return f"{direccion} {abs(self.lift or 0):.0%} (p={self.p_value:.3f})"


def _benjamini_hochberg(findings: list["Finding"], alpha: float = ALPHA) -> None:
    """Marca `pasa_correccion` controlando la tasa de falsos descubrimientos.

    Se prueban ~8 features a la vez. A alpha=0.05, uno de cada veinte tests
    da un "hallazgo" que es puro azar — con 8 tests, encontrar un falso
    positivo es lo esperado, no la excepción. Sin esta corrección el
    generador convertiría ese ruido en una regla de estilo y escribiría
    peor con cada análisis.

    Benjamini-Hochberg en vez de Bonferroni: con muestras chicas Bonferroni
    es tan conservador que borra también los efectos reales.
    """
    testeados = [f for f in findings if f.suficiente and f.p_value is not None]
    m = len(testeados)
    if m == 0:
        return
    ordenados = sorted(testeados, key=lambda f: f.p_value)
    corte = 0  # el mayor k cuyo p_k <= (k/m)*alpha
    for k, f in enumerate(ordenados, start=1):
        if f.p_value <= (k / m) * alpha:
            corte = k
    for k, f in enumerate(ordenados, start=1):
        f.pasa_correccion = k <= corte


def _mannwhitney(a: list[float], b: list[float]) -> float | None:
    """p-value de dos colas. None si scipy falta o la muestra es degenerada."""
    if len(a) < 3 or len(b) < 3:
        return None
    try:
        from scipy.stats import mannwhitneyu
    except ImportError:
        return None
    try:
        return float(mannwhitneyu(a, b, alternative="two-sided").pvalue)
    except ValueError:
        # Ocurre cuando todos los valores son idénticos.
        return None


def analyze_feature(posts: list[Post], name: str, metric: str = "reply_rate") -> Finding:
    """Compara la mediana de `metric` entre los posts con y sin la feature."""
    con = [getattr(p, metric) for p in posts if features(p)[name]]
    sin = [getattr(p, metric) for p in posts if not features(p)[name]]
    med_con = statistics.median(con) if con else 0.0
    med_sin = statistics.median(sin) if sin else 0.0
    lift = (med_con - med_sin) / med_sin if med_sin > 0 else None
    suficiente = len(con) >= MIN_GROUP and len(sin) >= MIN_GROUP
    return Finding(
        feature=name,
        n_con=len(con),
        n_sin=len(sin),
        mediana_con=med_con,
        mediana_sin=med_sin,
        lift=lift,
        p_value=_mannwhitney(con, sin) if suficiente else None,
        suficiente=suficiente,
        metric=metric,
    )


@dataclass
class Report:
    """Resultado del análisis. Lo consume el generador y el reporte en texto."""

    n_posts: int
    n_analizados: int
    periodo: tuple[str, str] | None
    total_impressions: float
    mediana_reply_rate: float
    mediana_engagement_rate: float
    findings: list[Finding] = field(default_factory=list)
    top_posts: list[Post] = field(default_factory=list)
    peores_posts: list[Post] = field(default_factory=list)
    por_horario: dict[str, tuple[int, float]] = field(default_factory=dict)

    @property
    def lecciones(self) -> list[Finding]:
        """Solo lo que sobrevive n mínimo Y significancia. Esto es lo que
        el generador tiene permitido usar como regla de estilo."""
        return [f for f in self.findings if f.significativo]

    @property
    def impresiones_faltantes(self) -> float:
        """Cuánto falta para el umbral de 5M del programa de monetización."""
        return max(0.0, 5_000_000 - self.total_impressions)


def analyze(posts: list[Post], *, metric: str = "reply_rate") -> Report:
    """Mide qué funciona. `metric` es la variable a explicar."""
    usables = [p for p in posts if p.impressions >= MIN_IMPRESSIONS]

    fechas = sorted(p.created for p in posts if p.created is not None)
    periodo = (
        (fechas[0].date().isoformat(), fechas[-1].date().isoformat())
        if fechas else None
    )

    por_horario: dict[str, list[float]] = {}
    for p in usables:
        b = _hour_bucket(p)
        if b:
            por_horario.setdefault(b, []).append(getattr(p, metric))

    findings: list[Finding] = []
    if usables:
        for name in features(usables[0]):
            findings.append(analyze_feature(usables, name, metric))
    _benjamini_hochberg(findings)
    # Primero lo accionable: significativo y de mayor efecto.
    findings.sort(
        key=lambda f: (f.significativo, abs(f.lift or 0)), reverse=True
    )

    ranked = sorted(usables, key=lambda p: getattr(p, metric), reverse=True)
    return Report(
        n_posts=len(posts),
        n_analizados=len(usables),
        periodo=periodo,
        total_impressions=sum(p.impressions for p in posts),
        mediana_reply_rate=(
            statistics.median([p.reply_rate for p in usables]) if usables else 0.0
        ),
        mediana_engagement_rate=(
            statistics.median([p.engagement_rate for p in usables]) if usables else 0.0
        ),
        findings=findings,
        top_posts=ranked[:5],
        peores_posts=ranked[-5:][::-1] if len(ranked) > 5 else [],
        por_horario={
            k: (len(v), statistics.median(v)) for k, v in sorted(por_horario.items())
        },
    )


# --- Export de CUENTA (una fila por día) ----------------------------------
#
# X exporta dos CSV distintos y no lo avisa:
#   - "Post activity": una fila por post, CON el texto -> patrones de contenido.
#   - "Account overview": una fila por día, SIN texto -> salud de la cuenta.
# El segundo no permite decir qué contenido funciona (no hay contenido que
# mirar), pero sí responde la pregunta que importa antes de esa: si el
# problema es lo que publicas o cuánto publicas.

_DIA_FORMATOS = ("%a, %b %d, %Y", "%Y-%m-%d", "%m/%d/%Y", "%b %d, %Y")

# Umbrales del programa de Ads Revenue Sharing.
UMBRAL_IMPRESIONES = 5_000_000
VENTANA_DIAS = 90


@dataclass
class Dia:
    fecha: object
    impressions: float
    likes: float
    replies: float
    reposts: float
    follows: float
    unfollows: float
    engagements: float


def _parse_dia(raw: str):
    s = (raw or "").strip().strip('"')
    for fmt in _DIA_FORMATOS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def es_export_de_cuenta(csv_path: Path) -> bool:
    """True si el CSV es el overview diario y no el de posts."""
    try:
        with csv_path.open(newline="", encoding="utf-8-sig") as fh:
            cabeceras = {_norm(h) for h in (csv.reader(fh).__next__() or [])}
    except (OSError, StopIteration):
        return False
    # La marca distintiva: trae fecha e impresiones pero NO texto de post.
    return "impressions" in cabeceras and not (
        cabeceras & {"posttext", "tweettext", "text", "post"}
    )


def load_account_days(csv_path: Path) -> list[Dia]:
    if not csv_path.exists():
        raise AnalyticsError(f"No existe {csv_path}")
    dias: list[Dia] = []
    with csv_path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        cols = {_norm(h): h for h in (reader.fieldnames or [])}

        def g(row, *alias):
            for a in alias:
                if a in cols:
                    return _num(row.get(cols[a]))
            return 0.0

        for row in reader:
            fecha = _parse_dia(row.get(cols.get("date", "Date"), ""))
            if fecha is None:
                continue
            dias.append(Dia(
                fecha=fecha,
                impressions=g(row, "impressions", "views"),
                likes=g(row, "likes"), replies=g(row, "replies"),
                reposts=g(row, "reposts", "retweets"),
                follows=g(row, "newfollows", "follows"),
                unfollows=g(row, "unfollows"),
                engagements=g(row, "engagements"),
            ))
    if not dias:
        raise AnalyticsError(f"{csv_path} no trae filas con fecha reconocible.")
    return sorted(dias, key=lambda d: d.fecha)


@dataclass
class ReporteCuenta:
    dias: int
    desde: str
    hasta: str
    impresiones_total: float
    impresiones_90d: float
    impresiones_30d: float
    mediana_diaria: float
    dias_en_cero: int
    follows_netos: float
    replies_total: float
    mejor_dia: float

    @property
    def ritmo_diario_90d(self) -> float:
        return self.impresiones_90d / min(self.dias, VENTANA_DIAS)

    @property
    def factor_faltante(self) -> float:
        """Cuántas veces hay que multiplicar el ritmo diario actual.

        Compara RITMOS, no totales. Antes dividía el umbral de 90 días entre
        las impresiones del CSV, y con un export de 7 días decía "123x"
        cuando el ritmo real (5,809/día contra 55,556 necesarias) da 9.6x:
        comparaba una semana contra un trimestre.
        """
        necesario = UMBRAL_IMPRESIONES / VENTANA_DIAS
        return necesario / max(self.ritmo_diario_90d, 1e-9)

    @property
    def es_proyeccion(self) -> bool:
        """True si el CSV cubre menos de la ventana del programa: el factor se
        calcula sobre el ritmo de esos días, no sobre 90 reales."""
        return self.dias < VENTANA_DIAS

    @property
    def dias_sin_publicar_pct(self) -> float:
        return self.dias_en_cero / self.dias if self.dias else 0.0

    @property
    def cuello_de_botella(self) -> str:
        """El diagnóstico honesto: ¿qué hay que arreglar primero?

        Con una cuenta chica casi siempre es volumen, no calidad — y confundir
        los dos lleva a pulir posts que nadie ve.
        """
        if self.dias_sin_publicar_pct > 0.30:
            return ("CONSISTENCIA: uno de cada tres días no genera ni una "
                    "impresión. Antes de optimizar contenido hay que publicar.")
        if self.mediana_diaria < 100:
            return ("ALCANCE: publicas, pero casi nadie lo ve. El problema es "
                    "distribución (replies a cuentas grandes), no redacción.")
        if self.impresiones_90d and self.replies_total / max(self.impresiones_90d, 1) < 0.001:
            return ("CONVERSACIÓN: te leen pero no te responden, y el revenue "
                    "share paga por replies. Ahí sí toca cambiar el contenido.")
        return "Sin cuello evidente: seguir midiendo."


def analyze_account(dias: list[Dia]) -> ReporteCuenta:
    imp = [d.impressions for d in dias]
    ult90 = dias[-VENTANA_DIAS:]
    return ReporteCuenta(
        dias=len(dias),
        desde=str(dias[0].fecha), hasta=str(dias[-1].fecha),
        impresiones_total=sum(imp),
        impresiones_90d=sum(d.impressions for d in ult90),
        impresiones_30d=sum(d.impressions for d in dias[-30:]),
        mediana_diaria=statistics.median(imp) if imp else 0.0,
        dias_en_cero=sum(1 for i in imp if i == 0),
        follows_netos=sum(d.follows - d.unfollows for d in dias),
        replies_total=sum(d.replies for d in dias),
        mejor_dia=max(imp) if imp else 0.0,
    )


# --- Respuestas vs posts propios ------------------------------------------
#
# La pregunta que más decide la estrategia de una cuenta chica: ¿de dónde
# viene tu alcance? Si casi todo llega por respuestas, invertir en pulir
# posts propios es optimizar la parte que nadie ve.

@dataclass
class MixDeAlcance:
    """Cómo se reparte el alcance entre responder y publicar."""

    n_respuestas: int
    n_propios: int
    imp_respuestas: float
    imp_propios: float
    mediana_respuestas: float
    mediana_propios: float
    p_value: float | None

    @property
    def pct_publicaciones(self) -> float:
        total = self.n_respuestas + self.n_propios
        return self.n_respuestas / total if total else 0.0

    @property
    def pct_alcance(self) -> float:
        total = self.imp_respuestas + self.imp_propios
        return self.imp_respuestas / total if total else 0.0

    @property
    def ratio_medianas(self) -> float:
        return self.mediana_respuestas / max(self.mediana_propios, 1.0)

    @property
    def diferencia_es_solida(self) -> bool:
        """Si una respuesta alcanza MÁS que un post propio, con evidencia.

        Es fácil mirar los tres posts de arriba del ranking, ver que son
        respuestas y concluir que responder rinde más. Con muestras chicas
        eso es casi siempre ruido: aquí hace falta el test.
        """
        return (
            self.n_respuestas >= MIN_GROUP
            and self.n_propios >= MIN_GROUP
            and self.p_value is not None
            and self.p_value < ALPHA
        )

    @property
    def veredicto(self) -> str:
        if self.n_propios < MIN_GROUP or self.n_respuestas < MIN_GROUP:
            return (f"muestra insuficiente para comparar "
                    f"(respuestas n={self.n_respuestas}, propios "
                    f"n={self.n_propios}; mínimo {MIN_GROUP} de cada)")
        if self.p_value is None:
            return "sin test"
        if self.p_value >= ALPHA:
            return (f"las medianas no se distinguen del ruido "
                    f"(p={self.p_value:.2f})")
        mas = "MÁS" if self.ratio_medianas > 1 else "MENOS"
        return (f"una respuesta alcanza {mas}: {self.ratio_medianas:.1f}x "
                f"(p={self.p_value:.3f})")


def _es_respuesta(post: Post) -> bool:
    """Un post que empieza con @ es una respuesta en el export de X."""
    return post.text.strip().startswith("@")


def mix_de_alcance(posts: list[Post]) -> MixDeAlcance:
    resp = [p for p in posts if _es_respuesta(p)]
    prop = [p for p in posts if not _es_respuesta(p)]
    ir = [p.impressions for p in resp]
    ip = [p.impressions for p in prop]
    return MixDeAlcance(
        n_respuestas=len(resp), n_propios=len(prop),
        imp_respuestas=sum(ir), imp_propios=sum(ip),
        mediana_respuestas=statistics.median(ir) if ir else 0.0,
        mediana_propios=statistics.median(ip) if ip else 0.0,
        p_value=_mannwhitney(ir, ip),
    )


def efecto_imagen(posts: list[Post], del_sistema: dict[str, tuple[str, bool]],
                  metric: str = "impressions") -> dict[str, Finding]:
    """¿Rinde más un post con gráfica que sin ella? Comparado DENTRO de cada tipo.

    La primera versión comparaba todos los posts con gráfica contra todos los
    sin ella, y dio 84 contra 29 con p<0.001. Era casi todo tema: los de
    acciones llevaban gráfica y los de cripto y macro no la habían tenido
    nunca. Comparar acciones con gráfica contra cripto sin ella mide el tema,
    no la imagen. Solo vale comparar dentro de un mismo tipo.

    `del_sistema` es {post_id: (tipo, llevaba_imagen)}, sacado de la cola:
    solo los posts del sistema, porque son los únicos de los que se SABE si
    llevaban imagen. Devuelve un Finding por tipo; `suficiente` exige
    MIN_GROUP por lado, y sin eso no hay veredicto.
    """
    por_tipo: dict[str, tuple[list[float], list[float]]] = {}
    for p in posts:
        if p.post_id not in del_sistema:
            continue
        tipo, img = del_sistema[p.post_id]
        con, sin = por_tipo.setdefault(tipo, ([], []))
        (con if img else sin).append(getattr(p, metric))

    out: dict[str, Finding] = {}
    for tipo, (con, sin) in sorted(por_tipo.items()):
        med_con = statistics.median(con) if con else 0.0
        med_sin = statistics.median(sin) if sin else 0.0
        suficiente = len(con) >= MIN_GROUP and len(sin) >= MIN_GROUP
        out[tipo] = Finding(
            feature=f"grafica_en_{tipo}",
            n_con=len(con), n_sin=len(sin),
            mediana_con=med_con, mediana_sin=med_sin,
            lift=(med_con - med_sin) / med_sin if med_sin > 0 else None,
            p_value=_mannwhitney(con, sin) if suficiente else None,
            suficiente=suficiente, metric=metric,
        )
    return out
