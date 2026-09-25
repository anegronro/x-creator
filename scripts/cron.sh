#!/bin/bash
# Tareas programadas de x-creator. Una sola entrada por tarea en el crontab,
# para que el log y el manejo de errores vivan aquí y no en la línea del cron.
#
# Uso: cron.sh <telegram|vigilar|redactar|macro|cripto|regulacion|marcador|citar|publicar>
set -uo pipefail

# La raíz se deriva de DÓNDE ESTÁ este script, nunca de $HOME: en la Mac el
# proyecto vive en ~/Proyectos/x-creator y en el VPS en /root/x-creator.
# Hardcodear la ruta de la Mac hizo que el cron del VPS fallara en silencio
# once horas, escribiendo sus errores en un directorio fantasma.
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
XC="$RAIZ/.venv/bin/xc"
LOG="$RAIZ/Contenido/cron.log"

mkdir -p "$(dirname "$LOG")"

# El log crece sin parar si nadie lo mira: se rota al pasar de 2 MB.
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 2000000 ]; then
  mv "$LOG" "$LOG.1"
fi

registrar() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

if [ ! -x "$XC" ]; then
  registrar "FATAL: no existe $XC — ¿se desplegó el proyecto en esta máquina?"
  echo "FATAL: no existe $XC" >&2
  exit 1
fi

# Una sola instancia por tarea. `vigilar` corre cada 15 minutos y llama al
# modelo por cada post relevante; cuando tarda más de 15, el siguiente cron
# arranca ENCIMA del anterior. Los dos leían el cupo diario de replies al
# empezar, cada uno se gastaba el suyo entero, y así salieron 19 replies
# propuestos con el tope puesto en 3. Lo mismo valdría para `publicar`, donde
# dos procesos solapados podrían publicar el mismo item dos veces — y eso no
# se deshace.
#
# `flock -n` hace que el segundo se rinda en vez de acumularse.
TAREA="${1:-sin-tarea}"
CERROJO="$RAIZ/Contenido/.cerrojo-$TAREA"
exec 9>"$CERROJO" || exit 1
if ! flock -n 9; then
  registrar "$TAREA: ya había una corrida en marcha, esta se salta."
  exit 0
fi

case "${1:-}" in
  telegram)
    # Recoge los botones que tocaste y manda los pendientes nuevos.
    # No toca la API de X: es gratis y puede correr seguido.
    salida=$("$XC" telegram ciclo 2>&1); codigo=$?
    # Solo se registra cuando pasa algo: si no, el log es 288 líneas diarias
    # de "sin novedades" y deja de leerse. Pero "Sin novedades" viene de la
    # parte que ESCUCHA botones, y aparecía aunque la parte que ENVÍA hubiera
    # mandado borradores: el evento más importante del día, que los borradores
    # llegaron al teléfono, no se registraba nunca. Angel preguntó por qué no
    # le llegaba nada y el log no tenía la respuesta.
    if echo "$salida" | grep -qi "error\|falta" \
       || echo "$salida" | grep -qiE "enviado|aprobado|rechazado|editado" \
       || ! echo "$salida" | grep -q "Sin novedades."; then
      registrar "telegram: $salida"
    fi
    exit $codigo
    ;;
  vigilar)
    # Lee las cuentas grandes y propone replies. Esto SÍ cuesta (~$0.17).
    # 10 por cuenta, no 5: entre pasadas de 15 min las cuentas de titulares
    # publican de sobra, y con `since_id` solo se paga lo nuevo — leerlo
    # ahora o dentro de tres horas cuesta lo mismo.
    salida=$("$XC" vigilar --limite 10 2>&1); codigo=$?
    registrar "vigilar: $(echo "$salida" | tail -3)"
    exit $codigo
    ;;
  redactar)
    # Diez empresas DISTINTAS al día desde el 2026-09-21 (contenido doble;
    # antes 5, y antes 3). Una por post, cada una con su ángulo.
    # Prueba desde el 2026-09-19 (antes eran 3): se mide si la mediana por
    # post aguanta con más volumen. Corre a las 11:30 UTC para que, con la
    # ventana de veto de 45 min y 90 min entre posts, los 8 del día quepan
    # entre 12:30 y 23:00 UTC.
    # La `n` de --auto son tickers, no variantes: subirla amplía el reparto,
    # no repite la misma empresa.
    salida=$("$XC" redactar --auto --n 10 2>&1); codigo=$?
    registrar "redactar: $(echo "$salida" | tail -6)"
    exit $codigo
    ;;
  macro)
    # Un post de mercado/economía al día. ADICIONAL a los de empresa: amplía
    # el repertorio y llega a gente que sigue macro pero no sigue tickers.
    salida=$("$XC" redactar --macro --n 2 2>&1); codigo=$?
    registrar "macro: $(echo "$salida" | tail -4)"
    exit $codigo
    ;;
  cripto)
    # Un post de activos digitales al día. Cripto cotiza los siete días, así
    # que este es el único que corre tambien en fin de semana: cuando la bolsa
    # está cerrada es lo único que se mueve.
    salida=$("$XC" redactar --cripto --n 2 2>&1); codigo=$?
    registrar "cripto: $(echo "$salida" | tail -4)"
    exit $codigo
    ;;
  regulacion)
    # Un post propio sobre regulación de cripto, anclado a un titular real y
    # reciente. Si no hay titular fresco, calla: mejor que inventar la noticia.
    # Corre también el fin de semana: las entrevistas y declaraciones siguen.
    salida=$("$XC" redactar --regulacion 2>&1); codigo=$?
    registrar "regulacion: $(echo "$salida" | grep -v '^live_price' | tail -4)"
    # Sin comunicado oficial de cripto (la mayoría de los días) el turno no
    # se pierde: Angel pidió el DOBLE de posts, y un hueco fijo lo dejaba en
    # 14 en vez de 16. Entre semana se rellena con otra empresa (el ranking
    # ya excluye las de los últimos 7 días); el fin de semana, con otro
    # activo digital, porque la bolsa está cerrada.
    if echo "$salida" | grep -q "Ningún comunicado oficial"; then
      if [ "$(date -u +%u)" -le 5 ]; then
        relleno=$("$XC" redactar --auto --n 1 2>&1); codigo=$?
      else
        relleno=$("$XC" redactar --cripto --n 2 2>&1); codigo=$?
      fi
      registrar "regulacion (relleno): $(echo "$relleno" | grep -v '^live_price' | tail -4)"
    fi
    exit $codigo
    ;;
  conversar)
    # Respuestas a quien contesta en tus posts. Lee solo las menciones NUEVAS
    # (since_id): X cobra por post devuelto, así que cuesta centavos al mes.
    salida=$("$XC" conversar 2>&1); codigo=$?
    registrar "conversar: $(echo "$salida" | tail -4)"
    exit $codigo
    ;;
  recuperar)
    # Tus replies de más de 500 impresiones, reescritos como post original:
    # los replies no cuentan para el programa de monetización; los posts sí.
    salida=$("$XC" recuperar 2>&1); codigo=$?
    registrar "recuperar: $(echo "$salida" | grep -v '^live_price' | tail -4)"
    exit $codigo
    ;;
  personal)
    # Un post de OPINIÓN de Angel, sin cifras y en positivo. Sale solo, tres
    # veces al día. Es lo que mejor le funciona: sus tres posts con más
    # alcance de septiembre no llevaban un solo número.
    salida=$("$XC" redactar --personal 2>&1); codigo=$?
    registrar "personal: $(echo "$salida" | tail -4)"
    exit $codigo
    ;;
  sistema)
    # Construir en público: una vez por semana, qué cambió en el agente y qué
    # costó. Sale de CAMBIOS.txt (lo escribe el despliegue) y del registro de
    # gasto. Si no hubo cambios, no publica.
    salida=$("$XC" redactar --sistema 2>&1); codigo=$?
    registrar "sistema: $(echo "$salida" | tail -4)"
    exit $codigo
    ;;
  marcador)
    # El marcador semanal: qué acciones se salieron de su rango del modelo.
    # Viernes después del cierre, para que "la semana" sea la semana entera.
    salida=$("$XC" redactar --marcador 2>&1); codigo=$?
    registrar "marcador: $(echo "$salida" | grep -v '^live_price' | tail -4)"
    exit $codigo
    ;;
  citar)
    # Una cita al día del titular con más conversación. Llega a Telegram para
    # pegarla a mano: X no deja publicar citas por API. Corre ANTES que la de
    # regulación para quedarse el titular más vivo; la otra lo excluye.
    salida=$("$XC" citar 2>&1); codigo=$?
    registrar "citar: $(echo "$salida" | grep -v '^live_price' | tail -3)"
    exit $codigo
    ;;
  publicar)
    # Publica lo aprobado, de uno en uno y con hora y media de separación.
    # "Aprobar = publicar" sin espaciado vacía la cola de golpe, y ocho posts
    # seguidos se leen como un bot. El espaciado sale de store.ESPACIADO_MINUTOS:
    # escribirlo aquí lo desincronizaba del aviso de Telegram.
    salida=$("$XC" publicar --no-en-seco --maximo 1 2>&1); codigo=$?
    if ! echo "$salida" | grep -q "Toca esperar\|Nada aprobado"; then
      registrar "publicar: $(echo "$salida" | tail -3)"
    fi
    exit $codigo
    ;;
  *)
    echo "uso: cron.sh <telegram|vigilar|redactar|macro|cripto|regulacion|marcador|citar|publicar>" >&2
    exit 2
    ;;
esac
