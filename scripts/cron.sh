#!/bin/bash
# Tareas programadas de x-creator. Una sola entrada por tarea en el crontab,
# para que el log y el manejo de errores vivan aquí y no en la línea del cron.
#
# Uso: cron.sh <telegram|vigilar|redactar>
set -uo pipefail

RAIZ="$HOME/Proyectos/x-creator"
XC="$RAIZ/.venv/bin/xc"
LOG="$RAIZ/Contenido/cron.log"

mkdir -p "$(dirname "$LOG")"

# El log crece sin parar si nadie lo mira: se rota al pasar de 2 MB.
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 2000000 ]; then
  mv "$LOG" "$LOG.1"
fi

registrar() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

case "${1:-}" in
  telegram)
    # Recoge los botones que tocaste y manda los pendientes nuevos.
    # No toca la API de X: es gratis y puede correr seguido.
    salida=$("$XC" telegram ciclo 2>&1)
    # Solo se registra cuando pasa algo: si no, el log es 288 líneas diarias
    # de "sin novedades" y deja de leerse.
    if ! echo "$salida" | grep -q "Sin novedades." || echo "$salida" | grep -qi "error\|falta"; then
      registrar "telegram: $salida"
    fi
    ;;
  vigilar)
    # Lee las cuentas grandes y propone replies. Esto SÍ cuesta (~$0.17).
    registrar "vigilar: $("$XC" vigilar --limite 5 2>&1 | tail -3)"
    ;;
  redactar)
    # Un post propio al día, sobre el tema con más tensión.
    registrar "redactar: $("$XC" redactar --auto --n 2 2>&1 | tail -4)"
    ;;
  *)
    echo "uso: cron.sh <telegram|vigilar|redactar>" >&2
    exit 2
    ;;
esac
