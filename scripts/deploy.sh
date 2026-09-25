#!/bin/bash
# Despliega x-creator en el VPS. Idempotente: se puede correr cuantas veces
# haga falta.
#
# Lo que NO se sube y por qué:
#   API/        secretos — van por separado, con permisos 600
#   Contenido/  estado vivo del agente (cola, tokens, qué se leyó ya).
#               Sobrescribirlo desde la Mac borraría las aprobaciones hechas
#               desde el teléfono y haría releer —y repagar— posts ya vistos.
set -euo pipefail

VPS="${VPS:-root@100.105.244.125}"
RAIZ="$(cd "$(dirname "$0")/.." && pwd)"

# El VPS no tiene repo (se copia el código, no el .git), así que el historial
# viaja como archivo: es la materia prima del post semanal de bitácora.
echo "-> historial de cambios para la bitácora"
git -C "$RAIZ" log -60 --pretty=format:'%h|%ad|%s' --date=short > "$RAIZ/CAMBIOS.txt"

echo "-> subiendo código a $VPS"
rsync -az --delete \
  --exclude '.venv' --exclude '__pycache__' --exclude '.pytest_cache' \
  --exclude 'API' --exclude 'Contenido' --exclude '.git' \
  "$RAIZ/" "$VPS:~/x-creator/"

echo "-> dependencias"
ssh "$VPS" 'cd ~/x-creator && (test -d .venv || python3 -m venv .venv) && ./.venv/bin/pip install -q -e "." && chmod +x scripts/cron.sh'

echo "-> el motor de acciones (de ahí salen los briefs y el Cerebro)"
rsync -az --exclude '__pycache__' "$HOME/Proyectos/warren-buffett-jr/engine/wbj/" \
  "$VPS:~/gatsby/engine/wbj/"

echo "-> comprobación"
ssh "$VPS" 'cd ~/x-creator && ./.venv/bin/python -c "
from xcreator.cerebro import disponible
from xcreator.config import load_settings
from xcreator.datos import load_company_names, load_predictions
s = load_settings()
falta = [n for n, v in (
    (\"TELEGRAM_X_BOT_TOKEN\", s.telegram_bot_token),
    (\"X_BEARER_TOKEN\", s.x_bearer_token),
    (\"X_CLIENT_ID\", s.x_client_id)) if not v]
print(\"credenciales:\", \"todas\" if not falta else f\"FALTAN {falta}\")
print(\"Cerebro:\", \"sí\" if disponible(s.cerebro_dir) else \"NO\")
print(\"predicciones:\", len(load_predictions(s.reportes_dir)))
print(\"nombres de empresa:\", len(load_company_names(s.reportes_dir)))
"'
echo "listo"
