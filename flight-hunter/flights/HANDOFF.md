# Flight Hunter — Handoff

Estado al **2026-05-26**. Documento operativo: cómo funciona, dónde está cada
cosa, cómo se opera, qué romperse podría romperse y qué hacer.

---

## 1. Qué hace, en una línea

Radar de gangas aéreas para Argentina: scrapea promociones-aéreas.com.ar,
**verifica el precio real con Google Flights (vía SerpApi)**, lo muestra
honesto, deja **buscar cualquier ruta+fecha en vivo**, y **avisa por
Telegram cuando aparece una 🟢 ganga confirmada**.

**Lo que NO es:** un buscador exhaustivo de vuelos (sale del blog, que es
curado, no listado completo). El "Buscador directo" sí va a Google Flights
puro y trae cualquier ruta, sea o no del blog.

---

## 2. URLs vivas

| Cosa | URL |
|---|---|
| App principal | **https://flighthunter-bruno.netlify.app** (la que controlo yo) |
| App espejo | https://flight-hunter90.netlify.app (mismo repo, otra cuenta Netlify; **sin SERPAPI_KEY**, no anda el buscador) |
| Bot Telegram | **@Taste90Bot** (compartido con el radar de autos) |
| Repo | https://github.com/btosto90-cloud/ganga-scraper |
| GitHub Actions | https://github.com/btosto90-cloud/ganga-scraper/actions |
| Netlify dashboard | https://app.netlify.com/projects/flighthunter-bruno |

---

## 3. Cómo funciona el ciclo automático

```
cron 3×día (06:37 / 12:37 / 18:37 UTC) → workflow flight-hunter-daily.yml
       ↓
   Scrape promociones-aéreas (RSS paginado + búsquedas por ciudad)
       ↓
   Normalize (parse precio del título, asignar origen/destino, fechas)
       ↓
   Score teaser (dealScore "desde", de referencia)
       ↓
   resolve_top_flights → top 11 por score, distintas rutas primero
       SerpApi/Google Flights → real_price_usd + 🟢/🟡/🔴
       ↓
   write flights.json (commitea al repo) + alert_new_gangas() Telegram
       ↓
   Deploy a Netlify (flighthunter-bruno)
```

Cap: **11 verificaciones/corrida × 3 corridas/día = 33/día ≈ 990/mes**, dentro
del plan SerpApi Starter (1.000/mes). Búsquedas repetidas las cachea SerpApi
gratis, así que el uso real es bastante menor.

---

## 4. Estructura del repo (lo de Flight Hunter)

```
flight-hunter/flights/
├── HANDOFF.md                              ← este doc
├── README.md                               (arquitectura genérica, vieja)
├── run.py                                  ← pipeline principal
├── requirements.txt
├── scrapers/
│   └── promociones_aereas.py               ← RSS paginado + search por ciudad
├── scoring/
│   ├── normalize.py                        ← parse title, IATA maps, blue rate
│   ├── score.py                            ← dealScore/qualScore "teaser"
│   ├── parse_post.py                       ← parse fecha-tablas del post
│   ├── route_baseline.py                   ← baseline hardcoded por ruta
│   ├── learning.py                         ← histórico learned baseline
│   ├── deeplinks.py                        ← URLs a Skyscanner/Google/Kayak
│   ├── price_resolver.py                   ← Google Flights vía SerpApi
│   └── notify.py                           ← alertas Telegram
├── public/
│   ├── index.html                          ← app frontend (1 sola página)
│   └── data/
│       └── flights.json                    ← output del pipeline (commiteado)
├── data/
│   ├── price_history.json                  ← histórico por ruta (90 días)
│   └── flight_alerts_state.json            ← dedup Telegram (24h)
└── netlify/functions/
    └── search-flight.js                    ← proxy serverless a SerpApi (para el buscador)

.github/workflows/
└── flight-hunter-daily.yml                 ← cron 3×día + steps

netlify.toml (raíz del repo)                ← publish dir, functions, redirects, cache headers
```

---

## 5. Credenciales / secrets

| Secret | Dónde vive | Para qué |
|---|---|---|
| `SERPAPI_KEY` | GitHub repo secrets + Netlify env vars (sitio flighthunter-bruno) | Verificar precio real (Google Flights) + buscador directo |
| `TELEGRAM_BOT_TOKEN` | GitHub repo secrets | Mandar alertas |
| `TELEGRAM_CHAT_ID` | GitHub repo secrets | Chat de Bruno |
| `NETLIFY_AUTH_TOKEN` | GitHub repo secrets | Deploy automático tras cada corrida |
| `NETLIFY_SITE_ID` | GitHub repo secrets | Site `flighthunter-bruno` (id: `a151caee-...`) |

**Copia local (NO commiteada):**
- `~/.ganga-auto/telegram.env` → mismas creds que el radar de autos
- `~/.ganga-auto/serpapi.env` → `SERPAPI_KEY=...`

Ver secrets en GitHub: `gh secret list --repo btosto90-cloud/ganga-scraper`
Setearlos: `printf '%s' "valor" | gh secret set NOMBRE --repo btosto90-cloud/ganga-scraper`

---

## 6. Operación

### Disparar una corrida manual
```bash
gh workflow run flight-hunter-daily.yml --repo btosto90-cloud/ganga-scraper
gh run watch <RUN_ID> --repo btosto90-cloud/ganga-scraper
```

### Ver el estado en vivo
```bash
curl -s https://flighthunter-bruno.netlify.app/data/flights.json | jq '.stats, .generated_at'
```

### Cambiar cuántos verifica por corrida
Editar `.github/workflows/flight-hunter-daily.yml`, env `FLIGHT_PRICE_MAX_RESOLVE`.
Cuenta: `cap × corridas/día × 30 ≤ cupo_mensual_serpapi`.

### Cambiar cadencia
Editar el `cron` en el mismo archivo (formato cron UTC). Evitar horas redondas
(pico de GitHub Actions, salteos).

### Ver consumo de SerpApi
```bash
curl -s "https://serpapi.com/account?api_key=$SERPAPI_KEY" | python3 -m json.tool
```

### Verificar que las alertas Telegram andan
```bash
source ~/.ganga-auto/telegram.env && python3 -c "
import os; os.environ.update({'TELEGRAM_BOT_TOKEN':os.environ['TELEGRAM_BOT_TOKEN'],'TELEGRAM_CHAT_ID':os.environ['TELEGRAM_CHAT_ID']})
import sys; sys.path.insert(0, 'flight-hunter/flights/scoring')
import notify; print(notify._send('🧪 test'))
"
```

---

## 7. Frontend — qué muestra y dónde

| Sección | Qué es |
|---|---|
| **🔎 Búsqueda directa** (banner verde arriba) | Llama al function serverless → SerpApi → trae precio real instantáneo. Acepta destinos puntuales o "⭐ Toda Europa" (multi-destino que rankea N en paralelo) |
| **Stats bar** | Verificados con Google / Gangas 🟢 / Precio normal 🟡 / Precio alto 🔴 |
| **Filtros** | Origen, Destino, Escalas, Equipaje, Score min, Ida desde / Vuelta hasta, **Ocultar 🔴** (default ON) |
| **Tabs** | Categorías por destino + Directos baratos + Posible error fare + A evitar |
| **Cards verificados** | Precio real + veredicto 🟢/🟡/🔴 + valija estimada (low-cost añade ~USD 100-160) + razón coherente + link a Google Flights |
| **Cards leads** (no verificados) | Solo "🔎 Ver precio real" + datos básicos. **No muestran número** (era el bug histórico de gangas falsas) |

Frontend está sorteado: **verificados arriba, leads abajo.**

---

## 8. Limitaciones honestas

- **La fuente es promociones-aéreas (curado, no exhaustivo).** Si una aerolínea
  tiene un vuelo a precio normal, el blog no lo postea — no lo vemos.
  Mitigación: el "Buscador directo" va a Google Flights puro.
- **Solo verificamos 11/corrida × 3/día = ~33/día** por costo. Las otras
  rutas quedan como "leads" sin precio.
- **La valija despachada en low-cost es ESTIMADA** (~USD 100 regional /
  USD 160 largo). El exacto requeriría una 2ª llamada Google por vuelo
  (doblar costo SerpApi).
- **No detecta error fares manuales** (los pros del rubro tienen equipos
  + relaciones con aerolíneas).
- **El cron de GitHub puede saltarse** (a veces, en horas pico). Mitigación:
  cadence 3×día con minutos raros off-peak.

---

## 9. Ideas para seguir (orden de impacto)

1. **Vista calendario por ruta** — elegís EZE-MAD y ves precio por día de
   los próximos 3-4 meses, con la fecha más barata resaltada. ~2h de
   trabajo, 1 search por ruta. Es lo que más pidió Bruno como "siguiente".
2. **Alerta con umbral custom** — "avisame si COR-MIA baja de USD 700" en
   vez de solo cuando Google diga "low". Permite criterios personales.
3. **Mejorvuelo como 2da fuente** — otro blog argentino similar; sumarlo
   triplica el caudal de leads.
4. **Valija exacta** — segunda llamada Google (booking-options) para
   precio total con bag exacto. Cuesta 2× SerpApi por vuelo verificado.
5. **Tablero histórico** — mostrar cómo evolucionó el precio real por
   ruta a lo largo de semanas (Google Flights API trae price_history).

---

## 10. Troubleshooting rápido

| Síntoma | Causa probable | Fix |
|---|---|---|
| App muestra data vieja | Cron saltado / commit failed | `gh workflow run flight-hunter-daily.yml` manual |
| Buscador directo dice "SERPAPI_KEY no configurada" | Estás en flight-hunter90 (no flighthunter-bruno) | Usar flighthunter-bruno |
| Push del workflow falla con non-fast-forward | Otro commit entró en el medio | Ya manejado (retry+rebase + `continue-on-error`) |
| No llegan alertas Telegram | (a) no hay 🟢 ese día (lo más común), (b) creds en GitHub vencieron, (c) bot bloqueado | Verificar `gh secret list`, probar `_send()` manual |
| SerpApi 401 / quota exceeded | Plan vencido / cupo blowout | Ver `/account` endpoint, upgradear plan o bajar `MAX_RESOLVE` |
| Card muestra contradicción tier vs verdicto | Bug viejo de recalc client-side | Ya gateado en index.html: `if (f.has_real_price) return {...f}` antes de recalcular |
| Precios "60 USD" o similar absurdo | Bug parse "descuento" en título | Ya filtrado en `normalize._parse_price` (skip context "descuento/cuota/off") |
| Fechas vencidas en deeplinks | Posts viejos del blog | `parse_post.py` filtra fechas pasadas; flight con todas vencidas → descartado |

---

## 11. Cosas que NO mezclar

- **Radar de autos (Ganga Hunter / Ganga Auto):** vive en `~/ganga-scraper`
  pero corre LOCAL en la Mac de Bruno con launchd. CONGELADO en config
  nacional-pura. **No tocar sin pedido explícito.** Sí comparte:
  - Mismo bot @Taste90Bot
  - Mismo telegram.env en `~/.ganga-auto/`
  - Mismo repo (carpeta `flight-hunter/` es subdirectorio aparte)

---

## 12. Contacto / contexto

- **Owner:** Bruno Tosto (`b.tosto90@gmail.com`) — gerente de eficiencia
  comercial en Nolter (Córdoba/NOA/Cuyo).
- **GitHub:** `btosto90-cloud`
- **Netlify team:** Tosto
- **Plan SerpApi:** Starter (USD 25/mes, 1.000 búsquedas)
