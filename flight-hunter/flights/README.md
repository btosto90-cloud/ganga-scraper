# Flight Hunter ✈️

Radar de gangas aéreas para Argentina. Adaptación de la filosofía de Ganga Hunter Autos al mercado de vuelos.

**Filosofía**: una oferta es ganga si el precio está significativamente debajo del histórico de la ruta, considerando además calidad del itinerario (escalas, equipaje, aerolínea, duración). Detecta posibles tarifas error y alertas tempranas (precio agresivo recién detectado).

## Arquitectura

```
flights/
├── run.py                         # entry point — corre el pipeline completo
├── requirements.txt               # deps Python (requests, beautifulsoup4, lxml)
├── scrapers/
│   ├── base.py                    # Source ABC (extensible para nuevas fuentes)
│   └── promociones_aereas.py      # scraper con cascada de 4 estrategias
├── scoring/
│   ├── normalize.py               # parser título+slug → schema unificado
│   ├── route_baseline.py          # tabla hardcodeada de precios típicos por ruta
│   ├── learning.py                # auto-aprendizaje (90 días rolling, override 15+ samples)
│   └── score.py                   # Deal Score, Quality Score, Error Fare detection
├── public/                        # ← lo que despliega Netlify
│   ├── index.html                 # frontend dashboard
│   └── data/
│       └── flights.json           # output diario del pipeline (autogenerado)
└── data/
    └── price_history.json         # histórico para auto-aprendizaje (autogenerado)
```

## Cómo correr local

```bash
cd flights
pip install -r requirements.txt
python run.py
```

Eso genera `public/data/flights.json` (output) y `data/price_history.json` (acumula).
Para ver el frontend:

```bash
python -m http.server 8000 -d public
# abrir http://localhost:8000/
```

## Deploy (en la repo `ganga-hunter`)

1. Mover este folder a `ganga-hunter/flights/`
2. Mover `.github/workflows/flight-hunter-daily.yml` a `ganga-hunter/.github/workflows/`
3. Push al repo
4. En Netlify, crear un nuevo site (o un branch deploy) que sirva `flights/public/` como publish dir
5. Activar GitHub Actions en la repo (debería estar activo por default)
6. Primer run: ir a la tab Actions y disparar `Flight Hunter — Daily` con "Run workflow"

El workflow corre todos los días a las 11:00 UTC (08:00 ART), commitea los archivos actualizados, y Netlify auto-deploya cuando ve el push.

## Cuando el scraper falla

El scraper tiene **4 estrategias en cascada** para resistir bloqueos de IP:

1. **WordPress REST API** (`/wp-json/wp/v2/posts`) — más limpia
2. **RSS feed** (`/feed/`) — casi siempre accesible
3. **HTML scraping** del home — fallback estándar
4. **Proxy r.jina.ai** — último recurso, cuando datacenter IPs están bloqueados

Si las 4 fallan en GitHub Actions:

- Mirá los logs del run en la tab Actions
- Probá disparar manualmente — a veces es transitorio
- Si es persistente, **opción nuclear**: correr el scraper en tu Mac con `cron`/`launchd` y commitear el resultado. Tu IP residencial argentina seguro funciona.

```bash
# crontab -e (en tu Mac, runs daily at 8AM)
0 8 * * * cd ~/code/ganga-hunter/flights && /usr/bin/python3 run.py && git add public/data data && git commit -m "daily refresh" && git push
```

## Filosofía del scoring

Cada vuelo tiene dos scores 0-100:

- **dealScore**: la "ganga total" — pondera descuento histórico, descuento vs market actual, calidad, rareza, condiciones, confianza. Cambia con el modo (Viaje personal / Máximo ahorro / Error fare hunter / Ejecutivo / Escapadas / Flexible total).
- **qualScore**: solo calidad del itinerario — escalas, equipaje, duración, aerolínea, taxes incluidos.

**Regla de oro**: en modos no agresivos, `qualScore < 25` ⇒ `dealScore` capeado a 55, `qualScore < 40` ⇒ capeado a 70. Esto evita que un vuelo con 3 escalas suba al podio solo por ser barato.

Categorías por dealScore:

- ≥90 🔥 GANGA EXTRAORDINARIA
- ≥80 ⚡ EMITIR URGENTE
- ≥70 ⭐ MUY BUENA OPORTUNIDAD
- ≥60 ✓ BUEN PRECIO
- ≥50 👁 MIRAR PERO NO CORRER
- <50 NO PRIORIZAR

## Cómo iterar

**Si una ruta tiene scores raros**, edita `scoring/route_baseline.py` y ajustá `historical_avg`, `historical_min`, `expected_low`, `exceptional_threshold`. El sistema empieza con esos valores y los va auto-corrigiendo.

**Si una ruta acumuló 15+ samples**, el módulo `learning.py` calcula su baseline empírica (avg, p25, exceptional) y la usa en lugar de la hardcodeada. Eso típicamente toma ~3 semanas de runs diarios.

**Si querés agregar una nueva fuente** (Mejorvuelo, TurismoCity, Skyscanner):

1. Crear `scrapers/<nombre>.py` que extiende `Source`
2. Implementar `fetch()` que devuelve lista de raws con `{source, title, url, slug, posted_at}`
3. Agregarla al list `sources` en `run.py`

El normalizador y el scorer ya están preparados para múltiples fuentes.

## Constantes compartidas con Ganga Hunter Autos

- `BLUE_RATE = 1290 ARS/USD`
- `GANGA_THRESHOLD = 0.85` (85% del histórico → ganga)
- `SUPER_GANGA_THRESHOLD = 0.75` (75% → super ganga)

## Roadmap (cuando esto esté estable 2 semanas)

1. **Mejorvuelo como segunda fuente** — más volumen, más cobertura de rutas
2. **TurismoCity** como tercera
3. **Detección de cambios entre runs** — alertar si un mismo deal bajó X% día a día
4. **Notificaciones WhatsApp** para gangas extraordinarias
5. **Toggle Autos / Vuelos** en la UI (unificada con Ganga Hunter Autos)
6. **Backfill** del histórico desde el archivo de Promociones Aéreas (tienen permalinks por mes desde hace años)
