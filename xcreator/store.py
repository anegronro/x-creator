"""Cola de borradores en disco. Append-only en espíritu: nada se borra.

Un borrador rechazado se marca, no se elimina — igual que las predicciones
del motor. El historial de qué se rechazó y por qué es la señal que después
permite medir si el generador mejoró.

Archivo: <repo>/Contenido/cola.jsonl (una línea por borrador).
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ESTADOS = ("pendiente", "programado", "aprobado", "rechazado", "publicado")

# Minutos entre que un borrador se programa y sale. Es la ventana para
# vetarlo: si nadie hace nada, se publica. Al revés que la aprobación, donde
# el silencio significaba que no salía nunca.
MINUTOS_DE_GRACIA = 45
# Minutos entre dos posts propios. Vivía suelto en la línea del cron, y el
# aviso de Telegram prometía "sale en 45 min" a los tres borradores del día
# sin saber que el publicador saca uno cada hora y media. Una constante en dos
# sitios acaba desincronizada: aquí manda.
# 90 -> 45 (2026-09-21, contenido doble) -> 30 (2026-09-25, seis posts de
# opinión al día). La cola creaba 17 posts propios al día y solo salían 12:
# la ventana estaba llena. Con 30 minutos y la ventana ensanchada caben 25.
ESPACIADO_MINUTOS = 30
# Cada cuántos minutos corre `publicar` en el cron. La proyección redondea a
# este paso. TIENE que coincidir con el `*/15` del crontab.
PASO_CRON_MINUTOS = 15
# Holgura al comparar contra el espaciado. El cron arranca a :00:05 y el post
# anterior quedó marcado a :00:08, así que a los 45 min "exactos" han pasado
# 44.95 y el turno se perdía: el espaciado real era el doble del configurado
# (se vio 16:00 -> 18:00 con el espaciado en 90).
HOLGURA_MINUTOS = 2

# Cuántos rechazos de X aguanta un post antes de bloquearse. Tres deja
# margen a un fallo de red o de token; a partir de ahí el problema es el
# contenido y reintentar solo sirve para que no salga nada detrás.
MAX_FALLOS_PUBLICAR = 3
# La ventana de publicación, en horas UTC. TIENE que coincidir con la línea
# `*/15 11-23,0-3 * * * cron.sh publicar` del crontab. De 7 AM a 11 PM de
# Puerto Rico: la ventana CRUZA la medianoche UTC, y eso es a propósito. Las
# 9 PM de Puerto Rico (1:00 UTC) es la mejor hora medida de la cuenta:
# mediana de 175 impresiones en los replies de esa hora (n=35) contra 60 del
# día entero, del 12 al 25 de septiembre.
VENTANA_UTC = (11, 3)


@dataclass
class Item:
    """Un borrador y todo su rastro de auditoría."""

    id: str
    creado: str
    estado: str
    texto: str
    hilo: list[str] = field(default_factory=list)
    ticker: str = ""
    kind: str = ""
    approach: str = ""
    reply_hook: str = ""
    brief_id: str = ""
    model: str = ""
    numeros_no_justificados: list[str] = field(default_factory=list)
    truncado: bool = False
    idioma_incorrecto: bool = False
    # Ruta del gráfico que acompaña al post, si lo tiene.
    imagen: str = ""
    tickers_faltantes: list[str] = field(default_factory=list)
    # La historia que cuenta ("bear_pegado"...). Vacío en replies y en items
    # anteriores a que existiera: no penalizan nada, que es lo correcto.
    motivo: str = ""
    frases_repetidas: list[str] = field(default_factory=list)
    partidismo: list[str] = field(default_factory=list)
    # El titular de origen de un post propio. NO va en `url_origen`: ese campo
    # es de los replies, y el publicador bloquea todo lo que tenga url_origen
    # de más de 12 horas. Guardarlo ahí habría vuelto impublicable el post.
    fuente: str = ""
    # A quién hay que atribuir el hecho ("@SECGov"). La revisión de
    # publicación exige que el texto final lo nombre.
    atribucion: list[str] = field(default_factory=list)
    # Se llenan al decidir / publicar / cosechar.
    texto_editado: str = ""
    decidido: str = ""
    motivo_rechazo: str = ""
    # Solo para replies: a quién y a qué post se responde.
    responde_a: str = ""
    url_origen: str = ""
    publicado_en: str = ""
    post_id: str = ""
    # Cuántas veces X rechazó este post. Un rechazo por contenido (un cashtag
    # de más, por ejemplo) no se arregla reintentando: el item se queda al
    # frente de la cola y NADA se publica detrás. A los tres intentos se
    # bloquea y la cola sigue.
    fallos_al_publicar: int = 0
    metricas: dict = field(default_factory=dict)

    @property
    def texto_final(self) -> str:
        """Lo que se publicaría: la edición de Angel gana sobre el original."""
        return self.texto_editado or self.texto


def _hoy_utc() -> str:
    """La fecha de HOY en UTC, que es la que usan las marcas de la cola.

    `date.today()` da la fecha LOCAL. En el VPS da igual porque corre en UTC,
    pero en la Mac de Angel (UTC-4) a partir de las 8 de la noche la fecha
    local es la de ayer y los cupos del día se contaban a cero: los replies
    de esta noche no existían para el contador.
    """
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).date().isoformat()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Queue:
    """Cola persistente de borradores."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> list[Item]:
        if not self.path.exists():
            return []
        items: list[Item] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                items.append(Item(**json.loads(line)))
            except (json.JSONDecodeError, TypeError):
                continue  # una línea corrupta no debe tumbar la cola entera
        return items

    def _write(self, items: list[Item]) -> None:
        """Reescritura atómica: tmp + rename, para no perder la cola si algo falla."""
        tmp = self.path.with_suffix(".jsonl.tmp")
        tmp.write_text(
            "\n".join(json.dumps(asdict(i), ensure_ascii=False) for i in items) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, self.path)

    def add(self, draft, *, estado: str = "pendiente") -> Item:
        """Encola un `generate.Draft`.

        Un borrador con problemas nunca nace programado: la publicación
        automática solo puede aplicarse a lo que pasó todas las validaciones.
        """
        if estado == "programado" and not getattr(draft, "valido", True):
            estado = "pendiente"
        item = Item(
            id=uuid.uuid4().hex[:10],
            creado=_now(),
            estado=estado,
            texto=draft.text,
            hilo=list(getattr(draft, "thread", [])),
            ticker=draft.ticker,
            kind=getattr(draft, "kind", "") or ("reply" if getattr(draft, "autor", "") else ""),
            approach=getattr(draft, "approach", ""),
            reply_hook=getattr(draft, "reply_hook", "")
            or getattr(draft, "que_aporta", ""),
            brief_id=draft.brief_id,
            model=draft.model,
            numeros_no_justificados=list(draft.numeros_no_justificados),
            truncado=getattr(draft, "truncado", False),
            idioma_incorrecto=getattr(draft, "idioma_incorrecto", False),
            imagen=str(getattr(draft, "imagen", "") or ""),
            tickers_faltantes=list(getattr(draft, "tickers_faltantes", [])),
            responde_a=getattr(draft, "autor", ""),
            url_origen=getattr(draft, "url", ""),
            motivo=getattr(draft, "motivo", ""),
            frases_repetidas=list(getattr(draft, "frases_repetidas", [])),
            partidismo=list(getattr(draft, "partidismo", [])),
            fuente=getattr(draft, "fuente", ""),
            atribucion=list(getattr(draft, "atribucion", []) or []),
        )
        items = self.load()
        items.append(item)
        self._write(items)
        return item

    def get(self, item_id: str) -> Item | None:
        return next((i for i in self.load() if i.id == item_id), None)

    def pendientes(self) -> list[Item]:
        """Lo que espera tu decisión: sin decidir, o programado y aún vetable.

        Los programados entran aquí a propósito: son los que MÁS urge mandar
        al teléfono, porque si nadie los mira salen solos.
        """
        return [i for i in self.load()
                if i.estado in ("pendiente", "programado")]

    def update(self, item_id: str, **campos) -> Item | None:
        """Cambia campos de un item. Devuelve el item actualizado, o None."""
        items = self.load()
        found = None
        for i in items:
            if i.id == item_id:
                for k, v in campos.items():
                    if hasattr(i, k):
                        setattr(i, k, v)
                found = i
                break
        if found is None:
            return None
        self._write(items)
        return found

    def programar(self, item_id: str) -> Item | None:
        """Lo deja listo para salir solo pasada la ventana de gracia."""
        return self.update(item_id, estado="programado", decidido=_now())

    def listos_para_publicar(self) -> list[Item]:
        """Aprobados, más los programados cuya ventana de veto ya pasó."""
        from datetime import datetime, timezone

        ahora = datetime.now(timezone.utc)
        listos = []
        for i in self.load():
            if i.estado == "aprobado":
                listos.append(i)
            elif i.estado == "programado":
                # La ventana de veto cuenta desde que el borrador EXISTE, no
                # desde que alguien lo tocó: un post que nace programado no
                # tiene `decidido` —eso solo lo escriben aprobar/rechazar— y
                # exigirlo lo dejaba invisible para el publicador para
                # siempre. Publicar solo, que es lo que se pidió, nunca
                # llegaba a ocurrir: salía únicamente lo aprobado a mano.
                desde_txt = i.decidido or i.creado
                if not desde_txt:
                    continue
                try:
                    desde = datetime.fromisoformat(desde_txt)
                except ValueError:
                    continue
                if desde.tzinfo is None:
                    desde = desde.replace(tzinfo=timezone.utc)
                if (ahora - desde).total_seconds() / 60 >= MINUTOS_DE_GRACIA:
                    listos.append(i)
        return listos

    def aprobar(self, item_id: str, texto_editado: str = "") -> Item | None:
        return self.update(
            item_id, estado="aprobado", decidido=_now(),
            texto_editado=texto_editado,
        )

    def rechazar(self, item_id: str, motivo: str = "") -> Item | None:
        return self.update(
            item_id, estado="rechazado", decidido=_now(), motivo_rechazo=motivo,
        )

    def marcar_publicado(self, item_id: str, post_id: str = "") -> Item | None:
        return self.update(
            item_id, estado="publicado", publicado_en=_now(), post_id=post_id,
        )

    def replies_de_hoy(self, autor: str = "") -> int:
        """Cuántos replies se han propuesto hoy (los descartados incluidos).

        Cuenta lo PROPUESTO, no lo publicado: el coste que se quiere limitar
        es el de mirar cada uno, y eso ocurre aunque luego se descarte.

        Con `autor`, solo los dirigidos a esa cuenta — que es como se aplica
        un tope por cuenta sin tocar el global.
        """

        hoy = _hoy_utc()
        quien = autor.lstrip("@").lower()
        # Las respuestas en tus propios posts NO gastan este cupo: tienen el
        # suyo (conversaciones_de_hoy). Son conversaciones que ya empezaron.
        return sum(1 for i in self.load()
                   if i.kind == "reply" and (i.creado or "")[:10] == hoy
                   and i.brief_id != "conversacion"
                   and (not quien
                        or (i.responde_a or "").lstrip("@").lower() == quien))

    def conversaciones_de_hoy(self) -> int:
        """Respuestas propuestas hoy a gente que contestó en tus posts."""

        hoy = _hoy_utc()
        return sum(1 for i in self.load()
                   if i.brief_id == "conversacion"
                   and (i.creado or "")[:10] == hoy)

    def replies_reciclados(self) -> set[str]:
        """Ids de tus replies que ya se reescribieron como post original."""
        return {i.motivo.split(":", 1)[1] for i in self.load()
                if (i.motivo or "").startswith("reply:")}

    def reciclados_de_hoy(self) -> int:

        hoy = _hoy_utc()
        return sum(1 for i in self.load()
                   if (i.motivo or "").startswith("reply:")
                   and (i.creado or "")[:10] == hoy)

    def ya_respondido(self, url_origen: str) -> bool:
        """True si ya hay un borrador de reply para ESE post.

        El cursor `desde_id` evita releer lo ya visto, pero es un solo puntero
        por cuenta: cualquier relectura —`--desde-cero`, un caché perdido, dos
        corridas solapadas— vuelve a proponer el mismo post. Dos respuestas al
        mismo tweet se leen como un bot, y eso es lo que cuesta cuentas.

        Cuentan también los rechazados: si se descartó, no se rehace.
        """
        if not url_origen:
            return False
        clave = url_origen.rstrip("/").split("/")[-1]
        if not clave:
            return False
        # Replies y citas juntos: responder Y citar el mismo post también se
        # lee como spam.
        return any(
            i.kind in ("reply", "cita")
            and (i.url_origen or "").rstrip("/").split("/")[-1] == clave
            for i in self.load()
        )

    def proyeccion_de_salida(self, *, espaciado: int = ESPACIADO_MINUTOS,
                             ahora=None) -> dict[str, "datetime"]:
        """Cuándo saldría de verdad cada post propio programado.

        No es lo mismo "ya se puede publicar" que "se publica": pasada la
        ventana de veto, el post entra en una cola que avanza de uno en uno
        cada `espaciado` minutos y solo dentro de la ventana horaria. Decirle
        a los tres borradores del día que salen en 45 minutos es falso para
        dos de ellos.
        """
        from datetime import datetime, timedelta, timezone

        ahora = ahora or datetime.now(timezone.utc)

        def en_ventana(t):
            ini, fin = VENTANA_UTC
            # La ventana puede cruzar la medianoche (11 a 3 UTC): entonces
            # "dentro" es lo de después del inicio O lo de antes del fin, no
            # lo de en medio. Sin esto, todo lo de la madrugada se empujaba
            # al día siguiente y la mejor hora de la cuenta no se usaba.
            dentro = (ini <= t.hour <= fin if ini <= fin
                      else t.hour >= ini or t.hour <= fin)
            if dentro:
                return t
            if t.hour < ini:
                return t.replace(hour=ini, minute=0, second=0, microsecond=0)
            return (t + timedelta(days=1)).replace(
                hour=ini, minute=0, second=0, microsecond=0)

        def al_siguiente_paso(t):
            """El cron publica cada PASO_CRON_MINUTOS: redondea hacia arriba."""
            extra = (-t.minute) % PASO_CRON_MINUTOS
            t = (t + timedelta(minutes=extra)).replace(second=0, microsecond=0)
            return t

        ultimo = None
        for i in self.load():
            if (i.estado == "publicado" and i.kind not in ("reply", "cita")
                    and i.publicado_en):
                try:
                    f = datetime.fromisoformat(i.publicado_en)
                except ValueError:
                    continue
                if f.tzinfo is None:
                    f = f.replace(tzinfo=timezone.utc)
                if ultimo is None or f > ultimo:
                    ultimo = f
        base = (ultimo + timedelta(minutes=espaciado)) if ultimo else ahora

        proyeccion: dict[str, datetime] = {}
        for i in self.load():
            if (i.estado not in ("programado", "aprobado")
                    or i.kind in ("reply", "cita")):
                continue
            desde_txt = i.decidido or i.creado
            try:
                desde = datetime.fromisoformat(desde_txt)
            except (ValueError, TypeError):
                continue
            if desde.tzinfo is None:
                desde = desde.replace(tzinfo=timezone.utc)
            elegible = desde + timedelta(minutes=MINUTOS_DE_GRACIA)
            t = en_ventana(al_siguiente_paso(max(elegible, base, ahora)))
            proyeccion[i.id] = t
            base = t + timedelta(minutes=espaciado)
        return proyeccion

    def citas_de_hoy(self) -> int:
        """Citas propuestas hoy. No gastan el cupo de replies: son otra cosa."""

        hoy = _hoy_utc()
        return sum(1 for i in self.load()
                   if i.kind == "cita" and (i.creado or "")[:10] == hoy)

    def replies_opinion_de_hoy(self) -> int:
        """Los replies de hoy sin cifras propias.

        Se distinguen por no colgar de NINGÚN brief (`brief_id` vacío). Antes
        se distinguían por no llevar ticker, y eso dejó de valer al entrar
        FRED en los replies: un reply sobre el IPC tampoco lleva ticker, pero
        sí trae datos. Cuatro replies de macro se contaron como opinión, se
        comieron el único hueco del día, y la opinión de verdad (la CFTC en
        WatcherGuru) no pudo salir.
        """

        hoy = _hoy_utc()
        return sum(1 for i in self.load()
                   if i.kind == "reply" and (i.creado or "")[:10] == hoy
                   and not (i.brief_id or "").strip())

    def minutos_desde_ultima_publicacion(self) -> float | None:
        """Minutos desde el último post publicado, o None si no hay ninguno."""
        from datetime import datetime, timezone

        # Solo cuentan los posts PROPIOS: un reply cuelga de otra
        # conversación y no compite con ellos en el timeline, así que no
        # tiene por qué consumir el turno del siguiente post propio.
        marcas = [i.publicado_en for i in self.load()
                  if i.estado == "publicado" and i.publicado_en
                  and i.kind not in ("reply", "cita")]
        if not marcas:
            return None
        try:
            ultima = datetime.fromisoformat(max(marcas))
        except ValueError:
            return None
        if ultima.tzinfo is None:
            ultima = ultima.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ultima).total_seconds() / 60

    def ultimo_uso_por_ticker(self) -> dict[str, str]:
        """{ticker: fecha ISO del borrador más reciente que lo usó}.

        Cuentan los pendientes, aprobados y publicados: si ya hay material de
        un ticker esperando en el teléfono, generar más del mismo es
        repetirse aunque el ángulo cambie. Los rechazados NO cuentan — se
        descartaron precisamente para no publicarlos.
        """
        ultimo: dict[str, str] = {}
        for i in self.load():
            if i.estado == "rechazado" or not i.ticker:
                continue
            fecha = (i.publicado_en or i.decidido or i.creado or "")[:10]
            t = i.ticker.upper()
            if fecha and fecha > ultimo.get(t, ""):
                ultimo[t] = fecha
        return ultimo

    def fuentes_usadas(self) -> set[str]:
        """Los ids de los titulares que ya dieron un post, rechazados incluidos.

        Si se descartó, rehacerlo es gastar dos veces la misma mala idea.
        """
        return {i.fuente.rstrip("/").split("/")[-1]
                for i in self.load() if getattr(i, "fuente", "")}

    def textos_recientes(self, n: int = 15) -> list[str]:
        """Los últimos `n` posts propios que salieron o van a salir.

        Cuentan los programados además de los publicados: tres borradores de
        la misma tanda pueden repetirse entre ellos antes de salir ninguno.
        Quince son unos tres días a cinco posts diarios.
        """
        propios = [i for i in self.load()
                   if i.kind != "reply" and i.estado in ("publicado", "programado",
                                                          "aprobado")]
        propios.sort(key=lambda i: i.publicado_en or i.creado or "")
        return [i.texto_final for i in propios[-n:]]

    def ultimo_uso_por_motivo(self) -> dict[str, str]:
        """{motivo: fecha del borrador más reciente que contó esa historia}.

        Mismo criterio que por ticker: cuentan pendientes, programados y
        publicados, no los rechazados. Si ya hay una historia esperando en el
        teléfono, redactar otra igual es repetirse.
        """
        ultimo: dict[str, str] = {}
        for i in self.load():
            if i.estado == "rechazado" or not getattr(i, "motivo", ""):
                continue
            fecha = (i.publicado_en or i.decidido or i.creado or "")[:10]
            if fecha and fecha > ultimo.get(i.motivo, ""):
                ultimo[i.motivo] = fecha
        return ultimo

    def resumen(self) -> dict[str, int]:
        items = self.load()
        return {e: sum(1 for i in items if i.estado == e) for e in ESTADOS}

    def tasa_aprobacion(self) -> tuple[float | None, int]:
        """Aprobados / decididos, y cuántos se decidieron.

        Es el criterio para pasar de cola manual a publicación automática:
        cuando Angel aprueba 4 de cada 5 sin editar, el generador se ganó
        la autonomía. Antes de eso, no.
        """
        decididos = [i for i in self.load()
                     if i.estado in ("aprobado", "rechazado", "publicado")]
        if not decididos:
            return None, 0
        ok = sum(1 for i in decididos if i.estado != "rechazado")
        return ok / len(decididos), len(decididos)
