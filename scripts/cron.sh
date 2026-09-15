#!/bin/bash
# Tareas programadas de x-creator. Una sola entrada por tarea en el crontab,
# para que el log y el manejo de errores vivan aquí y no en la línea del cron.
#
# Uso: cron.sh <telegram|vigilar|redactar|macro|cripto|publicar>
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
    # Tres empresas DISTINTAS al día, una por post, cada una con su ángulo.
    # La `n` de --auto son tickers, no variantes: subirla amplía el reparto,
    # no repite la misma empresa.
    salida=$("$XC" redactar --auto --n 3 2>&1); codigo=$?
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
  publicar)
    # Publica lo aprobado, de uno en uno y con hora y media de separación.
    # "Aprobar = publicar" sin espaciado vacía la cola de golpe, y ocho posts
    # seguidos se leen como un bot.
    salida=$("$XC" publicar --no-en-seco --maximo 1 --espaciado 90 2>&1); codigo=$?
    if ! echo "$salida" | grep -q "Toca esperar\|Nada aprobado"; then
      registrar "publicar: $(echo "$salida" | tail -3)"
    fi
    exit $codigo
    ;;
  *)
    echo "uso: cron.sh <telegram|vigilar|redactar|macro|cripto|publicar>" >&2
    exit 2
    ;;
esac
