# Especificación de x-creator: agente de contenido para X

Documento de implementación. Está escrito para que otro modelo de lenguaje
pueda reconstruir el sistema completo sin ver el código original. Todo lo que
aparece aquí salió de un sistema que lleva corriendo en producción desde
septiembre de 2026, publicando a diario en una cuenta real.

Cada regla rara que veas tiene detrás un fallo que costó dinero o alcance.
La sección 16 cuenta cuál fue cada uno. Léela antes de "simplificar" algo.

---

## 1. Qué es

Un agente que produce contenido financiero para una cuenta de X (Twitter) y
lo pasa por una cola de aprobación humana antes de publicar. No analiza para
invertir: convierte análisis que ya existen en posts que generan discusión.

**Objetivo de negocio:** el programa de monetización de X. Los requisitos
reales, comprobados en la pantalla del programa el 18 de septiembre de 2026:

| Requisito | Estado típico de una cuenta nueva |
|---|---|
| Suscripción Premium activa | cumplido |
| 18 años o más | cumplido |
| 500 seguidores **verificados** | 30 |
| 500,000 impresiones **verificadas** en Home Timeline en 90 días | 74 |

Las dos trampas de ese cuadro, y que definen el diseño entero:

1. **Los replies no cuentan** para las impresiones. Solo cuentan los posts
   originales vistos en el Home Timeline.
2. **Solo cuentan las impresiones de usuarios Premium.** Una cuenta puede
   hacer 5,800 impresiones al día y tener 74 que cuenten.

Consecuencia de diseño: los replies existen para ganar **seguidores
verificados**, los posts propios existen para ganar **impresiones
verificadas**. Son dos motores distintos con dos métricas distintas. Un
sistema que los mide juntos no sabe lo que está haciendo.

---

## 2. Restricciones de la plataforma (no negociables)

### 2.1 API de X

Desde febrero de 2026 es pay-per-use, sin free tier.

| Acción | Costo |
|---|---|
| Publicar un post | $0.015 |
| **Publicar un post con link** | **$0.20** (13x) |
| Leer un post | $0.005 |
| Leer un usuario | $0.010 |

Reglas que salen de ahí:

- **Prohibido incluir URLs en los posts.** Cuestan 13 veces más y además
  hunden el alcance orgánico.
- **Presupuesto por pasada.** Toda función que lea posts recibe un tope de
  gasto (por defecto $0.50) y se detiene al alcanzarlo. Un bucle con un bug
  no puede vaciar los créditos en una tarde.
- **Un solo cashtag por post.** X devuelve `403 Authorization Error` con el
  mensaje "Posts are limited to a maximum of one cashtag ($SYMBOL)". El
  segundo `$TICKER` hace fallar el post entero.

### 2.1b Autorización para publicar (OAuth 2.0)

La app de X tiene que ser **Native App** (cliente público): OAuth 2.0 con
PKCE, sin Client Secret. Como **Web App** exige el secreto en cada
renovación, y el 21 de septiembre de 2026 ese cambio de tipo tumbó la
publicación con `401 unauthorized_client: Missing valid authorization
header`. El callback registrado tiene que coincidir letra por letra con el
que usa el agente (`http://127.0.0.1:8788/callback`); `localhost` no vale
como sustituto.

La sesión dura 2 horas y se renueva sola con el refresh token. Solo UNA
máquina debe renovarla (el VPS): si otra también renueva, el refresh token
rota y deja a la primera sin sesión.

Diagnóstico sin molestar al usuario: POST al token endpoint con un código
falso. `400 invalid_request` = la app está bien configurada; `401
unauthorized_client` = tipo de app o secreto mal.

### 2.2 Lo que la API NO permite

**No se pueden publicar replies ni quotes por API** con los permisos
normales de una app de creador. El agente los redacta, pero los pega el
humano a mano. El sistema debe asumir esto desde el diseño:

- Un reply o una cita se entregan por Telegram en formato copiable.
- Nunca se intenta falsificar una cita pegando el enlace del post ajeno en
  un post normal. X lo renderiza parecido, pero el algoritmo lo trata como
  post con link: 13x de costo y menos alcance.

### 2.3 Pesos del algoritmo de X (versión pública 2026)

Del repositorio abierto del algoritmo, archivo de parámetros del mezclador
de Home. Son los pesos que multiplican la probabilidad predicha de cada
acción del lector:

| Acción del lector | Peso |
|---|---|
| Compartir copiando el enlace | 20.0 |
| Responder | 5.0 |
| Citar | 5.0 |
| Compartir por mensaje directo | 5.0 |
| Seguir al autor | 4.0 |
| Retweet | 1.0 |
| Like | 0.5 |
| Clic al perfil | 0.0 |
| Dwell (permanencia) | 0.05 |
| Abrir video | 0.07 |
| **No me interesa** | **-43.2** |
| **Silenciar** | **-58.8** |
| **Bloquear** | **-31.2** |
| **Reportar** | **-234** |

Otros parámetros relevantes: decaimiento por diversidad de autor 0.5 con
suelo en 0.25 (el segundo post tuyo en el mismo feed vale la mitad), factor
para contenido fuera de red 0.75, filtro de edad 48 horas.

Lo que implica:

- Un post que alguien quiere **mandarle a otra persona** vale 40 veces un
  like. Formato: listas, marcadores, gráficos de una sola imagen.
- Un post que provoca **respuesta** vale 10 veces un like.
- **Un solo silencio borra lo que suman 117 likes.** Por eso publicar más no
  es gratis: el volumen sin calidad tiene costo negativo real.
- No hay señal de "hilo" ni de "encuesta" en el código, y tampoco hay boost
  por Premium. Las guías que repiten el "x75 por reply del autor" citan la
  versión de 2023: ese multiplicador ya no existe.

### 2.4 Dato medido sobre formatos

Estudio de Buffer sobre unos 18.8 millones de posts: texto solo 3.56% de
engagement, imagen 3.40%, video 2.96%, link 2.25%. La diferencia entre
cuenta Premium y normal pesa más que el formato. **La imagen no es una
mejora automática**: hay que medirla en la propia cuenta, estratificando por
tipo de post (ver sección 14).

---

## 3. Arquitectura

Python 3.11+, CLI con Typer, sin servidor web ni base de datos. Todo el
estado vive en archivos dentro de `Contenido/`. Corre por cron.

```
xcreator/
  config.py      Settings desde API/.env. Nunca hace repr de un secreto.
  datos.py       Fuentes de mercado: precios e histórico (FMP).
  cerebro.py     Carga selectiva de metodología de análisis por ángulo.
  brief.py       Convierte una predicción guardada en hechos con fuente.
  temas.py       Puntúa qué ticker tiene HOY una historia que contar.
  generate.py    El modelo redacta. El validador verifica en código.
  macro.py       Series macro (FRED) como tema propio.
  cripto.py      Activos digitales (FMP) como tema propio.
  regulacion.py  Posts anclados a un titular real de regulación cripto.
  marcador.py    El marcador semanal: dónde falló el modelo.
  citas.py       Elegir un post ajeno para citar (una al día).
  replies.py     Emparejar posts ajenos con datos propios y redactar reply.
  xapi.py        Lectura de la API de X (app-only, no publica).
  xauth.py       OAuth 2.0 PKCE con refresh, para publicar como el usuario.
  publicar.py    Revisión final y publicación. Única acción irreversible.
  store.py       Cola append-only en JSONL. Nada se borra.
  telegram.py    Cola de aprobación con botones. Bot propio.
  graficos.py    Imágenes con matplotlib. Rango siempre, nunca una línea.
  analytics.py   Mide qué funciona con el CSV de analytics.x.com.
  cli.py         Comandos.
```

**Dependencia externa opcional:** un motor de análisis de acciones que
escribe `prediccion.json` por ticker y por fecha, y una carpeta de
metodología. Se leen **por ruta**, nunca se importa su código. Si ese
proyecto desaparece, se pierde una fuente, no el sistema.

---

## 4. Modelo de datos

### 4.1 Fact y Brief

Es la pieza central. **Un número solo puede aparecer en un post si viene de
un `Fact` con fuente declarada.**

```python
@dataclass(frozen=True)
class Fact:
    label: str      # "precio hoy", "escenario bajo (12m)"
    value: float
    unit: str       # ver tabla de unidades
    source: str     # "FMP quote", "FRED DGS10, dato del 2026-09-18"

@dataclass
class Brief:
    kind: str       # target_range | thesis_check | macro | cripto |
                    # regulacion | marcador
    ticker: str     # vacío en macro y marcador
    sujeto: tuple[str, ...]   # alias que el post DEBE nombrar
    angulo: str     # negocio|finanzas|mercado|tecnico|riesgo|valuacion
    angle: str      # la pregunta que abre este post, en inglés
    facts: list[Fact]
    context: list[str]        # instrucciones y prohibiciones para el modelo
    as_of: str                # fecha ISO
```

### 4.2 Unidades (esto causó dos posts publicados con cifras falsas)

| unit | Qué contiene | Cómo se renderiza |
|---|---|---|
| `usd` | dólares | `$305.61` |
| `pct` | **fracción** (0.33 = 33%) | `+33%` |
| `pct_val` | **ya viene en %** (4.94 = 4.94%) | `4.94%` |
| `pp` | puntos porcentuales | `+0.54 percentage points (+54 bps)` |
| `ratio` | múltiplo | `44.2x` |
| `num` | conteo | `153` |

La lista de números permitidos que usa el validador incluye, para `pct`, el
valor y su versión multiplicada por 100. Para `pp` **no** se multiplica: son
puntos, no una fracción. Confundirlos hizo publicar "la curva subió 33%"
cuando el hecho era "subió 0.33 puntos porcentuales".

### 4.3 Item de la cola

```python
@dataclass
class Item:
    id: str                 # sha1 corto
    creado: str             # ISO UTC
    estado: str             # pendiente|aprobado|programado|rechazado|
                            # publicado|bloqueado
    texto: str
    hilo: list[str]
    ticker: str
    kind: str               # ver Brief.kind, más "reply" y "cita"
    brief_id: str           # vacío en replies de opinión
    model: str
    imagen: str             # ruta del gráfico si lo lleva
    motivo: str             # la clave de la historia ("bear_pegado")
    fuente: str             # titular de origen, en posts de regulación
    # Banderas de problemas detectados al generar
    numeros_no_justificados: list[str]
    tickers_faltantes: list[str]
    frases_repetidas: list[str]
    partidismo: list[str]
    truncado: bool
    idioma_incorrecto: bool
    # Decisión y publicación
    texto_editado: str      # la edición del humano gana sobre el original
    decidido: str
    motivo_rechazo: str
    responde_a: str         # solo replies
    url_origen: str         # solo replies y citas
    publicado_en: str
    post_id: str
    metricas: dict
    fallos_al_publicar: int # a los 3 rechazos se bloquea
```

`texto_final` es `texto_editado or texto`. Todas las validaciones corren
sobre `texto_final`, no sobre el original: aprobar y editar son dos cosas
distintas y lo que sale es lo editado.

La cola es **append-only en JSONL**, con reescritura atómica (tmp + rename).
Una línea corrupta se salta sin tumbar la cola entera.

---

## 5. Las reglas de contenido

### 5.1 Prompt de sistema para posts propios

Va en inglés porque la cuenta publica en inglés. Literal:

```
You write for a finance/markets account on X. Your posts exist to start
arguments that informed people want to join, not to inform and stop.

Non-negotiable rules:
1. NEVER use a number that is not in the brief's allowed list. Not one. If
you want to make a point that needs a number you don't have, make a
different point.
1b. NEVER cite an internal score or rating ("scores 8.7/10", "our model
rates it 6/10"). The reader cannot see that scorecard, does not know the
scale, and cannot verify it, so it reads as self-promotion and burns
characters that could carry a checkable fact. Prices, multiples, growth
assumptions and scenario ranges ARE verifiable; say those instead.
2. NEVER tell anyone to buy, sell, or hold. You publish research
classifications and ranges with stated assumptions. "The model's range is X"
is fine; "load up here" is not.
3. NEVER include a link or a URL. Links cut organic reach and cost 13x more
to publish.
3b. ALWAYS mention the ticker BOTH ways somewhere in the post: as a cashtag
($NVDA) and as plain text (NVDA). X indexes them separately: the cashtag
makes it clickable and files it under the symbol, the plain text shows up in
regular search. Using only one throws away half the discovery. Work both
into sentences that read naturally; do NOT tack the ticker onto the end as a
label.
3c. ONE cashtag per post, never two. X rejects with an error any post
carrying two or more $TICKER. Name the other companies without the dollar
sign.
4. Always state the assumption behind a projection. A number without its
assumption is a lie told with confidence.
5. Never present a projection as a single value when the brief gives a range.
6. No dashes as punctuation: no em dash, no en dash, no " - " between
clauses. Use a full stop, a comma or a colon. Hyphens inside a word are fine
and expected ("10-year", "high-yield", "mid-range").
7. Numbers follow English convention: comma for thousands and a full stop
for decimals (79,900 and 10.99). Never the other way round.

How to earn replies (this is what gets paid):
- Take a position, then show the number that supports it. A post with no
position gets no replies.
- The number serves the position, not the other way round. A post whose
value is a judgement, an incentive nobody names, a distinction people are
collapsing, what would have to be true for the consensus to hold, is a good
post, and it does not need a statistic bolted on to justify itself. Rule 1
still binds every figure you do use; it never obliges you to use one.
- End on something a knowledgeable person would want to answer or correct:
an open question, a claim they can push back on, a scenario they'd price
differently. Not "what do you think?", which reads as engagement bait.
- Publishing your own misses beats publishing only your hits. It is rarer
and it draws better replies.
- Concrete beats clever. No hype adjectives, no emoji walls, no hashtags.

Voice: direct, numerate, unimpressed. Short sentences. Someone who has read
the filing and is mildly annoyed that others haven't.
```

El bloque de metodología del ángulo va en un segundo bloque de sistema con
`cache_control: ephemeral`, porque no cambia entre llamadas.

### 5.2 Prompt de sistema para replies de opinión (sin datos propios)

```
You write replies on X for a finance account. This one is different from the
rest: there is no data behind it.

You are answering a post about markets, policy or the industry where we hold
no figures of our own. That is not a reason to stay quiet: it means the
value of this reply is the judgement, not a statistic. Most replies under
these posts are cheering or booing. A reply that names the mechanism nobody
is naming is worth more than another number would be.

Hard rules:
1. NO NUMBERS. Not one, unless it already appears in the post you are
answering. You have no brief here, so any figure you write would be invented.
2. Assert no fact beyond what the post states. You do not know what a bill
contains, what happened after this post, or what anyone said elsewhere. If
your point needs a fact you do not have, make a different point.
3. Take a real position: a consequence the post skips, a distinction people
are collapsing, an incentive nobody named, or what would have to be true for
the headline to matter. "Interesting" is not a position.
4. No party politics. You may say an incentive is obvious or a rule is
incoherent; you never take a side between parties, and you never attack a
person. The account is about markets, not elections.
5. Never tell anyone to buy or sell, and never predict a price.
6. Don't insult the author. No links, no hashtags, no emoji. No dashes as
punctuation either. Hyphens inside a word are fine ("10-year").
7. If you have nothing worth saying, set aporta_algo to false. Silence is a
correct answer and is far better than a generic take.

Tone: someone who has watched this cycle before and is unimpressed by the
headline. One or two sentences, no preamble.
```

### 5.3 Validaciones en código (el prompt no garantiza nada)

Esta es la parte que distingue el sistema de "pedirle posts a un modelo".
Cada una corre **dos veces**: al generar y otra vez justo antes de publicar.

| Función | Qué detecta |
|---|---|
| `validate_numbers(texto, permitidos)` | toda cifra del texto que no esté en la lista del brief, con tolerancia de redondeo |
| `falta_ticker(texto, ticker)` | que falte `$TICKER` o `TICKER` a secas |
| `cashtags_de_mas(texto)` | el segundo cashtag y siguientes (X los rechaza) |
| `falta_sujeto(texto, alias)` | un post de macro o cripto que no nombra de qué habla |
| `lleva_raya(texto)` | raya larga, raya corta o " - " entre cláusulas |
| `cifras_mal_formateadas(texto)` | "4,95" en vez de "4.95", o "1.000" por mil |
| `afirma_llamada_propia(texto)` | "I called", "my miss", "we predicted", "I was wrong" en temas sin historial guardado |
| `es_ingles(texto)` | el post salió en otro idioma |
| `tiene_link(texto)` | cualquier URL |
| `frases_repetidas(texto, recientes, ignorar)` | 4-gramas que ya salieron en posts recientes |
| `_partidismo(texto)` | nombres de partidos o políticos |
| `_parece_cortado(texto)` | respuesta truncada por el techo de tokens |
| largo | más de 280 caracteres |

Detalles que importan:

- `frases_repetidas` ignora las palabras del sujeto del propio brief. Sin
  eso marcaba como repetición el nombre de la empresa, que obviamente se
  repite.
- Detectar el truncamiento requiere mirar dos cosas: el último carácter y
  los saltos de línea. Una palabra partida en medio no se ve mirando el
  final. Terminar en un ticker **no** es truncamiento, es un cierre normal.
- Un modelo no puede contar caracteres de forma fiable. El límite se
  comprueba en código y, si se pasa, se pide un recorte en una llamada
  aparte; si tampoco cabe, queda marcado para edición humana.

---

## 6. Pipeline de generación

```
predicción guardada
   -> brief.py         hechos con fuente y unidades
   -> temas.py         ¿tiene historia hoy? ¿ya salió esta semana?
   -> cerebro.py       metodología del ángulo (bloque cacheado)
   -> modelo           N variantes en salida estructurada
   -> validaciones     números, ticker, sujeto, estilo, repetición
   -> cola             pendiente o programado
   -> Telegram         aprobar / editar / rechazar
   -> publicar.py      revisión final y POST a X
```

Puntos de diseño:

- **Salida estructurada** con un esquema de variantes, no texto libre.
- `max_tokens` alto (16,000 con un modelo que razona antes de responder):
  el razonamiento cuenta contra ese techo, y con 8,000 la última variante
  salía cortada a media frase.
- Se le pasan al modelo **los posts recientes** con la instrucción de no
  reutilizar su arranque, su estructura ni su pregunta final.
- Un borrador con problemas **nunca nace programado**. La publicación
  automática solo se aplica a lo que pasó todas las validaciones.

---

## 7. Selección de tema (por qué este ticker y no otro)

Tener 178 análisis no es tener 178 temas. Un ticker dentro de su rango, con
múltiplo normal, no da post. El sistema puntúa la **tensión editorial** con
reglas explícitas, cada una con su motivo escrito:

| Condición | Puntos | Clave |
|---|---|---|
| precio por debajo del escenario bajo | +3 | `rompe_bajo` |
| precio por encima del escenario alto | +3 | `rompe_alto` |
| se movió 15% o más desde el análisis | +2 | `movimiento` |
| el escenario bajo está a menos del 5% del precio de entrada | +2 | `bear_pegado` |
| múltiplo extremo (P/E 50 o más, o 10 o menos) | +1 | `pe_extremo` |

Dos penalizaciones, y ambas nacieron de un fallo real:

1. **Descanso por ticker:** 7 días. Dos posts seguidos del mismo nombre se
   leen como relleno aunque cambie el ángulo.
2. **Descanso por motivo:** 3 días, penalización 2.5. Sin esto, 12 de 30
   posts contaban la misma historia ("el bear está pegado al precio")
   porque ese +2 manda en cuanto el mercado se calma. Rotar el ticker no
   basta: hay que rotar la **historia**.

Desempate: hash estable del ticker más un sello del día. Con un `sort`
estable puro, el mismo empatado ganaba siempre.

Al pedir N temas se usa una selección que fuerza **tickers distintos**: si
se pide "n variantes" sin esto, el sistema devuelve N versiones de la misma
empresa, que es lo contrario de la variedad que se buscaba.

---

## 8. Los seis tipos de post propio

| Tipo | Fuente de datos | Qué prohíbe el brief |
|---|---|---|
| `target_range` / `thesis_check` | predicciones guardadas + precio de hoy | citar el score interno; recomendar comprar |
| `macro` | FRED (tipos, curva, CPI, desempleo) | dar precio objetivo; olvidar nombrar la serie |
| `cripto` | FMP (BTC, XRP, ETH, SOL) | **cualquier precio objetivo o "fair value"**; hablar de márgenes o múltiplos |
| `regulacion` | un titular real y fresco de una cuenta vigilada | afirmar nada que el titular no diga; partidismo |
| `marcador` | todas las predicciones vivas | explicar la causa del movimiento |
| `cita` | un post ajeno con conversación | (se pega a mano, no sale por API) |
| `ciencia` | titulares de NASA, Nature, ScienceDaily y Ars Technica, filtrados por relevancia para esta audiencia | afirmar lo que el titular no dice; cifras que no estén en él; catastrofismo |
| `personal` | nada: solo la postura declarada de Angel y una semilla temática que rota. Entre semana, 30 semillas de mercado y vida; sábado y domingo, solo las 9 de familia, fe y descanso | cualquier cifra (la lista de permitidos está vacía), la negatividad, la política y el consejo de inversión |
| `idea` | una nota que Angel manda al bot de Telegram | añadir cualquier cifra, nombre, noticia o fuente que la nota no traiga |
| `sistema` | el historial de git y el registro de gasto del propio agente | hablar de servidores, rutas o proveedores; prometer resultados que la cuenta no tiene |

Reglas transversales que costaron caro:

- **Cripto no tiene modelo de valor.** No hay filings, ni beneficios, ni
  flujo de caja que descontar. El brief prohíbe explícitamente dar un precio
  objetivo. Lo que se publica son hechos de precio observables: nivel,
  caída desde máximos, volatilidad realizada (anualizada con 365, no con
  252: cripto cotiza los siete días).
- **Guarda de serie plana.** El percentil es relativo: con un recorrido
  minúsculo cualquier variación parece un extremo histórico. Si el rango
  completo es menor al 10% del nivel, no hay noticia, hay histórico roto.
- **Regulación sale de fuentes oficiales, como un periodista.** Desde el 21
  de septiembre de 2026 los posts de regulación salen de los comunicados de
  la SEC, la CFTC y el Federal Register (gratis, sin clave). El post atribuye
  el hecho a la agencia con su cuenta de X (@SECGov, @CFTC, @FDICgov,
  @USOCC, @federalreserve, @USTreasury, @IRSnews, @FinCENnews, @TheNCUA,
  todas comprobadas) y con el número del documento ("SEC press release
  2026-90"), para que cualquiera lo encuentre. **Sin enlace:** cuesta 13x y
  X le quita alcance. La @ nunca va como primera palabra: X esconde esos
  posts como si fueran respuestas. Sin comunicado oficial de cripto en las
  últimas 72 horas, el turno no publica; el respaldo con titulares de X
  existe pero va apagado (`REGULACION_RESPALDO_X`).
- **El marcador es el formato más compartible.** Lista de 5 y 5 en una sola
  imagen: las que quedaron por debajo del escenario bajo y las que se
  fueron por encima del alto. Publicar dónde falló el propio modelo es
  raro, verificable y atrae correcciones de gente que sabe.
- **Las ideas de Angel son suyas.** El tipo `idea` es el único contenido que
  no nace de un dato: el material es una nota que él manda al bot en
  cualquier idioma. Las únicas cifras permitidas son las que la nota trae, y
  el post nace `pendiente`, nunca `programado`: su voz la aprueba él.
- **Construir en público solo con hechos propios.** El tipo `sistema` sale de
  `CAMBIOS.txt` (el historial de git que escribe el despliegue, porque el
  servidor no tiene repo) y de `uso_llm.jsonl`. Sin cambios en la semana o
  sin posts publicados, no hay post: una bitácora vacía es relleno.
- **Nunca inventar historial.** En macro, cripto y regulación no hay
  predicciones guardadas, así que "me equivoqué" o "yo dije" serían inventos
  sobre el pasado del usuario. Validar las cifras no valida la afirmación.

---

## 9. Replies

### 9.1 Vigilancia

Una watchlist de cuentas grandes de mercado, cada una con su tema, su ángulo
preferido y un tope diario opcional. Ejemplo real: 8 cuentas de titulares y
datos, una de ellas limitada a 1 reply al día por publicar mucho volumen.

Cada pasada:

1. Lee los posts nuevos de cada cuenta (cache de ids para no repagar).
2. Filtra por frescura: **3 horas**. A las tres horas la conversación ya se
   movió y el reply llega tarde.
3. Empareja cada post con un brief propio, de forma **determinista y previa
   al modelo**, por este orden: empresa (cashtag o nombre) > cripto > macro
   > opinión sin cifras.
4. Solo si hay emparejamiento llama al modelo.
5. Descarta lo ya respondido (incluidos los rechazados: si se rechazó una
   vez, no se vuelve a proponer).

Devolver "no tenemos nada que aportar" es un resultado legítimo y frecuente.
Forzar una respuesta ahí es lo que convierte esto en spam.

### 9.2 Cupos

- **6 replies al día.** El límite no es el dinero, es el tiempo del humano:
  cada reply son tres toques manuales porque X no deja publicarlos por API.
- **1 de esos 6 puede ser de opinión** (sin cifras propias). Medición que lo
  justifica: los replies sin cashtag tienen mediana 22 impresiones frente a
  104 los que llevan datos (n = 8 contra 40, p = 0.003). Sin el sub-tope, la
  opinión se come el cupo entero porque hay muchos más candidatos, y se
  pierde justo lo que diferencia la cuenta.
- El conteo es de lo **propuesto**, no de lo publicado: el costo que se
  quiere limitar es el de mirar cada uno.
- Dos pasadas por ciclo: primero los que llevan datos, después la opinión
  con lo que sobre. En una sola pasada, la opinión llegaba primero y dejaba
  sin cupo a los buenos.

---

## 10. Cola, publicación y ritmo

| Constante | Valor | Por qué |
|---|---|---|
| Ventana de veto | 45 min | tiempo para vetar desde el teléfono antes de que salga |
| Espaciado entre posts | 45 min (90 hasta el 2026-09-21) | con 16 posts al día no cabían más; una tanda seguida se lee como bot |
| Holgura del espaciado | 2 min | sin ella el turno se perdía por segundos y el espaciado real era el doble |
| Ventana horaria | 12:00 a 23:00 UTC | horario activo de la audiencia |
| Rechazos antes de bloquear | 3 | ver sección 16, fallo 15 |

`listos_para_publicar` devuelve los aprobados más los programados cuya
ventana de veto ya pasó, **contando desde que el borrador existe**, no desde
que alguien lo tocó. Un post que nace programado no tiene fecha de decisión.

`proyeccion_de_salida` calcula la hora real de cada post en cola: avanza de
uno en uno cada 90 minutos y solo dentro de la ventana. Sin esto, la
notificación le decía "sale en 45 minutos" a los tres borradores del día, y
era falso para dos de ellos.

**Publicar es la única acción irreversible del sistema.** Por eso corre en
seco por defecto y hay que pedir explícitamente el modo real.

---

## 11. Cola de aprobación por Telegram

- Bot **propio** del proyecto, sin fallback a ningún token genérico de otro
  agente: un fallback silencioso mandaría estos posts al chat equivocado.
- Sin webhook ni proceso permanente: long-polling con offset persistido, así
  corre por cron como todo lo demás.
- Cada borrador llega con tres botones: aprobar, editar, rechazar. Editar
  pide el texto con `force_reply`; la respuesta se guarda como texto editado
  **y aprueba de una vez**.
- Los replies y las citas llegan en bloque preformateado para copiar, con
  los pasos manuales escritos, porque no se pueden publicar por API.
- **Una sola máquina puede hablar con el bot.** Dos instancias con el mismo
  token se roban los updates y cada una busca el borrador en su propia cola.

---

## 12. Gráficos

Cuatro reglas heredadas del motor de análisis, innegociables:

1. **Nunca una sola línea.** Siempre un rango. Una línea sola miente con
   confianza.
2. **Etiquetar los supuestos.** Cada escenario declara su tasa de
   crecimiento y su margen asumidos.
3. **El pasado no se proyecta.** Histórico en línea sólida, futuro proyectado
   en punteada, siempre.
4. **El agente decide, no el gráfico.** El gráfico ilustra el cálculo, nunca
   lo sustituye.

Cada imagen lleva firma con el handle y la fecha, y la fuente del dato.

---

## 13. Fuentes de datos

| Fuente | Qué da | Notas |
|---|---|---|
| FMP | precios, histórico, cripto | usar el endpoint vigente: uno retirado devuelve 403 y, si se traga la excepción, el sistema se queda sin precios en silencio |
| FRED | tipos, curva, CPI, desempleo | el CPI se publica como índice: hay que convertirlo a variación interanual o el post siempre dirá "está en máximos" |
| SEC EDGAR | filings, insider | gratis |
| API de X | posts ajenos, métricas propias | pay-per-use |
| CSV de analytics.x.com | rendimiento real de cada post | gratis, es la base de toda la medición |

---

## 14. Medición (cómo se decide qué funciona)

Sin esto el sistema es superstición con buen estilo.

- Métrica primaria: **tasa de respuestas** por impresión, no likes.
- Comparación no paramétrica: **Mann-Whitney** sobre medianas, no medias. La
  distribución de impresiones tiene cola larga y un post viral mueve
  cualquier media.
- Grupo mínimo: **8 posts** por lado. Por debajo no se declara nada.
- Corrección por comparaciones múltiples: **Benjamini-Hochberg**. Probar 15
  hipótesis a la vez garantiza falsos positivos.
- **Estratificar por tipo de post.** Un hallazgo de "los posts con gráfico
  hacen 84 contra 29" resultó ser el tema (acciones contra cripto), no la
  imagen.
- Comparar **tasas, no totales**, cuando los periodos son distintos. Una
  comparación de una semana contra un trimestre dio un factor de 123x que no
  existía.
- Un hallazgo de la semana 1 que no replica en la semana 2 **no es un
  hallazgo**. Registrar ambas cosas.

---

## 15. Infraestructura

Todo en un VPS pequeño con cron. Horario en UTC (el usuario está en UTC-4).

| Hora UTC | Tarea |
|---|---|
| cada 5 min | cola de Telegram (enviar y procesar toques) |
| 11:30 L-V | redactar 10 posts de empresa del día |
| cada 15 min, 12 a 23 | publicar el siguiente de la cola |
| cada 15 min, 13 a 21 L-V | vigilar cuentas y proponer replies |
| 15:00 y 21:00 diario | post de cripto (otro activo en el segundo turno) |
| 14:00 y 17:00 L-V | post de macro (otra serie en el segundo turno) |
| 17:30 diario | elegir la cita del día |
| 16:00 y 19:00 diario | post de regulación (otro titular) |
| 20:30 viernes | marcador semanal |

**`flock` por tarea, obligatorio.** El intervalo del cron no es un límite de
concurrencia: si una pasada tarda más que el intervalo, la siguiente arranca
encima. Sin el candado, una vigilancia lenta produjo 19 replies con el tope
puesto en 3.

---

## 16. Los fallos que ya ocurrieron (no los repitas)

1. **Tres posts salieron sin cashtag.** La regla existía solo en la
   generación y los borradores viejos ya estaban en cola con el campo vacío.
   *Guarda: toda regla corre otra vez justo antes de publicar.*
2. **`getattr(obj, campo, [])` enmascaró el problema anterior.** Un valor por
   defecto convirtió "este borrador es de antes de la regla" en "este
   borrador está bien". *Guarda: sin defaults silenciosos en validaciones.*
3. **Pedir n variantes daba n versiones de la misma empresa.** *Guarda: la
   n son tickers distintos, no variantes.*
4. **Un `sort` estable hacía ganar siempre al mismo empatado.** *Guarda:
   desempate por hash con sello del día.*
5. **12 de 30 posts contaban la misma historia.** *Guarda: descanso por
   motivo, no solo por ticker.*
6. **Un post de macro salió con "4.04%... 4.95%" sin nombrar el bono a 10
   años.** Sin cashtag, nada exigía decir de qué se hablaba. *Guarda: todo
   brief lleva sujeto obligatorio y se valida.*
7. **El estado "programado" nunca publicó nada durante semanas.** La consulta
   exigía un campo que solo escriben aprobar y rechazar. Todo lo publicado
   había sido manual. *Guarda: probar de extremo a extremo, no por partes.*
8. **El agente se atribuyó predicciones que nunca existieron** ("My miss: I
   called Ether..."). Las cifras eran correctas y la frase era falsa.
   *Guarda: lista de tipos sin historial y detector de auto-atribución.*
9. **19 replies con el tope en 3**, por solapamiento de cron. *Guarda:
   `flock` por tarea y recuento dentro del candado.*
10. **Una palabra ambigua en el detector de temas** ("settlement") metía
    posts de bolsa en la categoría de opinión, y la opinión se comía el
    cupo. *Guarda: claves inequívocas y dos pasadas.*
11. **Replies duplicados al mismo post.** *Guarda: registro de respondidos
    que incluye los rechazados.*
12. **El endpoint de precios retirado devolvía 403 y la excepción se
    tragaba.** Ningún brief llevó "precio hoy" durante días, y esa fue la
    causa raíz de que los posts se repitieran: sin precio no hay tensión que
    puntuar. *Guarda: los 4xx se escriben en la salida de error, siempre.*
13. **Dos posts publicados con la unidad equivocada** ("la curva subió 33%"
    cuando eran 0.33 puntos porcentuales). *Guarda: tres unidades separadas
    y la conversión solo donde toca.*
14. **El CPI se publicaba como nivel del índice**, así que siempre estaba "en
    máximos". Un índice acumulado siempre lo está. *Guarda: variación
    interanual.*
15. **Un post con tres cashtags bloqueó la cola dos días.** X lo rechazaba
    con 403, pero seguía primero en la cola y se reintentaba cada 30 minutos,
    así que nada salía detrás. *Guarda: validar el cashtag único antes de
    publicar y bloquear el item a los 3 rechazos.*
16. **El contador de replies de opinión contaba también los de macro**,
    porque miraba el tipo y no la ausencia de brief. *Guarda: contar por la
    propiedad que define la categoría.*
17. **El detector de frases repetidas marcaba el nombre de la empresa.**
    *Guarda: ignorar el vocabulario del propio sujeto.*
18. **153 precios en vivo por pasada de vigilancia**, uno por brief, cuando
    solo hacían falta los de los tickers mencionados. *Guarda: precios
    perezosos.*

---

## 17. Costo y cómo hacerlo sostenible

El costo real de este diseño, con un modelo de gama alta y razonamiento
activado, son entre 15 y 20 llamadas diarias que pueden sumar de 6 a 9
dólares al día. Es demasiado para una cuenta que todavía no monetiza.

Lo que haría distinto quien implemente esto de cero:

1. **Registrar el consumo de tokens de cada llamada desde el día uno.** Si no
   se registra, se descubre el gasto cuando se acaba el saldo. Guardar
   modelo, tokens de entrada, tokens de salida y tokens cacheados por
   llamada, y publicar un resumen diario.
2. **Un modelo por tarea.** Los replies son de 240 caracteres y el dato ya
   viene hecho del brief: un modelo pequeño los hace igual de bien por una
   fracción del precio. El modelo caro se reserva para los posts propios,
   que son los que ganan impresiones.
3. **Una sola llamada al día para todo lo que se pueda agrupar.** Generar
   los cinco posts de empresa en una sola petición con el mismo bloque de
   sistema cacheado sale mucho más barato que cinco peticiones.
4. **Aprovechar el caché de prompt de verdad.** Dura unos minutos: si las
   tareas corren cada 15 minutos, el caché siempre está frío. Agrupar las
   llamadas en el tiempo vale dinero real.
5. **Usar procesamiento por lotes** donde exista (suele costar la mitad) para
   todo lo que no necesite respuesta inmediata. Los posts del día siguiente
   no la necesitan.
6. **Topes de gasto dentro del código**, por pasada y por día, que corten
   antes de que lo haga la factura.

---

### 17.1 Proveedor actual: xAI (Grok)

Desde el 21 de septiembre de 2026 redacta **Grok 4.7** por la API de xAI
(`POST https://api.x.ai/v1/chat/completions`, salida estructurada con
`response_format` de tipo `json_schema` y `strict: true`). Precio: $2 por
millón de tokens de entrada y $6 de salida, unos 3 centavos por llamada.

`xcreator/llm.py` imita las dos llamadas del SDK de Anthropic que usa el
código (`messages.parse` y `messages.create`), así que cambiar de proveedor
no tocó ni un prompt ni una validación. Dos detalles del adaptador:

- El esquema de pydantic se aplana (sin `$defs`) y se vuelve estricto: todo
  objeto cerrado y todos sus campos obligatorios, aunque en pydantic tengan
  valor por defecto.
- `finish_reason: "length"` se traduce a `stop_reason: "max_tokens"`, que es
  lo que mira el detector de truncamiento.

Cada llamada deja una línea en `Contenido/uso_llm.jsonl` con tokens y costo.
`xc gasto` lo resume por día.

Selección: `LLM_PROVEEDOR` manda si está puesto; si no, xAI cuando existe
`XAI_API_KEY` y Anthropic en caso contrario.

---

## 18. Lo que el sistema no debe hacer nunca

- No publicar sin aprobación humana mientras no haya evidencia de que
  conviene. Criterio pre-declarado para pasar a automático: 80% de
  aprobación sobre al menos 20 borradores decididos.
- No dar consejo de inversión. Se publican clasificaciones de research y
  rangos con supuestos declarados. Nunca "compra" ni "vende".
- No ejecutar operaciones ni mover dinero. El agente no tiene ni debe tener
  credenciales de ejecución, solo claves de lectura de datos de mercado.
- No falsificar citas pegando enlaces para esquivar el límite de la API.
- No automatizar el navegador para saltarse lo que la API no permite.
- No inventar un historial de predicciones.
- No tomar partido político.
- No borrar nada de la cola: los rechazados se conservan, son la materia
  prima de la medición.

---

## 19. Pruebas

El repositorio original tiene 343 pruebas, y la mayoría nacieron de un fallo
de esta lista. Las imprescindibles:

- Cada validador, con un caso que pasa y uno que falla.
- Que una regla nueva se aplique también a un item ya encolado.
- Que el cupo se respete con dos pasadas simultáneas.
- Que un rechazo de la plataforma no bloquee la cola.
- Que las unidades se rendericen y se validen por separado.
- Que un post sin sujeto no pueda publicarse.

Dos trampas al escribir pruebas de este sistema: los identificadores falsos
de posts ("1", "2") se filtran por edad porque el identificador real
codifica la hora, así que hay que usar identificadores realistas; y los
nombres de ayudante genéricos colisionan entre archivos de prueba.
