#!/usr/bin/env python3
"""
ml_local.py — Scraper de MercadoLibre con Playwright headless.

Uso:
  cd ~/Downloads
  python3 ml_local.py

Pre-requisito (1 sola vez):
  pip3 install --break-system-packages playwright
  python3 -m playwright install chromium

Genera ml_listings.json. Subir al repo después.
"""

import json
import re
import sys
import time
import random
import urllib.request
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

OUTPUT_FILE = "ml_listings.json"

# Fuentes de dólar blue (venta), en orden de preferencia. Si una falla, prueba la siguiente.
BLUE_SOURCES = (
    ('dolarapi', 'https://dolarapi.com/v1/dolares/blue', lambda d: d.get('venta')),
    ('bluelytics', 'https://api.bluelytics.com.ar/v2/latest', lambda d: (d.get('blue') or {}).get('value_sell')),
    ('criptoya', 'https://criptoya.com/api/dolar', lambda d: (d.get('blue') or {}).get('ask')),
)

def fetch_blue_rate():
    """Lee dólar blue (venta) probando varias fuentes en orden. Fallback a 1400."""
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15'}
    for name, url, extract in BLUE_SOURCES:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
            rate = extract(data)
            if rate and 1000 < rate < 5000:
                print(f"BLUE_RATE actualizado: {int(rate)} ({name})")
                return int(rate)
        except Exception as e:
            print(f"WARN: {name} falló ({e})")
    print("WARN: todas las fuentes de blue fallaron, usando fallback 1400")
    return 1400

BLUE_RATE = fetch_blue_rate()

MARCAS = [
    'audi', 'toyota', 'volkswagen', 'ford', 'chevrolet',
    'peugeot', 'renault', 'honda', 'fiat', 'bmw',
    'mercedes-benz', 'hyundai', 'kia', 'nissan', 'mazda',
    'citroen', 'jeep', 'mitsubishi', 'subaru', 'chery', 'haval', 'byd',
]

PAGINAS_POR_MARCA = 10
ITEMS_POR_PAGINA = 48  # ML usa offset de 48 por defecto

UA_SAFARI = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"

# Pool de UAs reales para rotar entre marcas — reduce detección
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:128.0) Gecko/20100101 Firefox/128.0",
]

# ─── HELPERS ──────────────────────────────────────────────────────────────────

BRANDS_NORMALIZE = {'mercedes-benz': 'mercedes', 'mercedes benz': 'mercedes', 'vw': 'volkswagen'}
KNOWN_BRANDS = ['mercedes-benz', 'mercedes benz', 'mercedes', 'audi', 'toyota', 'volkswagen', 'ford',
    'chevrolet', 'peugeot', 'renault', 'honda', 'fiat', 'bmw', 'hyundai', 'kia', 'nissan',
    'mazda', 'citroen', 'jeep', 'mitsubishi', 'subaru', 'chery', 'haval', 'byd', 'ram',
    'dodge', 'suzuki', 'volvo', 'land rover']
KNOWN_MODELS = [
    # Audi performance/RS
    'rs3', 'rs4', 'rs5', 'rs6', 'rs7', 'rs q3', 'rs q5', 'rs q8', 'tt rs', 'tts',
    's3', 's4', 's5', 's6', 's7', 's8', 'sq5', 'sq7', 'sq8',
    # Audi normales
    'corolla cross', 'corolla', 'land cruiser', 'grand cherokee', 'santa fe',
    'a1', 'a3', 'a4', 'a5', 'a6', 'a7', 'a8', 'q2', 'q3', 'q5', 'q7', 'q8', 'tt',
    # BMW M y series
    'm135', 'm140', 'm235', 'm240', 'm340', 'm440', 'm550',
    'm2', 'm3', 'm4', 'm5', 'm6', 'm8',
    'x1 m', 'x2 m', 'x3 m', 'x4 m', 'x5 m', 'x6 m',
    '116', '118', '120', '125', '130',
    '218', '220', '228', '230',
    '318', '320', '325', '328', '330', '335', '340',
    '420', '428', '430', '435', '440',
    '520', '523', '525', '528', '530', '535', '540',
    'x1', 'x2', 'x3', 'x4', 'x5', 'x6', 'x7',
    # Mercedes AMG y normales
    'amg gt', 'a45', 'cla45', 'c43', 'c63', 'e43', 'e53', 'e63', 'gle63', 'glc63',
    'a200', 'a250', 'c180', 'c200', 'c250', 'c300',
    'gla', 'glb', 'glc', 'gle', 'gls',
    # Toyota
    'yaris', 'hilux', 'rav4', 'sw4', 'chr', 'c-hr', 'etios', 'fortuner', 'prius',
    # VW (incluyendo R/GTI)
    'golf gti', 'golf r', 'polo gti',
    'polo', 'golf', 'vento', 'tiguan', 'amarok', 'taos', 'nivus', 'virtus', 'saveiro',
    # Peugeot
    '208', '308', '2008', '3008', '408', '508',
    # Renault (incluyendo RS)
    'megane rs', 'clio rs', 'sandero rs',
    'clio', 'sandero', 'duster', 'logan', 'kwid', 'captur', 'arkana', 'oroch', 'megane',
    # Honda (incluyendo Type R)
    'civic type r', 'civic',
    'fit', 'hr-v', 'hrv', 'cr-v', 'crv', 'wr-v', 'wrv', 'accord',
    # Fiat
    'cronos', 'argo', 'pulse', 'fastback', 'mobi', 'toro', 'strada',
    # Hyundai
    'tucson', 'creta', 'venue', 'i30',
    # Kia
    'cerato', 'sportage', 'sorento', 'seltos', 'stinger', 'rio', 'picanto',
    # Nissan (incluyendo GT-R/Nismo)
    'gt-r', 'gtr', 'nismo',
    'march', 'versa', 'sentra', 'kicks', 'frontier',
    # Jeep
    'renegade', 'compass', 'wrangler', 'gladiator',
    # Chevrolet
    'onix', 'tracker', 'cruze', 'equinox', 's10', 'spin',
    # Ford (incluyendo ST/RS)
    'focus rs', 'focus st', 'fiesta st', 'mustang gt',
    'focus', 'ecosport', 'ranger', 'territory', 'kuga', 'maverick', 'bronco',
    # Citroen
    'c3', 'c4', 'berlingo',
    # Chinos
    'tiggo', 'jolion', 'h6', 'dolphin'
]

def normalize_brand(b):
    if not b: return 'other'
    b = b.lower().strip()
    return BRANDS_NORMALIZE.get(b, b).replace(' ', '_').replace('-', '_')

def find_brand_in_text(text):
    if not text: return None
    t = text.lower()
    for b in KNOWN_BRANDS:
        if b in t: return normalize_brand(b)
    return None

def find_model_in_text(text):
    if not text: return None
    t = text.lower()
    for m in KNOWN_MODELS:
        if m in t: return m.replace(' ', '_').replace('-', '_')
    return None

# Variantes de equipamiento/trim que afectan precio significativamente
TRIMS = [
    'amg line', 'm sport', 'm-sport', 'r line', 'r-line', 'n line', 'n-line',
    'gt line', 'gt-line', 'st line', 'st-line', 's line', 's-line',
    'sport', 'sportback', 'sportline', 'avantgarde', 'progressive', 'exclusive',
    'gti', 'gtd', 'gts', 'rs', 'st', 'gt',
    'highline', 'comfortline', 'trendline',
    'titanium', 'limited', 'platinum', 'premium', 'luxury',
    'ultimate', 'top', 'tope de gama',
    'xei', 'xls', 'xlt', 'xei plus', 'xls plus',
    'd-cab', 'cd', 'cs', 'ce',
    'awd', '4x4', 'quattro', 'xdrive', '4motion', '4matic',
    'cabrio', 'coupe', 'sedan', 'hatchback', 'wagon', 'sw',
    'manual', 'automatico', 'automatic', 'tiptronic', 'dsg', 'cvt',
]

def find_trim(text):
    """Detecta el trim/versión del título. Devuelve el más específico."""
    if not text: return None
    t = text.lower()
    found = []
    for trim in TRIMS:
        if trim in t:
            found.append(trim)
    if not found: return None
    # Priorizar el más largo/específico (ej. "amg line" > "line")
    found.sort(key=len, reverse=True)
    return found[0].replace(' ', '_').replace('-', '_')

def make_model_key(brand, model, year, trim=None):
    base = f"{brand or 'other'}_{model or 'other'}_{year}"
    if trim:
        base += f"_{trim}"
    return base

def is_realistic_price(precio_usd, year):
    if not precio_usd or precio_usd < 1500: return False
    if precio_usd > 500000: return False
    if year >= 2022 and precio_usd < 6000: return False
    if year >= 2020 and precio_usd < 4000: return False
    if year >= 2018 and precio_usd < 3000: return False
    return True

# ─── PLAYWRIGHT EXTRACTION ────────────────────────────────────────────────────

# Script JS que corre dentro de la página y extrae los listings.
# Cubre todos los layouts conocidos de ML.
EXTRACT_JS = """
() => {
  const items = [];
  const selectors = [
    '.poly-card',
    '.ui-search-layout__item',
    '.ui-search-result__wrapper',
    '.andes-card.poly-card',
    'li[class*="ui-search-layout"]',
  ];

  const found = new Set();
  for (const sel of selectors) {
    document.querySelectorAll(sel).forEach(el => found.add(el));
  }

  for (const card of found) {
    try {
      const linkEl = card.querySelector(
        'a.poly-component__title, a.ui-search-link, a.ui-search-result__content, h2 a, .poly-component__title-wrapper a, a[href*="MLA-"], a[href*="/MLA"]'
      );
      if (!linkEl) continue;

      const url = linkEl.href || '';
      if (!url || !url.includes('mercadolibre.com')) continue;

      const title = (linkEl.textContent || linkEl.getAttribute('title') || '').trim();

      // TODOS los precios del card (no solo el primero!)
      // Esto permite distinguir anticipo vs precio real
      const allPrices = [];
      card.querySelectorAll('.andes-money-amount').forEach(amt => {
        const sym = amt.querySelector('.andes-money-amount__currency-symbol');
        const frac = amt.querySelector('.andes-money-amount__fraction');
        if (sym && frac) {
          allPrices.push({
            symbol: sym.textContent.trim(),
            fraction: frac.textContent.trim(),
          });
        }
      });

      // Atributos
      const attrEls = card.querySelectorAll(
        '.poly-attributes_list__item, .ui-search-card-attributes__attribute, .poly-attributes-list__item, .ui-search-item__group__element'
      );
      const attrs = [];
      attrEls.forEach(e => attrs.push(e.textContent.trim()));

      // CRÍTICO: capturar TODO el texto del card para detectar "anticipo", "cuotas", etc.
      const fullText = (card.innerText || card.textContent || '').toLowerCase();

      items.push({ url, title, allPrices, attrs, fullText });
    } catch (e) {}
  }
  return items;
};
"""

# Palabras que indican que el precio mostrado NO es el del auto completo
ANTICIPO_KEYWORDS = [
    'anticipo', 'anticipá', 'anticipa',
    'cuotas de', 'cuotas fijas', 'en cuotas', 'cuotas sin interés',
    'financiado en cuotas', 'financiados',
    'entrega y cuotas', 'entrega de',
    'pago inicial', 'desde u$s', 'desde us$',
    'plan de ahorro', 'plan oficial',
    'por mes', '/mes',
]

def has_anticipo_keywords(text):
    """Detecta si el card tiene texto típico de financiación/anticipo."""
    if not text: return False
    t = text.lower()
    for kw in ANTICIPO_KEYWORDS:
        if kw in t:
            return True
    return False

def parse_extracted(items, marca_search):
    """Toma los datos crudos extraídos por JS y los convierte al formato listing."""
    listings = []
    seen = set()

    for raw in items:
        try:
            url = raw.get('url') or ''
            title = (raw.get('title') or '')[:80]
            all_prices = raw.get('allPrices') or []
            attrs = raw.get('attrs') or []
            full_text = raw.get('fullText') or ''

            # ID
            id_m = re.search(r'MLA[-]?(\d+)', url)
            if not id_m: continue
            item_id = f"ml_{id_m.group(1)}"
            if item_id in seen: continue
            seen.add(item_id)

            if not title: continue

            # ╔═══ FILTRO ANTI-ANTICIPO ══════════════════════════════════════════╗
            # Si el card menciona anticipo/cuotas, descartar — el precio es trampa
            if has_anticipo_keywords(full_text):
                continue
            # ╚════════════════════════════════════════════════════════════════════╝

            # Procesar TODOS los precios del card y elegir el más alto en USD
            # (los de anticipo suelen ser bajos, el real es el más alto)
            usd_candidates = []
            ars_candidates = []
            for p in all_prices:
                symbol = p.get('symbol') or ''
                fraction = p.get('fraction') or ''
                frac_clean = re.sub(r'[^\d]', '', fraction)
                if not frac_clean: continue
                n = int(frac_clean)
                if 'US' in symbol or 'U$S' in symbol or 'usd' in symbol.lower():
                    usd_candidates.append(n)
                elif n > 100000:  # ARS solo si es alto
                    ars_candidates.append(n)

            precio_usd = 0
            if usd_candidates:
                # Si hay USD, el real es el MAYOR (los anticipos son menores)
                # PERO solo si la diferencia tiene sentido
                precio_usd = max(usd_candidates)
            elif ars_candidates:
                # ARS: agarrar el mayor también
                precio_usd = round(max(ars_candidates) / BLUE_RATE)

            if not precio_usd: continue

            # Año/km — buscar en attrs y fullText
            search_text = ' '.join(attrs) + ' ' + title
            year = 0
            ym = re.search(r'\b(20\d{2}|19[89]\d)\b', search_text)
            if ym: year = int(ym.group(1))
            if year < 1990 or year > 2027: continue

            km = 0
            kmm = re.search(r'([\d.]+)\s*[Kk][Mm]', search_text)
            if kmm:
                try: km = int(kmm.group(1).replace('.', ''))
                except: pass
            if km > 600000: continue

            if not is_realistic_price(precio_usd, year): continue

            brand = find_brand_in_text(title) or normalize_brand(marca_search)
            model = find_model_in_text(title)

            trim = find_trim(title)
            listings.append({
                'id': item_id,
                'url': url.split('?')[0].split('#')[0],
                'title': title,
                'brand': brand,
                'model': model,
                'year': year,
                'km': km,
                'fuel': '?',
                'trans': '?',
                'precio_usd': precio_usd,
                'fuente': 'ml',
                'trim': trim,
                'model_key': make_model_key(brand, model, year, trim),
            })
        except Exception:
            continue

    return listings

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("ML SCRAPER (Playwright headless)")
    print("=" * 60)

    all_listings = []
    seen_ids = set()
    marcas_skip = 0
    first_seen_map = {}  # id -> ISO date string del primer scrape
    price_history_map = {}  # id -> [{fecha, precio_usd}, ...]

    today_iso = datetime.utcnow().date().isoformat()

    # RESUME: si hay un JSON parcial, cargarlo
    import os
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
                prev = json.load(f)
            prev_listings = prev.get('listings', [])

            # Cargar map de first_seen de TODOS los listings históricos
            # (incluso si no estamos resumiendo, queremos preservar las fechas)
            for l in prev_listings:
                lid = l.get('id')
                if lid:
                    first_seen_map[lid] = l.get('first_seen', today_iso)
                    # Cargar histórico de precios si existe
                    if l.get('price_history'):
                        price_history_map[lid] = l['price_history']

            if prev.get('parcial') and prev_listings:
                marcas_completas = prev.get('marcas_completas', 0)
                if sys.stdin.isatty():
                    respuesta = input(
                        f"\n⚠️  Encontré {OUTPUT_FILE} parcial con {len(prev_listings)} listings "
                        f"({marcas_completas} marcas completas). ¿Continuar desde ahí? [s/N]: "
                    ).strip().lower()
                else:
                    # Modo automatizado (launchd/cron): resumir desde donde quedó, sin preguntar.
                    respuesta = 's'
                    print(f"  [auto] {OUTPUT_FILE} parcial detectado → reanudando desde marca {marcas_completas + 1}")
                if respuesta == 's':
                    all_listings = prev_listings
                    seen_ids = set(l['id'] for l in prev_listings if 'id' in l)
                    marcas_skip = marcas_completas
                    print(f"✓ Reanudando desde marca {marcas_skip + 1}/{len(MARCAS)}")
                else:
                    print("✓ Empezando de cero (pero conservando first_seen del histórico)")
        except Exception as e:
            print(f"  (no pude leer JSON previo: {e})")

    with sync_playwright() as p:
        # Lanzar Chromium con args para evitar detección como bot
        browser = p.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
            ],
        )

        # Función helper para crear un context fresco (con cookies/storage limpios)
        def crear_context():
            ua_random = random.choice(USER_AGENTS)
            ctx = browser.new_context(
                user_agent=ua_random,
                viewport={'width': random.choice([1280, 1366, 1440, 1536]), 'height': random.choice([720, 800, 900])},
                locale='es-AR',
                timezone_id='America/Argentina/Buenos_Aires',
            )
            ctx.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'languages', { get: () => ['es-AR', 'es', 'en'] });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            """)
            return ctx

        def es_pagina_bloqueo(html):
            """Detecta si ML devolvió un block page (HTML chico, sin contenido útil)"""
            # Bloqueo real: HTML pequeño (< 50KB) — la página de bloqueo es minimalista
            if len(html) < 50000:
                return True
            if 'micro-landing' in html:
                return True
            # HTML grande sin keywords típicas: probablemente bloqueo elaborado
            # Si tiene 'mercadolibre' y scripts típicos NO es bloqueo, solo lazy-load
            has_ml_chrome = 'mercadolibre' in html.lower() and ('runtime' in html or 'webpack' in html)
            if not has_ml_chrome:
                return True
            return False

        for i, marca in enumerate(MARCAS, 1):
            # Skip marcas ya completadas (resume mode)
            if i <= marcas_skip:
                print(f"\n[{i}/{len(MARCAS)}] {marca} — saltada (ya completada)")
                continue

            print(f"\n[{i}/{len(MARCAS)}] {marca}")

            # Context FRESCO para cada marca con UA random → ML ve "nueva sesión + dispositivo"
            context = crear_context()
            page = context.new_page()

            # Visitar home de ML primero para "calentar" la sesión (parece humano)
            try:
                page.goto('https://www.mercadolibre.com.ar/', wait_until='domcontentloaded', timeout=20000)
                time.sleep(random.uniform(2.0, 4.0))
            except Exception:
                pass  # si falla no es crítico

            marca_url = marca.lower().replace(' ', '-')
            marca_listings = []
            bloqueos_consecutivos = 0

            for pg in range(PAGINAS_POR_MARCA):
                if pg == 0:
                    url = f"https://listado.mercadolibre.com.ar/autos-camionetas/{marca_url}-usado_NoIndex_True"
                else:
                    desde = pg * ITEMS_POR_PAGINA + 1
                    url = f"https://listado.mercadolibre.com.ar/autos-camionetas/{marca_url}-usado_Desde_{desde}_NoIndex_True"

                try:
                    page.goto(url, wait_until='domcontentloaded', timeout=30000)
                except PlaywrightTimeout:
                    print(f"    p{pg+1}: timeout")
                    break
                except Exception as e:
                    print(f"    p{pg+1}: error {type(e).__name__}")
                    break

                # Scroll inicial para forzar lazy-load (algunas páginas como Toyota tienen mucho contenido)
                try:
                    page.evaluate("window.scrollTo(0, 800)")
                    time.sleep(0.8)
                except Exception:
                    pass

                # Esperar a que aparezcan los listings
                try:
                    page.wait_for_selector(
                        '.poly-card, .ui-search-layout__item, .ui-search-result',
                        timeout=20000,
                    )
                    bloqueos_consecutivos = 0  # éxito, resetear contador
                except PlaywrightTimeout:
                    html = page.content()
                    if es_pagina_bloqueo(html):
                        bloqueos_consecutivos += 1
                        print(f"    p{pg+1}: 🚫 ML bloqueó (HTML {len(html)}b) — bloqueo #{bloqueos_consecutivos}")
                        if bloqueos_consecutivos >= 2:
                            print(f"    ✗ Abortando marca por bloqueos consecutivos")
                            break
                        wait_s = random.uniform(180, 300)
                        print(f"    ⏸  Esperando {wait_s:.0f}s antes de reintentar...")
                        time.sleep(wait_s)
                        continue
                    else:
                        # HTML grande pero no se ven listings: capaz lazy-load no terminó
                        # Probar scroll agresivo + reintentar wait
                        print(f"    p{pg+1}: HTML {len(html)}b sin listings detectados, scroll agresivo...")
                        try:
                            for _ in range(4):
                                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                                time.sleep(1)
                                page.evaluate("window.scrollTo(0, 0)")
                                time.sleep(0.5)
                            page.wait_for_selector(
                                '.poly-card, .ui-search-layout__item, .ui-search-result',
                                timeout=10000,
                            )
                            print(f"    p{pg+1}: ✓ recuperado tras scroll")
                        except PlaywrightTimeout:
                            print(f"    p{pg+1}: sin listings tras scroll, salteando")
                            break

                # Scroll para cargar lazy-loaded items
                page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
                time.sleep(0.5)
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(0.5)

                raw_items = page.evaluate(EXTRACT_JS)
                parsed = parse_extracted(raw_items, marca)

                nuevos = 0
                for l in parsed:
                    if l['id'] not in seen_ids:
                        # first_seen
                        l['first_seen'] = first_seen_map.get(l['id'], today_iso)
                        # Histórico de precios: append solo si cambió
                        prev_history = price_history_map.get(l['id'], [])
                        if not prev_history:
                            # Primer registro
                            l['price_history'] = [{'fecha': today_iso, 'precio_usd': l['precio_usd']}]
                            l['price_changed'] = False
                            l['price_drops'] = 0
                        else:
                            last_price = prev_history[-1]['precio_usd']
                            if l['precio_usd'] != last_price:
                                l['price_history'] = prev_history + [{'fecha': today_iso, 'precio_usd': l['precio_usd']}]
                                l['price_changed'] = True
                                # Contar bajadas
                                drops = 0
                                hist = l['price_history']
                                for k in range(1, len(hist)):
                                    if hist[k]['precio_usd'] < hist[k-1]['precio_usd']:
                                        drops += 1
                                l['price_drops'] = drops
                                # Bajada total %
                                if hist[0]['precio_usd'] > 0:
                                    l['price_drop_pct'] = round((1 - l['precio_usd'] / hist[0]['precio_usd']) * 100, 1)
                            else:
                                l['price_history'] = prev_history
                                l['price_changed'] = False
                                # mantener drops ya contado
                                drops = 0
                                for k in range(1, len(prev_history)):
                                    if prev_history[k]['precio_usd'] < prev_history[k-1]['precio_usd']:
                                        drops += 1
                                l['price_drops'] = drops
                                if prev_history[0]['precio_usd'] > 0:
                                    l['price_drop_pct'] = round((1 - l['precio_usd'] / prev_history[0]['precio_usd']) * 100, 1)
                        seen_ids.add(l['id'])
                        marca_listings.append(l)
                        all_listings.append(l)
                        nuevos += 1

                print(f"    p{pg+1}: {len(raw_items)} extraídos → {len(parsed)} válidos → {nuevos} nuevos")

                if nuevos == 0:
                    break

                # Pausa entre páginas: 3-6s (era 1.5-3s, ahora más conservador)
                time.sleep(random.uniform(3.0, 6.0))

            print(f"  >> {marca}: {len(marca_listings)} listings")

            # CERRAR el context al terminar la marca
            context.close()

            # SAVE INCREMENTAL: guardar después de cada marca
            try:
                with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
                    json.dump({
                        'updated': datetime.utcnow().isoformat() + 'Z',
                        'fuente': 'ml_local',
                        'parcial': i < len(MARCAS),
                        'marcas_completas': i,
                        'listings': all_listings,
                    }, f, ensure_ascii=False, indent=2)
                print(f"  💾 Guardado: {len(all_listings)} listings totales")
            except Exception as e:
                print(f"  ⚠️ No se pudo guardar: {e}")

            # Pausa entre marcas: 10-20s (era 5-10s)
            if i < len(MARCAS):
                pausa = random.uniform(10.0, 20.0)
                # Cada 4 marcas, una pausa larga para que ML "olvide" (era cada 5)
                if i % 4 == 0:
                    pausa = random.uniform(120.0, 240.0)  # 2-4 min
                    print(f"  ⏸  Pausa larga: {pausa:.0f}s (cada 4 marcas, evita rate-limiting)")
                time.sleep(pausa)

        browser.close()

    # ─── Validación de antigüedad de publicaciones (vía API pública ML) ───
    # ML tiene un endpoint público sin auth: /items?ids=MLA1,MLA2,...
    # que devuelve start_time. Filtramos los publicados hace > MAX_DIAS_PUBLICACION días.
    MAX_DIAS_PUBLICACION = 180  # 6 meses (60-180 = alta negociación, >180 descartado)
    print(f"\n🔍 Validando antigüedad de publicaciones (>{MAX_DIAS_PUBLICACION} días = descartado)...")

    def chunk(lst, size):
        for i in range(0, len(lst), size):
            yield lst[i:i+size]

    # Convertir IDs: nuestro id es MLA-1234567 pero el API quiere MLA1234567
    def normalize_mla(item_id):
        return item_id.replace('-', '') if item_id else None

    fecha_corte = datetime.utcnow().timestamp() - MAX_DIAS_PUBLICACION * 86400

    # Solo validamos los que tengan IDs que parezcan ML
    items_to_check = [l for l in all_listings if l.get('id', '').startswith('MLA')]
    print(f"  {len(items_to_check)} items a validar")

    descartados = 0
    sin_fecha = 0
    procesados = 0

    for batch in chunk(items_to_check, 20):
        ids_param = ','.join(normalize_mla(l['id']) for l in batch if l.get('id'))
        if not ids_param:
            continue
        try:
            url = f"https://api.mercadolibre.com/items?ids={ids_param}&attributes=id,start_time,status"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())

            # data es array de {code, body:{id, start_time, status}}
            fechas = {}
            for entry in data:
                if entry.get('code') == 200 and entry.get('body'):
                    body = entry['body']
                    item_id_raw = body.get('id', '')
                    # ML devuelve sin guion: MLA1234567
                    fechas[item_id_raw] = {
                        'start_time': body.get('start_time'),
                        'status': body.get('status'),
                    }

            # Aplicar a los listings del batch
            for l in batch:
                norm_id = normalize_mla(l.get('id', ''))
                info = fechas.get(norm_id)
                procesados += 1
                if not info or not info.get('start_time'):
                    sin_fecha += 1
                    continue
                # Parsear fecha ISO
                try:
                    st = info['start_time'].replace('Z', '+00:00')
                    ts = datetime.fromisoformat(st).timestamp()
                    l['start_time'] = info['start_time']
                    l['days_published'] = int((datetime.utcnow().timestamp() - ts) / 86400)
                    if ts < fecha_corte:
                        l['_descartar'] = True
                        descartados += 1
                except Exception:
                    sin_fecha += 1
        except Exception as e:
            # Si falla la API para este batch, no descartamos (mejor pecar de inclusivo)
            pass

        # Pausa breve cada batch para no abusar
        time.sleep(0.3)

        # Print progress cada 10 batches
        if procesados % 200 == 0:
            print(f"    {procesados}/{len(items_to_check)} procesados, {descartados} descartados...")

    # Filtrar los marcados
    antes = len(all_listings)
    all_listings = [l for l in all_listings if not l.get('_descartar')]
    for l in all_listings:
        l.pop('_descartar', None)

    print(f"  ✓ Validados: {procesados}, descartados por viejos: {descartados}, sin fecha: {sin_fecha}")
    print(f"  Total después de filtro de antigüedad: {len(all_listings)} (antes: {antes})")

    # Fallback: para los que NO conseguimos start_time (sin_fecha o errores de API),
    # usar heurística basada en el número de ID
    # Hipótesis: MLA emite ~1M IDs/día. ID actual rondaría los 1.85B+
    # Listings con ID demasiado bajo son sospechosamente viejos
    if sin_fecha > 0:
        print(f"\n  Aplicando heurística para {sin_fecha} items sin fecha...")
        # Calibrar: tomar el ID máximo visto como referencia "actual"
        ids_numericos = []
        for l in all_listings:
            try:
                num = int(l.get('id', '').replace('MLA-', '').replace('MLA', ''))
                ids_numericos.append(num)
            except Exception:
                pass
        if ids_numericos:
            id_max = max(ids_numericos)
            # ~1M IDs/día → MAX_DIAS días = MAX_DIAS * 1M IDs en el pasado
            id_min_aceptable = id_max - (MAX_DIAS_PUBLICACION * 1_000_000)
            heuristic_descartados = 0
            for l in all_listings:
                if l.get('start_time'):
                    continue  # ya tiene fecha real, no tocar
                try:
                    num = int(l.get('id', '').replace('MLA-', '').replace('MLA', ''))
                    if num < id_min_aceptable:
                        l['_descartar_heuristic'] = True
                        heuristic_descartados += 1
                        l['days_published_estimated'] = int((id_max - num) / 1_000_000)
                except Exception:
                    pass
            antes2 = len(all_listings)
            all_listings = [l for l in all_listings if not l.get('_descartar_heuristic')]
            for l in all_listings:
                l.pop('_descartar_heuristic', None)
            print(f"  ✓ Heurística: {heuristic_descartados} descartados (id_max={id_max}, corte={id_min_aceptable})")
            print(f"  Total post-heurística: {len(all_listings)} (antes: {antes2})")

    # Stats
    marcas_count = {}
    for l in all_listings:
        b = l.get('brand', 'other')
        marcas_count[b] = marcas_count.get(b, 0) + 1

    output = {
        'updated': datetime.utcnow().isoformat() + 'Z',
        'total': len(all_listings),
        'fuente': 'ml',
        'marcas': marcas_count,
        'listings': all_listings,
    }

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print(f"✓ Generado: {OUTPUT_FILE}")
    print(f"  Total: {len(all_listings)} autos")
    if marcas_count:
        top = dict(sorted(marcas_count.items(), key=lambda x: -x[1])[:8])
        print(f"  Top marcas: {top}")
    print("\nProximo paso: subi ml_listings.json al repo de GitHub")
    print("(arrastra a github.com/btosto90-cloud/ganga-scraper/upload/main)")
    print("=" * 60)


if __name__ == '__main__':
    main()
