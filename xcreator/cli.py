"""CLI de xcreator: analizar engagement, redactar y revisar la cola."""

from __future__ import annotations

from pathlib import Path

import typer

from xcreator.config import load_settings

app = typer.Typer(help="Agente de contenido para X.")


def _queue():
    from xcreator.store import Queue

    s = load_settings()
    return Queue(s.cola_path), s


@app.command("analizar")
def analizar(
    csv: Path = typer.Argument(..., help="Export de posts de analytics.x.com"),
) -> None:
    """Mide qué funciona en TU cuenta: patrones con n, efecto y p-value."""
    from xcreator.analytics import (
        MIN_GROUP, AnalyticsError, analyze, es_export_de_cuenta, load_posts,
    )

    # X exporta dos CSV distintos con el mismo botón y no lo avisa.
    if es_export_de_cuenta(csv):
        _analizar_cuenta(csv)
        return

    try:
        posts = load_posts(csv)
    except AnalyticsError as e:
        typer.secho(f"CSV inservible: {e}", fg="red", err=True)
        raise typer.Exit(1)

    rep = analyze(posts)
    typer.echo(f"\n=== Engagement — {rep.n_posts} posts "
               f"({rep.periodo[0]} a {rep.periodo[1]})" if rep.periodo
               else f"\n=== Engagement — {rep.n_posts} posts")
    typer.echo(f"Analizados (>= {rep.n_analizados and 200} impresiones): {rep.n_analizados}")
    typer.echo(f"Impresiones totales: {rep.total_impressions:,.0f}")
    typer.echo(f"Mediana reply rate:  {rep.mediana_reply_rate:.3%}  "
               f"(la métrica que paga)")
    typer.echo(f"Mediana engagement:  {rep.mediana_engagement_rate:.2%}")

    falta = rep.impresiones_faltantes
    if falta > 0:
        typer.secho(
            f"\nMonetización: faltan {falta:,.0f} impresiones para el umbral "
            f"de 5M en 3 meses (y ojo: solo cuentan las de usuarios Premium, "
            f"que este CSV no separa).",
            fg="yellow",
        )
    else:
        typer.secho("\nMonetización: superas 5M impresiones en el período del CSV.",
                    fg="green")

    typer.echo("\n--- Qué mueve la tasa de replies ---")
    for f in rep.findings:
        marca = "*" if f.significativo else " "
        typer.echo(f" {marca} {f.feature:<16} {f.mediana_con:>7.3%} vs "
                   f"{f.mediana_sin:>7.3%}  {f.veredicto}")

    # ¿Las gráficas suben el alcance? Se compara DENTRO de cada tipo de post:
    # juntarlos todos mide el tema y no la imagen (dio 84 contra 29 con
    # p<0.001, y era que las de acciones tenían gráfica y las de cripto no).
    from xcreator.analytics import efecto_imagen

    q_, _ = _queue()
    del_sistema = {i.post_id: (i.kind, bool(i.imagen)) for i in q_.load()
                   if i.estado == "publicado" and i.post_id and i.kind != "reply"}
    typer.echo("\n--- ¿Las gráficas suben el alcance? (dentro de cada tipo) ---")
    hay_veredicto = False
    for tipo, f in efecto_imagen(posts, del_sistema).items():
        linea = (f"   {tipo:13} con gráfica n={f.n_con:<3} med {f.mediana_con:>5,.0f}"
                 f"  |  sin gráfica n={f.n_sin:<3} med {f.mediana_sin:>5,.0f}")
        if f.suficiente and f.p_value is not None:
            hay_veredicto = True
            typer.echo(linea + f"  p={f.p_value:.3f}")
        else:
            typer.echo(linea + "  sin veredicto")
    if not hay_veredicto:
        typer.secho(f"   Ningún tipo tiene {MIN_GROUP} posts por lado todavía. "
                    f"Mezclar tipos mediría el tema, no la gráfica.", fg="yellow")

    # El alcance es una pregunta distinta a la conversación: un link no cambia
    # tu reply RATE (es un ratio) pero sí puede hundir las impresiones.
    from xcreator.analytics import analyze as _an
    alc = _an(posts, metric="impressions")
    typer.echo("\n--- Qué mueve el alcance (impresiones) ---")
    for f in alc.findings:
        if not f.suficiente:
            continue
        marca = "*" if f.significativo else " "
        typer.echo(f" {marca} {f.feature:<16} {f.mediana_con:>9,.0f} vs "
                   f"{f.mediana_sin:>9,.0f}  {f.veredicto}")

    if rep.por_horario:
        typer.echo("\n--- Por franja horaria (mediana reply rate) ---")
        for franja, (n, med) in rep.por_horario.items():
            typer.echo(f"   {franja:<20} n={n:<4} {med:.3%}")

    from xcreator.analytics import mix_de_alcance

    mix = mix_de_alcance(posts)
    typer.echo("\n--- ¿De dónde viene tu alcance? ---")
    typer.echo(f"   Respuestas a otros: {mix.n_respuestas:>3} publicaciones "
               f"({mix.pct_publicaciones:.0%})  {mix.imp_respuestas:>7,.0f} "
               f"impresiones ({mix.pct_alcance:.0%})  mediana {mix.mediana_respuestas:,.0f}")
    typer.echo(f"   Posts propios:      {mix.n_propios:>3} publicaciones      "
               f"      {mix.imp_propios:>7,.0f} impresiones        "
               f"mediana {mix.mediana_propios:,.0f}")
    typer.echo(f"   -> {mix.veredicto}")

    typer.echo("\n--- Tus 3 posts con más conversación ---")
    for p in rep.top_posts[:3]:
        typer.echo(f"   {p.reply_rate:.2%} | {p.impressions:>8,.0f} imp | "
                   f"{p.text[:80]}")

    lec = rep.lecciones
    typer.echo(f"\nLecciones con evidencia suficiente: {len(lec)}"
               + (f" -> {', '.join(f.feature for f in lec)}" if lec else
                  " (aún no hay base para reglas de estilo medidas)"))


@app.command("redactar")
def redactar(
    ticker: str = typer.Option("", help="Solo este ticker. Vacío = el más reciente."),
    angulo: str = typer.Option(
        "valuacion",
        help="Dimensión del Cerebro: negocio|finanzas|mercado|tecnico|riesgo|valuacion",
    ),
    csv: Path = typer.Option(None, help="Analytics CSV para aplicar estilo medido."),
    n: int = typer.Option(3, help="Variantes a generar. Con --auto: cuántos tickers distintos."),
    encolar: bool = typer.Option(True, help="Guardar en la cola de aprobación."),
    auto: bool = typer.Option(
        False,
        help="Un post por ticker: los `n` temas con más tensión, un ángulo distinto cada uno.",
    ),
    macro: bool = typer.Option(
        False, help="Post de mercado/economía, sin empresa concreta."),
    cripto: bool = typer.Option(
        False, help="Post de activos digitales (BTC, XRP, ETH, SOL)."),
    regulacion: bool = typer.Option(
        False, help="Post propio sobre un titular reciente de regulación de cripto."),
    marcador: bool = typer.Option(
        False, help="Marcador semanal: qué acciones se salieron de su rango."),
    sistema: bool = typer.Option(
        False, help="Bitácora semanal: qué cambió en el agente y qué costó."),
    idea: str = typer.Option(
        "", help="Una nota tuya, en el idioma que sea: sale un post con tu voz."),
) -> None:
    """Redacta variantes desde los datos del motor y las deja en la cola."""
    from xcreator.brief import load_briefs
    from xcreator.cerebro import ANGULOS, disponible
    from xcreator.datos import live_price
    from xcreator.generate import draft_posts

    q, s = _queue()

    if macro:
        _redactar_macro(q, s, n=n, encolar=encolar)
        return

    if cripto:
        _redactar_cripto(q, s, n=n, encolar=encolar)
        return

    if regulacion:
        _redactar_regulacion(q, s, encolar=encolar)
        return

    if marcador:
        _redactar_marcador(q, s, encolar=encolar)
        return

    if sistema:
        _redactar_bitacora(q, s, encolar=encolar)
        return

    if idea:
        from xcreator.idea import brief_idea, ticker_de_la_nota

        brief = brief_idea(idea, ticker_de_la_nota(idea))
        for d in draft_posts(brief, s, n=n, recientes=q.textos_recientes()):
            _mostrar_y_encolar(d, brief, q, s, encolar=False)
            if encolar:
                typer.echo(f"  -> cola id {q.add(d, estado='pendiente').id}")
        return

    lecciones = []
    if csv:
        from xcreator.analytics import AnalyticsError, analyze, load_posts

        try:
            lecciones = analyze(load_posts(csv)).lecciones
        except AnalyticsError as e:
            typer.secho(f"Aviso: no pude usar el CSV ({e}). Sigo sin estilo "
                        f"medido.", fg="yellow", err=True)

    if s.reportes_dir is None:
        typer.secho("Falta WBJ_REPORTES_DIR en API/.env — es de donde salen "
                    "los datos de acciones.", fg="red", err=True)
        raise typer.Exit(1)
    # Con 178 tickers analizados, un límite de 10 dejaba fuera casi todo: si
    # se pide un ticker concreto hay que buscar en todos, no en los primeros.
    briefs = load_briefs(
        s.reportes_dir, lambda t: live_price(t, s.fmp_api_key),
        limit=500 if (auto or ticker) else 10,
    )
    if ticker and not auto:
        briefs = [b for b in briefs if b.ticker.upper() == ticker.upper()]
    if not briefs:
        typer.secho("No hay predicciones en WBJ_REPORTES_DIR. Corre "
                    "`wbj analyze <TICKER>` en el motor de acciones primero.", fg="red", err=True)
        raise typer.Exit(1)

    if angulo not in ANGULOS:
        typer.secho(f"Ángulo desconocido: {angulo}. Opciones: "
                    f"{', '.join(ANGULOS)}", fg="red", err=True)
        raise typer.Exit(1)

    if auto:
        from datetime import date

        from xcreator.temas import ranking

        r = ranking(briefs, ultimo_uso=q.ultimo_uso_por_ticker(),
                    ultimo_motivo=q.ultimo_uso_por_motivo())
        if not r:
            typer.secho("Ningún brief tiene tensión hoy. Publicar por "
                        "publicar es peor que no publicar.", fg="yellow")
            raise typer.Exit(0)
        # Ticker distinto Y, mientras se pueda, historia distinta. Rotar solo
        # tickers dejaba tres empresas contando lo mismo el mismo día.
        from xcreator.temas import elegir_variados

        elegidos = elegir_variados(r, max(1, n))
        for t in elegidos:
            t.brief.motivo = t.clave
        # Cada uno con su propio ángulo: tres empresas miradas con la misma
        # lente vuelven a sonar a plantilla.
        claves = list(ANGULOS)
        base = date.today().timetuple().tm_yday
        planes = [(t.brief, claves[(base + i) % len(claves)], t)
                  for i, t in enumerate(elegidos)]
        typer.echo("Auto: " + ", ".join(
            f"{t.ticker} ({t.puntos:.0f} pts, {ang})"
            for _, ang, t in planes) + "\n")
        _redactar_planes(planes, q, s, lecciones=lecciones, encolar=encolar)
        return

    brief = briefs[0]
    brief.angulo = angulo
    a = ANGULOS[angulo]
    if disponible(s.cerebro_dir):
        typer.echo(f"Cerebro: {a.titulo} — {a.pregunta}")
    else:
        typer.secho("Sin Cerebro (falta WBJ_CEREBRO_DIR): el contenido saldrá "
                    "más genérico.", fg="yellow")
    typer.echo(f"Brief: {brief.brief_id} — {brief.angle}\n")

    drafts = draft_posts(brief, s, lecciones=lecciones, n=n)
    if not drafts:
        typer.secho("Sin borradores: falta la clave del modelo (XAI_API_KEY) o el modelo no respondió.",
                    fg="red", err=True)
        raise typer.Exit(1)

    for d in drafts:
        _mostrar_y_encolar(d, brief, q, s, encolar=encolar)


def _mostrar_y_encolar(d, brief, q, s, *, encolar: bool) -> None:
    """Pinta el borrador con sus avisos y, si toca, lo deja en la cola."""
    estado = "OK" if d.valido else "REVISAR"
    color = "green" if d.valido else "yellow"
    typer.secho(f"[{estado}] {d.approach}", fg=color, bold=True)
    typer.echo(f"  {d.text}  ({len(d.text)} c)")
    for i, t in enumerate(d.thread, 2):
        typer.echo(f"  {i}/ {t}  ({len(t)} c)")
    typer.echo(f"  gancho: {d.reply_hook}")
    if d.numeros_no_justificados:
        typer.secho(f"  CIFRAS SIN FUENTE: {d.numeros_no_justificados}", fg="red")
    if d.exceso_caracteres:
        typer.secho(f"  se pasa por {d.exceso_caracteres} caracteres", fg="red")
    if d.truncado:
        typer.secho("  TEXTO CORTADO a media frase — no publicar así", fg="red")
    if d.idioma_incorrecto:
        typer.secho("  NO ESTÁ EN INGLÉS — el contenido siempre va en inglés",
                    fg="red")
    if d.tickers_faltantes:
        typer.secho(f"  FALTA EL TICKER: {', '.join(d.tickers_faltantes)}",
                    fg="red")
    if getattr(d, "partidismo", None):
        typer.secho(f"  NOMBRA PARTIDOS/POLÍTICOS {d.partidismo}: no sale solo",
                    fg="yellow")
    if getattr(d, "llamada_inventada", None):
        typer.secho(f"  SE ATRIBUYE UNA LLAMADA QUE NO EXISTE: {d.llamada_inventada}",
                    fg="red")
    if getattr(d, "frases_repetidas", None):
        typer.secho(f"  REPITE: {d.frases_repetidas[:3]}", fg="yellow")
    if encolar:
        # Nace PROGRAMADO: sale solo pasada la ventana de veto. Lo que antes
        # hacía falta para publicar (aprobar) ahora hace falta para parar, que
        # es lo que Angel pidió.
        item = q.add(d, estado="programado" if d.valido else "pendiente")
        ruta = _grafico_para(brief, s, item.id)
        if ruta:
            q.update(item.id, imagen=str(ruta))
            typer.echo(f"  gráfico: {ruta.name}")
        typer.echo(f"  -> cola id {item.id}")
    typer.echo("")


def _redactar_planes(planes, q, s, *, lecciones, encolar: bool) -> None:
    """Un post por ticker: redacta cada plan y encola SOLO el mejor de cada uno.

    Se piden dos variantes y se queda una. La segunda no es para publicar
    las dos — es el repuesto de la primera: si sale con una cifra inventada,
    cortada o sin el ticker, publicar igual sería peor que el silencio, y
    quedarse sin post ese día también.
    """
    from xcreator.cerebro import ANGULOS, disponible
    from xcreator.generate import draft_posts

    if not disponible(s.cerebro_dir):
        typer.secho("Sin Cerebro (falta WBJ_CEREBRO_DIR): el contenido saldrá "
                    "más genérico.", fg="yellow")
    hubo = False
    for brief, angulo, tema in planes:
        brief.angulo = angulo
        a = ANGULOS[angulo]
        typer.secho(f"── {tema.ticker} · {a.titulo}", fg="cyan", bold=True)
        if tema.razones:
            typer.echo(f"   {tema.razones[0]}")
        # Se recalcula en cada vuelta: el borrador de la empresa anterior de
        # ESTA tanda ya está en la cola y tampoco hay que copiarlo.
        drafts = draft_posts(brief, s, lecciones=lecciones, n=2,
                             recientes=q.textos_recientes())
        if not drafts:
            typer.secho(f"   sin borradores para {tema.ticker}", fg="red",
                        err=True)
            continue
        hubo = True
        # El primero válido; si ninguno lo es, el primero a secas — así entra
        # como `pendiente` y queda a la vista en vez de desaparecer.
        elegido = next((d for d in drafts if d.valido), drafts[0])
        _mostrar_y_encolar(elegido, brief, q, s, encolar=encolar)
    if not hubo:
        typer.secho("Sin borradores: falta la clave del modelo (XAI_API_KEY) o el modelo no respondió.",
                    fg="red", err=True)
        raise typer.Exit(1)


def _redactar_cripto(q, s, *, n: int, encolar: bool) -> None:
    """Post de activos digitales. Sin modelo de valor: solo hechos de precio."""
    from xcreator.cripto import brief_cripto, mejores_temas
    from xcreator.generate import draft_posts

    temas = mejores_temas(s.fmp_api_key)
    if not temas:
        typer.secho("Ningún activo digital tiene algo que contar hoy. Un "
                    "precio en mitad de su rango no es un post.", fg="yellow")
        return

    # Misma ventana de descanso que los tickers: con cuatro activos, coger
    # siempre la cabeza del ranking sería publicar de Solana toda la semana.
    # Si todos han salido hace poco no se fuerza el silencio — se coge el más
    # antiguo, que es el que menos se repite.
    from datetime import date

    from xcreator.temas import VENTANA_DESCANSO

    ultimo = q.ultimo_uso_por_ticker()
    hoy = date.today()

    def _dias(t):
        f = ultimo.get(t.cfg.ticker.upper())
        if not f:
            return 10_000
        try:
            return (hoy - date.fromisoformat(f)).days
        except ValueError:
            return 10_000

    # Con dos posts de cripto al día, el mismo activo dos veces el mismo día
    # nunca: si solo uno tiene algo que contar, el segundo turno se calla.
    temas = [t for t in temas if _dias(t) > 0]
    if not temas:
        typer.secho("El único activo con algo que contar ya salió hoy.",
                    fg="yellow")
        return
    frescos = [t for t in temas if _dias(t) >= VENTANA_DESCANSO]
    lectura = frescos[0] if frescos else max(temas, key=_dias)
    # El bono a 10 años como contexto: es el único argumento cruzado que casi
    # nadie hace aquí —qué tasa sin riesgo tiene que batir un activo sin flujo
    # de caja— y sale gratis porque FRED ya está cableado.
    tasa10 = None
    try:
        from xcreator.datos import fred_series

        serie = fred_series("DGS10", s.fred_api_key)
        if serie:
            tasa10 = serie[-1]
    except Exception:
        tasa10 = None

    brief = brief_cripto(lectura, tasa10)
    typer.echo(f"Cripto: {lectura.cfg.nombre} ({lectura.cfg.ticker}) — "
               f"${lectura.precio:,.{lectura.cfg.decimales}f}, "
               f"percentil {lectura.percentil:.0%}, "
               f"{lectura.caida_desde_maximo:.0f}% bajo máximos, "
               f"vol {lectura.volatilidad:.0f}% — "
               f"{lectura.tension:.0f} pts de tensión")
    typer.echo(f"Ángulo: {brief.angle}\n")

    # Una sola variante a la cola. Las otras son repuesto, no posts extra:
    # encolarlas todas eran n posts seguidos del mismo activo, el mismo fallo
    # que ya costó tres posts de la misma serie macro en un día.
    drafts = draft_posts(brief, s, n=n, recientes=q.textos_recientes())
    if drafts:
        _mostrar_y_encolar(next((d for d in drafts if d.valido), drafts[0]),
                           brief, q, s, encolar=encolar)


def _redactar_regulacion(q, s, *, encolar: bool) -> None:
    """Post propio de regulación de cripto, de fuente oficial.

    Primero SEC, CFTC y Federal Register: fuente primaria, gratis y
    atribuible con nombre y @. Los titulares de X solo si se activó
    REGULACION_RESPALDO_X; si no, sin comunicado fresco no hay post.
    """
    from xcreator.fuentes_oficiales import (
        HORAS_MAX_OFICIAL, a_titular, leer_todos,
    )
    from xcreator.regulacion import brief_regulacion, elegir_titular

    tocados = q.fuentes_usadas()
    comunicados = leer_todos()
    por_clave = {c.clave: c for c in comunicados}
    oficial = elegir_titular([a_titular(c) for c in comunicados], tocados,
                             horas_max=HORAS_MAX_OFICIAL)
    typer.echo(f"{len(comunicados)} comunicados oficiales leídos "
               f"(SEC, CFTC, Federal Register). Gasto: $0.000")
    if oficial is not None:
        c = por_clave[oficial.post_id]
        typer.echo(f"Fuente oficial ({oficial.horas:.0f}h, {c.documento}, "
                   f"{c.handle or c.agencia}): {c.titulo[:110]}\n")
        brief = brief_regulacion(oficial, s.fmp_api_key, oficial=True,
                                 documento=c.documento, mencion=c.handle)
        brief.fuente = c.url
        _redactar_y_encolar_regulacion(q, s, brief, encolar=encolar)
        return
    if not s.regulacion_respaldo_x:
        typer.secho("Ningún comunicado oficial de cripto fresco y sin usar. "
                    "Sin fuente oficial no hay post (REGULACION_RESPALDO_X "
                    "está apagado).", fg="yellow")
        return
    _regulacion_desde_x(q, s, encolar=encolar)


def _redactar_y_encolar_regulacion(q, s, brief, *, encolar: bool) -> None:
    from xcreator.generate import draft_posts

    # Dos variantes y se queda una: la segunda es repuesto de la primera.
    drafts = draft_posts(brief, s, n=2, recientes=q.textos_recientes())
    if not drafts:
        typer.secho("Sin borradores: falta la clave del modelo (XAI_API_KEY) "
                    "o el modelo no respondió.", fg="red", err=True)
        raise typer.Exit(1)
    _mostrar_y_encolar(next((d for d in drafts if d.valido), drafts[0]),
                       brief, q, s, encolar=encolar)


def _regulacion_desde_x(q, s, *, encolar: bool) -> None:
    """Respaldo: titular de una cuenta de cripto de la watchlist (sin verificar)."""
    from xcreator.publicar import edad_horas
    from xcreator.regulacion import Titular, brief_regulacion, elegir_titular
    from xcreator.watchlist import Watchlist
    from xcreator.xapi import ClienteX, XAPIError

    # Solo las cuentas de cripto: leer las ocho para buscar un titular de
    # regulación costaría $0.40 por pasada a cambio de nada.
    fuentes = [c for c in Watchlist.cargar(s.watchlist_path).activas()
               if "cripto" in (c.tema or "").lower()]
    if not fuentes:
        typer.secho("Ninguna cuenta de la watchlist está marcada como de "
                    "cripto (el tema tiene que decir 'cripto').", fg="yellow")
        return
    try:
        cliente = ClienteX(s.x_bearer_token or "", s.x_cache_path,
                           presupuesto_diario=s.x_presupuesto_pasada)
    except XAPIError as e:
        typer.secho(str(e), fg="red", err=True)
        raise typer.Exit(1)

    candidatos: list[Titular] = []
    for cuenta in fuentes:
        try:
            posts = cliente.posts_recientes(cuenta.handle, limite=15)
        except XAPIError as e:
            typer.secho(f"  {cuenta.handle}: {e}", fg="yellow")
            continue
        candidatos += [Titular(cuenta.handle, p.texto, p.url, p.post_id,
                               edad_horas(p.post_id)) for p in posts]

    # Ni un titular ya usado, ni uno que ya se respondió o se citó: dos posts
    # del perfil sobre la misma noticia se leen como relleno.
    tocados = q.fuentes_usadas() | {
        (i.url_origen or "").rstrip("/").split("/")[-1]
        for i in q.load() if i.kind in ("reply", "cita") and i.url_origen}
    titular = elegir_titular(candidatos, tocados)
    typer.echo(f"{len(candidatos)} posts leídos de "
               f"{', '.join(c.handle for c in fuentes)}. "
               f"Gasto: ${cliente.gastado:.3f}")
    if titular is None:
        typer.secho("Ningún titular de regulación fresco y sin usar. Mejor "
                    "callar que inventarse la noticia.", fg="yellow")
        return

    typer.echo(f"Titular ({titular.horas:.1f}h, {titular.autor}): "
               f"{titular.texto[:110]}\n")
    brief = brief_regulacion(titular, s.fmp_api_key)
    brief.fuente = titular.url
    _redactar_y_encolar_regulacion(q, s, brief, encolar=encolar)


def _redactar_bitacora(q, s, *, encolar: bool) -> None:
    """Construir en público: qué cambió esta semana en el agente y qué costó."""
    from xcreator.bitacora import (
        brief_bitacora, gasto_semanal, leer_cambios, publicados_semana,
    )
    from xcreator.generate import draft_posts

    cambios = leer_cambios(s.root / "CAMBIOS.txt")
    llamadas, usd = gasto_semanal(s.uso_llm_path)
    propios, replies = publicados_semana(q.load())
    typer.echo(f"Semana: {len(cambios)} cambios, {propios} posts propios, "
               f"{replies} replies, ${usd:.2f} de modelo en {llamadas} llamadas")
    brief = brief_bitacora(cambios, llamadas, usd, propios, replies)
    if brief is None:
        typer.secho("Nada que contar esta semana (sin cambios o sin posts). "
                    "Una bitácora vacía es relleno.", fg="yellow")
        return
    typer.echo(f"Ángulo: {brief.angle}\n")
    drafts = draft_posts(brief, s, n=2, recientes=q.textos_recientes())
    if not drafts:
        typer.secho("Sin borradores: falta la clave del modelo (XAI_API_KEY) "
                    "o el modelo no respondió.", fg="red", err=True)
        raise typer.Exit(1)
    _mostrar_y_encolar(next((d for d in drafts if d.valido), drafts[0]),
                       brief, q, s, encolar=encolar)


def _redactar_marcador(q, s, *, encolar: bool) -> None:
    """El marcador semanal: una imagen para compartir y un post que la abre."""
    from xcreator.brief import load_briefs
    from xcreator.datos import live_price
    from xcreator.generate import draft_posts
    from xcreator.marcador import brief_marcador, extremos, filas

    briefs = load_briefs(s.reportes_dir, lambda t: live_price(t, s.fmp_api_key),
                         limit=500)
    brief = brief_marcador(briefs)
    if brief is None:
        typer.secho("Ninguna acción está fuera de su rango: un marcador vacío "
                    "no se publica.", fg="yellow")
        return
    todas = filas(briefs)
    abajo, arriba = extremos(todas)
    # La gráfica necesita las filas, que no caben en `facts` sin perder el
    # orden: viajan pegadas al brief solo durante esta corrida.
    brief._marcador = (abajo, arriba, len(todas))
    typer.echo(f"Marcador: {len(todas)} con precio y rango, "
               f"{len(abajo)} por debajo y {len(arriba)} por encima.\n")
    drafts = draft_posts(brief, s, n=2, recientes=q.textos_recientes())
    if not drafts:
        typer.secho("Sin borradores: falta la clave del modelo (XAI_API_KEY) o el modelo no respondió.",
                    fg="red", err=True)
        raise typer.Exit(1)
    _mostrar_y_encolar(next((d for d in drafts if d.valido), drafts[0]),
                       brief, q, s, encolar=encolar)


def _analizar_cuenta(csv: Path) -> None:
    """Salud de la cuenta desde el overview diario (sin texto de posts)."""
    from xcreator.analytics import (
        UMBRAL_IMPRESIONES, VENTANA_DIAS, AnalyticsError, analyze_account,
        load_account_days,
    )

    try:
        r = analyze_account(load_account_days(csv))
    except AnalyticsError as e:
        typer.secho(f"CSV inservible: {e}", fg="red", err=True)
        raise typer.Exit(1)

    typer.secho("Este es el export de CUENTA (una fila por día), no el de "
                "posts.", fg="yellow")
    typer.echo("Sirve para medir la salud de la cuenta; para saber QUÉ "
               "contenido funciona hace falta el export de Posts, que trae "
               "el texto.\n")

    typer.echo(f"=== {r.dias} días ({r.desde} a {r.hasta}) ===")
    typer.echo(f"Impresiones totales:   {r.impresiones_total:>12,.0f}")
    typer.echo(f"  últimos 90 días:     {r.impresiones_90d:>12,.0f}")
    typer.echo(f"  últimos 30 días:     {r.impresiones_30d:>12,.0f}")
    typer.echo(f"Mediana diaria:        {r.mediana_diaria:>12,.0f}")
    typer.echo(f"Mejor día del período: {r.mejor_dia:>12,.0f}")
    typer.echo(f"Días sin una impresión:{r.dias_en_cero:>12,.0f}  "
               f"({r.dias_sin_publicar_pct:.0%})")
    typer.echo(f"Seguidores netos:      {r.follows_netos:>+12,.0f}")
    typer.echo(f"Replies recibidos:     {r.replies_total:>12,.0f}")

    typer.secho(f"\n=== Programa de monetización ===", bold=True)
    typer.echo(f"Requisito: {UMBRAL_IMPRESIONES:,} impresiones en "
               f"{VENTANA_DIAS} días (solo de usuarios Premium).")
    typer.echo(f"Tienes:    {r.impresiones_90d:,.0f}")
    if r.es_proyeccion:
        typer.echo(f"(el CSV cubre {r.dias} días: el ritmo sale de esos días, "
                   f"no de 90 reales)")
    typer.secho(f"Falta multiplicar el ritmo por {r.factor_faltante:,.1f}x "
                f"({r.ritmo_diario_90d:,.0f} impresiones/día hoy vs "
                f"{UMBRAL_IMPRESIONES/VENTANA_DIAS:,.0f} necesarias).",
                fg="red" if r.factor_faltante > 10 else "yellow")

    typer.secho(f"\nCuello de botella -> {r.cuello_de_botella}", bold=True)


@app.command("angulos")
def angulos() -> None:
    """Los ángulos de contenido que da el Cerebro (uno por dimensión)."""
    from xcreator.cerebro import ANGULOS, disponible, metodologia

    _, s = _queue()
    if not disponible(s.cerebro_dir):
        typer.secho("Cerebro no encontrado. Configura WBJ_CEREBRO_DIR en "
                    "API/.env.", fg="red", err=True)
        raise typer.Exit(1)
    for a in ANGULOS.values():
        chars = len(metodologia(s.cerebro_dir, a.clave))
        typer.echo(f"  {a.clave:<10} {a.titulo:<22} {chars:>6,} c de metodología")
        typer.echo(f"             {a.pregunta}")


@app.command("responder")
def responder(
    autor: str = typer.Option(..., help="Handle del autor, ej. @unusual_whales"),
    texto: str = typer.Option("", help="Texto del post. Vacío = se lee de stdin."),
    url: str = typer.Option("", help="Link al post (para abrirlo al aprobar)."),
    encolar: bool = typer.Option(True, help="Guardar en la cola de aprobación."),
) -> None:
    """Propone un reply a un post ajeno, o dice por qué no hay nada que aportar.

    Aquí está la palanca de crecimiento de una cuenta chica: en FinTwit te
    descubren en las respuestas a cuentas grandes, no en tus propios posts.
    """
    import sys

    from xcreator.brief import load_briefs
    from xcreator.datos import live_price
    from xcreator.datos import load_company_names
    from xcreator.replies import Mencion, draft_reply, encontrar_relevancia

    q, s = _queue()
    if not texto:
        texto = sys.stdin.read()
    mencion = Mencion(autor=autor, texto=texto, url=url)

    # El cupo AVISA pero no bloquea aquí. Existe para protegerte de una
    # avalancha que genera el vigilante solo; un reply que pides tú, con su
    # URL en la mano, no es eso. Y este comando no lee X: el texto lo traes,
    # así que tampoco gasta lecturas. Se sigue contando para el día.
    ya = q.replies_de_hoy()
    if ya >= s.replies_por_dia:
        typer.secho(f"Aviso: ya van {ya}/{s.replies_por_dia} replies hoy. "
                    f"Este lo pediste tú, así que sigue.", fg="yellow")

    briefs = load_briefs(s.reportes_dir, lambda t: live_price(t, s.fmp_api_key),
                         limit=500)
    nombres = load_company_names(s.reportes_dir)

    def _cripto(t):
        from xcreator.cripto import brief_para

        return brief_para(t, s.fmp_api_key)

    def _macro(t):
        from xcreator.macro import brief_para_post

        return brief_para_post(t, s.fred_api_key)

    rel = encontrar_relevancia(mencion, briefs, nombres,
                               cripto=_cripto, macro=_macro)

    typer.echo(f"Post de {autor} — tickers detectados: "
               f"{', '.join(sorted(mencion.tickers(nombres))) or 'ninguno'}")
    if not rel.aporta:
        typer.secho(f"\nNO RESPONDER: {rel.motivo}", fg="yellow", bold=True)
        typer.echo("Abstenerse es el comportamiento correcto: un reply sin "
                   "dato nuevo es spam y X lo penaliza.")
        return

    typer.echo(f"Relevante: {rel.motivo}\n")
    d = draft_reply(mencion, rel, s)

    if d.declinado:
        typer.secho(f"NO RESPONDER: {d.motivo}", fg="yellow", bold=True)
        if d.que_aporta:
            typer.echo(f"  ({d.que_aporta})")
        return

    estado = "OK" if d.valido else "REVISAR"
    typer.secho(f"[{estado}] responde a {autor}  ({len(d.texto)} c)",
                fg="green" if d.valido else "yellow", bold=True)
    typer.echo(f"  {d.texto}")
    typer.echo(f"  aporta: {d.que_aporta}")
    if d.numeros_no_justificados:
        typer.secho(f"  CIFRAS SIN FUENTE: {d.numeros_no_justificados}", fg="red")
    if d.exceso_caracteres:
        typer.secho(f"  se pasa por {d.exceso_caracteres} caracteres", fg="red")
    if d.truncado:
        typer.secho("  TEXTO CORTADO — no publicar así", fg="red")
    if d.tickers_faltantes:
        typer.secho(f"  FALTA EL TICKER: {', '.join(d.tickers_faltantes)}",
                    fg="red")
    if getattr(d, "partidismo", None):
        typer.secho(f"  NOMBRA PARTIDOS/POLÍTICOS {d.partidismo}: no sale solo",
                    fg="yellow")
    if getattr(d, "llamada_inventada", None):
        typer.secho(f"  SE ATRIBUYE UNA LLAMADA QUE NO EXISTE: {d.llamada_inventada}",
                    fg="red")
    if getattr(d, "frases_repetidas", None):
        typer.secho(f"  REPITE: {d.frases_repetidas[:3]}", fg="yellow")
    if encolar:
        item = q.add(d)
        typer.echo(f"  -> cola id {item.id}")


@app.command("citar")
def citar(
    limite: int = typer.Option(10, help="Posts a leer por cuenta."),
    encolar: bool = typer.Option(True, help="Guardar la cita en la cola."),
) -> None:
    """Redacta UNA cita del titular con más conversación del día.

    X no deja publicar citas por API, así que llega a Telegram para pegarla a
    mano, igual que los replies.
    """
    from xcreator.brief import con_precio, load_briefs
    from xcreator.citas import CITAS_POR_DIA, elegir_para_citar
    from xcreator.datos import live_price, load_company_names
    from xcreator.replies import Mencion, draft_reply, encontrar_relevancia
    from xcreator.watchlist import Watchlist
    from xcreator.xapi import ClienteX, XAPIError

    q, s = _queue()
    if q.citas_de_hoy() >= CITAS_POR_DIA:
        typer.echo(f"Ya hay {q.citas_de_hoy()} cita hoy (tope {CITAS_POR_DIA}).")
        return
    cuentas = {c.normalizado(): c for c in
               Watchlist.cargar(s.watchlist_path).activas()}
    try:
        cliente = ClienteX(s.x_bearer_token or "", s.x_cache_path,
                           presupuesto_diario=s.x_presupuesto_pasada)
    except XAPIError as e:
        typer.secho(str(e), fg="red", err=True)
        raise typer.Exit(1)

    posts = []
    for c in cuentas.values():
        try:
            posts += cliente.posts_recientes(c.handle, limite=limite)
        except XAPIError as e:
            typer.secho(f"  {c.handle}: {e}", fg="yellow")

    briefs = load_briefs(s.reportes_dir, None, limit=500)
    nombres = load_company_names(s.reportes_dir)

    def _cripto(t):
        from xcreator.cripto import brief_para

        return brief_para(t, s.fmp_api_key)

    def _macro(t):
        from xcreator.macro import brief_para_post

        return brief_para_post(t, s.fred_api_key)

    def relevancia_de(p):
        return encontrar_relevancia(
            Mencion(autor=p.autor, texto=p.texto, url=p.url, post_id=p.post_id),
            briefs, nombres, cripto=_cripto, macro=_macro)

    # Nunca citar lo que ya se respondió o se citó: tocar dos veces el mismo
    # post se lee como spam.
    excluir = {(i.url_origen or "").rstrip("/").split("/")[-1]
               for i in q.load() if i.kind in ("reply", "cita") and i.url_origen}
    # Y tampoco el titular que ya usó un post propio de regulación: saldrían
    # dos posts en el perfil sobre la misma noticia.
    excluir |= q.fuentes_usadas()
    post, rel = elegir_para_citar(posts, relevancia_de, excluir)
    typer.echo(f"{len(posts)} posts leídos de {len(cuentas)} cuentas. "
               f"Gasto: ${cliente.gastado:.3f}")
    if post is None:
        typer.secho("Nada que citar con algo que aportar. Mejor callar.",
                    fg="yellow")
        return

    typer.echo(f"Elegido ({post.conversacion} de conversación, {post.autor}): "
               f"{post.texto[:100]}")
    if rel.brief is not None:
        cuenta = cuentas.get(post.autor.lstrip("@").lower())
        rel.brief = con_precio(s.reportes_dir, rel.brief,
                               lambda t: live_price(t, s.fmp_api_key))
        if cuenta:
            rel.brief.angulo = cuenta.angulo
    m = Mencion(autor=post.autor, texto=post.texto, url=post.url,
                post_id=post.post_id)
    d = draft_reply(m, rel, s, modo="cita")
    if d.declinado:
        typer.secho(f"Declinado: {d.motivo}", fg="yellow")
        return
    estado = "OK" if d.valido else "REVISAR"
    typer.secho(f"\n[{estado}] cita a {post.autor}", fg="green" if d.valido else "yellow")
    typer.echo(f"  {d.texto}")
    if not encolar:
        return
    q.add(d)
    try:
        from xcreator.telegram import bot_desde, enviar_pendientes

        enviar_pendientes(q, bot_desde(s), limite=3)
    except Exception as e:  # noqa: BLE001
        typer.secho(f"  (no se pudo avisar por Telegram: {e})", fg="yellow")


@app.command("watchlist")
def watchlist(
    add: str = typer.Option("", help="Añadir un handle."),
    quitar: str = typer.Option("", help="Desactivar un handle (no se borra)."),
) -> None:
    """Las cuentas grandes que vigilamos para responderles."""
    from xcreator.watchlist import Watchlist

    _, s = _queue()
    wl = Watchlist.cargar(s.watchlist_path)
    if add:
        c = wl.add(add)
        typer.secho(f"Añadida {c.handle}", fg="green")
    if quitar:
        typer.secho(f"{'Desactivada ' + quitar if wl.desactivar(quitar) else 'No estaba: ' + quitar}",
                    fg="yellow")
    for c in wl.cuentas:
        marca = " " if c.activa else "x"
        typer.echo(f" [{marca}] {c.handle:<20} {c.angulo:<10} {c.tema}")
        if c.notas:
            typer.echo(f"                          {c.notas}")


@app.command("vigilar")
def vigilar(
    limite: int = typer.Option(5, help="Posts a leer por cuenta (mínimo 5)."),
    encolar: bool = typer.Option(True, help="Guardar los replies en la cola."),
    detalle: bool = typer.Option(False, help="Mostrar por qué se descarta cada post."),
    desde_cero: bool = typer.Option(False, help="Ignorar lo ya leído (vuelve a pagar)."),
    cupo: int = typer.Option(0, help="Tope de replies SOLO para esta corrida (0 = el de la config)."),
    cupo_opinion: int = typer.Option(0, help="Tope de opinión solo para esta corrida."),
) -> None:
    """Lee las cuentas vigiladas y propone replies donde tengamos datos.

    El filtro determinista corre ANTES del modelo: de decenas de posts leídos,
    solo los que mencionan un ticker que cubrimos llegan a generar texto. Por
    eso vigilar mucho sale barato y responder sale caro — que es el orden
    correcto.
    """
    from xcreator.brief import load_briefs
    from xcreator.datos import live_price
    from xcreator.datos import load_company_names
    from xcreator.replies import Mencion, draft_reply, encontrar_relevancia
    from xcreator.watchlist import Watchlist
    from xcreator.xapi import ClienteX, XAPIError, costo_estimado

    q, s = _queue()
    wl = Watchlist.cargar(s.watchlist_path)
    activas = wl.activas()
    if not activas:
        typer.secho("Watchlist vacía. `xc watchlist --add @cuenta`", fg="red",
                    err=True)
        raise typer.Exit(1)

    est = costo_estimado(len(activas), limite)
    typer.echo(f"{len(activas)} cuentas x {limite} posts — costo estimado "
               f"${est:.3f} (tope ${s.x_presupuesto_pasada:.2f})\n")

    try:
        cliente = ClienteX(s.x_bearer_token or "", s.x_cache_path,
                           presupuesto_diario=s.x_presupuesto_pasada)
    except XAPIError as e:
        typer.secho(str(e), fg="red", err=True)
        typer.echo("\nMientras tanto puedes pegar un post a mano:\n"
                   "  xc responder --autor @unusual_whales --texto \"...\"")
        raise typer.Exit(1)

    import json as _json

    try:
        ultimos = {} if desde_cero else _json.loads(s.x_estado_path.read_text())
    except (OSError, ValueError):
        ultimos = {}

    # El cupo diario es de TIEMPO de Angel, no de dinero: cada reply cuesta
    # tres toques manuales porque X no deja publicarlos por API.
    # Un tope de la corrida NO se guarda en ninguna parte: subirlo "por hoy"
    # tocando la config se lo queda el cron de mañana y nadie se acuerda.
    tope = cupo if cupo > 0 else s.replies_por_dia
    tope_opinion = cupo_opinion if cupo_opinion > 0 else s.replies_opinion_por_dia
    if cupo or cupo_opinion:
        typer.secho(f"Topes SOLO para esta corrida: {tope} replies, "
                    f"{tope_opinion} de opinión.", fg="cyan")
    ya = q.replies_de_hoy()
    if ya >= tope:
        # Se corta ANTES de leer: el mensaje decía que se seguía leyendo y no
        # era verdad. Cortar aquí es justamente lo que hace que el cupo ahorre
        # dinero además de tiempo.
        typer.echo(f"Cupo de replies agotado ({ya}/{tope} hoy). No se lee "
                   f"ninguna cuenta en esta pasada: gasto $0.000.")
        return

    briefs = load_briefs(s.reportes_dir, None,  # sin precio: emparejar no lo necesita
                         limit=500)
    nombres = load_company_names(s.reportes_dir)
    typer.echo(f"{len(briefs)} briefs y {len(nombres)} nombres de empresa "
               f"para emparejar.\n")
    leidos = relevantes = encolados = 0

    # Los briefs de cripto se piden solo si un post nombra un activo: una
    # cuenta de titulares menciona Bitcoin cada dos posts, pero la mayoría de
    # las pasadas no lo menciona nadie y pedir precios entonces es tirar
    # llamadas.
    cache_cripto: dict[str, object] = {}

    def brief_cripto_de(ticker: str):
        from xcreator.cripto import brief_para

        t = ticker.upper()
        if t not in cache_cripto:
            cache_cripto[t] = brief_para(t, s.fmp_api_key)
        return cache_cripto[t]

    cache_macro: dict[str, object] = {}

    def brief_macro_de(texto: str):
        from xcreator.macro import brief_para_post, serie_para_post

        cfg = serie_para_post(texto)
        if cfg is None:
            return None
        if cfg.serie not in cache_macro:
            cache_macro[cfg.serie] = brief_para_post(texto, s.fred_api_key)
        return cache_macro[cfg.serie]

    # Los posts de opinión se apartan aquí y se resuelven al final.
    candidatos_opinion: list = []

    def _redactar_y_encolar(cuenta, m, rel) -> int:
        """Redacta el reply y lo deja en la cola. Devuelve 1 si se encoló."""
        # El precio de hoy se pide AQUÍ, solo para la empresa elegida, y no
        # al cargar los 153 briefs en cada pasada.
        if rel.brief is not None:
            from xcreator.brief import con_precio

            angulo = rel.brief.angulo
            rel.brief = con_precio(s.reportes_dir, rel.brief,
                                   lambda t: live_price(t, s.fmp_api_key))
            rel.brief.angulo = angulo
        d = draft_reply(m, rel, s)
        if d.declinado:
            typer.echo(f"  {cuenta.handle}: declinado — {d.motivo}")
            return 0
        estado = "OK" if d.valido else "REVISAR"
        sobre = f"${rel.ticker}" if rel.ticker else rel.tema
        typer.secho(f"  [{estado}] {cuenta.handle} sobre {sobre}",
                    fg="green" if d.valido else "yellow")
        typer.echo(f"     {d.texto}")
        if not encolar:
            return 0
        # Los replies NO se programan: no se pueden publicar por API, así que
        # programarlos sería prometer algo que no ocurre.
        q.add(d)
        # Y se mandan YA, sin esperar al ciclo de Telegram: un reply pierde
        # alcance por minutos, no por horas. Esperar al siguiente cron es
        # regalar la ventana.
        try:
            from xcreator.telegram import bot_desde, enviar_pendientes

            enviar_pendientes(q, bot_desde(s), limite=3)
        except Exception as e:  # noqa: BLE001
            typer.secho(f"     (no se pudo avisar por Telegram: {e})",
                        fg="yellow")
        return 1

    for cuenta in activas:
        # Tope propio de la cuenta, antes de gastar una sola lectura de X.
        if cuenta.tope_diario and q.replies_de_hoy(cuenta.handle) >= cuenta.tope_diario:
            typer.echo(f"  {cuenta.handle}: ya lleva su tope de "
                       f"{cuenta.tope_diario} hoy.")
            continue
        try:
            posts = cliente.posts_recientes(
                cuenta.handle, limite=limite,
                desde_id=ultimos.get(cuenta.normalizado()))
        except XAPIError as e:
            typer.secho(f"  {cuenta.handle}: {e}", fg="yellow")
            continue
        leidos += len(posts)
        if posts:
            ultimos[cuenta.normalizado()] = posts[0].post_id

        for p in posts:
            # El cupo se recuenta contra la cola en cada vuelta, no solo al
            # arrancar. Leerlo una vez bastaba mientras hubiera un único
            # proceso; con dos corridas solapadas, cada una se gastaba el
            # cupo entero y el tope de 3 acabó dejando pasar 19. El cerrojo
            # de cron.sh evita el solape, y esto lo hace exacto igual.
            if q.replies_de_hoy() >= tope:
                break
            if (cuenta.tope_diario
                    and q.replies_de_hoy(cuenta.handle) >= cuenta.tope_diario):
                break
            # Solo conversaciones vivas: a las pocas horas responder es
            # hablarle a un hilo que ya nadie mira.
            from xcreator.publicar import edad_horas

            horas = edad_horas(p.post_id)
            if horas is not None and horas > s.horas_frescura_reply:
                continue
            # Nunca dos borradores para el mismo post: se comprueba antes de
            # gastar una llamada al modelo.
            if q.ya_respondido(p.url or p.post_id):
                if detalle:
                    typer.echo(f"  == {cuenta.handle}: ya hay un reply para "
                               f"ese post")
                continue
            m = Mencion(autor=cuenta.handle, texto=p.texto, url=p.url,
                        post_id=p.post_id)
            rel = encontrar_relevancia(m, briefs, nombres,
                                       cripto=brief_cripto_de,
                                       macro=brief_macro_de)
            if rel.solo_opinion:
                # La opinión se aparca para una SEGUNDA vuelta. Procesarla
                # aquí la hacía competir por el cupo con los replies de
                # datos y ganaba por llegar antes: un falso positivo de
                # zerohedge se llevó el único hueco del día y la cuenta para
                # la que se construyó ni se miró.
                candidatos_opinion.append((cuenta, m, horas))
                if detalle:
                    typer.echo(f"  ~~ {cuenta.handle}: {rel.motivo}")
                continue
            if not rel.aporta:
                if detalle:
                    typer.echo(f"  -- {cuenta.handle}: {rel.motivo}")
                    typer.echo(f"     \"{p.texto[:100]}\"")
                continue
            relevantes += 1
            if rel.brief:
                rel.brief.angulo = cuenta.angulo  # el ángulo lo fija la cuenta
            encolados += _redactar_y_encolar(cuenta, m, rel)

    # --- segunda vuelta: la opinión, con lo que haya sobrado del cupo ------
    # Se ordenan por frescura y no por el orden de la watchlist: un reply a
    # una conversación recién abierta llega a más gente, y así ninguna cuenta
    # se queda fuera solo por estar al final de la lista.
    for cuenta, m, horas in sorted(candidatos_opinion,
                                   key=lambda c: c[2] if c[2] is not None else 99):
        if q.replies_de_hoy() >= tope:
            break
        if q.replies_opinion_de_hoy() >= tope_opinion:
            if detalle:
                typer.echo(f"  ~~ cupo de opinión agotado ({tope_opinion})")
            break
        if (cuenta.tope_diario
                and q.replies_de_hoy(cuenta.handle) >= cuenta.tope_diario):
            continue
        rel = encontrar_relevancia(m, briefs, nombres,
                                   cripto=brief_cripto_de, macro=brief_macro_de)
        if not rel.solo_opinion:
            continue
        relevantes += 1
        encolados += _redactar_y_encolar(cuenta, m, rel)

    s.x_estado_path.parent.mkdir(parents=True, exist_ok=True)
    s.x_estado_path.write_text(_json.dumps(ultimos, indent=2))
    typer.echo(f"\n{leidos} posts leídos -> {relevantes} con datos nuestros "
               f"-> {encolados} propuestos. Gasto: ${cliente.gastado:.3f}. "
               f"Cupo de hoy: {ya + encolados}/{tope}")


@app.command("temas")
def temas(
    top: int = typer.Option(15, help="Cuántos mostrar."),
    detalle: bool = typer.Option(False, help="Mostrar las razones."),
) -> None:
    """Qué tickers tienen HOY una historia que contar, y por qué.

    Tener muchos briefs no es tener muchos temas: sin tensión no hay
    conversación, y sin conversación no hay monetización.
    """
    from xcreator.brief import load_briefs
    from xcreator.datos import live_price
    from xcreator.temas import ranking

    q, s = _queue()
    briefs = load_briefs(s.reportes_dir, lambda t: live_price(t, s.fmp_api_key),
                         limit=500)
    r = ranking(briefs, ultimo_uso=q.ultimo_uso_por_ticker())
    typer.echo(f"{len(briefs)} briefs disponibles -> {len(r)} con historia hoy\n")
    for t in r[:top]:
        typer.secho(f"  {t.puntos:>4.0f}  {t.ticker:<6}", fg="green", nl=False)
        typer.echo(f"  {t.razones[0] if t.razones else ''}")
        if detalle:
            for razon in t.razones[1:]:
                typer.echo(f"              {razon}")
    if not r:
        typer.secho("Ningún brief tiene tensión hoy. Publicar por publicar "
                    "es peor que no publicar.", fg="yellow")


@app.command("x-auth")
def x_auth() -> None:
    """Autoriza la app para publicar en tu nombre (lo haces tú, en tu navegador)."""
    from xcreator.xauth import CALLBACK, AlmacenTokens, AuthError, autorizar

    _, s = _queue()
    try:
        callback = s.x_callback or CALLBACK
        typer.echo(f"Callback usado: {callback}\n"
                   f"(tiene que coincidir EXACTO con el de developer.x.com)\n")
        t = autorizar(s.x_client_id or "", AlmacenTokens(s.x_tokens_path),
                      client_secret=s.x_client_secret or "", callback=callback)
    except AuthError as e:
        typer.secho(str(e), fg="red", err=True)
        typer.echo(f"\nEn la app de X, el callback debe ser exactamente:\n  "
                   f"{s.x_callback or CALLBACK}")
        raise typer.Exit(1)
    typer.secho("Autorizado. Ya se puede publicar.", fg="green")
    typer.echo(f"  refresh token: {'sí' if t.refresh_token else 'NO — tendrás que reautorizar cada 2h'}")


@app.command("publicar")
def publicar(
    item_id: str = typer.Option("", help="Publicar solo este. Vacío = todos los aprobados."),
    en_seco: bool = typer.Option(True, help="Sin --no-en-seco no se publica nada."),
    permitir_link: bool = typer.Option(False, help="Permitir links (cuestan 13x)."),
    maximo: int = typer.Option(0, help="Máximo por pasada (0 = sin límite)."),
    espaciado: int = typer.Option(
        0, help="Minutos mínimos desde el último post propio (0 = el de store)."),
) -> None:
    """Publica en X lo que YA aprobaste. En seco por defecto.

    El modo en seco es el que manda a propósito: publicar es la única acción
    irreversible de todo el sistema, así que hay que pedirla explícitamente.
    """
    from xcreator.publicar import (
        PublicarError, costo, publicar_item, revisar_antes_de_publicar,
    )
    from xcreator.store import MAX_FALLOS_PUBLICAR
    from xcreator.xauth import AlmacenTokens, AuthError, token_vigente

    q, s = _queue()
    items = [q.get(item_id)] if item_id else q.listos_para_publicar()
    items = [i for i in items if i is not None]
    if not items:
        typer.echo("Nada listo para publicar.")
        return

    # Espaciar es parte de publicar bien: una tanda de posts seguidos se lee
    # como automatizada y los posts compiten entre sí por el mismo lector.
    # Los replies van primero y se saltan el espaciado: caducan en horas,
    # mientras que un post propio sigue igual de bueno dentro de un rato.
    items.sort(key=lambda i: 0 if i.kind == "reply" else 1)
    # El espaciado por defecto sale de la constante, no de la línea del cron:
    # tenerlo escrito en dos sitios es como se desincronizan las cosas, y aquí
    # el aviso de Telegram depende del mismo número.
    from xcreator.store import ESPACIADO_MINUTOS

    if espaciado == 0 and not item_id:
        espaciado = ESPACIADO_MINUTOS
    # Antes: si en la lista había CUALQUIER reply, el espaciado se saltaba
    # entero. Los replies aprobados no se pueden publicar por API (la
    # revisión los bloquea), pero su sola presencia dejaba salir posts
    # propios cada 30 minutos: 13:30, 14:00 y 14:30 el 18 de septiembre.
    # El espaciado mira solo si hay posts PROPIOS esperando.
    from xcreator.store import HOLGURA_MINUTOS

    propios = [i for i in items if i.kind not in ("reply", "cita")]
    if espaciado and not item_id and propios:
        desde = q.minutos_desde_ultima_publicacion()
        if desde is not None and desde < espaciado - HOLGURA_MINUTOS:
            typer.echo(f"Toca esperar: el último post propio salió hace "
                       f"{desde:.0f} min y el espaciado es de {espaciado} min.")
            return
    # El máximo se aplica DESPUÉS de descartar lo impublicable. Al revés, un
    # borrador inválido consume el cupo y la pasada no publica nada — el
    # mismo error que ya costó que Telegram dejara de enviar borradores.
    bloqueados = [(i, revisar_antes_de_publicar(i, permitir_link=permitir_link))
                  for i in items]
    publicables = [i for i, problemas in bloqueados if not problemas]
    if maximo:
        publicables = publicables[:maximo]
    # Los problemas se siguen mostrando: callarlos es dejar borradores
    # muertos en la cola sin que nadie sepa por qué.
    for i, problemas in bloqueados:
        if problemas:
            typer.secho(f"[NO] {i.id} {i.ticker}", fg="red")
            for p in problemas:
                typer.echo(f"     {p}")
    items = publicables
    if not items:
        typer.echo("Nada publicable en esta pasada.")
        return

    total = sum(costo([i.texto_final, *i.hilo]) for i in items)
    typer.echo(f"{len(items)} publicación(es) — costo estimado ${total:.3f}\n")

    token = ""
    if not en_seco:
        try:
            token = token_vigente(s.x_client_id or "",
                                  AlmacenTokens(s.x_tokens_path),
                                  client_secret=s.x_client_secret or "").access_token
        except AuthError as e:
            typer.secho(str(e), fg="red", err=True)
            raise typer.Exit(1)

    publicados = 0
    for i in items:
        if en_seco:
            con_img = " (+gráfico)" if i.imagen else ""
            typer.secho(f"[seco] {i.id} {i.ticker}{con_img} — se publicaría:",
                        fg="yellow")
            typer.echo(f"     {i.texto_final[:120]}")
            continue
        from pathlib import Path as _Path

        imagen = _Path(i.imagen) if i.imagen else None
        if imagen is not None and not imagen.exists():
            typer.secho(f"     (el gráfico {imagen.name} ya no está; sale sin "
                        f"imagen)", fg="yellow")
            imagen = None
        try:
            res = publicar_item(i, token, handle=s.x_handle or "",
                                imagen=imagen)
        except PublicarError as e:
            fallos = (i.fallos_al_publicar or 0) + 1
            typer.secho(f"[FALLÓ x{fallos}] {i.id}: {e}", fg="red")
            if fallos >= MAX_FALLOS_PUBLICAR:
                q.update(i.id, fallos_al_publicar=fallos, estado="bloqueado",
                         motivo_rechazo=f"X lo rechazó {fallos} veces: {e}")
                typer.secho(
                    f"  bloqueado tras {fallos} intentos: no se reintenta más "
                    f"y la cola sigue con el siguiente.", fg="yellow")
            else:
                q.update(i.id, fallos_al_publicar=fallos)
            continue
        q.marcar_publicado(i.id, post_id=res.post_id)
        publicados += 1
        typer.secho(f"[OK] {i.id} -> {res.url}", fg="green")

    if en_seco:
        typer.secho("\nEsto fue en seco. Para publicar de verdad: "
                    "`xc publicar --no-en-seco`", bold=True)
    else:
        typer.echo(f"\n{publicados} publicado(s).")


def _redactar_macro(q, s, *, n: int, encolar: bool) -> None:
    """Post de mercado/economía. Complementa a los de empresa, no los sustituye."""
    from xcreator.generate import draft_posts
    from xcreator.macro import brief_macro, mejores_temas

    temas = mejores_temas(s.fred_api_key)
    if not temas:
        typer.secho("Ninguna serie macro tiene algo que contar hoy. Un dato "
                    "en su media no es un post.", fg="yellow")
        return

    # Dos posts de macro al día desde el 2026-09-21. El segundo coge la
    # siguiente serie con tensión, nunca la misma: tres posts del mismo dato
    # en un día ya pasaron una vez. Si no queda otra serie, se calla.
    from datetime import date

    hoy = date.today().isoformat()
    usadas = {i.motivo for i in q.load()
              if i.kind == "macro" and (i.creado or "")[:10] == hoy}
    frescas = [t for t in temas if f"macro:{t.cfg.serie}" not in usadas]
    if not frescas:
        typer.secho("Las series macro con algo que contar ya salieron hoy.",
                    fg="yellow")
        return
    lectura = frescas[0]
    brief = brief_macro(lectura)
    typer.echo(f"Macro: {lectura.cfg.serie} — {lectura.valor:.2f} "
               f"(percentil {lectura.percentil_5a:.0%}, "
               f"{lectura.tension:.0f} pts de tensión)")
    typer.echo(f"Ángulo: {brief.angle}\n")

    # Una sola a la cola: las demás son repuesto. Encolarlas todas puso tres
    # posts del mismo dato macro en un día.
    drafts = draft_posts(brief, s, n=n, recientes=q.textos_recientes())
    if drafts:
        _mostrar_y_encolar(next((d for d in drafts if d.valido), drafts[0]),
                           brief, q, s, encolar=encolar)


def _grafico_para(brief, settings, item_id: str):
    """Gráfico de escenarios del brief, o None si no hay con qué dibujarlo.

    Nunca aborta la generación: un post sin gráfico sigue siendo publicable,
    uno con gráfico inventado no.
    """
    from xcreator.datos import price_history
    from xcreator.graficos import grafico_escenarios, puede_graficar

    destino = settings.root / "Contenido" / "graficos" / f"{item_id}.png"
    firma = settings.x_handle or ""
    try:
        if puede_graficar(brief):
            historico = price_history(brief.ticker, settings.fmp_api_key, dias=180)
            return grafico_escenarios(brief, historico, destino, firma=firma)
        # Cripto y macro salían sin imagen. Una gráfica es lo que más se
        # comparte y compartir es lo que más pesa: cada tipo lleva la suya.
        if brief.kind in ("cripto", "regulacion") and brief.ticker:
            return _grafico_cripto(brief, settings, destino, firma)
        if brief.kind == "macro":
            return _grafico_macro(brief, settings, destino, firma)
        if brief.kind == "marcador" and getattr(brief, "_marcador", None):
            abajo, arriba, total = brief._marcador
            from xcreator.graficos import grafico_marcador

            return grafico_marcador(abajo, arriba, total, destino, firma=firma)
    except Exception as e:  # noqa: BLE001 - el gráfico es opcional
        typer.secho(f"  (sin gráfico: {type(e).__name__})", fg="yellow")
    return None


def _valor(brief, empieza: str):
    return next((f.value for f in brief.facts if f.label.startswith(empieza)),
                None)


def _grafico_cripto(brief, settings, destino, firma):
    from xcreator.cripto import DIAS_HISTORICO, activo_por_ticker
    from xcreator.datos import price_history
    from xcreator.graficos import grafico_rango

    cfg = activo_por_ticker(brief.ticker)
    if cfg is None:
        return None
    serie = price_history(cfg.simbolo, settings.fmp_api_key, dias=DIAS_HISTORICO)
    caida = _valor(brief, f"caída de {cfg.nombre}")
    vol = _valor(brief, f"volatilidad anualizada de {cfg.nombre}")
    partes = []
    if caida is not None:
        partes.append(f"{caida:.0f}% below its high")
    if vol is not None:
        partes.append(f"annualized volatility {vol:.0f}%")
    return grafico_rango(
        # "XRP (XRP)" repetía: solo se añade el ticker cuando aporta algo.
        serie, destino,
        titulo=(f"{cfg.nombre} ({cfg.ticker})" if cfg.nombre != cfg.ticker
                else cfg.nombre) + " · price vs its range",
        subtitulo="   ".join(partes),
        fuente="Data: FMP daily closes. Descriptive range, not a forecast.",
        firma=firma)


def _grafico_macro(brief, settings, destino, firma):
    from xcreator.datos import fred_series
    from xcreator.graficos import grafico_rango
    from xcreator.macro import SERIES

    # El brief no guarda el id de FRED, pero sí su sujeto, que es el `alias`
    # de su serie: con eso se encuentra sin añadir otro campo.
    cfg = next((c for c in SERIES.values() if c.alias == tuple(brief.sujeto)),
               None)
    if cfg is None:
        return None
    from xcreator.macro import serie_de

    serie = serie_de(cfg, settings.fred_api_key)
    ano = _valor(brief, f"{cfg.nombre} hace un año")
    mes = _valor(brief, f"{cfg.nombre} hace un mes")
    u = {"pct": "%", "pp": " pp"}.get(cfg.unidad, "")
    partes = []
    if ano is not None:
        partes.append(f"a year ago {ano:.2f}{u}")
    if mes is not None:
        partes.append(f"a month ago {mes:.2f}{u}")
    nombre = cfg.nombre[0].upper() + cfg.nombre[1:]
    return grafico_rango(
        serie, destino, titulo=f"{nombre} · where it sits in its range",
        subtitulo="   ".join(partes),
        formato={"pct": "pct", "pp": "pp"}.get(cfg.unidad, "num"),
        fuente=f"Data: FRED {cfg.serie}. Observed values, not a forecast.",
        firma=firma)


@app.command("conversar")
def conversar(
    encolar: bool = typer.Option(True, help="Guardar en la cola (y Telegram)."),
) -> None:
    """Propone respuesta a quien contestó en tus posts. Se pegan a mano."""
    import json as _json

    from xcreator.conversaciones import (
        CONVERSACIONES_POR_DIA, respuestas_por_contestar,
    )
    from xcreator.replies import Mencion, Relevancia, draft_reply
    from xcreator.xapi import ClienteX, XAPIError

    q, s = _queue()
    if not s.x_handle:
        typer.secho("Falta X_HANDLE en API/.env.", fg="red", err=True)
        raise typer.Exit(1)
    hechas = q.conversaciones_de_hoy()
    if hechas >= CONVERSACIONES_POR_DIA:
        typer.echo(f"Cupo de conversaciones agotado ({hechas}/"
                   f"{CONVERSACIONES_POR_DIA} hoy). Sin lecturas: $0.000.")
        return
    try:
        cliente = ClienteX(s.x_bearer_token or "", s.x_cache_path,
                           presupuesto_diario=s.x_presupuesto_pasada)
    except XAPIError as e:
        typer.secho(str(e), fg="red", err=True)
        raise typer.Exit(1)

    clave = f"menciones:{s.x_handle.lstrip('@').lower()}"
    try:
        ultimos = _json.loads(s.x_estado_path.read_text())
    except (OSError, ValueError):
        ultimos = {}
    try:
        pares = cliente.menciones(s.x_handle, desde_id=ultimos.get(clave))
    except XAPIError as e:
        typer.secho(str(e), fg="red", err=True)
        raise typer.Exit(1)
    # En prueba (--no-encolar) el cursor no avanza: si avanzara, esas
    # menciones ya no se volverían a ver cuando corra de verdad.
    if pares and encolar:
        ultimos[clave] = max((m.post_id for m, _ in pares), key=int)
        s.x_estado_path.parent.mkdir(parents=True, exist_ok=True)
        s.x_estado_path.write_text(_json.dumps(ultimos, indent=2))

    pendientes = respuestas_por_contestar(pares, s.x_handle, q.ya_respondido)
    typer.echo(f"{len(pares)} menciones nuevas -> {len(pendientes)} respuestas "
               f"a tus posts por contestar. Gasto: ${cliente.gastado:.3f}")
    for m, padre in pendientes[:CONVERSACIONES_POR_DIA - hechas]:
        d = draft_reply(
            Mencion(m.autor, m.texto, m.url, m.post_id),
            Relevancia(None, solo_opinion=True, tema="una conversación en tu post"),
            s, modo="conversacion", contexto_propio=padre.texto)
        d.brief_id = "conversacion"
        if d.declinado or not d.texto:
            typer.echo(f"  {m.autor}: sin respuesta ({d.motivo or 'nada que aportar'})")
            continue
        typer.echo(f"  {m.autor}: {d.texto}")
        if encolar:
            q.add(d)


@app.command("recuperar")
def recuperar(
    encolar: bool = typer.Option(True, help="Guardar en la cola."),
    umbral: int = typer.Option(0, help="Impresiones mínimas (0 = la de fábrica)."),
) -> None:
    """Reescribe como post original tus replies que ya funcionaron."""
    from xcreator.conversaciones import (
        POSTS_DESDE_REPLIES_POR_DIA, UMBRAL_REPLY_A_POST, brief_desde_reply,
        candidatos_reply_a_post,
    )
    from xcreator.generate import draft_posts
    from xcreator.xapi import ClienteX, XAPIError

    q, s = _queue()
    if not s.x_handle:
        typer.secho("Falta X_HANDLE en API/.env.", fg="red", err=True)
        raise typer.Exit(1)
    hechos = q.reciclados_de_hoy()
    if hechos >= POSTS_DESDE_REPLIES_POR_DIA:
        typer.echo(f"Ya se reciclaron {hechos} replies hoy.")
        return
    try:
        cliente = ClienteX(s.x_bearer_token or "", s.x_cache_path,
                           presupuesto_diario=s.x_presupuesto_pasada)
        pares = cliente.mis_replies(s.x_handle)
    except XAPIError as e:
        typer.secho(str(e), fg="red", err=True)
        raise typer.Exit(1)

    candidatos = candidatos_reply_a_post(
        pares, q.replies_reciclados(), umbral=umbral or UMBRAL_REPLY_A_POST)
    typer.echo(f"{len(pares)} replies tuyos leídos -> {len(candidatos)} con "
               f"más de {umbral or UMBRAL_REPLY_A_POST} impresiones y de "
               f"mercados. Gasto: ${cliente.gastado:.3f}")
    for reply, _ in candidatos[:POSTS_DESDE_REPLIES_POR_DIA - hechos]:
        typer.echo(f"\nReply ({reply.impresiones:,} imp): {reply.texto[:120]}")
        padre = None
        if reply.responde_a:
            try:
                padre = cliente.post(reply.responde_a)
            except XAPIError as e:
                typer.secho(f"  sin el post padre ({e}); se sigue sin él",
                            fg="yellow")
        brief = brief_desde_reply(reply, padre)
        drafts = draft_posts(brief, s, n=2, recientes=q.textos_recientes())
        if not drafts:
            typer.secho("Sin borradores: el modelo no respondió.", fg="red", err=True)
            raise typer.Exit(1)
        _mostrar_y_encolar(next((d for d in drafts if d.valido), drafts[0]),
                           brief, q, s, encolar=encolar)


@app.command("gasto")
def gasto_cmd(dias: int = typer.Option(7, help="Cuántos días mostrar.")) -> None:
    """Lo que ha costado el modelo que redacta, día a día."""
    from datetime import date, timedelta

    from xcreator.config import load_settings, proveedor
    from xcreator.llm import gasto

    s = load_settings()
    typer.echo(f"Proveedor: {proveedor(s)}  modelo: {s.xai_modelo}")
    total_n, total_usd = 0, 0.0
    for k in range(dias - 1, -1, -1):
        d = (date.today() - timedelta(days=k)).isoformat()
        n, usd = gasto(s.uso_llm_path, d)
        total_n, total_usd = total_n + n, total_usd + usd
        typer.echo(f"  {d}  {n:>3} llamadas  ${usd:,.2f}")
    typer.echo(f"Total: {total_n} llamadas, ${total_usd:,.2f}")


@app.command("cola")
def cola(todos: bool = typer.Option(False, help="Incluir ya decididos.")) -> None:
    """Lista los borradores pendientes de tu revisión."""
    q, _ = _queue()
    items = q.load() if todos else q.pendientes()
    if not items:
        typer.echo("Cola vacía.")
        return
    for i in items:
        flag = "  <- cifras sin fuente" if i.numeros_no_justificados else ""
        typer.echo(f"[{i.id}] {i.estado:<10} {i.ticker:<6} {i.texto[:90]}{flag}")
    r = q.resumen()
    pct, n = q.tasa_aprobacion()
    typer.echo(f"\n{r}")
    if pct is not None:
        listo = "sí" if (pct >= 0.8 and n >= 20) else "todavía no"
        typer.echo(f"Tasa de aprobación: {pct:.0%} sobre {n} decididos. "
                   f"¿Listo para auto-publicar? {listo} (criterio: >=80% con n>=20)")


@app.command("aprobar")
def aprobar(item_id: str, texto: str = typer.Option("", help="Texto editado.")) -> None:
    """Aprueba un borrador (opcionalmente con tu edición)."""
    q, _ = _queue()
    if q.aprobar(item_id, texto) is None:
        typer.secho(f"No existe {item_id}", fg="red", err=True)
        raise typer.Exit(1)
    typer.secho(f"{item_id} aprobado.", fg="green")


@app.command("rechazar")
def rechazar(item_id: str, motivo: str = typer.Option("", help="Por qué.")) -> None:
    """Rechaza un borrador. Nunca se borra: el rechazo es la señal de mejora."""
    q, _ = _queue()
    if q.rechazar(item_id, motivo) is None:
        typer.secho(f"No existe {item_id}", fg="red", err=True)
        raise typer.Exit(1)
    typer.secho(f"{item_id} rechazado.", fg="yellow")


# --- Telegram -------------------------------------------------------------

tg = typer.Typer(help="Cola de aprobación por Telegram (bot propio).")
app.add_typer(tg, name="telegram")


def _bot():
    from xcreator.telegram import Estado, TelegramError, bot_desde

    q, s = _queue()
    try:
        b = bot_desde(s)
    except TelegramError as e:
        typer.secho(str(e), fg="red", err=True)
        raise typer.Exit(1)
    return q, s, b, Estado(s.estado_telegram_path)


@tg.command("setup")
def tg_setup() -> None:
    """Verifica el bot y descubre tu chat_id (escríbele algo primero)."""
    from xcreator.telegram import Bot, TelegramError

    _, s = _queue()
    if not s.telegram_bot_token:
        typer.secho(
            "Falta TELEGRAM_X_BOT_TOKEN en API/.env.\n"
            "  1. Abre @BotFather en Telegram y manda /newbot\n"
            "  2. Ponle un nombre (un bot NUEVO, solo para este proyecto)\n"
            "  3. Pega el token:  echo 'TELEGRAM_X_BOT_TOKEN=...' >> API/.env\n"
            "  4. Escríbele /start a tu bot nuevo y corre esto otra vez",
            fg="red", err=True)
        raise typer.Exit(1)

    b = Bot(s.telegram_bot_token, str(s.telegram_chat_id or ""))
    try:
        yo = b.me()
    except TelegramError as e:
        typer.secho(f"El token no sirve: {e}", fg="red", err=True)
        raise typer.Exit(1)
    typer.secho(f"Bot OK: @{yo.get('username')} ({yo.get('first_name')})", fg="green")

    chats = {}
    for up in b.updates():
        ch = (up.get("message") or up.get("callback_query", {}).get("message") or {}).get("chat")
        if ch:
            chats[str(ch["id"])] = ch.get("username") or ch.get("first_name") or "?"
    if not chats:
        typer.secho("No veo mensajes todavía. Escríbele /start al bot y repite.",
                    fg="yellow")
        raise typer.Exit(1)
    for cid, quien in chats.items():
        typer.echo(f"  chat_id {cid}  ({quien})")
    if not s.telegram_chat_id:
        typer.echo("\nAñádelo:  echo 'TELEGRAM_X_CHAT_ID=<el de arriba>' >> API/.env")
    elif str(s.telegram_chat_id) in chats:
        typer.secho(f"\nchat_id configurado ({s.telegram_chat_id}) — coincide.",
                    fg="green")
    else:
        typer.secho(f"\nOJO: tienes configurado {s.telegram_chat_id}, que no "
                    f"aparece arriba. Puede ser el chat de otro agente.",
                    fg="yellow")


@tg.command("enviar")
def tg_enviar(limite: int = typer.Option(10, help="Máximo de borradores.")) -> None:
    """Manda a tu teléfono los pendientes que aún no se enviaron."""
    from xcreator.telegram import TelegramError, enviar_pendientes

    q, _, b, _e = _bot()
    try:
        n = enviar_pendientes(q, b, limite=limite)
    except TelegramError as e:
        typer.secho(str(e), fg="red", err=True)
        raise typer.Exit(1)
    typer.secho(f"{n} borrador(es) enviados." if n else
                "Nada nuevo que enviar.", fg="green" if n else None)


def _redactar_desde_nota(q, s, nota: str) -> list[str]:
    """Convierte una nota de Angel en borradores. Devuelve sus ids."""
    from xcreator.generate import draft_posts
    from xcreator.idea import brief_idea, ticker_de_la_nota

    brief = brief_idea(nota, ticker_de_la_nota(nota))
    ids = []
    for d in draft_posts(brief, s, n=2, recientes=q.textos_recientes()):
        # Pendiente, nunca programado: es la voz de Angel y la aprueba él.
        # Un post suyo que sale solo porque se le olvidó mirarlo es
        # exactamente lo contrario de lo que pidió.
        ids.append(q.add(d, estado="pendiente").id)
    return ids


@tg.command("escuchar")
def tg_escuchar() -> None:
    """Aplica los botones que tocaste y convierte tus notas en borradores."""
    from xcreator.telegram import TelegramError, procesar_updates

    q, s, b, est = _bot()
    try:
        log = procesar_updates(q, b, est,
                               redactar_idea=lambda n: _redactar_desde_nota(q, s, n))
    except TelegramError as e:
        typer.secho(str(e), fg="red", err=True)
        raise typer.Exit(1)
    for linea in log:
        typer.echo(linea)
    typer.echo(f"{len(log)} acción(es) aplicadas." if log else "Sin novedades.")


@tg.command("ciclo")
def tg_ciclo(
    limite: int = typer.Option(10, help="Máximo de borradores a enviar."),
) -> None:
    """escuchar + enviar en una pasada. Es lo que va en el cron."""
    # Los valores van EXPLÍCITOS: llamar a un comando de Typer como función
    # normal le pasa los objetos `OptionInfo` en vez de los valores por
    # defecto, y el comando revienta con un TypeError opaco.
    tg_escuchar()
    tg_enviar(limite=limite)
