#!/bin/zsh
# ml_auto.sh — Ganga Hunter: scrapea MercadoLibre local, pushea ml_listings.json
# y dispara el scraper de GitHub. Lo corre launchd una vez por día.
#
# Opera sobre un clone DEDICADO (~/.ganga-auto/repo) para no interferir con tu
# clone de trabajo (~/ganga-scraper).
#
# Instalación: ver SETUP_ML_AUTO.md
set -u

AUTO_DIR="$HOME/.ganga-auto"
REPO_DIR="$AUTO_DIR/repo"
PY="/usr/bin/python3"
GH="/opt/homebrew/bin/gh"
REMOTE="https://github.com/btosto90-cloud/ganga-scraper.git"
BRANCH="main"
LOG="$AUTO_DIR/ml_auto.log"

mkdir -p "$AUTO_DIR"
# Rotar log si supera ~2MB
[ -f "$LOG" ] && [ "$(wc -c < "$LOG" 2>/dev/null || echo 0)" -gt 2000000 ] && mv "$LOG" "$LOG.old"
exec >> "$LOG" 2>&1
echo ""
echo "========== $(date '+%Y-%m-%d %H:%M:%S') — ML auto run =========="

# PATH mínimo para que git/gh estén disponibles bajo launchd
export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

# 1. Clone dedicado (primera vez) o sincronizar a lo último de main
if [ ! -d "$REPO_DIR/.git" ]; then
    echo "Primera vez: clonando repo en $REPO_DIR"
    git clone "$REMOTE" "$REPO_DIR" || { echo "ERROR: clone falló"; exit 1; }
fi
cd "$REPO_DIR" || { echo "ERROR: no pude cd a $REPO_DIR"; exit 1; }
git fetch origin "$BRANCH" 2>&1 || echo "WARN: fetch falló, sigo con lo que haya"
git reset --hard "origin/$BRANCH" 2>&1 || echo "WARN: reset falló, sigo con lo que haya"

# 2. Elegir el ml_local.py: el del repo (si ya está mergeado) o la copia en $AUTO_DIR.
# OJO: NO usar ~/Downloads — launchd no puede leer carpetas protegidas por TCC
# (Downloads/Desktop/Documents) → "Operation not permitted".
ML_SCRIPT="ml_local.py"
if [ ! -f "$ML_SCRIPT" ]; then
    ML_SCRIPT="$AUTO_DIR/ml_local.py"
    echo "Nota: ml_local.py no está en el repo todavía, uso $ML_SCRIPT"
fi
if [ ! -f "$ML_SCRIPT" ]; then
    echo "ERROR: no encuentro ml_local.py (ni en el repo ni en $AUTO_DIR)"; exit 1
fi

# 3. Scrapear ML (genera ./ml_listings.json en el clone, con history del repo)
echo "Corriendo ml_local.py (esto tarda ~30-50 min)..."
"$PY" "$ML_SCRIPT" < /dev/null || { echo "ERROR: ml_local.py falló"; exit 1; }

# 4. Commit + push si ml_listings.json cambió (con retry por si origin avanzó)
if git diff --quiet ml_listings.json 2>/dev/null; then
    echo "Sin cambios en ml_listings.json — no commiteo"
else
    git add ml_listings.json
    TOTAL=$("$PY" -c "import json;print(json.load(open('ml_listings.json')).get('total','?'))" 2>/dev/null || echo "?")
    git -c user.name="ganga-ml-bot" -c user.email="ml-bot@users.noreply.github.com" \
        commit -m "chore(ml): refresh $(date -u +%Y-%m-%d) - ${TOTAL} autos ML"
    if ! git push origin "HEAD:$BRANCH" 2>&1; then
        echo "Push rechazado, reintento tras rebase..."
        git fetch origin "$BRANCH" && git rebase "origin/$BRANCH" && git push origin "HEAD:$BRANCH" \
            && echo "✓ pusheado tras rebase ($TOTAL autos)" || echo "ERROR: push falló tras rebase"
    else
        echo "✓ ml_listings.json pusheado ($TOTAL autos)"
    fi
fi

# 5. Disparar el scraper de GitHub para regenerar listings.json con ML fresco
if [ -x "$GH" ]; then
    "$GH" workflow run scraper.yml --repo btosto90-cloud/ganga-scraper 2>&1 \
        && echo "✓ scraper disparado" || echo "WARN: no pude disparar el scraper (correrá en su cron)"
else
    echo "WARN: gh no disponible en $GH — el scraper correrá en su cron"
fi

echo "========== fin $(date '+%H:%M:%S') =========="
