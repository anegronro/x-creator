# X Creator

Agente de contenido para X. Analiza el engagement real de la cuenta, redacta
sobre datos duros con la metodología de un analista, y deja los borradores en
una cola de aprobación. **No publica nada por su cuenta.**

## Instalación

```bash
cd ~/Proyectos/x-creator
uv venv --python 3.12 && uv pip install --python .venv -e ".[dev]"
cp API/.env.example API/.env   # y rellena las claves
```

## Uso

```bash
# 1. Qué funciona en TU cuenta (analytics.x.com -> Posts -> Export)
./.venv/bin/xc analizar ~/Downloads/posts.csv

# 2. Ver los ángulos que da el Cerebro
./.venv/bin/xc angulos

# 3. Redactar (el ángulo cambia por completo de qué habla el post)
./.venv/bin/xc redactar --ticker NVDA --angulo riesgo

# 4. Revisar
./.venv/bin/xc cola
./.venv/bin/xc telegram enviar     # o al teléfono, con botones
```

## Los seis ángulos

El mismo ticker da seis contenidos distintos, no seis versiones del mismo:

| Ángulo | La pregunta que hace |
|---|---|
| `negocio` | ¿Es un negocio durable, antes de mirar el precio? |
| `finanzas` | ¿Los márgenes y el flujo de caja sostienen lo que promete la acción? |
| `mercado` | ¿El mercado que persigue es tan grande como dice el consenso? |
| `tecnico` | ¿Dónde están los niveles que invalidarían la tesis? |
| `riesgo` | ¿Qué tendría que pasar para que esto se rompa de verdad? |
| `valuacion` | ¿Qué crecimiento hay que creerse para justificar el precio? |

Cada uno carga la metodología de esa dimensión del Cerebro — en particular
sus *Boundaries*, que son las afirmaciones que un analista serio no hace.

## Por qué no miente

- **Números**: el brief precomputa todas las cifras permitidas, derivados
  incluidos. `validate_numbers` es determinista, corre sin modelo y marca
  cualquier cifra que no salga de ahí. Un número inventado no llega a la cola.
- **Patrones**: nada se declara sin n mínimo (8 por grupo), efecto sobre la
  **mediana** (las distribuciones de engagement son long-tail) y p-value por
  Mann-Whitney U.
- **Comparaciones múltiples**: se prueban ~8 features a la vez, así que un
  p<0.05 aislado es un falso positivo esperado. Se aplica Benjamini-Hochberg.
  No es teórico: en pruebas, una feature de ruido puro dio p=0.041 y sin la
  corrección habría entrado como regla de estilo del generador.
- **Truncamiento**: en Opus 5 el thinking cuenta contra `max_tokens`; con el
  techo bajo, una variante salía cortada a media frase y pasaba como válida.
  Se detecta por `stop_reason` y por puntuación final.
- **Nada se borra**: los rechazos quedan. La tasa de aprobación es el
  criterio para pasar de revisión manual a auto-publicación (≥80% con n≥20).

## Límite de caracteres: hilo o recorte

El límite de 280 se hace cumplir en código, nunca pidiéndoselo al prompt —
un modelo no cuenta caracteres de forma fiable.

- Exceso > 40 caracteres → hilo por frases completas (el corte ignora
  decimales: `45.10` no es fin de frase).
- Exceso ≤ 40 → se pide una versión más corta conservando todas las cifras.
- Si el recorte tampoco cabe, se conserva el original y se marca `REVISAR`.

## Telegram

Bot **propio**. Sin fallback a ningún token genérico: mandaría estos posts al
chat de otro agente.

```bash
# @BotFather -> /newbot -> pega el token en API/.env como TELEGRAM_X_BOT_TOKEN
./.venv/bin/xc telegram setup      # verifica y descubre tu chat_id
```

Long-polling con offset persistido, sin webhook, para que corra por cron:

```cron
*/3 * * * * cd ~/Proyectos/x-creator && ./.venv/bin/xc telegram ciclo >> /tmp/xc-tg.log 2>&1
```

## Asistente de replies

Donde de verdad crece una cuenta chica. En FinTwit te descubren en las
respuestas a cuentas grandes, no en tus propios posts.

```bash
xc responder --autor "@unusual_whales" --texto "\$NVDA is the most crowded trade"
```

**La regla que lo mantiene honesto: sabe abstenerse.** Si no hay un dato duro
que aporte al post, no se genera respuesta. El emparejamiento (ticker
mencionado ↔ brief que tenemos) es determinista y ocurre ANTES de llamar al
modelo, así que declinar no cuesta ni un token. Y el modelo puede declinar
también, aunque el ticker coincida: mencionar `$NVDA` no significa que
nuestras cifras aporten a ESE post.

Un asistente que siempre encuentra algo que decir es una máquina de spam, y
es exactamente lo que X penaliza.

## Qué publicar hoy

```bash
xc temas --detalle
```

Tener muchos briefs no es tener muchos temas. Un ticker con score medio,
múltiplo normal y precio dentro del rango no da un post: sin tensión no hay
conversación, y sin conversación no hay monetización. `xc temas` puntúa la
tensión editorial de cada brief con reglas explícitas —cada punto trae su
motivo escrito, para que el ranking se pueda discutir— y ordena.

La jerarquía sale de qué genera respuestas, no de qué es buena inversión: un
modelo que se equivocó da mejor contenido que uno que acertó.

## Vigilar cuentas grandes

```bash
xc watchlist                 # las cuentas que vigilamos
xc watchlist --add @cuenta
xc vigilar                   # lee, filtra y propone replies
```

El filtro determinista corre **antes** del modelo: de decenas de posts
leídos, solo los que mencionan un ticker que cubrimos generan texto. Por eso
vigilar sale barato y responder sale caro, que es el orden correcto.

Costos reales de la API de X ($0.005 por post leído, $0.010 por usuario):

| Pasadas/día | 5 posts × 7 cuentas |
|---|---|
| 2 | ~$10/mes |
| 4 | ~$21/mes |

Dos cosas abaratan esto de verdad: los user_id se cachean en disco (un handle
nunca cambia de id) y `since_id` evita releer lo ya visto — una pasada sin
posts nuevos no cuesta nada, porque solo se cobra lo devuelto. Hay además un
tope por pasada (`X_PRESUPUESTO_PASADA`) para que un bucle con un bug no
vacíe los créditos.

## Publicar

```bash
xc x-auth                      # una vez: autorizas la app en TU navegador
xc publicar                    # EN SECO por defecto: enseña qué saldría
xc publicar --no-en-seco       # publica de verdad
```

Publicar es la única acción irreversible del sistema, así que el modo en seco
es el que manda por defecto y hay que pedir lo contrario explícitamente.
Cuatro guardas antes de cada envío:

- **Solo se publica lo aprobado.** El estado se comprueba en el publicador,
  no en el CLI.
- **Se revalida el texto FINAL**, no el original: entre aprobar y publicar
  pudo editarse, y manda lo editado. Se vuelven a comprobar cifras sin
  fuente, largo e idioma.
- **Los links se bloquean** salvo `--permitir-link`: cuestan $0.20 en vez de
  $0.015 y hunden el alcance.
- **Idempotencia**: lo publicado deja de estar aprobado, así que correr el
  comando dos veces no duplica nada.

Los hilos se encadenan solos, y un reply cuelga del post original.

Las credenciales son dos y distintas: el **bearer token** (app-only) solo
lee; publicar necesita **OAuth 2.0 de usuario**, que autorizas tú en tu
navegador. Aquí nunca se ve ni se pide una contraseña.

## Automatización (cron)

```bash
scripts/cron.sh telegram    # cada 5 min — recoge botones, manda pendientes
scripts/cron.sh vigilar     # 9:00, 13:00, 16:00 L-V — lee cuentas, propone replies
scripts/cron.sh redactar    # 8:30 L-V — un post propio sobre el tema con más tensión
```

**Publicar NO está en el cron, a propósito.** Es la única acción irreversible
y sigue necesitando `xc publicar --no-en-seco` a mano. Aprobar en Telegram
deja el borrador listo; publicarlo es una decisión aparte.

Costo del cron: ~$11/mes de la API de X (tres pasadas diarias de `vigilar`)
más unos centavos de Anthropic. `telegram` es gratis. Para abaratar, bajar a
dos pasadas o quitar de la watchlist las cuentas de macro, que casi nunca
mencionan tickers que cubrimos.

El log vive en `Contenido/cron.log` y solo registra cuando pasa algo: un log
que dice "sin novedades" 288 veces al día deja de leerse.

### En el VPS (24/7)

El cron vive en el VPS, no en la Mac: un portátil suspendido no ejecuta nada.

```bash
scripts/deploy.sh          # sube código y motor, instala dependencias, verifica
```

El despliegue **no sube `Contenido/`** a propósito: ahí está el estado vivo
del agente (la cola, los tokens de OAuth, qué posts ya se leyeron).
Sobrescribirlo desde la Mac borraría las aprobaciones hechas desde el
teléfono y obligaría a releer —y repagar— posts ya vistos.

El VPS corre en **UTC** y Angel en **AST (UTC−4)**: las horas del crontab
están en UTC con la hora local anotada al lado. Un despliegue que ignora esto
funciona, pero publica a deshora y nadie entiende por qué.

Hay además un cron diario de `wbj analyze-batch` en el VPS. Sin él, los
briefs se quedan congelados en el día del despliegue y el contenido empieza a
repetirse: `Reportes/` está en el `.gitignore`, así que el autosync de git
nunca los lleva.

## Lo que falta

- Publicador contra la API de X (créditos + OAuth).
- Cosecha del engagement real por post publicado, para cerrar el bucle
  predicción → resultado.
- Fuentes más allá de acciones: FRED (macro), OANDA (divisas), FinnHub
  (noticias) — las claves ya están, faltan los briefs.
