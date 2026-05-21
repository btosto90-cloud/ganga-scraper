# Automatización de MercadoLibre (launchd)

MercadoLibre bloquea las IPs de datacenter de GitHub Actions, así que su scraper
(`ml_local.py`, Playwright) corre **local en la Mac**. Antes había que acordarse de
correrlo a mano y subir `ml_listings.json` (el 81% de la data). Esto lo automatiza.

## Qué hace

Todos los días a las **10:00 ART**, un job de launchd corre `ml_auto.sh`, que:
1. Sincroniza un clone dedicado (`~/.ganga-auto/repo`) con `main`.
2. Corre `ml_local.py` (scrapea ML, ~30-50 min, headless).
3. Commitea y pushea `ml_listings.json`.
4. Dispara el scraper de GitHub (`gh workflow run scraper.yml`) para regenerar
   `listings.json` con la data fresca.

Usa un clone aparte para no tocar tu clone de trabajo (`~/ganga-scraper`).

## Requisitos (ya instalados)

- `/usr/bin/python3` con `playwright` (`pip3 install --break-system-packages playwright`)
- Chromium de Playwright (`python3 -m playwright install chromium`)
- `gh` autenticado (`gh auth status`)
- git con credenciales en el keychain (push sin prompt)

## Instalación (una vez)

```bash
mkdir -p ~/.ganga-auto
cp ~/ganga-scraper/ml_auto.sh ~/.ganga-auto/ml_auto.sh
chmod +x ~/.ganga-auto/ml_auto.sh
cp ~/ganga-scraper/launchd/com.brunotosto.gangahunter-ml.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.brunotosto.gangahunter-ml.plist
```

## Operación

```bash
# Ver que está cargado
launchctl list | grep gangahunter

# Correr AHORA mismo (sin esperar a las 10:00) — útil para probar
launchctl start com.brunotosto.gangahunter-ml

# Ver el log
tail -f ~/.ganga-auto/ml_auto.log

# Cambiar el horario: editá Hour/Minute en el plist y recargá:
launchctl unload ~/Library/LaunchAgents/com.brunotosto.gangahunter-ml.plist
launchctl load   ~/Library/LaunchAgents/com.brunotosto.gangahunter-ml.plist

# Desactivar
launchctl unload ~/Library/LaunchAgents/com.brunotosto.gangahunter-ml.plist
```

## Notas

- Si la Mac está dormida a las 10:00, el job corre al despertar (StartCalendarInterval).
- Si la Mac está apagada todo el día, ese día no corre; al día siguiente sí.
- El scraper de GitHub sigue teniendo su cron diario (8 UTC) como red de seguridad
  para RG/AC aunque ML no se haya refrescado.
- El wrapper "vivo" es `~/.ganga-auto/ml_auto.sh`. Si lo mejorás en el repo, recopiá:
  `cp ~/ganga-scraper/ml_auto.sh ~/.ganga-auto/ml_auto.sh`
