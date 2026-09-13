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

## Lo que falta

- Publicador contra la API de X (créditos + OAuth).
- Cosecha del engagement real por post publicado, para cerrar el bucle
  predicción → resultado.
- Fuentes más allá de acciones: FRED (macro), OANDA (divisas), FinnHub
  (noticias) — las claves ya están, faltan los briefs.
