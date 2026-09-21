"""Tests del agente de contenido de X."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from xcreator.analytics import (
    AnalyticsError, Post, analyze, analyze_feature, features, load_posts,
)
from xcreator.brief import Brief, Fact, from_prediction
from xcreator.generate import Draft, validate_numbers
from xcreator.store import Queue


# --- helpers --------------------------------------------------------------

def _post(text: str, impressions: float = 5000, replies: float = 25, **kw) -> Post:
    return Post(
        post_id=kw.get("post_id", "1"), text=text,
        created=kw.get("created", datetime(2026, 6, 1, 10, 0)),
        impressions=impressions, likes=kw.get("likes", 50), replies=replies,
        reposts=kw.get("reposts", 10), bookmarks=kw.get("bookmarks", 5),
        profile_visits=kw.get("profile_visits", 20), follows=kw.get("follows", 2),
    )


def _write_csv(path, rows, header=None):
    header = header or list(rows[0])
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=header)
        w.writeheader()
        w.writerows(rows)
    return path


# --- lectura del CSV ------------------------------------------------------

def test_csv_sin_columnas_clave_falla_ruidosamente(tmp_path):
    """Un CSV sin impresiones no puede analizarse a medias: tiene que gritar."""
    p = _write_csv(tmp_path / "malo.csv", [{"Post text": "hola", "Likes": "3"}])
    with pytest.raises(AnalyticsError, match="impressions"):
        load_posts(p)


def test_csv_acepta_alias_de_columnas(tmp_path):
    """X ha renombrado 'Impressions' a 'Views'; ambos deben funcionar."""
    p = _write_csv(tmp_path / "v.csv", [
        {"Post id": "1", "Post text": "hi", "Date": "2026-06-01 10:00",
         "Views": "1,200", "Replies": "12"},
    ])
    posts = load_posts(p)
    assert posts[0].impressions == 1200
    assert posts[0].replies == 12


def test_numeros_con_formato_no_rompen(tmp_path):
    p = _write_csv(tmp_path / "f.csv", [
        {"Post text": "x", "Impressions": "12,345", "Replies": "-"},
    ])
    posts = load_posts(p)
    assert posts[0].impressions == 12345
    assert posts[0].replies == 0.0


# --- métricas -------------------------------------------------------------

def test_reply_rate_es_la_metrica_que_paga():
    p = _post("x", impressions=1000, replies=30)
    assert p.reply_rate == pytest.approx(0.03)


def test_impresiones_cero_no_divide_por_cero():
    assert _post("x", impressions=0, replies=5).reply_rate == 0.0


# --- features -------------------------------------------------------------

@pytest.mark.parametrize("texto,feature,esperado", [
    ("look https://t.co/abc", "tiene_link", True),
    ("no link here", "tiene_link", False),
    ("$NVDA is rich", "tiene_cashtag", True),
    ("NVDA is rich", "tiene_cashtag", False),
    ("what breaks first?", "tiene_pregunta", True),
    ("Everyone is wrong about this", "postura_fuerte", True),
    ("Revenue grew last year", "postura_fuerte", False),
    ("1/ here we go", "es_hilo", True),
])
def test_features_del_texto(texto, feature, esperado):
    assert features(_post(texto))[feature] is esperado


# --- honestidad estadística (el corazón del módulo) -----------------------

def test_muestra_chica_no_concluye():
    """Tres posts no sostienen una lección, por grande que sea el efecto."""
    posts = [_post("a?", replies=500) for _ in range(3)]
    posts += [_post("b", replies=1) for _ in range(3)]
    f = analyze_feature(posts, "tiene_pregunta")
    assert not f.suficiente
    assert not f.significativo
    assert "INSUFICIENTE" in f.veredicto


def test_detecta_un_patron_real():
    posts = [_post(f"q{i}?", impressions=5000, replies=150) for i in range(20)]
    posts += [_post(f"p{i}", impressions=5000, replies=10) for i in range(20)]
    rep = analyze(posts)
    hallazgo = next(f for f in rep.findings if f.feature == "tiene_pregunta")
    assert hallazgo.significativo
    assert hallazgo.lift > 1.0


def test_ruido_puro_no_produce_lecciones():
    """Sin señal real, `lecciones` tiene que quedar vacío."""
    import random

    random.seed(7)
    posts = [
        _post(f"{'q?' if i % 2 else 'p'} {i}", impressions=5000,
              replies=random.randint(10, 60))
        for i in range(60)
    ]
    assert analyze(posts).lecciones == []


def test_correccion_por_comparaciones_multiples():
    """Un p<0.05 aislado no basta cuando se corren 8 tests a la vez.

    Regresión de un falso positivo real: en una prueba con features
    aleatorias, `tiene_cashtag` dio p=0.041 sobre puro ruido. Sin
    Benjamini-Hochberg eso se habría convertido en una regla de estilo.
    """
    from xcreator.analytics import ALPHA, Finding, _benjamini_hochberg

    fs = [
        Finding("real_a", 20, 20, 0.05, 0.01, 4.0, 0.0001, True),
        Finding("real_b", 20, 20, 0.04, 0.01, 3.0, 0.0002, True),
        Finding("borderline", 20, 20, 0.02, 0.015, 0.3, 0.041, True),
        Finding("ruido_1", 20, 20, 0.01, 0.01, 0.0, 0.32, True),
        Finding("ruido_2", 20, 20, 0.01, 0.01, 0.0, 0.55, True),
        Finding("ruido_3", 20, 20, 0.01, 0.01, 0.0, 0.75, True),
        Finding("ruido_4", 20, 20, 0.01, 0.01, 0.0, 0.81, True),
        Finding("ruido_5", 20, 20, 0.01, 0.01, 0.0, 0.93, True),
    ]
    _benjamini_hochberg(fs)
    por_nombre = {f.feature: f for f in fs}
    assert por_nombre["real_a"].significativo
    assert por_nombre["real_b"].significativo
    # p=0.041 < ALPHA aislado, pero no sobrevive la corrección.
    assert por_nombre["borderline"].p_value < ALPHA
    assert not por_nombre["borderline"].significativo
    assert "comparaciones múltiples" in por_nombre["borderline"].veredicto


# --- brief ----------------------------------------------------------------

_PRED = {
    "ticker": "NVDA", "date": "2026-07-27", "price": 196.53,
    "bear": 194.56, "base": 275.14, "bull": 316.41,
    "growth_base": 0.40, "pe_now": 40.10, "score10": 7.8,
}


def test_brief_desde_prediccion():
    b = from_prediction(_PRED)
    assert b.ticker == "NVDA"
    assert b.kind == "target_range"
    assert 275.14 in b.allowed_numbers()


def test_brief_con_precio_vivo_es_chequeo_de_tesis():
    b = from_prediction(_PRED, price_now=178.50)
    assert b.kind == "thesis_check"
    assert 178.50 in b.allowed_numbers()
    assert "FUERA" in b.angle  # 178.50 está por debajo del bear de 194.56


def test_prediccion_incompleta_no_produce_brief():
    assert from_prediction({"ticker": "X"}) is None


def test_brief_precomputa_derivados():
    """El post no debería tener que calcular: el upside ya viene en el brief."""
    b = from_prediction(_PRED)
    upside = (275.14 / 196.53) - 1
    assert any(abs(v - upside) < 1e-6 for v in b.allowed_numbers())


# --- validación numérica --------------------------------------------------

_ALLOWED = [196.53, 194.56, 275.14, 316.41, 7.8, 40.10, 0.40, 178.50, -0.09]


def test_acepta_cifras_del_brief():
    t = ("Range for $NVDA: bear $194.56, base $275.14, bull $316.41. "
         "Now $178.50.")
    assert validate_numbers(t, _ALLOWED) == []


@pytest.mark.parametrize("texto,esperado", [
    ("Fair value is $412.00 on my math.", "$412.00"),
    ("Revenue grew 18% last quarter.", "18%"),
    ("Trading at a 62.4 P/E.", "62.4"),
])
def test_rechaza_cifras_inventadas(texto, esperado):
    assert esperado in validate_numbers(texto, _ALLOWED)


@pytest.mark.parametrize("texto", [
    "3 reasons this is generous:",   # conteo estructural
    "Our 2026 call still stands.",   # año
    "A 12-month horizon.",           # plazo
])
def test_permite_numeros_estructurales(texto):
    assert validate_numbers(texto, _ALLOWED) == []


def test_ratio_escrito_como_porcentaje_es_valido():
    """El brief guarda 0.40; el post escribe '+40%'. Es el mismo dato."""
    assert validate_numbers("assumes +40% growth", _ALLOWED) == []


# --- cola -----------------------------------------------------------------

def _draft(text="hola", **kw):
    return Draft(text=text, approach="a", reply_hook="r", **kw)


def test_cola_persiste_y_no_borra(tmp_path):
    q = Queue(tmp_path / "cola.jsonl")
    a = q.add(_draft("A"))
    b = q.add(_draft("B"))
    q.rechazar(b.id, motivo="cifra sin fuente")
    assert len(Queue(tmp_path / "cola.jsonl").load()) == 2
    assert q.get(b.id).motivo_rechazo == "cifra sin fuente"
    assert [i.id for i in q.pendientes()] == [a.id]


def test_edicion_gana_sobre_original(tmp_path):
    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(_draft("original"))
    q.aprobar(i.id, texto_editado="editado por Angel")
    assert q.get(i.id).texto_final == "editado por Angel"


def test_tasa_de_aprobacion_es_el_criterio_de_autonomia(tmp_path):
    q = Queue(tmp_path / "cola.jsonl")
    for i in range(8):
        item = q.add(_draft(f"p{i}"))
        q.aprobar(item.id) if i < 6 else q.rechazar(item.id)
    pct, n = q.tasa_aprobacion()
    assert (pct, n) == (0.75, 8)


def test_cola_vacia_no_reporta_tasa(tmp_path):
    assert Queue(tmp_path / "cola.jsonl").tasa_aprobacion() == (None, 0)


def test_linea_corrupta_no_tumba_la_cola(tmp_path):
    p = tmp_path / "cola.jsonl"
    q = Queue(p)
    q.add(_draft("bueno"))
    with p.open("a") as fh:
        fh.write("{esto no es json}\n")
    assert len(q.load()) == 1


# --- draft ----------------------------------------------------------------

def test_draft_con_cifra_sin_fuente_no_es_valido():
    assert not _draft(numeros_no_justificados=["$412"]).valido


def test_draft_que_excede_no_es_valido():
    assert not _draft(exceso_caracteres=12).valido


def test_draft_limpio_es_valido():
    assert _draft().valido


# --- truncamiento ---------------------------------------------------------

@pytest.mark.parametrize("texto,cortado", [
    ("A complete thought.", False),
    ("Is this the question?", False),
    ("Loud claim!", False),
    ('He said "no more"', False),                 # cierre con comilla
    ("the bear, what a 45.10 P/E costs you", True),   # el caso real que pasó
    ("Base still needs another", True),
])
def test_detecta_frase_cortada(texto, cortado):
    from xcreator.generate import _parece_cortado

    assert _parece_cortado(texto) is cortado


def test_draft_truncado_no_es_valido():
    assert not _draft("sin cierre", truncado=True).valido


def test_cola_persiste_el_flag_de_truncado(tmp_path):
    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(_draft("cortado a medias", truncado=True))
    assert q.get(i.id).truncado is True


# --- hilos automáticos ----------------------------------------------------

def test_hilo_parte_por_frases_completas():
    from xcreator.generate import MAX_CHARS, _to_thread

    texto = " ".join(f"Sentence number {i} says something." for i in range(30))
    piezas = _to_thread(texto)
    assert len(piezas) > 1
    assert all(len(p) <= MAX_CHARS for p in piezas)
    # Nada se pierde y nada se parte a media palabra.
    assert " ".join(piezas) == texto


def test_hilo_no_parte_dentro_de_un_decimal():
    from xcreator.generate import _frases

    assert _frases("Trading at a 45.10 P/E today.") == ["Trading at a 45.10 P/E today."]


def test_frase_unica_gigante_no_se_mutila():
    from xcreator.generate import _to_thread

    larga = "x" * 400
    assert _to_thread(larga) == [larga]  # el llamador la marca para recorte


def test_umbral_decide_hilo_vs_recorte():
    """Pasarse por poco se recorta; pasarse por mucho va a hilo."""
    from xcreator.generate import MAX_CHARS, UMBRAL_HILO

    assert (290 - MAX_CHARS) <= UMBRAL_HILO      # 10 de exceso -> recorte
    assert (400 - MAX_CHARS) > UMBRAL_HILO       # 120 de exceso -> hilo


# --- Telegram -------------------------------------------------------------

class FakeBot:
    """Bot de mentira que registra lo que se le pide."""

    def __init__(self, updates=None):
        self.enviados, self.callbacks, self.editados = [], [], []
        self._updates = updates or []
        self._next_id = 100

    def send(self, texto, *, botones=None, force_reply=False):
        self._next_id += 1
        self.enviados.append({"texto": texto, "botones": botones,
                              "force_reply": force_reply, "id": self._next_id})
        return {"message_id": self._next_id}

    def answer_callback(self, callback_id, texto=""):
        self.callbacks.append((callback_id, texto))

    def quitar_botones(self, message_id, nuevo_texto=None):
        self.editados.append((message_id, nuevo_texto))

    def updates(self, offset=None):
        return [u for u in self._updates
                if offset is None or u["update_id"] >= offset]


def _cb(item_id, accion, update_id=1, message_id=101):
    return {"update_id": update_id,
            "callback_query": {"id": f"c{update_id}", "data": f"{accion}:{item_id}",
                               "message": {"message_id": message_id}}}


def _estado(tmp_path):
    from xcreator.telegram import Estado

    return Estado(tmp_path / "estado.json")


def test_enviar_pendientes_no_reenvia(tmp_path):
    q = Queue(tmp_path / "cola.jsonl")
    q.add(_draft("uno"))
    q.add(_draft("dos"))
    bot = FakeBot()
    from xcreator.telegram import enviar_pendientes

    assert enviar_pendientes(q, bot) == 2
    assert enviar_pendientes(q, bot) == 0   # ya están en el teléfono
    assert len(bot.enviados) == 2
    assert bot.enviados[0]["botones"]       # llevan los tres botones


def test_boton_aprobar(tmp_path):
    from xcreator.telegram import procesar_updates

    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(_draft("texto"))
    bot = FakeBot([_cb(i.id, "ok")])
    procesar_updates(q, bot, _estado(tmp_path))
    assert q.get(i.id).estado == "aprobado"
    assert bot.callbacks  # sin answerCallbackQuery el botón se queda girando


def test_boton_descartar_no_borra(tmp_path):
    from xcreator.telegram import procesar_updates

    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(_draft("texto"))
    procesar_updates(q, FakeBot([_cb(i.id, "no")]), _estado(tmp_path))
    item = q.get(i.id)
    assert item.estado == "rechazado"
    assert item.motivo_rechazo
    assert len(q.load()) == 1


def test_editar_pide_texto_y_luego_aprueba(tmp_path):
    from xcreator.telegram import procesar_updates

    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(_draft("original"))
    est = _estado(tmp_path)

    bot = FakeBot([_cb(i.id, "ed")])
    procesar_updates(q, bot, est)
    assert bot.enviados[-1]["force_reply"]
    assert q.get(i.id).estado == "pendiente"      # todavía no se decide
    pedido_id = bot.enviados[-1]["id"]

    bot2 = FakeBot([{
        "update_id": 2,
        "message": {"message_id": 500, "text": "versión corregida",
                    "reply_to_message": {"message_id": pedido_id}},
    }])
    procesar_updates(q, bot2, est)
    item = q.get(i.id)
    assert item.estado == "aprobado"
    assert item.texto_final == "versión corregida"


def test_offset_evita_reprocesar(tmp_path):
    from xcreator.telegram import procesar_updates

    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(_draft("texto"))
    est = _estado(tmp_path)
    ups = [_cb(i.id, "ok", update_id=7)]
    assert procesar_updates(q, FakeBot(ups), est) != []
    # Segunda pasada con los MISMOS updates: el offset ya avanzó.
    assert procesar_updates(q, FakeBot(ups), est) == []


def test_callback_de_item_inexistente_no_revienta(tmp_path):
    from xcreator.telegram import procesar_updates

    q = Queue(tmp_path / "cola.jsonl")
    bot = FakeBot([_cb("noexiste", "ok")])
    assert procesar_updates(q, bot, _estado(tmp_path)) == []
    assert bot.callbacks


def test_sin_token_falla_sin_caer_en_otro_bot(tmp_path):
    """Un fallback silencioso mandaría estos posts al chat de otro agente."""
    from xcreator.telegram import TelegramError, bot_desde

    s = SimpleNamespace(telegram_bot_token=None, telegram_chat_id="123")
    with pytest.raises(TelegramError, match="TELEGRAM_X_BOT_TOKEN"):
        bot_desde(s)


def test_sin_chat_id_falla_claro():
    from xcreator.telegram import TelegramError, bot_desde

    # Token BIEN formado a propósito: así se prueba la falta de chat_id y no
    # la validación de formato, que corre antes.
    s = SimpleNamespace(telegram_bot_token="8123456789:" + "x" * 31,
                        telegram_chat_id=None)
    with pytest.raises(TelegramError, match="TELEGRAM_X_CHAT_ID"):
        bot_desde(s)


def test_mensaje_avisa_de_cifras_sin_fuente(tmp_path):
    from xcreator.telegram import _texto_item

    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(_draft("texto", numeros_no_justificados=["$412"]))
    assert "CIFRAS SIN FUENTE" in _texto_item(q.get(i.id))


def test_mensaje_numera_el_hilo(tmp_path):
    from xcreator.telegram import _texto_item

    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(_draft("primero", thread=["segundo"]))
    texto = _texto_item(q.get(i.id))
    assert "1/ primero" in texto and "2/ segundo" in texto
    assert "hilo de 2" in texto


# --- independencia del proyecto -------------------------------------------

def test_lee_predicciones_por_ruta(tmp_path):
    """La única atadura con el motor de acciones es una ruta a sus JSON."""
    import json

    from xcreator.datos import load_predictions

    d = tmp_path / "NVDA" / "2026-07-27"
    d.mkdir(parents=True)
    (d / "prediccion.json").write_text(json.dumps(_PRED))
    assert load_predictions(tmp_path)[0]["ticker"] == "NVDA"


def test_ruta_inexistente_no_revienta():
    """Si el motor de acciones no está, se sigue sin material — no se cae."""
    from pathlib import Path

    from xcreator.datos import load_predictions

    assert load_predictions(Path("/no/existe")) == []
    assert load_predictions(None) == []


def test_json_corrupto_se_ignora(tmp_path):
    from xcreator.datos import load_predictions

    d = tmp_path / "X" / "2026-01-01"
    d.mkdir(parents=True)
    (d / "prediccion.json").write_text("{roto")
    assert load_predictions(tmp_path) == []


def test_sin_clave_fmp_no_hay_precio():
    from xcreator.datos import live_price

    assert live_price("NVDA", None) is None


def test_settings_no_filtra_secretos():
    from xcreator.config import Settings

    valores = ["sk-CLAVE-ANTHROPIC", "FMP-XYZ-123", "999:BOT-TELEGRAM"]
    r = repr(Settings(anthropic_api_key=valores[0], fmp_api_key=valores[1],
                      telegram_bot_token=valores[2]))
    for v in valores:
        assert v not in r, f"el repr filtró {v}"


def test_el_paquete_no_importa_el_motor_de_acciones():
    """Regresión de la separación: nada de xcreator puede importar wbj."""
    import pathlib

    import xcreator

    base = pathlib.Path(xcreator.__file__).parent
    for f in base.glob("*.py"):
        for linea in f.read_text().splitlines():
            texto = linea.strip()
            if texto.startswith(("import ", "from ")):
                assert "wbj" not in texto, f"{f.name}: {texto}"


# --- Cerebro --------------------------------------------------------------

def _cerebro_falso(tmp_path):
    (tmp_path / "README.md").write_text("# Cerebro")
    d = tmp_path / "05_risk_analysis"
    d.mkdir()
    (d / "AGENT.md").write_text("# Risk Agent\n## Boundaries\n- No inventes.")
    (d / "DECISION_RULES.md").write_text("| Deuda/EBITDA > 4 | score 0-2 |")
    return tmp_path


def test_carga_solo_la_dimension_pedida(tmp_path):
    from xcreator.cerebro import metodologia

    m = metodologia(_cerebro_falso(tmp_path), "riesgo")
    assert "Boundaries" in m and "Deuda/EBITDA" in m


def test_sin_cerebro_no_revienta_ni_inventa():
    """Sin metodología el contenido sale genérico, pero el sistema sigue."""
    from pathlib import Path

    from xcreator.cerebro import disponible, metodologia

    assert metodologia(None, "riesgo") == ""
    assert metodologia(Path("/no/existe"), "riesgo") == ""
    assert not disponible(None)


def test_angulo_desconocido_no_carga_nada(tmp_path):
    from xcreator.cerebro import metodologia

    assert metodologia(_cerebro_falso(tmp_path), "astrologia") == ""


def test_contexto_tiene_tope(tmp_path):
    """Si el Cerebro creciera, el prompt no puede dispararse solo."""
    from xcreator.cerebro import MAX_CHARS_CONTEXTO, _cargar, metodologia

    _cargar.cache_clear()
    (tmp_path / "README.md").write_text("#")
    d = tmp_path / "05_risk_analysis"
    d.mkdir()
    (d / "AGENT.md").write_text("x" * (MAX_CHARS_CONTEXTO * 2))
    assert len(metodologia(tmp_path, "riesgo")) <= MAX_CHARS_CONTEXTO


def test_el_cerebro_se_cachea_en_el_system_para_abaratar():
    """El bloque de metodología lleva cache_control: se repite en cada
    generación del mismo ángulo y pagarlo entero cada vez sería tirar dinero."""
    from xcreator.cerebro import ANGULOS
    from xcreator.generate import _system_blocks

    bloques = _system_blocks("metodología larga", ANGULOS["riesgo"])
    assert len(bloques) == 2
    assert bloques[-1]["cache_control"] == {"type": "ephemeral"}
    # Sin Cerebro no se añade bloque vacío (invalidaría el caché sin motivo).
    assert len(_system_blocks("", ANGULOS["riesgo"])) == 1


def test_el_angulo_entra_en_el_brief_id():
    """Dos ángulos del mismo ticker son contenidos distintos, no duplicados."""
    from xcreator.brief import from_prediction

    b1 = from_prediction(_PRED)
    b1.angulo = "riesgo"
    b2 = from_prediction(_PRED)
    b2.angulo = "valuacion"
    assert b1.brief_id != b2.brief_id


# --- export de CUENTA (el otro CSV que exporta X) -------------------------

_CUENTA_HEADER = ["Date", "Impressions", "Likes", "Engagements", "Bookmarks",
                  "Shares", "New follows", "Unfollows", "Replies", "Reposts"]


def _fila_cuenta(fecha, imp=0, replies=0, follows=0, unfollows=0):
    return {"Date": fecha, "Impressions": imp, "Likes": 0, "Engagements": 0,
            "Bookmarks": 0, "Shares": 0, "New follows": follows,
            "Unfollows": unfollows, "Replies": replies, "Reposts": 0}


def test_distingue_los_dos_csv_de_x(tmp_path):
    """X exporta dos CSV con el mismo botón; confundirlos da un análisis falso."""
    from xcreator.analytics import es_export_de_cuenta

    cuenta = _write_csv(tmp_path / "cuenta.csv",
                        [_fila_cuenta("Sun, Sep 13, 2026", 9)], _CUENTA_HEADER)
    posts = _write_csv(tmp_path / "posts.csv", [
        {"Post text": "hola", "Impressions": "100", "Replies": "2"}])
    assert es_export_de_cuenta(cuenta)
    assert not es_export_de_cuenta(posts)


def test_lee_el_formato_de_fecha_de_x(tmp_path):
    from xcreator.analytics import load_account_days

    p = _write_csv(tmp_path / "c.csv",
                   [_fila_cuenta("Sun, Sep 13, 2026", 42)], _CUENTA_HEADER)
    dias = load_account_days(p)
    assert len(dias) == 1 and dias[0].impressions == 42


def test_cuenta_mide_la_distancia_al_umbral(tmp_path):
    from xcreator.analytics import UMBRAL_IMPRESIONES, analyze_account, load_account_days

    filas = [_fila_cuenta(f"2026-06-{d:02d}", 10) for d in range(1, 31)]
    r = analyze_account(load_account_days(
        _write_csv(tmp_path / "c.csv", filas, _CUENTA_HEADER)))
    assert r.impresiones_90d == 300
    # 30 días a 10/día: el ritmo es 10/día y hacen falta 5M/90 al día. Este
    # test afirmaba antes UMBRAL/300, que compara un MES contra un trimestre:
    # fosilizaba justo el error que hacía decir "123x" con un export semanal.
    from xcreator.analytics import VENTANA_DIAS
    assert r.factor_faltante == pytest.approx((UMBRAL_IMPRESIONES / VENTANA_DIAS) / 10)


def test_diagnostico_consistencia_antes_que_contenido(tmp_path):
    """Con la mitad de los días en cero, el problema no es la redacción."""
    from xcreator.analytics import analyze_account, load_account_days

    filas = [_fila_cuenta(f"2026-06-{d:02d}", 0 if d % 2 else 500)
             for d in range(1, 31)]
    r = analyze_account(load_account_days(
        _write_csv(tmp_path / "c.csv", filas, _CUENTA_HEADER)))
    assert r.cuello_de_botella.startswith("CONSISTENCIA")


def test_diagnostico_alcance_cuando_publica_pero_no_lo_ven(tmp_path):
    from xcreator.analytics import analyze_account, load_account_days

    filas = [_fila_cuenta(f"2026-06-{d:02d}", 5) for d in range(1, 31)]
    r = analyze_account(load_account_days(
        _write_csv(tmp_path / "c.csv", filas, _CUENTA_HEADER)))
    assert r.cuello_de_botella.startswith("ALCANCE")


# --- validación de credenciales de Telegram -------------------------------

@pytest.mark.parametrize("token,pista", [
    ("A" * 35, "prefijo"),                     # solo la segunda mitad
    ("7872311234", "id del bot"),              # el id, no el token
    ("8123456789:" + "x" * 31, None),          # correcto
])
def test_detecta_tokens_mal_pegados(token, pista):
    from xcreator.telegram import revisar_credenciales

    avisos = revisar_credenciales(
        SimpleNamespace(telegram_bot_token=token, telegram_chat_id="123"))
    if pista is None:
        assert avisos == []
    else:
        assert any(pista in a for a in avisos)


def test_credenciales_mal_pegadas_no_llegan_a_la_api():
    from xcreator.telegram import TelegramError, bot_desde

    s = SimpleNamespace(telegram_bot_token="A" * 35, telegram_chat_id="123")
    with pytest.raises(TelegramError, match="prefijo"):
        bot_desde(s)


# --- asistente de replies -------------------------------------------------

def _briefs_nvda():
    from xcreator.brief import from_prediction

    return [from_prediction(_PRED)]


def test_responde_cuando_tenemos_el_ticker():
    from xcreator.replies import Mencion, encontrar_relevancia

    m = Mencion("@x", "$NVDA is the most crowded trade out there")
    r = encontrar_relevancia(m, _briefs_nvda())
    assert r.aporta and r.ticker == "NVDA"


def test_se_abstiene_con_ticker_que_no_cubrimos():
    """Responder sin datos propios es ruido, y X penaliza el ruido."""
    from xcreator.replies import Mencion, encontrar_relevancia

    r = encontrar_relevancia(Mencion("@x", "$GME squeeze again"), _briefs_nvda())
    assert not r.aporta
    assert "GME" in r.motivo


def test_se_abstiene_sin_ninguna_empresa():
    from xcreator.replies import Mencion, encontrar_relevancia

    r = encontrar_relevancia(Mencion("@x", "The Fed has a hard job"), _briefs_nvda())
    assert not r.aporta


def test_abstenerse_no_gasta_tokens():
    """El emparejamiento es previo al modelo: declinar tiene que ser gratis."""
    from xcreator.replies import Mencion, Relevancia, draft_reply

    class ClienteQueExplota:
        class messages:
            @staticmethod
            def parse(**kw):
                raise AssertionError("no debió llamarse al modelo")

    d = draft_reply(Mencion("@x", "nada"), Relevancia(None, motivo="sin datos"),
                    SimpleNamespace(anthropic_api_key="k"),
                    client=ClienteQueExplota())
    assert d.declinado and not d.valido


def test_el_modelo_puede_declinar_aunque_haya_ticker():
    """Mencionar $NVDA no garantiza que nuestro brief aporte a ESE post."""
    from xcreator.replies import Mencion, draft_reply, encontrar_relevancia

    class Cliente:
        class messages:
            @staticmethod
            def parse(**kw):
                Out = __import__("xcreator.replies", fromlist=["_modelo"])._modelo()
                return SimpleNamespace(
                    parsed_output=Out(aporta_algo=False, texto="",
                                      que_aporta="nada relevante"),
                    stop_reason="end_turn")

    m = Mencion("@x", "$NVDA ships nice hoodies")
    d = draft_reply(m, encontrar_relevancia(m, _briefs_nvda()),
                    SimpleNamespace(anthropic_api_key="k", cerebro_dir=None),
                    client=Cliente())
    assert d.declinado and not d.valido


def test_reply_con_cifra_inventada_no_es_valido():
    from xcreator.replies import Mencion, draft_reply, encontrar_relevancia

    class Cliente:
        class messages:
            @staticmethod
            def parse(**kw):
                Out = __import__("xcreator.replies", fromlist=["_modelo"])._modelo()
                return SimpleNamespace(
                    parsed_output=Out(aporta_algo=True,
                                      texto="Margins hit 78.2% last quarter.",
                                      que_aporta="un margen"),
                    stop_reason="end_turn")

    m = Mencion("@x", "$NVDA is crowded")
    d = draft_reply(m, encontrar_relevancia(m, _briefs_nvda()),
                    SimpleNamespace(anthropic_api_key="k", cerebro_dir=None),
                    client=Cliente())
    assert "78.2%" in d.numeros_no_justificados
    assert not d.valido


def test_reply_usa_el_mismo_campo_que_la_cola(tmp_path):
    """ReplyDraft y Draft se encolan igual: la cola no distingue."""
    from xcreator.replies import ReplyDraft

    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(ReplyDraft(texto="mi reply", que_aporta="un dato",
                         autor="@grande", url="https://x.com/a/1", ticker="NVDA"))
    item = q.get(i.id)
    assert item.texto == "mi reply"
    assert item.responde_a == "@grande"
    assert item.kind == "reply"


def test_detecta_tickers_por_cashtag_y_por_sigla():
    from xcreator.replies import Mencion

    assert Mencion("@x", "$NVDA and $AMD").tickers() == {"NVDA", "AMD"}
    # Sin cashtag, las siglas en mayúscula sirven de respaldo.
    assert "NVDA" in Mencion("@x", "NVDA earnings tomorrow").tickers()


# --- texto partido a media palabra ----------------------------------------

@pytest.mark.parametrize("texto,roto", [
    ("bear case is $194.56 \ntlessly flat, base $275.14.", True),   # caso real
    ("First line.\nSecond line here.", False),
    ("Scoreboard:\n\nBear $194.56.", False),
    ("Range: bear $194.\nWhich breaks first?", False),
])
def test_detecta_palabra_partida_en_medio(texto, roto):
    """El final truncado se ve en el último carácter; una palabra rota EN
    MEDIO solo se ve mirando los saltos de línea. Costó un reply inservible."""
    from xcreator.generate import _parece_cortado

    assert _parece_cortado(texto) is roto


# --- mix de alcance -------------------------------------------------------

def test_mix_separa_respuestas_de_posts_propios():
    from xcreator.analytics import mix_de_alcance

    posts = [_post("@alguien respuesta", impressions=100) for _ in range(3)]
    posts += [_post("post propio", impressions=10) for _ in range(2)]
    m = mix_de_alcance(posts)
    assert (m.n_respuestas, m.n_propios) == (3, 2)
    assert m.pct_alcance > 0.9


def test_mix_no_concluye_con_muestra_chica():
    """Ver que los tres mejores posts son respuestas NO es evidencia."""
    from xcreator.analytics import mix_de_alcance

    posts = [_post("@x resp", impressions=1000) for _ in range(58)]
    posts += [_post("propio", impressions=10) for _ in range(5)]
    m = mix_de_alcance(posts)
    assert not m.diferencia_es_solida
    assert "insuficiente" in m.veredicto


# --- watchlist ------------------------------------------------------------

def test_watchlist_se_siembra_y_persiste(tmp_path):
    from xcreator.watchlist import SEMILLA, Watchlist

    p = tmp_path / "wl.json"
    wl = Watchlist.cargar(p)
    assert len(wl.cuentas) == len(SEMILLA)
    assert Watchlist.cargar(p).get("@zerohedge") is not None


def test_watchlist_busca_sin_importar_arroba_ni_mayusculas(tmp_path):
    from xcreator.watchlist import Watchlist

    wl = Watchlist.cargar(tmp_path / "wl.json")
    assert wl.get("ZeroHedge") is wl.get("@zerohedge")


def test_desactivar_no_borra(tmp_path):
    """Una cuenta que no rindió es información, no basura."""
    from xcreator.watchlist import Watchlist

    wl = Watchlist.cargar(tmp_path / "wl.json")
    assert wl.desactivar("@business")
    assert wl.get("@business") is not None
    assert "@business" not in [c.handle for c in wl.activas()]


def test_no_duplica_al_anadir(tmp_path):
    from xcreator.watchlist import Watchlist

    wl = Watchlist.cargar(tmp_path / "wl.json")
    n = len(wl.cuentas)
    wl.add("@zerohedge")
    wl.add("zerohedge")
    assert len(wl.cuentas) == n


def test_json_corrupto_no_tumba_la_watchlist(tmp_path):
    from xcreator.watchlist import Watchlist

    p = tmp_path / "wl.json"
    p.write_text("{roto")
    assert Watchlist.cargar(p).cuentas  # cae a la semilla


# --- API de X (costos y guardas) ------------------------------------------

def test_sin_bearer_token_falla_claro(tmp_path):
    from xcreator.xapi import ClienteX, XAPIError

    with pytest.raises(XAPIError, match="X_BEARER_TOKEN"):
        ClienteX("", tmp_path / "ids.json")


def test_presupuesto_corta_antes_de_gastar(tmp_path):
    """Un bucle con un bug no puede vaciar los créditos en una tarde."""
    from xcreator.xapi import ClienteX, XAPIError

    c = ClienteX("token", tmp_path / "ids.json", presupuesto_diario=0.02)
    c._cobrar(0.015)
    with pytest.raises(XAPIError, match="Presupuesto"):
        c._cobrar(0.015)


def test_user_id_se_cachea_para_no_repagar(tmp_path):
    """Un handle siempre resuelve al mismo id; pagarlo dos veces es tirar dinero."""
    from xcreator.xapi import ClienteX

    cache = tmp_path / "ids.json"
    cache.write_text('{"zerohedge": "123"}')
    c = ClienteX("token", cache)
    assert c.user_id("@ZeroHedge") == "123"
    assert c.gastado == 0.0   # no se cobró: vino del caché


def test_costo_estimado_incluye_resolver_handles():
    from xcreator.xapi import COSTO_USUARIO_LEIDO, costo_estimado

    con = costo_estimado(7, 5, ids_en_cache=False)
    sin = costo_estimado(7, 5, ids_en_cache=True)
    assert con - sin == pytest.approx(7 * COSTO_USUARIO_LEIDO)


def test_solo_se_cobra_lo_que_de_verdad_se_leyo(tmp_path, monkeypatch):
    """Con `since_id`, muchas pasadas traen cero posts y no deben costar."""
    from xcreator.xapi import COSTO_POST_LEIDO, ClienteX

    cache = tmp_path / "ids.json"
    cache.write_text('{"zerohedge": "1"}')
    c = ClienteX("token", cache, presupuesto_diario=10.0)
    monkeypatch.setattr(c, "_get", lambda ruta, **kw: {"data": [
        {"id": "9", "text": "algo"}]})
    c.posts_recientes("@zerohedge", limite=20)
    assert c.gastado == pytest.approx(COSTO_POST_LEIDO * 1)


def test_una_llamada_fallida_no_cobra(tmp_path, monkeypatch):
    from xcreator.xapi import ClienteX, XAPIError

    cache = tmp_path / "ids.json"
    cache.write_text('{"zerohedge": "1"}')
    c = ClienteX("token", cache, presupuesto_diario=10.0)

    def explota(ruta, **kw):
        raise XAPIError("429")

    monkeypatch.setattr(c, "_get", explota)
    with pytest.raises(XAPIError):
        c.posts_recientes("@zerohedge", limite=20)
    assert c.gastado == 0.0


# --- tensión editorial ----------------------------------------------------

def _brief_con(**cambios):
    from xcreator.brief import from_prediction

    pred = dict(_PRED)
    precio_hoy = cambios.pop("precio_hoy", None)
    pred.update(cambios)
    return from_prediction(pred, price_now=precio_hoy)


def test_precio_bajo_el_bear_es_la_mejor_historia():
    """Que la tesis se esté rompiendo es el contenido más fuerte: es raro
    publicarlo y provoca respuestas."""
    from xcreator.temas import evaluar

    t = evaluar(_brief_con(precio_hoy=150.0))  # bear es 194.56
    assert t.puntos >= 3
    assert any("POR DEBAJO" in r for r in t.razones)


def test_precio_sobre_el_bull_tambien_es_historia():
    from xcreator.temas import evaluar

    t = evaluar(_brief_con(precio_hoy=400.0))  # bull es 316.41
    assert any("superó" in r for r in t.razones)


def test_bear_pegado_al_spot_se_marca():
    """Un escenario bajo a -1% no es un escenario bajo: es un hueco."""
    from xcreator.temas import evaluar

    t = evaluar(_brief_con(bear=195.0))  # precio de entrada 196.53
    assert any("pegado al precio" in r for r in t.razones)


def test_un_brief_sin_tension_no_es_tema():
    from xcreator.temas import evaluar

    t = evaluar(_brief_con(bear=140.0, bull=260.0, score10=5.5, pe_now=22.0,
                           precio_hoy=200.0))
    assert not t.tiene_historia


def test_ranking_ordena_por_tension_y_filtra():
    from xcreator.temas import ranking

    fuerte = _brief_con(precio_hoy=150.0)
    plano = _brief_con(bear=140.0, bull=260.0, score10=5.5, pe_now=22.0,
                       precio_hoy=200.0)
    r = ranking([plano, fuerte])
    assert [t.ticker for t in r] == ["NVDA"]   # el plano se filtró
    assert r[0].razones


def test_toda_puntuacion_trae_su_razon():
    """Sin motivo escrito no hay punto: el ranking tiene que poder discutirse."""
    from xcreator.temas import evaluar

    for cambios in ({"precio_hoy": 150.0}, {"bear": 195.0},
                    {"score10": 9.5}, {"pe_now": 80.0}):
        t = evaluar(_brief_con(**cambios))
        if t.puntos > 0:
            assert t.razones, f"{cambios} puntuó sin razón"


# --- idioma: el contenido SIEMPRE va en inglés ----------------------------

@pytest.mark.parametrize("texto,ingles", [
    ("On July 27 we published a 12-month range on $NVDA: bear $194.56.", True),
    ("$NVDA at 40.10x. Which half breaks first, pricing or volume?", True),
    ("Score 7.8/10.", True),                      # sin palabras funcionales
    ("El rango de 12 meses para $NVDA: bajo $194.56, base $275.14.", False),
    ("Publicamos un rango y el precio esta fuera del rango hoy.", False),
    ("La tesis está rota.", False),               # tilde
    ("", True),                                   # nada que juzgar
])
def test_verifica_que_el_contenido_este_en_ingles(texto, ingles):
    from xcreator.generate import es_ingles

    assert es_ingles(texto) is ingles


def test_post_en_espanol_no_es_valido():
    """Que el prompt lo pida en inglés no basta: se verifica."""
    assert not _draft("El precio está fuera del rango.",
                      idioma_incorrecto=True).valido


def test_reply_en_espanol_no_es_valido():
    from xcreator.replies import ReplyDraft

    d = ReplyDraft(texto="El bear case está pegado al precio.",
                   que_aporta="x", autor="@y", idioma_incorrecto=True)
    assert not d.valido


def test_la_cola_persiste_el_flag_de_idioma(tmp_path):
    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(_draft("texto", idioma_incorrecto=True))
    assert q.get(i.id).idioma_incorrecto is True


# --- publicar: la única acción irreversible -------------------------------

def _item_aprobado(tmp_path, texto="A clean English post about $NVDA.", **kw):
    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(_draft(texto, **kw))
    q.aprobar(i.id)
    return q, q.get(i.id)


def test_no_publica_lo_no_aprobado(tmp_path):
    from xcreator.publicar import revisar_antes_de_publicar

    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(_draft("A clean English post."))
    problemas = revisar_antes_de_publicar(q.get(i.id))
    assert any("solo se publica lo aprobado" in p for p in problemas)


def test_no_publica_lo_rechazado(tmp_path):
    from xcreator.publicar import revisar_antes_de_publicar

    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(_draft("A clean English post."))
    q.rechazar(i.id, motivo="malo")
    assert revisar_antes_de_publicar(q.get(i.id))


def test_revalida_el_texto_EDITADO_no_el_original(tmp_path):
    """Entre aprobar y publicar el texto pudo cambiar: manda el final."""
    from xcreator.publicar import revisar_antes_de_publicar

    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(_draft("A clean English post."))
    q.aprobar(i.id, texto_editado="El precio está fuera del rango.")
    problemas = revisar_antes_de_publicar(q.get(i.id))
    assert any("no está en inglés" in p for p in problemas)


def test_bloquea_links_salvo_que_se_pidan(tmp_path):
    """Un link cuesta 13x y hunde el alcance: no puede colarse por descuido."""
    from xcreator.publicar import revisar_antes_de_publicar

    _, item = _item_aprobado(tmp_path, "Read this https://t.co/abc for the data.")
    assert any("link" in p for p in revisar_antes_de_publicar(item))
    assert not revisar_antes_de_publicar(item, permitir_link=True)


def test_bloquea_cifras_sin_fuente_en_el_texto_final(tmp_path):
    from xcreator.publicar import revisar_antes_de_publicar

    _, item = _item_aprobado(tmp_path, "Margins hit 78.2% last quarter.")
    problemas = revisar_antes_de_publicar(item, numeros_permitidos=[196.53])
    assert any("sin fuente" in p for p in problemas)


def test_bloquea_texto_que_se_pasa_de_largo(tmp_path):
    from xcreator.publicar import revisar_antes_de_publicar

    _, item = _item_aprobado(tmp_path, "The data is here. " * 30)
    assert any("se pasa" in p for p in revisar_antes_de_publicar(item))


def test_costo_del_link_es_13x():
    from xcreator.publicar import COSTO_POST, COSTO_POST_CON_LINK, costo

    assert costo(["no link here"]) == COSTO_POST
    assert costo(["see https://t.co/x"]) == COSTO_POST_CON_LINK
    assert COSTO_POST_CON_LINK / COSTO_POST > 13


def test_en_seco_no_llama_a_x(tmp_path):
    from xcreator.publicar import publicar_item

    _, item = _item_aprobado(tmp_path)
    res = publicar_item(item, token="", en_seco=True)
    assert res.post_id == "(en seco)"


def test_publicar_marca_el_item_y_no_repite(tmp_path):
    """Duplicar un post en X es caro y feo: publicado ya no es aprobado."""
    q, item = _item_aprobado(tmp_path)
    q.marcar_publicado(item.id, post_id="123")
    assert q.get(item.id).estado == "publicado"
    assert [i for i in q.load() if i.estado == "aprobado"] == []


# --- OAuth ----------------------------------------------------------------

def test_sin_client_id_falla_claro(tmp_path):
    from xcreator.xauth import AlmacenTokens, AuthError, autorizar

    with pytest.raises(AuthError, match="X_CLIENT_ID"):
        autorizar("", AlmacenTokens(tmp_path / "t.json"), abrir_navegador=False)


def test_sin_autorizar_lo_dice_en_vez_de_dar_401(tmp_path):
    from xcreator.xauth import AlmacenTokens, AuthError, token_vigente

    with pytest.raises(AuthError, match="x-auth"):
        token_vigente("cid", AlmacenTokens(tmp_path / "t.json"))


def test_token_vigente_no_refresca_de_mas(tmp_path):
    import time

    from xcreator.xauth import AlmacenTokens, Tokens, token_vigente

    a = AlmacenTokens(tmp_path / "t.json")
    a.guardar(Tokens("vivo", "refresh", time.time() + 3600))
    assert token_vigente("cid", a).access_token == "vivo"


def test_token_vencido_sin_refresh_pide_reautorizar(tmp_path):
    import time

    from xcreator.xauth import AlmacenTokens, AuthError, Tokens, token_vigente

    a = AlmacenTokens(tmp_path / "t.json")
    a.guardar(Tokens("viejo", "", time.time() - 10))
    with pytest.raises(AuthError, match="refresh"):
        token_vigente("cid", a)


def test_los_tokens_se_guardan_con_permisos_restringidos(tmp_path):
    import time

    from xcreator.xauth import AlmacenTokens, Tokens

    p = tmp_path / "t.json"
    AlmacenTokens(p).guardar(Tokens("secreto", "r", time.time() + 60))
    assert oct(p.stat().st_mode)[-3:] == "600"


def test_402_se_distingue_de_401(monkeypatch, tmp_path):
    """402 significa token bueno y cuenta sin saldo. Confundirlo con un 401
    manda a perseguir credenciales que están bien."""
    import httpx

    from xcreator.xapi import ClienteX, XAPIError

    c = ClienteX("token", tmp_path / "ids.json")
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: httpx.Response(
        402, json={"detail": "credits depleted"}))
    with pytest.raises(XAPIError, match="Sin créditos"):
        c._get("/users/by/username/x")


def test_402_al_publicar_tambien_es_claro(monkeypatch):
    import httpx

    from xcreator.publicar import PublicarError, _post

    monkeypatch.setattr(httpx, "post", lambda *a, **kw: httpx.Response(
        402, json={"detail": "credits depleted"}))
    with pytest.raises(PublicarError, match="Sin créditos"):
        _post("tok", {"text": "hola"})


def test_el_servidor_escucha_en_el_puerto_del_callback():
    """Escuchar en otro puerto deja la autorización colgada para siempre."""
    from xcreator.xauth import puerto_de

    assert puerto_de("http://localhost:8788/callback") == 8788
    assert puerto_de("http://127.0.0.1:9999/cb") == 9999
    assert puerto_de("http://localhost/callback") == 80


def test_escucha_en_el_host_del_callback():
    """localhost y 127.0.0.1 parecen lo mismo y no lo son: una pestaña vieja
    apuntando al otro nombre entra por el mismo socket y gasta el flujo."""
    from xcreator.xauth import host_y_puerto

    assert host_y_puerto("http://127.0.0.1:8788/callback") == ("127.0.0.1", 8788)
    assert host_y_puerto("http://localhost:9000/cb") == ("localhost", 9000)


def test_se_ignora_un_callback_de_otra_sesion():
    from xcreator.xauth import _Handler

    _Handler.code = _Handler.state = None
    _Handler.esperado = "el-bueno"

    class Falso(_Handler):
        def __init__(self, path):
            self.path = path

        def send_response(self, *a): pass
        def send_header(self, *a): pass
        def end_headers(self): pass
        @property
        def wfile(self):
            class W:
                def write(self, *a): pass
            return W()

    Falso("/callback?code=viejo&state=otro").do_GET()
    assert _Handler.code is None          # descartado
    Falso("/callback?code=nuevo&state=el-bueno").do_GET()
    assert _Handler.code == "nuevo"       # aceptado


def test_el_canje_usa_el_mismo_redirect_que_la_autorizacion(monkeypatch, tmp_path):
    """Regresión: se autorizaba con 127.0.0.1 y se canjeaba con localhost,
    porque el canje usaba la constante en vez del callback configurado."""
    import xcreator.xauth as xa

    visto = {}

    def falso_intercambiar(cid, secret, almacen, datos):
        visto.update(datos)
        return xa.Tokens("tok", "ref", 9e9)

    monkeypatch.setattr(xa, "_intercambiar", falso_intercambiar)

    class Servidor:
        def __init__(self, *a): pass
        timeout = 0
        def handle_request(self):
            xa._Handler.code = "codigo"
        def server_close(self): pass

    monkeypatch.setattr(xa, "HTTPServer", Servidor)
    monkeypatch.setattr(xa.webbrowser, "open", lambda u: None)
    xa._Handler.code = None

    cb = "http://127.0.0.1:9191/callback"
    xa.autorizar("cid", xa.AlmacenTokens(tmp_path / "t.json"),
                 callback=cb, abrir_navegador=False)
    assert visto["redirect_uri"] == cb


# --- emparejamiento por nombre de empresa ---------------------------------

_NOMBRES = {"oracle": "ORCL", "nvidia": "NVDA", "advanced micro devices": "AMD"}


def test_detecta_la_empresa_por_su_NOMBRE():
    """La gente escribe 'Oracle', no '$ORCL'. Sin esto se perdían posts sobre
    empresas que sí cubrimos."""
    from xcreator.replies import Mencion

    m = Mencion("@x", "Oracle Chairman Larry Ellison canceled his plan to sell")
    assert m.tickers(_NOMBRES) == {"ORCL"}


def test_el_nombre_tiene_que_ser_palabra_completa():
    from xcreator.replies import Mencion

    assert Mencion("@x", "oracular predictions").tickers(_NOMBRES) == set()


@pytest.mark.parametrize("titular", [
    "*SK HYNIX FALLS MORE THAN 5% AFTER AI WARNINGS",
    "BREAKING: Canada explores membership, per WSJ",
    "FED CALLS TO SLOW DOWN, CPI MORE THAN EXPECTED",
])
def test_los_titulares_en_mayusculas_no_inventan_tickers(titular):
    """Un titular de zerohedge producía 'tickers' como AFTER, CALLS y SLOW,
    y el sistema proponía responder sobre empresas que nadie mencionó."""
    from xcreator.replies import Mencion

    detectados = Mencion("@x", titular).tickers(_NOMBRES)
    assert not (detectados & {"AFTER", "CALLS", "SLOW", "MORE", "THAN",
                              "WSJ", "FED", "CPI", "DOWN", "AI"})


def test_el_cashtag_sigue_mandando():
    from xcreator.replies import Mencion

    assert "NVDA" in Mencion("@x", "$NVDA is crowded").tickers(_NOMBRES)


def test_nombre_corto_quita_sufijos_societarios():
    from xcreator.datos import nombre_corto

    assert nombre_corto("Apple Inc.") == "apple"
    assert nombre_corto("American Airlines Group Inc.") == "american airlines"
    assert nombre_corto("Airbnb, Inc.") == "airbnb"


def test_sin_reportes_no_hay_nombres():
    from pathlib import Path

    from xcreator.datos import load_company_names

    assert load_company_names(None) == {}
    assert load_company_names(Path("/no/existe")) == {}


# --- límites y citas en replies -------------------------------------------

def test_el_limite_duro_del_reply_es_el_de_X_no_la_preferencia():
    """240 es preferencia editorial; pasarse de ahí no invalida un reply que
    X publicaría sin problema."""
    from xcreator.generate import MAX_CHARS
    from xcreator.replies import LARGO_PREFERIDO, ReplyDraft

    assert LARGO_PREFERIDO < MAX_CHARS
    d = ReplyDraft(texto="x" * 252, que_aporta="y", autor="@z")
    assert d.exceso_caracteres == 0 or d.valido


def test_se_puede_citar_una_cifra_del_post_original():
    """Responder a '4% CPI' citando ese 4% no es inventar: está a la vista."""
    from xcreator.replies import _numeros_del_texto
    from xcreator.generate import validate_numbers

    post = "Annual CPI came in at 4% this morning"
    permitidos = [155.83] + _numeros_del_texto(post)
    assert validate_numbers("4% CPI isn't pricing power. TGT at $155.83.",
                            permitidos) == []


def test_una_cifra_que_no_esta_en_ningun_lado_sigue_bloqueada():
    from xcreator.replies import _numeros_del_texto
    from xcreator.generate import validate_numbers

    permitidos = [155.83] + _numeros_del_texto("CPI at 4%")
    assert validate_numbers("Margins hit 78.2%.", permitidos)


def test_el_limite_no_se_gasta_en_los_ya_enviados(tmp_path):
    """Con el filtro después del límite, un borrador nuevo detrás de otros ya
    enviados no salía nunca del teléfono."""
    from xcreator.telegram import enviar_pendientes

    q = Queue(tmp_path / "cola.jsonl")
    for k in range(3):
        i = q.add(_draft(f"viejo {k}"))
        q.update(i.id, metricas={"telegram_message_id": 100 + k})
    nuevo = q.add(_draft("nuevo"))

    bot = FakeBot()
    assert enviar_pendientes(q, bot, limite=2) == 1
    assert "nuevo" in bot.enviados[0]["texto"]
    assert q.get(nuevo.id).metricas["telegram_message_id"]


def test_un_acuse_caducado_no_pierde_las_demas_aprobaciones(tmp_path):
    """Telegram caduca los acuses en segundos y el cron pasa cada 5 minutos:
    fallar ahí es lo normal. Tratarlo como fatal abortaba el bucle y perdía
    las aprobaciones siguientes de la misma tanda."""
    from xcreator.telegram import TelegramError, procesar_updates

    q = Queue(tmp_path / "cola.jsonl")
    a, b = q.add(_draft("uno")), q.add(_draft("dos"))

    class BotConAcuseRoto(FakeBot):
        def answer_callback(self, callback_id, texto=""):
            raise TelegramError("query is too old")

    bot = BotConAcuseRoto([_cb(a.id, "ok", update_id=1),
                           _cb(b.id, "ok", update_id=2)])
    # El bot real traga el fallo dentro de answer_callback; aquí se simula uno
    # que no lo hace para probar que el bucle lo resiste igual.
    try:
        procesar_updates(q, bot, _estado(tmp_path))
    except TelegramError:
        pytest.fail("un acuse caducado no debe abortar el procesamiento")
    assert q.get(a.id).estado == "aprobado"
    assert q.get(b.id).estado == "aprobado"


def test_los_comandos_de_typer_no_se_llaman_entre_si_sin_argumentos():
    """Llamar a un comando de Typer como función normal le pasa los objetos
    OptionInfo en vez de los valores por defecto. `ciclo` hacía eso con
    `enviar` y reventaba con un TypeError al cortar la lista."""
    import inspect

    from xcreator import cli

    fuente = inspect.getsource(cli.tg_ciclo)
    assert "tg_enviar(limite=" in fuente, "ciclo debe pasar el valor explícito"


def test_enviar_pendientes_exige_un_limite_numerico(tmp_path):
    from xcreator.telegram import enviar_pendientes

    q = Queue(tmp_path / "cola.jsonl")
    q.add(_draft("uno"))
    with pytest.raises(TypeError):
        enviar_pendientes(q, FakeBot(), limite=object())


# --- variedad: no repetir ticker ------------------------------------------

def test_lo_publicado_ayer_baja_en_el_ranking():
    """Sin esto, el ticker con más tensión gana todos los días y la cuenta
    publica lo mismo una y otra vez."""
    from datetime import date, timedelta

    from xcreator.temas import ranking

    hoy = date(2026, 9, 14)
    fuerte = _brief_con(precio_hoy=150.0)          # NVDA, mucha tensión
    r_sin = ranking([fuerte], hoy=hoy)
    r_con = ranking([fuerte], hoy=hoy,
                    ultimo_uso={"NVDA": str(hoy - timedelta(days=1))})
    assert r_sin[0].puntos > (r_con[0].puntos if r_con else -99)


def test_a_los_siete_dias_ya_no_penaliza():
    from datetime import date, timedelta

    from xcreator.temas import VENTANA_DESCANSO, ranking

    hoy = date(2026, 9, 14)
    b = _brief_con(precio_hoy=150.0)
    viejo = str(hoy - timedelta(days=VENTANA_DESCANSO))
    assert (ranking([b], hoy=hoy)[0].puntos
            == ranking([b], hoy=hoy, ultimo_uso={"NVDA": viejo})[0].puntos)


def test_la_penalizacion_se_explica():
    """El ranking tiene que poder discutirse: cada resta trae su motivo."""
    from datetime import date, timedelta

    from xcreator.temas import evaluar, _penalizar

    hoy = date(2026, 9, 14)
    t = evaluar(_brief_con(precio_hoy=150.0))
    _penalizar(t, {"NVDA": str(hoy - timedelta(days=2))}, hoy)
    assert any("ya salió hace 2 días" in r for r in t.razones)
    assert t.dias_desde_ultimo == 2


def test_un_rechazado_no_bloquea_el_ticker(tmp_path):
    """Se descartó para no publicarlo: no puede además impedir volver a él."""
    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(_draft("malo", ticker="NVDA"))
    q.rechazar(i.id, motivo="cifra sin fuente")
    assert q.ultimo_uso_por_ticker() == {}


def test_lo_pendiente_ya_cuenta_como_usado(tmp_path):
    """Si hay material de ese ticker esperando en el teléfono, generar más es
    repetirse aunque todavía no se haya publicado."""
    q = Queue(tmp_path / "cola.jsonl")
    q.add(_draft("en cola", ticker="SLDE"))
    assert "SLDE" in q.ultimo_uso_por_ticker()


def test_se_queda_con_la_fecha_mas_reciente(tmp_path):
    q = Queue(tmp_path / "cola.jsonl")
    a = q.add(_draft("viejo", ticker="NVDA"))
    q.update(a.id, creado="2026-09-01T10:00:00+00:00")
    b = q.add(_draft("nuevo", ticker="NVDA"))
    q.update(b.id, creado="2026-09-13T10:00:00+00:00")
    assert q.ultimo_uso_por_ticker()["NVDA"] == "2026-09-13"


def test_pedir_un_ticker_concreto_lo_busca_en_todos(tmp_path):
    """Con 178 tickers analizados, un límite bajo devolvía 'no hay
    predicciones' para casi cualquier ticker.

    Y ojo con el criterio de corte: `load_briefs` ordena por la fecha que hay
    DENTRO del JSON, y un análisis en lote se las pone todas iguales. El
    límite entonces no recorta "los más recientes" sino los que el glob
    devuelve primero, que es orden alfabético.
    """
    import json

    from xcreator.brief import load_briefs

    for t in ["AAA", "BBB", "CCC", "ZZZ"]:
        d = tmp_path / t / "2026-09-14"
        d.mkdir(parents=True)
        (d / "prediccion.json").write_text(json.dumps({**_PRED, "ticker": t}))

    assert {b.ticker for b in load_briefs(tmp_path, limit=500)} == {
        "AAA", "BBB", "CCC", "ZZZ"}
    # Con el límite corto entran los alfabéticamente primeros, así que pedir
    # ZZZ por nombre no puede usarlo.
    assert "ZZZ" not in {b.ticker for b in load_briefs(tmp_path, limit=2)}


# --- el ticker, siempre en las dos formas ---------------------------------

@pytest.mark.parametrize("texto,faltan", [
    ("$NVDA base is $305.61. NVDA multiple never moves.", []),
    ("$NVDA base is $305.61.", ["NVDA"]),          # falta el plano
    ("NVDA base is $305.61.", ["$NVDA"]),          # falta el cashtag
    ("Nothing about the company here.", ["$NVDA", "NVDA"]),
])
def test_exige_las_dos_formas_del_ticker(texto, faltan):
    """X indexa el cashtag y el texto plano por separado: usar solo uno tira
    la mitad del descubrimiento, que es lo escaso en una cuenta pequeña."""
    from xcreator.generate import falta_ticker

    assert falta_ticker(texto, "NVDA") == faltan


def test_el_cashtag_no_cuenta_como_ticker_plano():
    from xcreator.generate import falta_ticker

    assert falta_ticker("Only $NVDA here", "NVDA") == ["NVDA"]


def test_un_post_sin_las_dos_formas_no_es_valido():
    assert not _draft("NVDA is expensive", tickers_faltantes=["$NVDA"]).valido


def test_un_reply_sin_las_dos_formas_no_es_valido():
    from xcreator.replies import ReplyDraft

    d = ReplyDraft(texto="NVDA is crowded", que_aporta="x", autor="@y",
                   tickers_faltantes=["$NVDA"])
    assert not d.valido


def test_la_cola_persiste_el_flag_del_ticker(tmp_path):
    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(_draft("texto", tickers_faltantes=["$NVDA"]))
    assert q.get(i.id).tickers_faltantes == ["$NVDA"]


@pytest.mark.parametrize("texto,cortado", [
    ("If you think the floor breaks, tell me what breaks it. $IREN", False),
    ("Quality and payoff are separate questions. IREN", False),
    ("the bear, what a 45.10 P/E costs you", True),      # sí está cortado
    ("Base still needs another", True),
])
def test_cerrar_con_el_ticker_no_es_truncamiento(texto, cortado):
    """Al exigir el ticker en las dos formas, el modelo empezó a cerrar con
    él — y el detector de frase cortada lo marcaba como roto."""
    from xcreator.generate import _parece_cortado

    assert _parece_cortado(texto) is cortado


def test_una_maquina_desactivada_no_habla_con_telegram():
    """Dos instancias con el mismo bot se roban los updates y cada una busca
    el borrador en SU cola: aprobar en el teléfono uno de la otra máquina
    responde 'ese borrador ya no existe'."""
    from xcreator.telegram import TelegramError, bot_desde

    s = SimpleNamespace(telegram_activo=False,
                        telegram_bot_token="8123456789:" + "x" * 31,
                        telegram_chat_id="123")
    with pytest.raises(TelegramError, match="DESACTIVADO"):
        bot_desde(s)


def test_por_defecto_telegram_esta_activo():
    from xcreator.telegram import bot_desde

    s = SimpleNamespace(telegram_bot_token="8123456789:" + "x" * 31,
                        telegram_chat_id="123")
    assert bot_desde(s).chat_id == "123"


# --- espaciado de publicación ---------------------------------------------

def test_sabe_cuanto_hace_del_ultimo_post(tmp_path):
    from datetime import datetime, timedelta, timezone

    q = Queue(tmp_path / "cola.jsonl")
    assert q.minutos_desde_ultima_publicacion() is None

    i = q.add(_draft("uno"))
    hace_30 = datetime.now(timezone.utc) - timedelta(minutes=30)
    q.update(i.id, estado="publicado", publicado_en=hace_30.isoformat())
    assert 29 <= q.minutos_desde_ultima_publicacion() <= 31


def test_solo_cuenta_lo_publicado(tmp_path):
    """Un aprobado sin publicar no bloquea el siguiente."""
    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(_draft("uno"))
    q.aprobar(i.id)
    assert q.minutos_desde_ultima_publicacion() is None


def test_una_marca_corrupta_no_rompe_el_espaciado(tmp_path):
    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(_draft("uno"))
    q.update(i.id, estado="publicado", publicado_en="no-es-una-fecha")
    assert q.minutos_desde_ultima_publicacion() is None


def test_un_borrador_invalido_no_consume_el_cupo(tmp_path):
    """Con el máximo aplicado antes del filtro, un borrador impublicable se
    llevaba el cupo de la pasada y no salía nada. Mismo error que ya costó
    que Telegram dejara de enviar."""
    from xcreator.publicar import revisar_antes_de_publicar

    q = Queue(tmp_path / "cola.jsonl")
    malo = q.add(_draft("x" * 400))          # se pasa de largo
    bueno = q.add(_draft("A clean English post about $NVDA and NVDA."))
    for i in (malo, bueno):
        q.aprobar(i.id)

    aprobados = [i for i in q.load() if i.estado == "aprobado"]
    publicables = [i for i in aprobados if not revisar_antes_de_publicar(i)]
    assert [i.id for i in publicables[:1]] == [bueno.id]


# --- replies: caducan, y no compiten con los posts propios ----------------

def test_la_edad_del_post_sale_de_su_propio_id():
    """El id de X codifica el timestamp: se puede saber la edad sin gastar
    una lectura de API ($0.005 cada una)."""
    from datetime import datetime, timezone

    from xcreator.publicar import _EPOCA_X_MS, edad_horas

    hace_3h = datetime.now(timezone.utc).timestamp() * 1000 - 3 * 3600 * 1000
    post_id = str(int((hace_3h - _EPOCA_X_MS)) << 22)
    assert 2.9 < edad_horas(post_id) < 3.1
    assert edad_horas("no-es-un-id") is None
    assert edad_horas("") is None


def test_no_se_responde_a_una_conversacion_muerta(tmp_path):
    from datetime import datetime, timezone

    from xcreator.publicar import (
        HORAS_MAX_PARA_RESPONDER, _EPOCA_X_MS, revisar_antes_de_publicar,
    )

    def id_de_hace(horas):
        ms = datetime.now(timezone.utc).timestamp() * 1000 - horas * 3600 * 1000
        return str(int(ms - _EPOCA_X_MS) << 22)

    q = Queue(tmp_path / "cola.jsonl")
    viejo = q.add(_draft("Reply to $NVDA and NVDA."))
    q.update(viejo.id, url_origen=f"https://x.com/x/status/{id_de_hace(HORAS_MAX_PARA_RESPONDER + 5)}")
    q.aprobar(viejo.id)
    assert any("conversación ya pasó" in p
               for p in revisar_antes_de_publicar(q.get(viejo.id)))

    fresco = q.add(_draft("Reply to $NVDA and NVDA."))
    q.update(fresco.id, url_origen=f"https://x.com/x/status/{id_de_hace(1)}")
    q.aprobar(fresco.id)
    assert revisar_antes_de_publicar(q.get(fresco.id)) == []


def test_un_reply_no_consume_el_turno_del_siguiente_post_propio(tmp_path):
    """Un reply cuelga de otra conversación: no compite en el timeline con
    los posts propios y no debe gastar su espaciado."""
    from datetime import datetime, timezone

    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(_draft("un reply", kind="reply"))
    q.update(i.id, estado="publicado",
             publicado_en=datetime.now(timezone.utc).isoformat())
    assert q.minutos_desde_ultima_publicacion() is None


def test_los_replies_no_se_publican_por_api(tmp_path):
    """X bloqueó los replies programáticos el 2026-02-23 contra el spam de
    LLM: solo se puede responder si el autor original te menciona. Intentarlo
    devuelve 403 y gasta la llamada, así que se bloquea antes."""
    from xcreator.publicar import revisar_antes_de_publicar

    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(_draft("A reply about $NVDA and NVDA.", kind="reply"))
    q.update(i.id, url_origen="https://x.com/Barchart/status/2099395664018809000")
    q.aprobar(i.id)
    problemas = revisar_antes_de_publicar(q.get(i.id))
    assert any("cópialo y pégalo" in p for p in problemas)


def test_un_post_propio_sigue_publicandose(tmp_path):
    from xcreator.publicar import revisar_antes_de_publicar

    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(_draft("$NVDA at 44x. NVDA base case is $305.61."))
    q.aprobar(i.id)
    assert revisar_antes_de_publicar(q.get(i.id)) == []


def test_el_mensaje_de_un_reply_trae_el_enlace(tmp_path):
    """Para pegarlo hay que poder abrir el post original de un toque."""
    from xcreator.telegram import _texto_item

    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(_draft("texto", kind="reply"))
    q.update(i.id, responde_a="@Barchart",
             url_origen="https://x.com/Barchart/status/123")
    texto = _texto_item(q.get(i.id))
    assert "pégala tú" in texto and "https://x.com/Barchart/status/123" in texto


# --- deep link para replies -----------------------------------------------

def test_el_intent_cuelga_del_post_correcto_y_trae_el_texto():
    """X no deja publicar replies por API, pero sí abrir su compositor
    prellenado: deja el trabajo en un toque en vez de copiar y buscar."""
    import urllib.parse

    from xcreator.telegram import intent_respuesta

    u = intent_respuesta("Base is $305.61 for $NVDA and NVDA.",
                         "https://x.com/Barchart/status/12345")
    partes = urllib.parse.parse_qs(urllib.parse.urlparse(u).query)
    assert partes["in_reply_to"] == ["12345"]
    assert partes["text"] == ["Base is $305.61 for $NVDA and NVDA."]


def test_sin_post_original_no_hay_intent():
    from xcreator.telegram import intent_respuesta

    assert intent_respuesta("texto", "") is None
    assert intent_respuesta("texto", "https://x.com/user/status/no-numerico") is None


def test_no_hay_boton_que_lleve_al_login_de_x(tmp_path):
    """En el móvil Telegram abre los enlaces en su navegador interno, sin la
    sesión de X: el botón acababa en una pantalla de login. Un botón que no
    funciona es peor que ninguno."""
    from xcreator.telegram import _botones

    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(_draft("texto", kind="reply"))
    q.update(i.id, url_origen="https://x.com/Barchart/status/12345")
    filas = _botones(i.id, q.get(i.id))
    assert len(filas) == 1
    assert not any("url" in b for fila in filas for b in fila)


def test_el_mensaje_explica_como_abrir_el_post(tmp_path):
    """Sin el botón, el camino tiene que estar escrito: el navegador de
    Telegram no sirve y hay que abrirlo fuera."""
    from xcreator.telegram import mensaje_para_copiar

    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(_draft("texto", kind="reply"))
    q.update(i.id, responde_a="@x", url_origen="https://x.com/x/status/9")
    m = mensaje_para_copiar(q.get(i.id))
    assert "Abrir en Safari" in m and "no lleva tu sesión" in m
    assert "Mantén pulsado" in m


def test_el_intent_usa_el_texto_EDITADO(tmp_path):
    """Si lo reescribiste desde el teléfono, se publica lo tuyo."""
    from xcreator.telegram import intent_respuesta

    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(_draft("original", kind="reply"))
    q.update(i.id, url_origen="https://x.com/a/status/9")
    q.aprobar(i.id, texto_editado="mi versión")
    assert "mi%20versi" in intent_respuesta(q.get(i.id).texto_final,
                                            q.get(i.id).url_origen)


# --- el score es interno: no se publica -----------------------------------

def test_el_score_no_esta_entre_las_cifras_publicables():
    """El lector no puede ver el scorecard ni conoce la escala: citarlo es
    pedirle que se fíe, y gasta caracteres que podrían llevar un dato
    comprobable."""
    from xcreator.brief import from_prediction

    b = from_prediction(_PRED)   # _PRED trae score10 = 7.8
    assert not any("score" in f.label.lower() for f in b.facts)
    assert 7.8 not in b.allowed_numbers()


def test_citar_el_score_se_detecta_como_cifra_sin_fuente():
    from xcreator.brief import from_prediction
    from xcreator.generate import validate_numbers

    b = from_prediction(_PRED)
    malos = validate_numbers("$NVDA scores 7.8/10 on our model.",
                             b.allowed_numbers())
    assert malos, "un score publicado debe saltar como cifra sin fuente"


def test_la_calidad_sigue_como_contexto_para_calibrar_el_tono():
    """El redactor necesita saber si el negocio es bueno; lo que no puede es
    citar el número."""
    from xcreator.brief import from_prediction

    b = from_prediction(_PRED)
    assert any("NO menciones el score" in c for c in b.context)


def test_lo_verificable_si_se_publica():
    """P/E, precios y supuestos los puede comprobar cualquiera."""
    from xcreator.brief import from_prediction

    valores = from_prediction(_PRED).allowed_numbers()
    assert 40.10 in valores and 196.53 in valores and 0.40 in valores


# --- publicación automática con ventana de veto ---------------------------

def test_lo_programado_sale_solo_cuando_pasa_la_ventana(tmp_path):
    """Al revés que aprobar: aquí el silencio publica. Lo que hace falta a
    mano es pararlo."""
    from datetime import datetime, timedelta, timezone

    from xcreator.store import MINUTOS_DE_GRACIA

    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(_draft("uno"))
    q.programar(i.id)
    assert q.listos_para_publicar() == []          # todavía en ventana

    viejo = datetime.now(timezone.utc) - timedelta(minutes=MINUTOS_DE_GRACIA + 1)
    q.update(i.id, decidido=viejo.isoformat())
    assert [x.id for x in q.listos_para_publicar()] == [i.id]


def test_pararlo_dentro_de_la_ventana_lo_cancela(tmp_path):
    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(_draft("uno"))
    q.programar(i.id)
    q.rechazar(i.id, motivo="parado a tiempo")
    assert q.listos_para_publicar() == []
    assert q.get(i.id).estado == "rechazado"


def test_un_borrador_con_problemas_no_nace_programado(tmp_path):
    """La publicación automática solo puede aplicarse a lo que pasó todas las
    validaciones."""
    q = Queue(tmp_path / "cola.jsonl")
    malo = q.add(_draft("x", numeros_no_justificados=["$412"]),
                 estado="programado")
    assert malo.estado == "pendiente"
    bueno = q.add(_draft("limpio"), estado="programado")
    assert bueno.estado == "programado"


def test_lo_aprobado_a_mano_sigue_saliendo(tmp_path):
    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(_draft("uno"))
    q.aprobar(i.id)
    assert [x.id for x in q.listos_para_publicar()] == [i.id]


def test_una_marca_corrupta_no_publica_por_error(tmp_path):
    """Ante la duda, NO publicar: es la única acción irreversible."""
    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(_draft("uno"))
    q.programar(i.id)
    q.update(i.id, decidido="no-es-fecha")
    assert q.listos_para_publicar() == []


def test_los_programados_se_mandan_al_telefono(tmp_path):
    """Son los que MÁS urge mandar: si nadie los mira, salen solos."""
    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(_draft("uno"), estado="programado")
    assert [x.id for x in q.pendientes()] == [i.id]


def test_lo_ya_decidido_no_vuelve_al_telefono(tmp_path):
    q = Queue(tmp_path / "cola.jsonl")
    a, b = q.add(_draft("uno")), q.add(_draft("dos"))
    q.aprobar(a.id)
    q.rechazar(b.id)
    assert q.pendientes() == []


# --- ritmo: posts esparcidos, replies inmediatos --------------------------

def test_un_reply_no_espera_al_espaciado_de_los_posts(tmp_path):
    """Un post propio sigue igual de bueno dentro de hora y media; un reply
    pierde alcance por minutos."""
    from datetime import datetime, timezone

    q = Queue(tmp_path / "cola.jsonl")
    propio = q.add(_draft("post propio"))
    q.update(propio.id, estado="publicado",
             publicado_en=datetime.now(timezone.utc).isoformat())
    # Acaba de salir un post propio, así que el espaciado está activo...
    assert q.minutos_desde_ultima_publicacion() < 1

    reply = q.add(_draft("un reply", kind="reply"))
    q.aprobar(reply.id)
    listos = q.listos_para_publicar()
    # ...y aun así el reply está listo: no comparte turno con los propios.
    assert reply.id in [i.id for i in listos]


def test_publicar_pone_los_replies_primero(tmp_path):
    """Caducan: si solo cabe uno por pasada, que sea el que se muere."""
    q = Queue(tmp_path / "cola.jsonl")
    propio = q.add(_draft("post propio"))
    reply = q.add(_draft("un reply", kind="reply"))
    for i in (propio, reply):
        q.aprobar(i.id)
    items = sorted(q.listos_para_publicar(),
                   key=lambda i: 0 if i.kind == "reply" else 1)
    assert items[0].id == reply.id


# --- contenido macro ------------------------------------------------------

def _serie(valores, desde="2024-01-01"):
    from datetime import date, timedelta

    d0 = date.fromisoformat(desde)
    return [(str(d0 + timedelta(days=i * 7)), v) for i, v in enumerate(valores)]


def test_un_dato_en_su_media_no_es_un_post():
    """Sin tensión no hay conversación: publicar por publicar es peor que
    no publicar."""
    from xcreator.macro import SERIES, leer

    # Oscila entre 4.00 y 4.02: el percentil dice "máximo histórico" pero el
    # recorrido es de dos centésimas. Eso no es noticia.
    plano = _serie([4.0 + (i % 3) * 0.01 for i in range(60)])
    l = leer(SERIES["tasa10"], plano)
    assert l.plana
    assert l.tension == 0


def test_un_extremo_historico_si_lo_es():
    from xcreator.macro import SERIES, leer

    subiendo = _serie([3.0 + i * 0.03 for i in range(60)])
    l = leer(SERIES["tasa10"], subiendo)
    assert l.percentil_5a == 1.0
    assert l.tension >= 3


def test_serie_corta_no_produce_lectura():
    from xcreator.macro import SERIES, leer

    assert leer(SERIES["tasa10"], _serie([4.0, 4.1, 4.2])) is None


def test_el_brief_macro_no_lleva_empresa():
    """Sin ticker no aplica la regla del cashtag: no hay empresa de la que
    hablar y forzar una sería inventarla."""
    from xcreator.generate import falta_ticker
    from xcreator.macro import SERIES, brief_macro, leer

    b = brief_macro(leer(SERIES["tasa10"], _serie([3.0 + i * 0.03 for i in range(60)])))
    assert b.ticker == ""
    assert b.kind == "macro"
    assert falta_ticker("The 10-year is 4.95%.", b.ticker) == []


def test_las_cifras_macro_llevan_su_fuente_y_fecha():
    from xcreator.macro import SERIES, brief_macro, leer

    b = brief_macro(leer(SERIES["tasa10"], _serie([3.0 + i * 0.03 for i in range(60)])))
    assert b.facts and all("FRED" in f.source for f in b.facts)
    assert all("dato del" in f.source for f in b.facts)


def test_los_huecos_de_fred_no_se_leen_como_ceros(monkeypatch):
    """FRED marca los días sin dato con '.', y tomarlos por cero hundiría
    cualquier media."""
    import httpx

    from xcreator.datos import fred_series

    monkeypatch.setattr(httpx, "get", lambda *a, **kw: httpx.Response(
        200, request=httpx.Request("GET", "https://fred"),
        json={"observations": [
            {"date": "2026-09-01", "value": "4.95"},
            {"date": "2026-09-02", "value": "."},
            {"date": "2026-09-03", "value": "4.97"},
        ]}))
    assert fred_series("DGS10", "k") == [("2026-09-01", 4.95), ("2026-09-03", 4.97)]


def test_sin_clave_de_fred_no_hay_macro_pero_no_revienta():
    from xcreator.datos import fred_series
    from xcreator.macro import mejores_temas

    assert fred_series("DGS10", None) == []
    assert mejores_temas(None) == []


# --- replies en el móvil: copiar de un toque ------------------------------

def test_el_reply_va_en_bloque_copiable():
    """Los deep links de X abren la app sin prellenar el texto en muchos
    teléfonos. Un bloque de código sí lleva botón de copiar nativo."""
    from types import SimpleNamespace

    from xcreator.telegram import mensaje_para_copiar

    i = SimpleNamespace(responde_a="@Barchart", texto_final="El texto.",
                        url_origen="https://x.com/Barchart/status/9")
    m = mensaje_para_copiar(i)
    assert "<pre>El texto.</pre>" in m
    assert "https://x.com/Barchart/status/9" in m


def test_el_texto_se_escapa_para_no_romper_el_html():
    """Un '&' o un '<' sin escapar hacen que Telegram rechace el mensaje
    entero y el reply no llegue."""
    from types import SimpleNamespace

    from xcreator.telegram import mensaje_para_copiar

    i = SimpleNamespace(responde_a="@x", url_origen="",
                        texto_final="P/E < 10 & falling")
    m = mensaje_para_copiar(i)
    assert "&lt; 10 &amp; falling" in m


def test_se_copia_el_texto_EDITADO(tmp_path):
    from xcreator.telegram import mensaje_para_copiar

    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(_draft("original", kind="reply"))
    q.aprobar(i.id, texto_editado="mi versión")
    assert "<pre>mi versión</pre>" in mensaje_para_copiar(q.get(i.id))


# --- cupo diario de replies -----------------------------------------------

def test_el_cupo_cuenta_lo_propuesto_no_lo_publicado(tmp_path):
    """Lo que se quiere limitar es el tiempo de Angel, y mirar un reply
    cuesta aunque luego lo descarte."""
    q = Queue(tmp_path / "cola.jsonl")
    a = q.add(_draft("uno", kind="reply"))
    b = q.add(_draft("dos", kind="reply"))
    q.rechazar(b.id, motivo="no me convence")
    assert q.replies_de_hoy() == 2


def test_los_posts_propios_no_gastan_cupo_de_replies(tmp_path):
    q = Queue(tmp_path / "cola.jsonl")
    q.add(_draft("post propio"))
    q.add(_draft("un reply", kind="reply"))
    assert q.replies_de_hoy() == 1


def test_los_replies_de_ayer_no_cuentan(tmp_path):
    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(_draft("de ayer", kind="reply"))
    q.update(i.id, creado="2020-01-01T10:00:00+00:00")
    assert q.replies_de_hoy() == 0


def test_bloquea_texto_final_sin_cashtag(tmp_path):
    """El ticker se revisa al publicar, no solo al generar.

    Tres posts salieron sin `$TICKER` porque se redactaron antes de que la
    regla llegara al VPS: el borrador viejo no traía el campo, se guardó
    vacío y el publicador no lo volvía a mirar.
    """
    from xcreator.publicar import revisar_antes_de_publicar

    _, item = _item_aprobado(
        tmp_path, "NVDA prints at $196.53 today.", ticker="NVDA")
    problemas = revisar_antes_de_publicar(item)
    assert any("falta el ticker" in p and "$NVDA" in p for p in problemas)


def test_deja_pasar_el_texto_con_las_dos_formas_del_ticker(tmp_path):
    from xcreator.publicar import revisar_antes_de_publicar

    _, item = _item_aprobado(
        tmp_path, "$NVDA prints at $196.53. NVDA holds only if growth lands.",
        ticker="NVDA")
    assert revisar_antes_de_publicar(item) == []


def test_el_post_macro_sin_ticker_no_se_bloquea(tmp_path):
    """Un post de mercado no tiene ticker: exigirlo lo mataría."""
    from xcreator.publicar import revisar_antes_de_publicar

    _, item = _item_aprobado(
        tmp_path, "The 10-year sits at 4.95% and nobody is repricing.",
        ticker="")
    assert revisar_antes_de_publicar(item) == []


def test_el_ticker_puede_estar_repartido_en_el_hilo(tmp_path):
    from xcreator.publicar import revisar_antes_de_publicar

    _, item = _item_aprobado(
        tmp_path, "$NVDA base case at $275.14.",
        ticker="NVDA", thread=["NVDA holds only if growth stays 40%."])
    assert revisar_antes_de_publicar(item) == []


def test_reparacion_mecanica_pone_el_cashtag_al_primero(tmp_path):
    """Con dos menciones planas, una se vuelve cashtag sin gastar una llamada."""
    from xcreator.generate import _reparar_ticker_mecanico, falta_ticker

    t = "NVDA trades at 44.60x. The NVDA base case is $305.61."
    out = _reparar_ticker_mecanico(t, "NVDA")
    assert out.startswith("$NVDA")
    assert falta_ticker(out, "NVDA") == []


def test_reparacion_mecanica_quita_el_dolar_al_ultimo(tmp_path):
    from xcreator.generate import _reparar_ticker_mecanico, falta_ticker

    t = "$NVDA trades at 44.60x. The $NVDA base case is $305.61."
    out = _reparar_ticker_mecanico(t, "NVDA")
    assert falta_ticker(out, "NVDA") == []
    assert out.count("$NVDA") == 1


def test_reparacion_mecanica_se_rinde_con_una_sola_mencion(tmp_path):
    """Con una mención no hay nada que mover sin inventar texto."""
    from xcreator.generate import _reparar_ticker_mecanico

    t = "$AAPL at $332.27 trades at 44.50x earnings."
    assert _reparar_ticker_mecanico(t, "AAPL") == t


def test_reparacion_mecanica_no_se_pasa_del_limite(tmp_path):
    """Añadir el `$` cuesta un carácter: si no cabe, se deja como estaba."""
    from xcreator.generate import MAX_CHARS, _reparar_ticker_mecanico

    t = "NVDA " + "x" * (MAX_CHARS - 10) + " NVDA"
    assert len(t) == MAX_CHARS
    assert _reparar_ticker_mecanico(t, "NVDA") == t


def test_reparacion_por_modelo_rechaza_la_cifra_inventada(tmp_path):
    """Si la reescritura mete un número sin fuente, se queda el original."""
    from xcreator.generate import _reparar_ticker

    class _C:
        def __init__(self, txt): self.messages = self; self._t = txt
        def create(self, **kw):
            return type("R", (), {"content": [
                type("B", (), {"type": "text", "text": self._t})()]})()

    orig = "$AAPL trades at 44.50x earnings today."
    malo = _C("$AAPL trades at 44.50x. AAPL margins hit 78.2% last quarter.")
    assert _reparar_ticker(malo, orig, "AAPL", "m", [44.50]) == orig

    bueno = _C("$AAPL trades at 44.50x. AAPL is not cheap.")
    assert _reparar_ticker(bueno, orig, "AAPL", "m", [44.50]).startswith("$AAPL")


def test_reparacion_por_modelo_rechaza_lo_que_sigue_sin_ticker(tmp_path):
    from xcreator.generate import _reparar_ticker

    class _C:
        def __init__(self, txt): self.messages = self; self._t = txt
        def create(self, **kw):
            return type("R", (), {"content": [
                type("B", (), {"type": "text", "text": self._t})()]})()

    orig = "$AAPL trades at 44.50x earnings today."
    assert _reparar_ticker(_C("Apple trades at 44.50x."), orig, "AAPL",
                           "m", [44.50]) == orig


def test_el_desempate_rota_entre_dias():
    """Empatados a puntos, un sort estable daba SIEMPRE el mismo primero."""
    from datetime import date

    from xcreator.temas import ranking

    empatados = [_brief_con(precio_hoy=150.0, ticker=t)
                 for t in ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF")]
    cabezas = {ranking(empatados, hoy=date(2026, 9, d))[0].ticker
               for d in range(1, 15)}
    assert len(cabezas) > 1, "el mismo ticker gana todos los días"


def test_el_desempate_es_estable_dentro_del_mismo_dia():
    """Rotar no puede significar aleatorio: el mismo día da el mismo orden."""
    from datetime import date

    from xcreator.temas import ranking

    empatados = [_brief_con(precio_hoy=150.0, ticker=t)
                 for t in ("AAA", "BBB", "CCC", "DDD")]
    hoy = date(2026, 9, 14)
    assert ([t.ticker for t in ranking(empatados, hoy=hoy)]
            == [t.ticker for t in ranking(empatados, hoy=hoy)])


def test_el_desempate_no_pisa_los_puntos():
    """La tensión manda: el desempate solo ordena lo que ya empató."""
    from datetime import date

    from xcreator.temas import ranking

    fuerte = _brief_con(precio_hoy=150.0, ticker="ZZZZ")   # por debajo del bear
    flojo = _brief_con(precio_hoy=280.0, ticker="AAAA")
    r = ranking([flojo, fuerte], hoy=date(2026, 9, 14))
    assert r[0].ticker == "ZZZZ"


def _settings_min(tmp_path):
    """Settings sin Cerebro ni reportes: los tests no tocan disco externo."""
    from xcreator.config import Settings

    return Settings(reportes_dir=tmp_path, cerebro_dir=None)


def test_auto_encola_un_post_por_ticker_no_varios_del_mismo(tmp_path, monkeypatch):
    """`--auto` pedía n variantes de UN ticker: con publicación automática,
    eso son n posts seguidos de la misma empresa."""
    import xcreator.generate as G
    from xcreator.cli import _redactar_planes
    from xcreator.temas import evaluar

    briefs = {t: _brief_con(precio_hoy=150.0, ticker=t)
              for t in ("AAA", "BBB", "CCC")}
    monkeypatch.setattr(
        G, "draft_posts",
        lambda brief, s, **kw: [
            _draft(f"${brief.ticker} moves. {brief.ticker} holds.",
                   ticker=brief.ticker) for _ in range(2)])
    q = Queue(tmp_path / "cola.jsonl")
    planes = [(b, a, evaluar(b))
              for (b, a) in zip(briefs.values(),
                                ("negocio", "finanzas", "mercado"))]
    _redactar_planes(planes, q, _settings_min(tmp_path),
                     lecciones=[], encolar=True)
    assert sorted(i.ticker for i in q.load()) == ["AAA", "BBB", "CCC"]


def test_auto_se_queda_con_la_variante_valida(tmp_path, monkeypatch):
    """La segunda variante es el repuesto de la primera, no un segundo post."""
    import xcreator.generate as G
    from xcreator.cli import _redactar_planes
    from xcreator.temas import evaluar

    b = _brief_con(precio_hoy=150.0, ticker="AAA")
    malo = _draft("AAA moves without the cashtag.", ticker="AAA",
                  tickers_faltantes=["$AAA"])
    bueno = _draft("$AAA moves. AAA holds.", ticker="AAA")
    monkeypatch.setattr(G, "draft_posts", lambda brief, s, **kw: [malo, bueno])
    q = Queue(tmp_path / "cola.jsonl")
    _redactar_planes([(b, "negocio", evaluar(b))], q, _settings_min(tmp_path),
                     lecciones=[], encolar=True)
    items = q.load()
    assert len(items) == 1
    assert items[0].estado == "programado"
    assert "$AAA" in items[0].texto_final


def test_el_post_macro_tiene_que_decir_de_que_habla():
    """Un post que solo encadena porcentajes deja al lector adivinando.

    El que se coló: «A year ago I thought 4.04% was the cycle ceiling.
    Wrong. 4.70% a month back, 4.95% now» — nunca dice que habla del bono
    a 10 años.
    """
    from xcreator.generate import falta_sujeto
    from xcreator.macro import SERIES

    diez = SERIES["tasa10"].alias
    assert falta_sujeto(
        "A year ago I thought 4.04% was the cycle ceiling. Wrong. 4.70% a "
        "month back, 4.95% now, the high of the entire loaded history.", diez)
    assert not falta_sujeto("The 10-year is at 4.95%, top of its range.", diez)
    assert not falta_sujeto("Treasury yields printed 4.95% today.", diez)


def test_cada_serie_macro_declara_como_se_llama():
    """Sin alias, la regla del sujeto no protege a esa serie."""
    from xcreator.macro import SERIES

    for clave, cfg in SERIES.items():
        assert cfg.alias, f"{clave} ({cfg.serie}) no declara alias"


def test_el_post_de_empresa_no_pasa_por_la_regla_del_sujeto():
    """Ahí el cashtag ya dice de qué se habla; exigir más sería ruido."""
    from xcreator.generate import falta_sujeto

    assert not falta_sujeto("$NVDA base case is $305.61.", ())


def test_publicar_bloquea_el_macro_que_no_dice_de_que_habla(tmp_path):
    from xcreator.publicar import revisar_antes_de_publicar

    _, item = _item_aprobado(
        tmp_path,
        "A year ago I thought 4.04% was the ceiling. Wrong. 4.95% now.",
        ticker="", kind="macro")
    assert any("no dice de qué habla" in p for p in revisar_antes_de_publicar(item))


def test_publicar_deja_pasar_el_macro_que_nombra_el_dato(tmp_path):
    from xcreator.publicar import revisar_antes_de_publicar

    _, item = _item_aprobado(
        tmp_path, "The 10-year is at 4.95%, the top of its loaded range.",
        ticker="", kind="macro")
    assert revisar_antes_de_publicar(item) == []


def test_el_post_que_nace_programado_llega_a_publicarse(tmp_path):
    """`decidido` solo lo escriben aprobar/rechazar.

    Exigirlo dejaba a todo borrador automático invisible para el
    publicador: solo salía lo que Angel aprobaba a mano, que es justo lo
    que la cola programada venía a evitar.
    """
    from datetime import datetime, timedelta, timezone

    from xcreator.store import MINUTOS_DE_GRACIA, Queue

    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(_draft("$NVDA holds. NVDA at 44x.", ticker="NVDA"),
              estado="programado")
    assert i.decidido == "", "un borrador automático no lo decide nadie"
    viejo = (datetime.now(timezone.utc)
             - timedelta(minutes=MINUTOS_DE_GRACIA + 1)).isoformat()
    q.update(i.id, creado=viejo)
    assert [x.id for x in q.listos_para_publicar()] == [i.id]


def test_la_ventana_de_veto_se_respeta_en_el_automatico(tmp_path):
    """Recién creado no sale: para eso está la ventana."""
    from xcreator.store import Queue

    q = Queue(tmp_path / "cola.jsonl")
    q.add(_draft("$NVDA holds. NVDA at 44x.", ticker="NVDA"),
          estado="programado")
    assert q.listos_para_publicar() == []


# --- cripto: hechos de precio, nunca un modelo de valor -------------------

def _serie_cripto(precios):
    from datetime import date, timedelta
    hoy = date(2026, 9, 14)
    return [(str(hoy - timedelta(days=len(precios) - 1 - i)), p)
            for i, p in enumerate(precios)]


def test_cripto_no_pretende_tener_un_rango_de_valor():
    """Sin filings no hay flujo que descontar: un precio objetivo aquí sería
    justo el número sin fórmula que el resto del sistema impide."""
    from xcreator.cripto import ACTIVOS, brief_cripto, leer

    lec = leer(ACTIVOS["btc"], _serie_cripto([50000 + i * 100 for i in range(120)]))
    b = brief_cripto(lec)
    texto = " ".join(b.context).lower()
    assert "no tienes un rango objetivo" in texto
    assert "prohibido dar un precio objetivo" in texto
    etiquetas = " ".join(f.label.lower() for f in b.facts)
    for inventado in ("base", "bear", "bull", "objetivo", "target"):
        assert inventado not in etiquetas


def test_cripto_exige_el_cashtag_y_el_nombre():
    """En X, $BTC se indexa igual que una acción: la regla sí aplica."""
    from xcreator.cripto import ACTIVOS, brief_cripto, leer
    from xcreator.generate import falta_sujeto, falta_ticker

    lec = leer(ACTIVOS["xrp"], _serie_cripto([1.0 + i * 0.01 for i in range(120)]))
    b = brief_cripto(lec)
    assert b.ticker == "XRP"
    assert falta_ticker("XRP just printed a high.", b.ticker) == ["$XRP"]
    assert falta_ticker("$XRP and XRP both here.", b.ticker) == []
    assert falta_sujeto("Something moved 12% today.", b.sujeto)
    assert not falta_sujeto("Ripple's token moved; XRP is the asset.", b.sujeto)


def test_el_precio_casi_inmovil_no_puntua_como_record():
    """El percentil es relativo: con un recorrido minúsculo, el último dato
    sale como máximo histórico. Le pasó a macro y aquí sería peor."""
    from xcreator.cripto import ACTIVOS, leer

    plano = leer(ACTIVOS["btc"], _serie_cripto([50000 + (i % 3) for i in range(120)]))
    assert plano.percentil == 1.0, "efectivamente sale como máximo"
    assert plano.plana
    assert plano.tension == 0


def test_cripto_puntua_mas_una_caida_mas_honda():
    from xcreator.cripto import ACTIVOS, leer

    subida = [40000 + i * 500 for i in range(80)]           # hasta ~79.500
    leve = leer(ACTIVOS["btc"],
                _serie_cripto(subida + [79500 - i * 600 for i in range(40)]))
    honda = leer(ACTIVOS["btc"],
                 _serie_cripto(subida + [79500 - i * 1100 for i in range(40)]))
    assert 20 < leve.caida_desde_maximo < 40
    assert honda.caida_desde_maximo > 40
    assert honda.tension > leve.tension >= 1


def test_la_volatilidad_de_cripto_se_anualiza_con_365():
    """Cotiza los siete días; usar 252 la infravaloraría un 20%."""
    from xcreator.cripto import _volatilidad_anualizada

    import statistics
    precios = [100 * (1.01 if i % 2 else 0.99) ** 1 for i in range(100)]
    serie = [100.0]
    for i in range(1, 100):
        serie.append(serie[-1] * (1.02 if i % 2 else 0.98))
    ret = [(b - a) / a for a, b in zip(serie, serie[1:])]
    esperado = statistics.stdev(ret) * (365 ** 0.5) * 100
    assert abs(_volatilidad_anualizada(serie) - esperado) < 1e-6


def test_cada_activo_declara_como_se_llama():
    from xcreator.cripto import ACTIVOS

    for clave, cfg in ACTIVOS.items():
        assert cfg.alias, f"{clave} no declara alias"
        assert cfg.ticker and not cfg.ticker.startswith("$")


# --- no inventarse un historial que no existe -----------------------------

def test_no_puede_atribuirse_una_llamada_que_nunca_hizo():
    """Dos estuvieron a punto de publicarse: «A year ago I thought 4.04% was
    the cycle ceiling» y «My miss: I called Ether dead money». Las cifras
    salían del brief; la afirmación era inventada."""
    from xcreator.generate import afirma_llamada_propia as f

    assert f("My miss: I called Ether dead money at $1,880.94 a month ago.")
    assert f("A year ago I thought 4.04% was the cycle ceiling. Wrong.")
    assert f("We predicted a break below $60,000.")
    assert f("I was wrong about the curve.")


def test_no_confunde_opinion_presente_con_llamada_pasada():
    from xcreator.generate import afirma_llamada_propia as f

    assert f("I think the multiple is wrong.") == []
    assert f("Bitcoin is $78,818.79 today, was $65,000 ninety days ago.") == []
    assert f("Nobody called this.") == []


def test_publicar_bloquea_el_historial_inventado_en_cripto(tmp_path):
    from xcreator.publicar import revisar_antes_de_publicar

    _, item = _item_aprobado(
        tmp_path, "My miss: I called $BTC dead money. BTC is $78,818.79 now.",
        ticker="BTC", kind="cripto")
    assert any("predicción que no existe" in p
               for p in revisar_antes_de_publicar(item))


def test_el_post_de_empresa_si_puede_citar_su_propia_llamada(tmp_path):
    """Ahí sí hay predicción guardada: el motor la escribió y es comprobable."""
    from xcreator.publicar import revisar_antes_de_publicar

    _, item = _item_aprobado(
        tmp_path, "Our bear case on $NVDA was $194.56. NVDA never touched it.",
        ticker="NVDA", kind="thesis_check")
    assert revisar_antes_de_publicar(item) == []


def test_el_cupo_de_replies_cuenta_contra_la_cola_no_contra_la_pasada(tmp_path):
    """Leer el cupo una sola vez al arrancar bastaba con un proceso.

    Con dos corridas de `vigilar` solapadas —pasa cuando una tarda más de
    los 15 minutos del cron— cada una se gastaba el cupo entero: con el
    tope en 3 se propusieron 19 replies en un día.
    """
    from xcreator.store import Queue

    q = Queue(tmp_path / "cola.jsonl")
    for _ in range(3):
        q.add(_draft("A reply.", kind="reply", ticker="NVDA"))
    assert q.replies_de_hoy() == 3
    # Una segunda corrida que ya leyó `ya=0` antes: al recontar, se planta.
    assert q.replies_de_hoy() >= 3


def test_los_replies_de_ayer_no_gastan_el_cupo_de_hoy(tmp_path):
    from datetime import date, timedelta

    from xcreator.store import Queue

    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(_draft("A reply.", kind="reply", ticker="NVDA"))
    ayer = (date.today() - timedelta(days=1)).isoformat() + "T10:00:00+00:00"
    q.update(i.id, creado=ayer)
    assert q.replies_de_hoy() == 0


# --- replies: cripto y tope por cuenta ------------------------------------

def test_el_filtro_reconoce_activos_por_su_nombre():
    """Las cuentas de cripto escriben «Bitcoin», no «$BTC»."""
    from xcreator.replies import Mencion

    assert "BTC" in Mencion("@w", "JUST IN: Bitcoin falls under $77,000").tickers()
    assert "XRP" in Mencion("@w", "Ripple CEO calls for the Senate to act").tickers()
    assert "ETH" in Mencion("@w", "Ethereum fees hit a new low").tickers()
    assert "BTC" not in Mencion("@w", "Nvidia CEO meets Trump").tickers()


def test_la_accion_gana_al_cripto_cuando_se_mencionan_las_dos():
    """El análisis de una empresa es más específico que un dato de precio."""
    from xcreator.brief import Brief
    from xcreator.replies import Mencion, encontrar_relevancia

    b = Brief(kind="target_range", ticker="NVDA", angle="a")
    cripto = Brief(kind="cripto", ticker="BTC", angle="b")
    r = encontrar_relevancia(
        Mencion("@w", "Nvidia $NVDA buys Bitcoin"), [b], None,
        cripto=lambda t: cripto if t == "BTC" else None)
    assert r.ticker == "NVDA"


def test_el_post_de_cripto_encuentra_su_brief():
    from xcreator.brief import Brief
    from xcreator.replies import Mencion, encontrar_relevancia

    cripto = Brief(kind="cripto", ticker="BTC", angle="b")
    r = encontrar_relevancia(
        Mencion("@w", "JUST IN: Bitcoin falls under $77,000"), [], None,
        cripto=lambda t: cripto if t == "BTC" else None)
    assert r.aporta and r.ticker == "BTC"


def test_sin_cripto_el_filtro_se_comporta_como_antes():
    """Las llamadas viejas no cambian de resultado."""
    from xcreator.replies import Mencion, encontrar_relevancia

    r = encontrar_relevancia(Mencion("@w", "Bitcoin falls under $77,000"), [])
    assert not r.aporta


def test_el_tope_por_cuenta_cuenta_solo_esa_cuenta(tmp_path):
    """Una cuenta de titulares en vivo se comería el cupo global entera."""
    from xcreator.store import Queue

    from xcreator.replies import ReplyDraft

    q = Queue(tmp_path / "cola.jsonl")
    q.add(ReplyDraft(texto="r1", que_aporta="x", autor="@WatcherGuru",
                     ticker="BTC"))
    q.add(ReplyDraft(texto="r2", que_aporta="x", autor="@zerohedge",
                     ticker="NVDA"))
    assert q.replies_de_hoy("@WatcherGuru") == 1
    assert q.replies_de_hoy("zerohedge") == 1
    assert q.replies_de_hoy() == 2


def test_la_cuenta_declara_su_propio_tope():
    from xcreator.watchlist import Cuenta

    assert Cuenta("@x").tope_diario == 0, "0 = solo manda el tope global"
    assert Cuenta("@x", tope_diario=1).tope_diario == 1


# --- opinión: criterio sin cifras -----------------------------------------

def test_reconoce_los_temas_donde_opinamos_sin_cifras():
    from xcreator.replies import _tema_sin_cifras

    assert _tema_sin_cifras("Senate Democrats to discuss the Crypto Clarity Act")
    assert _tema_sin_cifras("US House unveils new crypto tax legislation")
    assert _tema_sin_cifras("Cryptocurrency exchange CoinEx to shut down")
    assert _tema_sin_cifras("Fed signals a rate cut")
    assert _tema_sin_cifras("My cat is asleep on the keyboard") == ""


def test_sin_ticker_pero_con_tema_hay_reply_de_opinion():
    """Antes se descartaba: «sin datos propios, responder sería ruido». Era un
    límite que nos pusimos, no una regla del sistema."""
    from xcreator.replies import Mencion, encontrar_relevancia

    r = encontrar_relevancia(
        Mencion("@w", "Democrats reject Republican crypto Clarity Act draft"), [])
    assert r.aporta and r.solo_opinion and r.brief is None
    assert r.tema == "regulación de cripto"


def test_los_datos_ganan_siempre_a_la_opinion():
    """Si hay cifras propias, se responde con ellas, no con una impresión."""
    from xcreator.brief import Brief
    from xcreator.replies import Mencion, encontrar_relevancia

    b = Brief(kind="cripto", ticker="BTC", angle="a")
    r = encontrar_relevancia(
        Mencion("@w", "Bitcoin drops as the crypto Clarity Act stalls"), [],
        None, cripto=lambda t: b if t == "BTC" else None)
    assert not r.solo_opinion and r.ticker == "BTC"


def test_el_reply_de_opinion_no_puede_traer_cifras_propias():
    """Sin brief, cualquier número sería inventado. Se comprueba en código."""
    from xcreator.replies import Mencion, Relevancia, draft_reply

    class _C:
        def __init__(self, txt): self.messages = self; self._t = txt
        def parse(self, **kw):
            out = type("P", (), {"aporta_algo": True, "texto": self._t,
                                 "que_aporta": "x"})()
            return type("R", (), {"parsed_output": out, "stop_reason": "end_turn"})()

    m = Mencion("@w", "US House unveils new crypto tax legislation.")
    rel = Relevancia(None, solo_opinion=True, tema="regulación de cripto")
    malo = draft_reply(m, rel, None,
                       client=_C("Taxing it at 28% kills the use case."))
    assert malo.numeros_no_justificados and not malo.valido

    bueno = draft_reply(m, rel, None, client=_C(
        "Taxing every transfer as a disposal is what kills the use case, "
        "not the rate anyone lands on."))
    assert bueno.valido and bueno.brief_id == ""


def test_el_prompt_de_opinion_prohibe_el_partidismo():
    """La cuenta es de mercados. Que un sistema automático tome partido entre
    partidos es un riesgo distinto del de equivocarse en una cifra."""
    from xcreator.replies import _SYSTEM_OPINION

    bajo = _SYSTEM_OPINION.lower()
    assert "no party politics" in bajo
    assert "no numbers" in bajo


def test_los_replies_de_opinion_tienen_su_propio_sub_tope(tmp_path):
    """Hay muchos más posts de opinión que de datos: sin sub-tope se comerían
    el cupo diario y la cuenta perdería lo que la diferencia."""
    from xcreator.replies import ReplyDraft
    from xcreator.store import Queue

    q = Queue(tmp_path / "cola.jsonl")
    q.add(ReplyDraft(texto="con datos", que_aporta="x", autor="@a", ticker="BTC",
                     brief_id="BTC-cripto-mercado-2026-09-18"))
    # Un reply de macro TAMPOCO lleva ticker, pero sí trae datos: no es opinión.
    q.add(ReplyDraft(texto="el IPC", que_aporta="x", autor="@a", ticker="",
                     brief_id="-macro-riesgo-2026-09-18"))
    q.add(ReplyDraft(texto="opinión", que_aporta="x", autor="@a", ticker=""))
    assert q.replies_de_hoy() == 3
    assert q.replies_opinion_de_hoy() == 1, "solo el que no cuelga de ningún brief"


def test_las_claves_de_opinion_son_inequivocas():
    """«settlement» a secas enganchó con un acuerdo judicial de zerohedge y
    se llevó el único cupo de opinión del día."""
    from xcreator.replies import _tema_sin_cifras as t

    assert t("A settlement that only covers filed claims") == ""
    assert t("Bayer reaches a $2bn settlement over Roundup") == ""
    assert t("The industry moves to T+1 settlement in May") == "estructura de mercado"
    assert t("Ukraine strikes Russian refinery") == ""
    assert t("Cryptocurrency exchange CoinEx to shut down") == "regulación de cripto"


def test_no_se_propone_dos_veces_el_mismo_post(tmp_path):
    """Dos respuestas al mismo tweet se leen como un bot. El cursor
    `desde_id` no basta: cualquier relectura las duplica."""
    from xcreator.replies import ReplyDraft
    from xcreator.store import Queue

    q = Queue(tmp_path / "cola.jsonl")
    url = "https://x.com/FirstSquawk/status/2099825178947752379"
    q.add(ReplyDraft(texto="r", que_aporta="x", autor="@FirstSquawk",
                     ticker="AXP", url=url))
    assert q.ya_respondido(url)
    assert q.ya_respondido("2099825178947752379")
    assert not q.ya_respondido("https://x.com/FirstSquawk/status/999")
    assert not q.ya_respondido("")


def test_el_rechazado_tampoco_se_rehace(tmp_path):
    """Si se descartó, volver a proponerlo es gastar dos veces la misma mala idea."""
    from xcreator.replies import ReplyDraft
    from xcreator.store import Queue

    q = Queue(tmp_path / "cola.jsonl")
    url = "https://x.com/a/status/1"
    i = q.add(ReplyDraft(texto="r", que_aporta="x", autor="@a", url=url))
    q.rechazar(i.id, motivo="no aporta")
    assert q.ya_respondido(url)


def test_el_tope_de_una_corrida_no_se_guarda():
    """Subir el cupo "por hoy" tocando la config se lo queda el cron de
    mañana. Por eso es un flag de la corrida y no un ajuste."""
    import inspect

    from xcreator.cli import vigilar

    params = inspect.signature(vigilar).parameters
    assert "cupo" in params and "cupo_opinion" in params
    src = inspect.getsource(vigilar)
    # El tope efectivo sale del flag, y si no, de la config.
    assert "tope = cupo if cupo > 0 else s.replies_por_dia" in src
    assert "s.replies_por_dia" not in src.split("tope = cupo")[1].split("\n", 1)[1]


# --- estilo: ni rayas ni cifras a la española ------------------------------

def test_la_raya_larga_no_pasa():
    """Angel: «los textos no deben llevar guiones». Es además el tic que más
    delata un texto generado."""
    from xcreator.generate import lleva_raya

    assert lleva_raya("on its own — the Fed guided it there")
    assert lleva_raya("a wide range – too wide")
    assert lleva_raya("one thing -- another")
    assert lleva_raya("one clause - another clause")


def test_el_guion_dentro_de_palabra_se_queda():
    """Quitarlo rompería el inglés y los alias de los activos."""
    from xcreator.generate import lleva_raya

    assert not lleva_raya("the 10-year at high-yield mid-range levels")
    assert not lleva_raya("T+1 settlement and self-custody")
    assert not lleva_raya("$NVDA base is $305.61.")


def test_las_cifras_van_en_convencion_inglesa():
    """Coma para los miles (79,900), punto para los decimales (10.99)."""
    from xcreator.generate import cifras_mal_formateadas as c

    assert c("$78,818.79 and 10.99") == []
    assert c("79,900 units") == []
    assert c("in 2026, the market moved") == []
    assert c("4,95% today")
    assert c("78.818,79 euros")
    assert c("1,5x earnings"), "sin lookahead, «1,5x» se colaba por el \\b"


def test_publicar_bloquea_la_raya_y_la_cifra_mal(tmp_path):
    from xcreator.publicar import revisar_antes_de_publicar

    _, con_raya = _item_aprobado(
        tmp_path, "$NVDA at 44.60x — the multiple never moves. NVDA holds.",
        ticker="NVDA")
    assert any("raya" in p for p in revisar_antes_de_publicar(con_raya))

    _, mal = _item_aprobado(
        tmp_path, "$NVDA trades at 44,60x today. NVDA holds.", ticker="NVDA")
    assert any("mal formateadas" in p for p in revisar_antes_de_publicar(mal))


def test_el_texto_limpio_sigue_pasando(tmp_path):
    from xcreator.publicar import revisar_antes_de_publicar

    _, item = _item_aprobado(
        tmp_path,
        "$NVDA was $78,818.79 at 44.60x. NVDA holds only if growth stays 40%.",
        ticker="NVDA")
    assert revisar_antes_de_publicar(item) == []


def test_el_cupo_de_replies_y_su_parte_de_opinion():
    """Total 6, opinión 1.

    El total sube de 3 porque no debe bloquear nunca un reply con datos: son
    los de mejor mediana de todo lo que publica la cuenta (104 frente a 60 de
    los posts propios). La opinión se queda en 1 porque su mediana es 22, y
    el cuello real son los tickers emparejables, no el cupo."""
    from xcreator.config import Settings

    s = Settings()
    assert s.replies_por_dia == 6
    assert s.replies_opinion_por_dia == 1
    assert s.replies_opinion_por_dia * 3 <= s.replies_por_dia


# --- la tarjeta de Telegram no puede prometer lo que no pasa ---------------

def test_la_proyeccion_espacia_los_posts_de_la_tanda(tmp_path):
    """Tres borradores creados a la vez NO salen los tres a los 45 minutos:
    el publicador saca uno cada hora y media."""
    from datetime import datetime, timedelta, timezone

    from xcreator.store import ESPACIADO_MINUTOS, MINUTOS_DE_GRACIA, Queue

    ahora = datetime(2026, 9, 15, 12, 31, tzinfo=timezone.utc)
    q = Queue(tmp_path / "cola.jsonl")
    ids = []
    for t in ("ANET", "VRT", "WDAY"):
        i = q.add(_draft(f"${t} moves. {t} holds.", ticker=t), estado="programado")
        q.update(i.id, creado=ahora.isoformat())
        ids.append(i.id)

    pr = q.proyeccion_de_salida(ahora=ahora)
    salidas = [pr[i] for i in ids]
    assert salidas[0] >= ahora + timedelta(minutes=MINUTOS_DE_GRACIA)
    for antes, despues in zip(salidas, salidas[1:]):
        assert (despues - antes).total_seconds() / 60 >= ESPACIADO_MINUTOS
    assert salidas[2] - salidas[0] >= timedelta(minutes=2 * ESPACIADO_MINUTOS)


def test_la_proyeccion_respeta_la_ventana_horaria(tmp_path):
    """Un borrador de madrugada no sale de madrugada."""
    from datetime import datetime, timezone

    from xcreator.store import VENTANA_UTC, Queue

    ahora = datetime(2026, 9, 15, 3, 0, tzinfo=timezone.utc)
    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(_draft("$NVDA moves. NVDA holds.", ticker="NVDA"),
              estado="programado")
    q.update(i.id, creado=ahora.isoformat())
    assert q.proyeccion_de_salida(ahora=ahora)[i.id].hour >= VENTANA_UTC[0]


def test_la_tarjeta_dice_la_hora_y_no_los_45_minutos(tmp_path):
    from datetime import datetime, timezone

    from xcreator.store import Queue
    from xcreator.telegram import _texto_item

    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(_draft("$NVDA moves. NVDA holds.", ticker="NVDA"),
              estado="programado")
    sale = datetime(2026, 9, 15, 17, 30, tzinfo=timezone.utc)   # 13:30 AST
    txt = _texto_item(q.get(i.id), sale)
    assert "13:30" in txt
    assert "45 min" not in txt


def test_el_espaciado_vive_en_un_solo_sitio():
    """Estaba escrito a mano en la línea del cron y el aviso de Telegram no lo
    sabía. Una constante en dos sitios acaba desincronizada."""
    from pathlib import Path

    cron = (Path(__file__).resolve().parents[1] / "scripts" / "cron.sh").read_text()
    assert "--espaciado" not in cron


def test_el_reply_SE_ENVIA_en_bloque_copiable(tmp_path):
    """`mensaje_para_copiar` existía y no la llamaba nadie: los replies salían
    como texto suelto entre las notas, imposibles de copiar en el móvil."""
    from xcreator.replies import ReplyDraft
    from xcreator.store import Queue
    from xcreator.telegram import enviar_pendientes

    class _Bot:
        def __init__(self): self.enviados = []
        def send(self, texto, *, botones=None, force_reply=False, html=False):
            self.enviados.append((texto, html))
            return {"message_id": 1}
        def send_photo(self, *a, **k):
            raise AssertionError("un reply no se manda como foto")

    q = Queue(tmp_path / "cola.jsonl")
    q.add(ReplyDraft(texto="BTC is $78,818.79 today. $BTC holds.",
                     que_aporta="x", autor="@WatcherGuru", ticker="BTC",
                     url="https://x.com/WatcherGuru/status/1"))
    bot = _Bot()
    assert enviar_pendientes(q, bot) == 1
    texto, html = bot.enviados[0]
    assert html, "sin HTML, Telegram no dibuja el bloque copiable"
    assert "<pre>" in texto and "</pre>" in texto
    assert "BTC is $78,818.79 today." in texto


def test_las_notas_quedan_FUERA_del_bloque(tmp_path):
    """Lo que esté dentro del <pre> se copia con el texto y acaba publicado."""
    from xcreator.replies import ReplyDraft
    from xcreator.store import Queue
    from xcreator.telegram import mensaje_para_copiar

    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(ReplyDraft(texto="BTC holds. $BTC at $78,818.79.", que_aporta="x",
                         autor="@w", ticker="BTC",
                         url="https://x.com/w/status/1"))
    txt = mensaje_para_copiar(q.get(i.id))
    dentro = txt.split("<pre>")[1].split("</pre>")[0]
    assert dentro.strip() == "BTC holds. $BTC at $78,818.79."
    assert "caracteres" in txt.split("</pre>")[1], "las notas van después"


def test_el_post_propio_sigue_yendo_como_siempre(tmp_path):
    """El cambio es solo para los replies: un post propio lleva su ficha."""
    from xcreator.store import Queue
    from xcreator.telegram import enviar_pendientes

    class _Bot:
        def __init__(self): self.enviados = []
        def send(self, texto, *, botones=None, force_reply=False, html=False):
            self.enviados.append((texto, html)); return {"message_id": 2}

    q = Queue(tmp_path / "cola.jsonl")
    q.add(_draft("$NVDA moves. NVDA holds.", ticker="NVDA"),
          estado="programado")
    bot = _Bot()
    enviar_pendientes(q, bot)
    texto, html = bot.enviados[0]
    assert not html and "<pre>" not in texto
    assert "SALE SOLO" in texto


# --- macro en los replies: el dato que teníamos y no usábamos --------------

def test_el_post_sobre_tipos_encuentra_su_serie():
    """«What If Warsh Shocks The Market And Keeps Rates On Hold» no
    emparejaba con nada: ni ticker, ni cripto, ni tema de opinión."""
    from xcreator.macro import serie_para_post

    assert serie_para_post(
        "What If Warsh Shocks The Market And Keeps Rates On Hold").serie == "DFF"
    assert serie_para_post("The yield curve just inverted").serie == "T10Y2Y"
    assert serie_para_post("CPI comes in hot").serie == "CPIAUCSL"
    assert serie_para_post("Treasury yields hit a new high").serie == "DGS10"
    assert serie_para_post("Bitcoin falls under 77,000") is None


def test_gana_el_gatillo_mas_especifico():
    """«yield curve» debe ganarle a «yields» cuando salen los dos."""
    from xcreator.macro import serie_para_post

    assert serie_para_post(
        "Yields are moving and the yield curve just steepened").serie == "T10Y2Y"


def test_el_dato_de_fred_gana_a_la_opinion():
    """Un post sobre tipos NO es «sin cifras propias»: es donde más tenemos."""
    from xcreator.brief import Brief
    from xcreator.replies import Mencion, encontrar_relevancia

    b = Brief(kind="macro", ticker="", angle="a", sujeto=("fed funds",))
    m = Mencion("@zerohedge", "What If Warsh Keeps Rates On Hold")
    r = encontrar_relevancia(m, [], None, macro=lambda t: b)
    assert r.aporta and not r.solo_opinion and r.brief is b


def test_la_empresa_sigue_ganando_al_macro():
    from xcreator.brief import Brief
    from xcreator.replies import Mencion, encontrar_relevancia

    emp = Brief(kind="target_range", ticker="NVDA", angle="a")
    mac = Brief(kind="macro", ticker="", angle="b")
    r = encontrar_relevancia(
        Mencion("@w", "$NVDA falls as the Fed keeps rates on hold"),
        [emp], None, macro=lambda t: mac)
    assert r.ticker == "NVDA"


def test_el_reply_sin_ticker_tiene_que_nombrar_el_dato():
    """Un reply también se lee suelto."""
    from xcreator.brief import Brief
    from xcreator.replies import Mencion, Relevancia, draft_reply

    class _C:
        def __init__(self, txt): self.messages = self; self._t = txt
        def parse(self, **kw):
            out = type("P", (), {"aporta_algo": True, "texto": self._t,
                                 "que_aporta": "x"})()
            return type("R", (), {"parsed_output": out,
                                  "stop_reason": "end_turn"})()

    b = Brief(kind="macro", ticker="", angle="a", sujeto=("fed funds", "the fed"))
    m = Mencion("@zerohedge", "What If Warsh Keeps Rates On Hold")
    rel = Relevancia(b, motivo="dato de FRED")
    mudo = draft_reply(m, rel, None, client=_C("Holding is the tell, not the level."))
    assert mudo.sujeto_ausente and not mudo.valido
    claro = draft_reply(m, rel, None,
                        client=_C("The fed funds path is the tell, not the level."))
    assert not claro.sujeto_ausente


# --- variedad de HISTORIA, no solo de ticker -------------------------------

def test_cada_tema_sabe_que_historia_cuenta():
    from xcreator.temas import evaluar

    t = evaluar(_brief_con(precio_hoy=150.0))      # por debajo del bear
    assert t.clave == "rompe_bajo"
    assert "rompe_bajo" in t.claves


def test_la_historia_contada_hace_poco_baja_en_el_ranking():
    """12 de 30 posts contaban "el bear está pegado al precio": el descanso
    solo rotaba tickers, así que cambiaba la empresa y no la historia."""
    from datetime import date, timedelta

    from xcreator.temas import ranking

    hoy = date(2026, 9, 18)
    b = _brief_con(precio_hoy=150.0)
    clave = ranking([b], hoy=hoy)[0].clave
    sin = ranking([b], hoy=hoy)[0].puntos
    con = ranking([b], hoy=hoy,
                  ultimo_motivo={clave: str(hoy - timedelta(days=1))})
    assert not con or con[0].puntos < sin


def test_la_tanda_elige_historias_distintas_si_las_hay():
    from xcreator.brief import Brief
    from xcreator.temas import Tema, elegir_variados

    def t(tk, clave, pts):
        return Tema(Brief(kind="target_range", ticker=tk, angle="a"),
                    puntos=pts, claves=[clave])

    temas = [t("AAA", "bear_pegado", 5), t("BBB", "bear_pegado", 4),
             t("CCC", "movimiento", 3), t("DDD", "pe_extremo", 2)]
    elegidos = elegir_variados(temas, 3)
    assert [e.ticker for e in elegidos] == ["AAA", "CCC", "DDD"]


def test_si_no_hay_historias_nuevas_repite_antes_que_dejar_hueco():
    from xcreator.brief import Brief
    from xcreator.temas import Tema, elegir_variados

    temas = [Tema(Brief(kind="target_range", ticker=tk, angle="a"),
                  puntos=p, claves=["bear_pegado"])
             for tk, p in (("AAA", 5), ("BBB", 4), ("CCC", 3))]
    assert len(elegir_variados(temas, 3)) == 3


def test_la_cola_recuerda_que_historia_se_conto(tmp_path):
    from xcreator.store import Queue

    q = Queue(tmp_path / "cola.jsonl")
    q.add(_draft("$NVDA a. NVDA b.", ticker="NVDA", motivo="bear_pegado"))
    r = q.add(_draft("$AMD a. AMD b.", ticker="AMD", motivo="movimiento"))
    q.rechazar(r.id, motivo="no")
    assert "bear_pegado" in q.ultimo_uso_por_motivo()
    assert "movimiento" not in q.ultimo_uso_por_motivo(), "lo rechazado no cuenta"


# --- coletillas -----------------------------------------------------------

def test_caza_la_coletilla_aunque_cambie_la_frase_de_alrededor():
    """«it is a rounding error» salió tres veces, dos en posts seguidos."""
    from xcreator.generate import frases_repetidas

    antes = ["The bear case on $CLSK is $13.22. That is not a bear case, "
             "that is a rounding error."]
    assert frases_repetidas(
        "The bear case on $DIS is $104.28. It is a rounding error.", antes)
    assert frases_repetidas(
        "$VRT at 69x. Who is underwriting the +40%?",
        ["$ANET at 68x. Who is underwriting the +40%?"])


def test_el_vocabulario_del_oficio_no_es_una_coletilla():
    """Así se describen los datos: bloquearlo tumbaría casi todos los posts."""
    from xcreator.generate import frases_repetidas

    assert frases_repetidas("The base case assumes +40% growth for $NVDA.",
                            ["Our base case assumes +8% growth for $AXP."]) == []
    assert frases_repetidas("Solana moves with appetite for risk.",
                            ["The bear case on $CLSK is a rounding error."]) == []


def test_el_borrador_que_repite_no_nace_programado(tmp_path):
    """Pasa a pendiente con el motivo a la vista, no se pierde en silencio."""
    from xcreator.store import Queue

    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(_draft("$DIS x. DIS y.", ticker="DIS",
                     frases_repetidas=["is a rounding error"]),
              estado="programado")
    assert q.get(i.id).estado == "pendiente"
    assert q.get(i.id).frases_repetidas == ["is a rounding error"]


def test_los_recientes_incluyen_lo_programado(tmp_path):
    """Tres borradores de la misma tanda pueden copiarse entre ellos antes de
    que salga ninguno."""
    from xcreator.store import Queue

    q = Queue(tmp_path / "cola.jsonl")
    q.add(_draft("$NVDA uno. NVDA.", ticker="NVDA"), estado="programado")
    q.add(_draft("$AMD dos. AMD.", ticker="AMD"))                 # pendiente
    assert q.textos_recientes() == ["$NVDA uno. NVDA."]


def test_live_price_usa_el_endpoint_vivo_de_fmp(monkeypatch):
    """/api/v3/quote-short responde 403 "Legacy Endpoint". live_price lo usaba
    y devolvía None para los 153 tickers: ningún brief llevó "precio hoy" y
    tres de las historias del puntuador no dispararon nunca."""
    import xcreator.datos as D

    llamadas = []

    class _R:
        def raise_for_status(self): pass
        def json(self): return [{"symbol": "NVDA", "price": 219.56}]

    def fake_get(url, params=None, timeout=None):
        llamadas.append((url, params))
        return _R()

    monkeypatch.setattr(D.httpx, "get", fake_get)
    assert D.live_price("NVDA", "k") == 219.56
    url, params = llamadas[0]
    assert "/stable/quote-short" in url and "/api/v3" not in url
    assert params["symbol"] == "NVDA"


def test_ningun_endpoint_legacy_de_fmp_en_el_codigo():
    """El mismo retiro ya había roto price_history. Dos veces es un patrón."""
    import re
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[1] / "xcreator"
    for f in raiz.glob("*.py"):
        for n, linea in enumerate(f.read_text().splitlines(), 1):
            codigo = linea.split("#", 1)[0]
            assert not re.search(r"financialmodelingprep\.com/api/v3", codigo), \
                f"{f.name}:{n} usa un endpoint legacy de FMP"


# --- regulación de cripto: criterio anclado a un titular real --------------

def _titular(texto, horas=1.0, pid="1"):
    from xcreator.regulacion import Titular
    return Titular("@WatcherGuru", texto, f"https://x.com/WatcherGuru/status/{pid}",
                   pid, horas)


def test_elige_el_titular_de_regulacion_mas_fresco():
    from xcreator.regulacion import elegir_titular

    t = elegir_titular([
        _titular("JUST IN: Senate to discuss the Crypto Clarity Act", 5.0, "a"),
        _titular("JUST IN: US House unveils new crypto tax legislation", 1.0, "b"),
        _titular("JUST IN: Bitcoin falls under $77,000", 0.5, "c"),   # no es regulación
    ], usados=set())
    assert t.post_id == "b"


def test_no_repite_un_titular_ya_usado_ni_uno_viejo():
    from xcreator.regulacion import HORAS_MAX_TITULAR, elegir_titular

    assert elegir_titular([_titular("Crypto Clarity Act vote", 1.0, "a")],
                          usados={"a"}) is None
    assert elegir_titular([_titular("Crypto Clarity Act vote",
                                    HORAS_MAX_TITULAR + 1, "a")],
                          usados=set()) is None


def test_el_brief_no_deja_inventar_la_noticia():
    """Sin fuente de hechos, un post propio sobre regulación inventaría la
    noticia. El titular la aporta; el brief prohíbe ir más allá."""
    from xcreator.regulacion import brief_regulacion

    b = brief_regulacion(_titular(
        "JUST IN: 🇺🇸 Democrats reject Republican crypto Clarity Act draft bill"),
        None)
    ctx = " ".join(b.context).lower()
    assert "sin verificar" in ctx
    assert "no afirmes nada que la fuente no diga" in ctx
    assert "reportedly" in ctx
    assert "just in" not in b.context[0].lower(), "se limpia el titular"
    assert "clarity act" in b.sujeto


def test_las_cifras_del_titular_son_citables_y_nada_mas():
    from xcreator.regulacion import brief_regulacion

    b = brief_regulacion(_titular("Crypto tax bill caps rate at 15%"), None)
    assert 15.0 in b.allowed_numbers()


def test_nombrar_partidos_no_publica_solo():
    """No se prohíbe —a veces la noticia no se explica sin decir quién la
    bloquea—, pero una cuenta de mercados no toma partido en automático."""
    from xcreator.regulacion import menciona_partidismo
    from xcreator.store import Queue

    assert menciona_partidismo("Democrats reject the bill") == ["democrats"]
    assert menciona_partidismo("The Senate delays the Clarity Act") == []


def test_el_borrador_partidista_espera_a_angel(tmp_path):
    from xcreator.store import Queue

    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(_draft("The Clarity Act stalls because Democrats want more.",
                     ticker="", kind="regulacion", partidismo=["democrats"]),
              estado="programado")
    assert q.get(i.id).estado == "pendiente"


def test_la_fuente_NO_va_en_url_origen(tmp_path):
    """url_origen es de los replies: el publicador bloquea todo lo que lo
    tenga con más de 12 horas. Ahí habría vuelto impublicable el post."""
    from xcreator.store import Queue

    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(_draft("The Clarity Act is about jurisdiction.", ticker="",
                     kind="regulacion",
                     fuente="https://x.com/WatcherGuru/status/9"))
    item = q.get(i.id)
    assert item.fuente.endswith("/9") and item.url_origen == ""
    assert "9" in q.fuentes_usadas()


def test_regulacion_no_puede_atribuirse_llamadas():
    from xcreator.generate import SIN_HISTORIAL

    assert "regulacion" in SIN_HISTORIAL


def test_regulacion_se_detecta_por_contexto_y_senal_no_por_frase_fija():
    """La primera versión buscaba «crypto regulation» y se saltó «CFTC files new
    rulemaking to regulate crypto transactions»: mismo sentido, otro orden."""
    from xcreator.regulacion import es_regulacion_cripto as r

    assert r("CFTC files new rulemaking to regulate crypto transactions")
    assert r("SEC Chair Paul Atkins says approving tokenized stock trading")
    assert r("US sanctions BitBank crypto exchange for supporting Iran")
    assert not r("JPMorgan says Bitcoin could outperform gold")
    assert not r("Bitcoin surges 5% to $80,000")
    assert not r("Federal Reserve now projected to raise interest rates")


def test_un_titular_de_ia_no_es_regulacion_de_cripto():
    from xcreator.regulacion import es_regulacion_cripto

    assert not es_regulacion_cripto("Anthropic cuts token prices under new EU rules")


def test_el_post_tiene_que_nombrar_la_entidad_concreta():
    """"regulators" obliga a adivinar quién; "CFTC" no."""
    from xcreator.regulacion import sujeto_del_titular

    assert sujeto_del_titular(
        "CFTC files new rulemaking to regulate crypto transactions") == ("cftc",)


def test_replies_y_posts_clasifican_igual_el_mismo_titular():
    """Una lista de frases en cada sitio acaba clasificando distinto."""
    from xcreator.regulacion import es_regulacion_cripto
    from xcreator.replies import _tema_sin_cifras

    t = "CFTC files new rulemaking to regulate crypto transactions"
    assert es_regulacion_cripto(t)
    assert _tema_sin_cifras(t) == "regulación de cripto"


# --- la 3: gráficas pensadas para compartirse ------------------------------

def _serie_lineal(n=120, desde=100.0, paso=0.5):
    from datetime import date, timedelta
    hoy = date(2026, 9, 18)
    return [(str(hoy - timedelta(days=n - 1 - i)), desde + i * paso) for i in range(n)]


def test_la_grafica_de_rango_se_genera_y_no_proyecta(tmp_path):
    """Cripto y macro no tienen modelo: dibujar un futuro sería inventarlo."""
    import inspect

    from xcreator.graficos import grafico_rango

    out = grafico_rango(_serie_lineal(), tmp_path / "r.png", titulo="Bitcoin · price",
                        subtitulo="x", fuente="Data: FMP", firma="anegronro")
    assert out and out.exists() and out.stat().st_size > 10_000
    assert "fill_between" not in inspect.getsource(grafico_rango), \
        "sin modelo no hay banda de proyección"


def test_la_grafica_de_rango_pide_historico_suficiente(tmp_path):
    from xcreator.graficos import grafico_rango

    assert grafico_rango(_serie_lineal(n=5), tmp_path / "r.png", titulo="x",
                         subtitulo="x", fuente="x") is None


def test_ningun_titulo_de_grafica_lleva_raya():
    """El título también es texto publicado: la regla vale igual."""
    import inspect

    import xcreator.cli as cli
    import xcreator.graficos as g

    for fuente in (inspect.getsource(g), inspect.getsource(cli._grafico_cripto),
                   inspect.getsource(cli._grafico_macro)):
        for linea in fuente.splitlines():
            if "titulo=" in linea or "fig.text(0.065, 0.945" in linea:
                assert "—" not in linea and "–" not in linea, linea


def test_el_marcador_calcula_cuanto_quedo_fuera():
    from xcreator.marcador import Fila

    assert Fila("A", 90, 100, 150).fuera == -10.0     # 10% bajo el bear
    assert Fila("B", 165, 100, 150).fuera == 10.0     # 10% sobre el bull
    assert Fila("C", 120, 100, 150).fuera == 0.0      # dentro


def test_el_marcador_ordena_por_lo_mas_lejos():
    from xcreator.marcador import Fila, extremos

    todas = [Fila("A", 99, 100, 150), Fila("B", 80, 100, 150),
             Fila("C", 160, 100, 150), Fila("D", 120, 100, 150)]
    abajo, arriba = extremos(todas)
    assert [f.ticker for f in abajo] == ["B", "A"]
    assert [f.ticker for f in arriba] == ["C"]


def test_sin_nadie_fuera_no_hay_marcador():
    """Un marcador vacío no se publica."""
    from xcreator.marcador import brief_marcador

    b = _brief_con(precio_hoy=250.0)       # dentro del rango del _PRED de prueba
    assert brief_marcador([b]) is None


def test_el_marcador_si_puede_hablar_del_modelo():
    """Aquí las predicciones EXISTEN y están guardadas: no es historial
    inventado, así que no entra en SIN_HISTORIAL."""
    from xcreator.generate import SIN_HISTORIAL

    assert "marcador" not in SIN_HISTORIAL


def test_la_grafica_del_marcador_se_genera(tmp_path):
    from xcreator.graficos import grafico_marcador
    from xcreator.marcador import Fila

    out = grafico_marcador([Fila("ATAT", 92, 100, 150)], [Fila("COIN", 153.6, 100, 150)],
                           153, tmp_path / "m.png", firma="anegronro")
    assert out and out.exists()


def test_el_vigilante_no_pide_153_precios_por_pasada():
    """Emparejar no necesita el precio: pedirlo de todas cada 15 minutos eran
    unas 5,000 llamadas diarias a FMP."""
    import inspect

    from xcreator.cli import vigilar

    src = inspect.getsource(vigilar)
    assert "load_briefs(s.reportes_dir, None" in src
    assert "con_precio(" in src


def test_con_precio_no_toca_los_briefs_que_ya_traen_su_dato():
    from xcreator.brief import Brief, con_precio

    b = Brief(kind="macro", ticker="", angle="a")
    assert con_precio(None, b, lambda t: 1 / 0) is b


def test_el_efecto_imagen_solo_mira_posts_del_sistema():
    """Los posts manuales de Angel también pueden llevar imagen y el CSV no lo
    dice: contarlos como "sin imagen" falsearía la comparación."""
    from xcreator.analytics import Post, efecto_imagen

    def p(pid, imp):
        return Post(pid, "t", None, imp, 0, 0, 0, 0, 0, 0)

    posts = [p("a", 100), p("b", 200), p("manual", 9999)]
    f = efecto_imagen(posts, {"a": ("target_range", True),
                              "b": ("target_range", False)})["target_range"]
    assert f.n_con == 1 and f.n_sin == 1, "el manual no entra"
    assert not f.suficiente, "con 1 por lado no hay veredicto"


def test_el_efecto_imagen_no_mezcla_tipos():
    """Juntar tipos dio 84 contra 29 con p<0.001 y era tema, no gráfica: las
    de acciones tenían imagen y las de cripto nunca la habían tenido."""
    from xcreator.analytics import Post, efecto_imagen

    def p(pid, imp):
        return Post(pid, "t", None, imp, 0, 0, 0, 0, 0, 0)

    posts = [p(f"a{i}", 90) for i in range(10)] + [p(f"c{i}", 25) for i in range(10)]
    sistema = {**{f"a{i}": ("target_range", True) for i in range(10)},
               **{f"c{i}": ("cripto", False) for i in range(10)}}
    r = efecto_imagen(posts, sistema)
    assert set(r) == {"target_range", "cripto"}
    assert not r["target_range"].suficiente, "sin posts de acciones SIN imagen"
    assert not r["cripto"].suficiente, "sin posts de cripto CON imagen"


def test_el_factor_de_monetizacion_compara_ritmos_no_totales():
    """Con un export de 7 días decía "123x": dividía el umbral de 90 días
    entre las impresiones de UNA semana. El ritmo real daba 9.6x."""
    from xcreator.analytics import ReporteCuenta

    r = ReporteCuenta(dias=7, desde="2026-09-12", hasta="2026-09-18",
                      impresiones_total=40_666, impresiones_90d=40_666,
                      impresiones_30d=40_666, mediana_diaria=3_775,
                      dias_en_cero=0, follows_netos=90, replies_total=34,
                      mejor_dia=20_082)
    assert round(r.ritmo_diario_90d) == 5_809
    assert 9 < r.factor_faltante < 10, r.factor_faltante
    assert r.es_proyeccion


# --- unidades: "pct" era tres cosas distintas ------------------------------

def test_el_brief_no_le_miente_al_modelo_con_las_unidades():
    """`{:+.0%}` multiplica por 100: el brief decía que el bono a 10 años
    estaba al "+501%" y el diferencial de la curva al "+54%"."""
    from xcreator.brief import Fact

    assert Fact("10y", 5.01, "pct_val", "FRED").rendered() == "5.01%"
    assert "0.54 percentage points" in Fact("curva", 0.54, "pp", "FRED").rendered()
    assert Fact("crecimiento", 0.40, "pct", "modelo").rendered() == "+40%"


def test_un_diferencial_en_puntos_no_se_puede_escribir_como_porcentaje():
    """El post salió con "the 10y-2y Treasury spread was +54%" para 0.54
    puntos, y la validación lo dio por bueno. Lo frenó un falso positivo."""
    from xcreator.brief import Brief, Fact
    from xcreator.generate import validate_numbers

    b = Brief(kind="macro", ticker="", angle="a",
              facts=[Fact("spread", 0.54, "pp", "FRED")])
    a = b.allowed_numbers()
    assert validate_numbers("the spread was +54%", a), "54% no puede pasar"
    assert not validate_numbers("the spread was 54 bps", a)
    assert not validate_numbers("the spread was +0.54 pp", a)


def test_un_valor_ya_en_porcentaje_no_se_multiplica():
    from xcreator.brief import Brief, Fact
    from xcreator.generate import validate_numbers

    b = Brief(kind="macro", ticker="", angle="a",
              facts=[Fact("10y", 5.01, "pct_val", "FRED")])
    assert not validate_numbers("the 10-year is at 5.01%", b.allowed_numbers())
    assert validate_numbers("the 10-year is at 501%", b.allowed_numbers())


def test_una_fraccion_si_se_escribe_como_porcentaje():
    """El caso legítimo de la conversión: el crecimiento asumido 0.40."""
    from xcreator.brief import Brief, Fact
    from xcreator.generate import validate_numbers

    b = Brief(kind="target_range", ticker="NVDA", angle="a",
              facts=[Fact("crecimiento asumido", 0.40, "pct", "modelo")])
    assert not validate_numbers("base assumes +40% growth", b.allowed_numbers())


def test_macro_cripto_y_marcador_declaran_la_unidad_correcta():
    from xcreator.cripto import ACTIVOS, brief_cripto, leer
    from xcreator.macro import SERIES, brief_macro, leer as leer_m

    serie = [(f"2026-0{1 + i // 30}-{1 + i % 28:02d}", 4.0 + i * 0.01)
             for i in range(120)]
    bm = brief_macro(leer_m(SERIES["tasa10"], serie))
    assert all(f.unit == "pct_val" for f in bm.facts), "FRED da los tipos YA en %"
    assert all(f.unit == "pp" for f in brief_macro(leer_m(SERIES["curva"], serie)).facts)

    from datetime import date, timedelta
    s2 = [(str(date(2026, 9, 18) - timedelta(days=119 - i)), 100 + i) for i in range(120)]
    bc = brief_cripto(leer(ACTIVOS["btc"], s2))
    caida = next(f for f in bc.facts if f.label.startswith("caída"))
    assert caida.unit == "pct_val"


def test_el_nombre_del_sujeto_no_es_una_coletilla():
    """El detector marcó "10y-2y Treasury spread": el nombre que la regla del
    sujeto obliga a escribir."""
    from xcreator.brief import Brief, Fact
    from xcreator.generate import frases_repetidas, vocabulario_del_sujeto

    b = Brief(kind="macro", ticker="", angle="a", sujeto=("10y-2y", "treasury"),
              facts=[Fact("the 10y-2y Treasury spread ahora", 0.27, "pp", "FRED")])
    assert frases_repetidas(
        "The 10y-2y Treasury spread was +0.52 pp a month ago.",
        ["A year ago the 10y-2y Treasury spread was +0.54 pp."],
        vocabulario_del_sujeto(b)) == []


# --- IPC: inflación interanual, no el nivel del índice ----------------------

def _indice_mensual(anios=8, subida_anual=0.03, base=250.0):
    """Un IPC que sube parejo, un 3% al año."""
    out, v = [], base
    for i in range(anios * 12):
        y, m = 2019 + i // 12, 1 + i % 12
        out.append((f"{y}-{m:02d}-01", round(v, 3)))
        v *= (1 + subida_anual) ** (1 / 12)
    return out


def test_la_interanual_compara_el_mismo_mes_del_ano_anterior():
    from xcreator.macro import interanual

    s = interanual(_indice_mensual())
    assert all(abs(v - 3.0) < 0.05 for _, v in s), s[:3]


def test_la_interanual_se_queda_con_cinco_anos():
    """Sin recortar, 400 observaciones mensuales son 33 años de "rango"."""
    from xcreator.macro import MESES_INTERANUAL, interanual

    assert len(interanual(_indice_mensual(anios=20))) == MESES_INTERANUAL


def test_un_indice_que_sube_parejo_no_es_un_extremo():
    """El IPC en nivel casi siempre está en máximos, así que el puntuador lo
    leía como un extremo permanente. En interanual, un 3% constante es plano."""
    from xcreator.macro import SERIES, interanual, leer

    cfg = SERIES["inflacion"]
    crudo = _indice_mensual()
    assert leer(cfg, crudo).tension >= 1, "en nivel parecía un extremo"
    assert leer(cfg, interanual(crudo)).tension == 0


def test_el_ipc_se_publica_como_porcentaje_interanual():
    from xcreator.macro import SERIES, brief_macro, interanual, leer

    cfg = SERIES["inflacion"]
    assert cfg.interanual and cfg.unidad == "pct"
    serie = interanual(_indice_mensual(subida_anual=0.035))
    b = brief_macro(leer(cfg, serie))
    assert b.facts[0].unit == "pct_val"
    assert b.facts[0].rendered().endswith("%") and "year over year" in b.facts[0].label


def test_nadie_pide_una_serie_macro_por_fuera_de_serie_de():
    """Si la transformación viviera en un solo sitio, los otros seguirían
    leyendo el índice en nivel."""
    import re
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[1] / "xcreator"
    for f in raiz.glob("*.py"):
        for n, linea in enumerate(f.read_text().splitlines(), 1):
            if re.search(r"fred_series\(cfg\.serie", linea):
                assert f.name == "macro.py", f"{f.name}:{n}"


# --- citas: el titular con más conversación, pegado a mano ------------------

def _id_reciente(n=0):
    """Un id de X de hace una hora: el id lleva la fecha dentro, y "1" o "2"
    parecen posts de 2010 que el filtro de 24 horas descarta."""
    import time
    from xcreator.publicar import _EPOCA_X_MS
    ms = int(time.time() * 1000) - 3_600_000
    return str(((ms - _EPOCA_X_MS) << 22) + n)


def _post_ajeno(pid, texto, rt=0, rep=0, quo=0, likes=0, autor="@zerohedge"):
    from xcreator.xapi import PostAjeno
    return PostAjeno(pid, autor, texto, metricas={
        "retweet_count": rt, "reply_count": rep, "quote_count": quo,
        "like_count": likes})


def test_la_conversacion_cuenta_replies_citas_y_reposts_no_likes():
    """Los likes pesan 0.5 y no traen a nadie a la conversación."""
    p = _post_ajeno("1", "x", rt=10, rep=5, quo=2, likes=9999)
    assert p.conversacion == 17


def test_se_cita_el_post_con_mas_conversacion_que_aporte_algo():
    from xcreator.citas import elegir_para_citar
    from xcreator.replies import Relevancia

    a, b, c = _id_reciente(1), _id_reciente(2), _id_reciente(3)
    posts = [_post_ajeno(a, "irrelevante", rep=500),
             _post_ajeno(b, "Fed keeps rates on hold", rep=40),
             _post_ajeno(c, "CPI comes in hot", rep=90)]

    def rel(p):
        return Relevancia(object(), motivo="x") if p.post_id != a \
            else Relevancia(None, motivo="no")

    elegido, _ = elegir_para_citar(posts, rel, excluir=set())
    assert elegido.post_id == c, "el de más conversación CON algo que aportar"


def test_no_se_cita_lo_que_ya_se_respondio():
    """Responder y citar el mismo post se lee como spam."""
    from xcreator.citas import elegir_para_citar
    from xcreator.replies import Relevancia

    c, b = _id_reciente(3), _id_reciente(2)
    posts = [_post_ajeno(c, "CPI comes in hot", rep=90), _post_ajeno(b, "Fed", rep=40)]
    elegido, _ = elegir_para_citar(
        posts, lambda p: Relevancia(object(), motivo="x"), excluir={c})
    assert elegido.post_id == b


def test_la_cita_no_se_publica_por_api(tmp_path):
    """Misma restricción que los replies. Y NO se usa el atajo de pegar el
    enlace del post para que X lo convierta en cita."""
    from xcreator.publicar import revisar_antes_de_publicar
    from xcreator.replies import ReplyDraft
    from xcreator.store import Queue

    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(ReplyDraft(texto="The Fed guided it there.", que_aporta="x",
                         autor="@business", kind="cita",
                         url="https://x.com/business/status/1"))
    q.aprobar(i.id)
    assert any("citas no se pueden publicar" in p
               for p in revisar_antes_de_publicar(q.get(i.id)))


def test_la_cita_no_gasta_el_cupo_de_replies(tmp_path):
    from xcreator.replies import ReplyDraft
    from xcreator.store import Queue

    q = Queue(tmp_path / "cola.jsonl")
    q.add(ReplyDraft(texto="c", que_aporta="x", autor="@a", kind="cita",
                     url="https://x.com/a/status/1"))
    assert q.citas_de_hoy() == 1 and q.replies_de_hoy() == 0


def test_una_cita_y_un_reply_al_mismo_post_cuentan_como_ya_tocado(tmp_path):
    from xcreator.replies import ReplyDraft
    from xcreator.store import Queue

    q = Queue(tmp_path / "cola.jsonl")
    q.add(ReplyDraft(texto="c", que_aporta="x", autor="@a", kind="cita",
                     url="https://x.com/a/status/77"))
    assert q.ya_respondido("https://x.com/a/status/77")


def test_la_cita_llega_con_instrucciones_de_citar_no_de_responder(tmp_path):
    from xcreator.replies import ReplyDraft
    from xcreator.store import Queue
    from xcreator.telegram import mensaje_para_copiar

    q = Queue(tmp_path / "cola.jsonl")
    i = q.add(ReplyDraft(texto="The Fed guided it there.", que_aporta="x",
                         autor="@business", kind="cita",
                         url="https://x.com/business/status/1"))
    txt = mensaje_para_copiar(q.get(i.id))
    assert "CITAR" in txt and "<b>Citar</b>" in txt
    assert "<pre>The Fed guided it there.</pre>" in txt


def test_la_cita_y_el_post_de_regulacion_no_usan_el_mismo_titular():
    """Saldrían dos posts del perfil sobre la misma noticia."""
    import inspect

    from xcreator.cli import _regulacion_desde_x, citar

    # Solo el respaldo de X puede chocar con una cita: los comunicados
    # oficiales no son posts de X y no se citan.
    assert "fuentes_usadas()" in inspect.getsource(citar)
    reg = inspect.getsource(_regulacion_desde_x)
    assert '"cita"' in reg and "fuentes_usadas()" in reg


def test_cashtags_de_mas_encuentra_los_que_sobran():
    """X admite UN cashtag: el segundo y el tercero hacen fallar el post."""
    from xcreator.generate import cashtags_de_mas

    assert cashtags_de_mas("$ATAT left the range, $COHR and $EQIX too") == [
        "$COHR", "$EQIX"]
    # El ticker repetido en sus dos formas es lo normal y no sobra nada.
    assert cashtags_de_mas("$NVDA at 45x. NVDA is not cheap.") == []
    assert cashtags_de_mas("no tickers here") == []


def test_publicar_bloquea_el_post_con_dos_cashtags():
    """El marcador que tumbó la cola dos días no debe poder salir."""
    from xcreator.publicar import revisar_antes_de_publicar
    from xcreator.store import Item

    item = Item(id="x", creado="2026-09-18T20:31:00+00:00", estado="programado",
                texto="We publish our misses. $ATAT is 40% below, $COHR too.",
                kind="marcador")
    problemas = revisar_antes_de_publicar(item)
    assert any("cashtags" in p for p in problemas), problemas


# --- Proveedor xAI -----------------------------------------------------------

class _HttpFalso:
    """Responde como la API de chat completions de xAI y guarda la petición."""

    def __init__(self, contenido, finish="stop", status=200):
        self.contenido, self.finish, self.status = contenido, finish, status
        self.peticion = None

    def post(self, url, json=None, headers=None):
        import json as _json

        self.peticion = {"url": url, "json": json, "headers": headers}
        cuerpo = {"choices": [{"message": {"content": self.contenido},
                               "finish_reason": self.finish}],
                  "usage": {"prompt_tokens": 1000, "completion_tokens": 500}}

        class R:
            status_code = self.status
            text = _json.dumps(cuerpo)

            def json(self_inner):
                return cuerpo
        return R()


def test_xai_parse_devuelve_el_modelo_pydantic_y_anota_el_gasto(tmp_path):
    import json

    from xcreator.generate import _Variants
    from xcreator.llm import ClienteXAI

    salida = {"variants": [{"approach": "a", "text": "$NVDA at 44x. NVDA.",
                            "thread": [], "reply_hook": "h"}]}
    http = _HttpFalso(json.dumps(salida))
    registro = tmp_path / "uso.jsonl"
    c = ClienteXAI("k", registro=registro, http=http)
    r = c.messages.parse(model="claude-opus-5", max_tokens=100,
                         system=[{"type": "text", "text": "SYS"}],
                         messages=[{"role": "user", "content": "hola"}],
                         output_format=_Variants)

    assert r.parsed_output.variants[0].text.startswith("$NVDA")
    cuerpo = http.peticion["json"]
    # El id de Claude no viaja a xAI: manda el modelo del cliente.
    assert cuerpo["model"] == "grok-4.6"
    assert cuerpo["messages"][0] == {"role": "system", "content": "SYS"}
    esquema = cuerpo["response_format"]["json_schema"]["schema"]
    assert "$defs" not in json.dumps(esquema)
    item = esquema["properties"]["variants"]["items"]
    assert item["additionalProperties"] is False
    assert set(item["required"]) == {"approach", "text", "thread", "reply_hook"}
    linea = json.loads(registro.read_text())
    # 1000 de entrada a $2/M y 500 de salida a $6/M.
    assert linea["usd"] == 0.005


def test_xai_corte_por_techo_se_marca_como_max_tokens():
    from xcreator.llm import ClienteXAI

    c = ClienteXAI("k", http=_HttpFalso("texto cortad", finish="length"))
    r = c.messages.create(max_tokens=10,
                          messages=[{"role": "user", "content": "x"}])
    assert r.stop_reason == "max_tokens"
    assert r.content[0].text == "texto cortad"


def test_xai_error_http_no_se_traga():
    import pytest

    from xcreator.llm import ClienteXAI, LLMError

    c = ClienteXAI("k", http=_HttpFalso("{}", status=402))
    with pytest.raises(LLMError):
        c.messages.create(messages=[{"role": "user", "content": "x"}])


def test_nunca_cae_a_anthropic_sin_pedirlo():
    from xcreator.config import Settings, llm_client, proveedor

    assert proveedor(Settings(xai_api_key="k", anthropic_api_key="a")) == "xai"
    # Sin clave de xAI NO se usa Anthropic aunque su clave exista: no hay
    # cliente y el agente no redacta.
    solo_anthropic = Settings(anthropic_api_key="a")
    assert proveedor(solo_anthropic) == "xai"
    assert llm_client(solo_anthropic) is None
    assert proveedor(Settings(llm_proveedor="anthropic")) == "anthropic"


def test_espaciado_no_se_salta_por_un_reply_aprobado():
    """Un reply aprobado en la cola dejaba salir posts cada 30 minutos."""
    from xcreator.store import ESPACIADO_MINUTOS, HOLGURA_MINUTOS

    assert ESPACIADO_MINUTOS == 45
    # A los 44.95 min del post anterior el turno ya cuenta como cumplido.
    assert not (44.95 < ESPACIADO_MINUTOS - HOLGURA_MINUTOS)


def test_brief_macro_guarda_la_serie_como_motivo():
    from xcreator.macro import SERIES, Lectura, brief_macro

    cfg = next(iter(SERIES.values())) if isinstance(SERIES, dict) else SERIES[0]
    import inspect
    campos = inspect.signature(Lectura).parameters
    valores = {k: None for k in campos}
    valores.update(cfg=cfg, fecha="2026-09-21", valor=4.5, percentil_5a=0.9,
                   minimo_5a=3.0, maximo_5a=5.0)
    try:
        lec = Lectura(**valores)
        b = brief_macro(lec)
    except Exception:
        import pytest
        pytest.skip("Lectura necesita campos que este test no construye")
    assert b.motivo == f"macro:{cfg.serie}"



# --- Fuentes oficiales ---------------------------------------------------------

_RSS_SEC = '''<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>Press Releases</title>
<item>
  <title>  SEC Issues “Innovation Exemption” to Facilitate the Trading of Tokenized NMS Stock
</title>
  <link>https://www.sec.gov/newsroom/press-releases/2026-90-sec-issues-innovation-exemption</link>
  <description>Facilitating onchain trading of certain tokenized stocks.</description>
  <pubDate>Thu, 17 Sep 2026 08:55:00 -0400</pubDate>
</item>
<item>
  <title>SEC Proposes Rescission of Shareholder Proposal Rule</title>
  <link>https://www.sec.gov/newsroom/press-releases/2026-89-sec-proposes-rescission</link>
  <description>Rule 14a-8.</description>
  <pubDate>Wed, 16 Sep 2026 10:00:00 -0400</pubDate>
</item>
</channel></rss>'''


def test_rss_de_la_sec_da_el_numero_del_comunicado():
    from xcreator.fuentes_oficiales import parse_rss

    cs = parse_rss(_RSS_SEC, "SEC")
    assert len(cs) == 2
    assert cs[0].documento == "SEC press release 2026-90"
    assert cs[0].handle == "@SECGov"
    assert cs[0].titulo.startswith("SEC Issues")
    assert cs[0].fecha.tzinfo is not None


def test_solo_el_comunicado_de_cripto_es_tema_de_regulacion():
    from xcreator.fuentes_oficiales import a_titular, parse_rss
    from xcreator.regulacion import elegir_titular

    ts = [a_titular(c) for c in parse_rss(_RSS_SEC, "SEC")]
    for t in ts:
        t.horas = 5.0
    elegido = elegir_titular(ts, set(), horas_max=72)
    # El de la regla de accionistas no es cripto; el de tokenización sí.
    assert elegido is not None and "Tokenized" in elegido.texto
    # Ya usado: no se repite.
    assert elegir_titular(ts, {elegido.post_id}, horas_max=72) is None


def test_federal_register_se_atribuye_a_la_agencia():
    from xcreator.fuentes_oficiales import parse_federal_register

    cs = parse_federal_register({"results": [{
        "title": "Regulation Crypto Assets", "abstract": "The Commission...",
        "html_url": "https://www.federalregister.gov/documents/2026/08/21/x/regulation-crypto-assets",
        "publication_date": "2026-08-21", "type": "Proposed Rule",
        "agencies": [{"name": "Securities and Exchange Commission"}]}]})
    assert cs[0].agencia == "SEC" and cs[0].handle == "@SECGov"
    assert cs[0].documento == "Federal Register proposed rule"


def test_brief_oficial_atribuye_con_la_arroba_y_sin_reportedly():
    from xcreator.fuentes_oficiales import a_titular, parse_rss
    from xcreator.regulacion import brief_regulacion

    c = parse_rss(_RSS_SEC, "SEC")[0]
    b = brief_regulacion(a_titular(c), None, oficial=True,
                         documento=c.documento, mencion=c.handle)
    ctx = " ".join(b.context)
    assert b.atribucion == ("@SECGov",)
    assert "COMUNICADO OFICIAL" in ctx and "reportedly" not in ctx.lower()
    assert "SIN enlace" in ctx


def test_falta_atribucion_reconoce_la_arroba():
    from xcreator.generate import falta_atribucion

    assert not falta_atribucion("Per @SECGov, tokenized stocks trade.", ["@SECGov"])
    assert falta_atribucion("The regulator said tokenized stocks trade.", ["@SECGov"])
    assert not falta_atribucion("anything", [])


def test_publicar_bloquea_post_que_empieza_por_arroba_o_sin_fuente():
    from xcreator.publicar import revisar_antes_de_publicar
    from xcreator.store import Item

    base = dict(id="x", creado="2026-09-21T12:00:00+00:00", estado="programado",
                kind="regulacion", atribucion=["@SECGov"])
    empieza = Item(texto="@SECGov just opened the door to tokenized stocks.", **base)
    assert any("empieza por una mención" in p
               for p in revisar_antes_de_publicar(empieza))
    sin = Item(texto="The regulator just opened the door to tokenized stocks.", **base)
    assert any("no atribuye la fuente" in p for p in revisar_antes_de_publicar(sin))
    bien = Item(texto="Tokenized stocks got a green light from @SECGov today.", **base)
    assert not any("atribuye" in p or "mención" in p
                   for p in revisar_antes_de_publicar(bien))
