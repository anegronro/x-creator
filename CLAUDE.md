# X Creator — agente de contenido para la cuenta de X de Angel

Proyecto **independiente**. No es el agente de acciones, ni el de forex, ni
el de opciones. Aquí no se analiza para invertir: se produce contenido para
una cuenta de X que busca monetizar vía el programa de Creator Studio.

## Regla innegociable (heredada del Cerebro)

> Sin evidencia, no hay número. Sin fuente, no hay cifra.

Una cifra solo entra en un post si viene de un `Fact` con fuente declarada.
`generate.validate_numbers` lo verifica en código, sin modelo, después de
cada generación. Un patrón de engagement solo se declara con su n, su tamaño
de efecto y su p-value corregido por comparaciones múltiples.

## Lo que este agente NO hace

- **No publica sin aprobación de Angel.** Todo borrador pasa por la cola.
  El criterio pre-declarado para pasar a automático es ≥80% de aprobación
  sobre ≥20 borradores decididos (`Queue.tasa_aprobacion`).
- **No da consejo de inversión.** Publica clasificaciones de research y
  rangos con supuestos declarados. Nunca "compra" ni "vende".
- **No ejecuta nada.** No tiene ni debe tener credenciales de ejecución
  (TradeLocker, Alpaca). Solo claves de lectura de datos de mercado.
- **No usa el bot de Telegram de otro agente.** `TELEGRAM_X_BOT_TOKEN` no
  tiene fallback: si falta, se falla ruidosamente.
- **No importa código de otros proyectos.** Lee sus archivos por ruta.

## Cómo se relaciona con warren-buffett-jr

Solo por dos rutas de `API/.env`, ambas de **solo lectura**:

- `WBJ_REPORTES_DIR` → los `prediccion.json` que ese motor escribe. Son la
  materia prima de los briefs.
- `WBJ_CEREBRO_DIR` → la metodología (83 documentos). De ahí salen los seis
  ángulos de contenido: negocio, finanzas, mercado, técnico, riesgo,
  valuación. Se carga solo la dimensión del ángulo, con prompt caching.

Si ese proyecto desaparece, aquí se pierde una fuente, no el sistema.

## Especificación completa

`SPEC.md` es el documento autocontenido del sistema: restricciones de la
plataforma, modelo de datos, prompts literales, validaciones, cupos, cron,
método de medición y los 18 fallos ya ocurridos con su guarda. Está escrito
para que otro modelo pueda reimplementar el agente sin leer el código. Si
cambias una regla de contenido o un cupo, actualízalo ahí también.

## Arquitectura

| Módulo | Qué hace |
|---|---|
| `analytics.py` | Lee el CSV de analytics.x.com y mide qué funciona. Sin API, costo cero. |
| `datos.py` | Fuentes de datos. Hoy: predicciones por ruta y precios de FMP. |
| `cerebro.py` | Carga selectiva de la metodología por ángulo. |
| `brief.py` | Precomputa las cifras permitidas, con fuente. |
| `generate.py` | Claude redacta; el validador numérico verifica. |
| `store.py` | Cola append-only. Nada se borra. |
| `telegram.py` | Cola de aprobación con botones. Bot propio. |
| `personal.py` | Opinión sin cifras, en positivo y automática. 12 semillas que rotan. |
| `idea.py` | Tus notas de Telegram convertidas en posts con tu voz. |
| `bitacora.py` | Construir en público: qué cambió y qué costó esta semana. |

## Qué hace bueno a un post (y por qué)

El Ads Revenue Sharing paga por los anuncios en la **sección de replies**.
Un post que informa y se acaba no monetiza; uno que abre discusión, sí. Por
eso la métrica primaria de todo el sistema es `reply_rate`, no likes, y por
eso el redactor busca una postura discutible con datos duros detrás.

Publicar los errores del modelo funciona mejor que publicar los aciertos: es
raro, es verificable, y atrae correcciones de gente que sabe.

## Economía

- API de X: pay-per-use desde feb 2026, sin free tier. $0.015 por post,
  **$0.20 si lleva link** (13x). Por eso el redactor tiene prohibido incluir
  URLs — y además los links hunden el alcance orgánico.
- Modelo que redacta: **Grok 4.7 por la API de xAI** desde el 2026-09-21
  (los créditos de Anthropic se acabaron y no se recargan). Unos 3 centavos
  por llamada. `xc gasto` muestra lo gastado; `llm.py` es el adaptador.
- Monetización: Premium activo + 500 seguidores **verificados** + 5M
  impresiones orgánicas en 3 meses, solo de usuarios Premium.

## Comandos

```bash
xc analizar <csv>                    # qué funciona en la cuenta
xc angulos                           # los 6 ángulos del Cerebro
xc redactar --ticker NVDA --angulo riesgo
xc cola | aprobar <id> | rechazar <id>
xc telegram setup | enviar | escuchar | ciclo
```
