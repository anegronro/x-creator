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
    n: int = typer.Option(3, help="Variantes a generar."),
    encolar: bool = typer.Option(True, help="Guardar en la cola de aprobación."),
) -> None:
    """Redacta variantes desde los datos del motor y las deja en la cola."""
    from xcreator.datos import live_price
    from xcreator.brief import load_briefs
    from xcreator.generate import draft_posts

    q, s = _queue()

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
    briefs = load_briefs(
        s.reportes_dir, lambda t: live_price(t, s.fmp_api_key)
    )
    if ticker:
        briefs = [b for b in briefs if b.ticker.upper() == ticker.upper()]
    if not briefs:
        typer.secho("No hay predicciones en WBJ_REPORTES_DIR. Corre "
                    "`wbj analyze <TICKER>` en el motor de acciones primero.", fg="red", err=True)
        raise typer.Exit(1)

    from xcreator.cerebro import ANGULOS, disponible

    if angulo not in ANGULOS:
        typer.secho(f"Ángulo desconocido: {angulo}. Opciones: "
                    f"{', '.join(ANGULOS)}", fg="red", err=True)
        raise typer.Exit(1)

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
        estado = "OK" if d.valido else "REVISAR"
        color = "green" if d.valido else "yellow"
        typer.secho(f"[{estado}] {d.approach}", fg=color, bold=True)
        typer.echo(f"  {d.text}  ({len(d.text)} c)")
        for i, t in enumerate(d.thread, 2):
            typer.echo(f"  {i}/ {t}  ({len(t)} c)")
        typer.echo(f"  gancho: {d.reply_hook}")
        if d.numeros_no_justificados:
            typer.secho(f"  CIFRAS SIN FUENTE: {d.numeros_no_justificados}",
                        fg="red")
        if d.exceso_caracteres:
            typer.secho(f"  se pasa por {d.exceso_caracteres} caracteres", fg="red")
        if d.truncado:
            typer.secho("  TEXTO CORTADO a media frase — no publicar así", fg="red")
        if encolar:
            item = q.add(d)
            typer.echo(f"  -> cola id {item.id}")
        typer.echo("")


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
def tg_ciclo() -> None:
    """escuchar + enviar en una pasada. Es lo que va en el cron."""
    tg_escuchar()
    tg_enviar()
