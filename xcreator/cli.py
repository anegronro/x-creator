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
        AnalyticsError, analyze, es_export_de_cuenta, load_posts,
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

        r = ranking(briefs, ultimo_uso=q.ultimo_uso_por_ticker())
        if not r:
            typer.secho("Ningún brief tiene tensión hoy. Publicar por "
                        "publicar es peor que no publicar.", fg="yellow")
            raise typer.Exit(0)
        # Un ticker por post, no `n` posts del mismo ticker. Antes `--auto`
        # cogía solo la cabeza del ranking y pedía n variantes de ESA empresa;
        # con la aprobación automática, eso son n posts seguidos de lo mismo.
        elegidos, vistos = [], set()
        for t in r:
            if t.ticker.upper() in vistos:
                continue
            vistos.add(t.ticker.upper())
            elegidos.append(t)
            if len(elegidos) >= max(1, n):
                break
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
        typer.secho("Sin borradores: falta ANTHROPIC_API_KEY o el SDK.",
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
        drafts = draft_posts(brief, s, lecciones=lecciones, n=2)
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
        typer.secho("Sin borradores: falta ANTHROPIC_API_KEY o el SDK.",
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
    drafts = draft_posts(brief, s, n=n)
    if drafts:
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
    typer.secho(f"Falta multiplicar el alcance por {r.factor_faltante:,.0f}x "
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

    # El cupo diario es de TIEMPO de Angel, no de dinero: cada reply cuesta
    # tres toques manuales porque X no deja publicarlos por API.
    ya = q.replies_de_hoy()
    cupo = max(0, s.replies_por_dia - ya)
    if cupo == 0:
        typer.echo(f"Cupo de replies agotado ({ya}/{s.replies_por_dia} hoy). "
                   f"Se siguen leyendo cuentas, pero no se proponen más.")
        return

    briefs = load_briefs(s.reportes_dir, lambda t: live_price(t, s.fmp_api_key),
                         limit=500)
    nombres = load_company_names(s.reportes_dir)
    rel = encontrar_relevancia(mencion, briefs, nombres)

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
    if encolar:
        item = q.add(d)
        typer.echo(f"  -> cola id {item.id}")


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

    briefs = load_briefs(s.reportes_dir, lambda t: live_price(t, s.fmp_api_key),
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

    # Los posts de opinión se apartan aquí y se resuelven al final.
    candidatos_opinion: list = []

    def _redactar_y_encolar(cuenta, m, rel) -> int:
        """Redacta el reply y lo deja en la cola. Devuelve 1 si se encoló."""
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
                                       cripto=brief_cripto_de)
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
        rel = encontrar_relevancia(m, briefs, nombres, cripto=brief_cripto_de)
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
    if espaciado and not item_id and not any(i.kind == "reply" for i in items):
        desde = q.minutos_desde_ultima_publicacion()
        if desde is not None and desde < espaciado:
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
            typer.secho(f"[FALLÓ] {i.id}: {e}", fg="red")
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

    lectura = temas[0]
    brief = brief_macro(lectura)
    typer.echo(f"Macro: {lectura.cfg.serie} — {lectura.valor:.2f} "
               f"(percentil {lectura.percentil_5a:.0%}, "
               f"{lectura.tension:.0f} pts de tensión)")
    typer.echo(f"Ángulo: {brief.angle}\n")

    # Una sola a la cola: las demás son repuesto. Encolarlas todas puso tres
    # posts del mismo dato macro en un día.
    drafts = draft_posts(brief, s, n=n)
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

    if not puede_graficar(brief):
        return None
    try:
        historico = price_history(brief.ticker, settings.fmp_api_key, dias=180)
        destino = settings.root / "Contenido" / "graficos" / f"{item_id}.png"
        return grafico_escenarios(brief, historico, destino)
    except Exception as e:  # noqa: BLE001 - el gráfico es opcional
        typer.secho(f"  (sin gráfico: {type(e).__name__})", fg="yellow")
        return None


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


@tg.command("escuchar")
def tg_escuchar() -> None:
    """Aplica los botones que tocaste. Pensado para cron cada pocos minutos."""
    from xcreator.telegram import TelegramError, procesar_updates

    q, _, b, est = _bot()
    try:
        log = procesar_updates(q, b, est)
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
