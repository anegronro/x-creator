#!/bin/bash
# Tareas programadas de x-creator. Una sola entrada por tarea en el crontab,
# para que el log y el manejo de errores vivan aquí y no en la línea del cron.
#
# Uso: cron.sh <telegram|vigilar|redactar|macro|publicar>
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

case "${1:-}" in
  telegram)
    # Recoge los botones que tocaste y manda los pendientes nuevos.
    # No toca la API de X: es gratis y puede correr seguido.
    salida=$("$XC" telegram ciclo 2>&1); codigo=$?
    # Solo se registra cuando pasa algo: si no, el log es 288 líneas diarias
    # de "sin novedades" y deja de leerse.
    if ! echo "$salida" | grep -q "Sin novedades." || echo "$salida" | grep -qi "error\|falta"; then
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
    # Un post propio al día, sobre el tema con más tensión.
    salida=$("$XC" redactar --auto --n 2 2>&1); codigo=$?
    registrar "redactar: $(echo "$salida" | tail -4)"
    exit $codigo
    ;;
  macro)
    # Un post de mercado/economía al día. ADICIONAL a los de empresa: amplía
    # el repertorio y llega a gente que sigue macro pero no sigue tickers.
    salida=$("$XC" redactar --macro --n 2 2>&1); codigo=$?
    registrar "macro: $(echo "$salida" | tail -4)"
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
    echo "uso: cron.sh <telegram|vigilar|redactar|macro|publicar>" >&2
    exit 2
    ;;
esac
