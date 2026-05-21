#!/bin/zsh
# ml_radar.sh — Radar de gangas frescas. Lo corre launchd cada ~2h en horario diurno.
# Escanea los avisos nuevos de ML y alerta al instante por Telegram las super-gangas
# confirmadas. Liviano (~5 min). Usa el clone de ~/.ganga-auto/repo (lo refresca ml_auto.sh).
set -u

AUTO_DIR="$HOME/.ganga-auto"
REPO_DIR="$AUTO_DIR/repo"
PY="/usr/bin/python3"
LOG="$AUTO_DIR/ml_radar.log"

mkdir -p "$AUTO_DIR"
[ -f "$LOG" ] && [ "$(wc -c < "$LOG" 2>/dev/null || echo 0)" -gt 1000000 ] && mv "$LOG" "$LOG.old"
exec >> "$LOG" 2>&1
echo ""
echo "===== $(date '+%Y-%m-%d %H:%M:%S') — radar ====="

export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

# Credenciales de Telegram (mismas que GitHub secrets)
if [ -f "$AUTO_DIR/telegram.env" ]; then
    set -a; . "$AUTO_DIR/telegram.env"; set +a
fi

if [ ! -d "$REPO_DIR/.git" ]; then
    echo "No existe el clone en $REPO_DIR — corré ml_auto.sh primero (o esperá al run de las 10:00)"
    exit 1
fi
cd "$REPO_DIR" || exit 1

# ml_radar.py del repo si ya está mergeado; si no, el de $AUTO_DIR (fallback)
RADAR="ml_radar.py"
if [ ! -f "$RADAR" ]; then
    RADAR="$AUTO_DIR/ml_radar.py"
    echo "Nota: ml_radar.py no está en el repo todavía, uso $RADAR"
fi
if [ ! -f "$RADAR" ]; then
    echo "ERROR: no encuentro ml_radar.py"; exit 1
fi

"$PY" "$RADAR" < /dev/null
echo "===== fin $(date '+%H:%M:%S') ====="
