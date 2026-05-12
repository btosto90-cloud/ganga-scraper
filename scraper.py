import json
import os
import re
import time
import random
import urllib.request
import urllib.parse
from datetime import datetime, timedelta

BLUE_RATE = 1400  # default, se sobreescribe abajo con valor real

def fetch_blue_rate():
    """Lee dólar blue (venta) desde dolarapi.com. Fallback a 1400."""
    try:
        with urllib.request.urlopen('https://dolarapi.com/v1/dolares/blue', timeout=10) as r:
            data = json.loads(r.read())
            rate = data.get('venta')
            if rate and 1000 < rate < 5000:
                print(f"BLUE_RATE actualizado: {rate} (dolarapi.com)")
                return int(rate)
    except Exception as e:
        print(f"WARN: dolarapi falló ({e}), usando fallback 1400")
    return 1400

BLUE_RATE = fetch_blue_rate()
OUTPUT_FILE = "listings.json"

# Credenciales ML (vienen de GitHub Actions secrets)
ML_CLIENT_ID = os.environ.get('ML_CLIENT_ID', '')
ML_CLIENT_SECRET = os.environ.get('ML_CLIENT_SECRET', '')
ML_REFRESH_TOKEN = os.environ.get('ML_REFRESH_TOKEN', '')

HEADERS_LIST = [
    {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'es-AR,es;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    },
    {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'es-AR,es;q=0.8',
    },
]

# ─── HTTP ──────────────────────────────────────────────────────────────────────

def fetch(url, headers=None, retries=3, delay=2):
    if headers is None:
        headers = random.choice(HEADERS_LIST)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as r:
                content = r.read()
                if r.info().get('Content-Encoding') == 'gzip':
                    import gzip
                    content = gzip.decompress(content)
                return content
        except Exception as e:
            print(f"  [fetch] err {attempt+1}/{retries} {url[:80]}: {e}")
            if attempt < retries - 1:
                time.sleep(delay * (attempt + 1))
    return b""

# ─── PRICE PARSING ────────────────────────────────────────────────────────────

def parse_price_smart(raw, currency_hint=None):
    """
    Devuelve (precio_usd, currency) o (0, None) si no es válido.
    currency_hint: 'USD' | 'ARS' | None
    """
    if not raw or 'consultar' in str(raw).lower():
        return 0, None
    raw = str(raw).strip()
    num_str = re.sub(r'[^\d]', '', raw)
    if not num_str:
        return 0, None
    num = int(num_str)
    if num < 100:
        return 0, None

    is_usd = currency_hint == 'USD' or bool(re.search(r'u\$s|usd', raw, re.I))
    is_ars = currency_hint == 'ARS' or '$' in raw and not is_usd

    if is_usd:
        return num, 'USD'
    if is_ars:
        # Precios en ARS: deberían ser >= 1M para un auto razonable
        if num < 500000:
            return 0, None
        return round(num / BLUE_RATE), 'USD'
    # Sin pista clara: heurística
    if num >= 500000:
        return round(num / BLUE_RATE), 'USD'
    if 1000 <= num < 500000:
        return num, 'USD'
    return 0, None

def is_realistic_price(precio_usd, year):
    """Filtra precios obviamente erróneos."""
    if not precio_usd or precio_usd < 1500:
        return False
    if precio_usd > 500000:
        return False
    # Auto reciente no puede valer menos de cierto piso
    if year >= 2022 and precio_usd < 6000:
        return False
    if year >= 2020 and precio_usd < 4000:
        return False
    if year >= 2018 and precio_usd < 3000:
        return False
    return True

# ─── MODEL KEY ────────────────────────────────────────────────────────────────

BRANDS_NORMALIZE = {
    'mercedes-benz': 'mercedes',
    'mercedes benz': 'mercedes',
    'mercedesbenz': 'mercedes',
    'vw': 'volkswagen',
}

KNOWN_BRANDS = [
    'mercedes-benz', 'mercedes benz', 'mercedes',
    'audi', 'toyota', 'volkswagen', 'ford', 'chevrolet',
    'peugeot', 'renault', 'honda', 'fiat', 'bmw',
    'hyundai', 'kia', 'nissan', 'mazda', 'citroen',
    'jeep', 'mitsubishi', 'subaru', 'chery', 'haval', 'byd',
    'ram', 'dodge', 'suzuki', 'volvo', 'land rover',
]

KNOWN_MODELS = [
    # Audi performance
    'rs3', 'rs4', 'rs5', 'rs6', 'rs7', 'rs q3', 'rs q5', 'rs q8', 'tt rs', 'tts',
    's3', 's4', 's5', 's6', 's7', 's8', 'sq5', 'sq7', 'sq8',
    # Audi normales
    'corolla cross', 'corolla', 'land cruiser', 'grand cherokee', 'santa fe',
    'a1', 'a3', 'a4', 'a5', 'a6', 'a7', 'a8', 'q2', 'q3', 'q5', 'q7', 'q8', 'tt',
    # BMW M y series
    'm135', 'm140', 'm235', 'm240', 'm340', 'm440', 'm550',
    'm2', 'm3', 'm4', 'm5', 'm6', 'm8',
    'serie 1', 'serie 2', 'serie 3', 'serie 4', 'serie 5',
    '116', '118', '120', '125', '130',
    '218', '220', '228', '230',
    '318', '320', '325', '328', '330', '335', '340',
    '420', '428', '430', '435', '440',
    '520', '523', '525', '528', '530', '535', '540',
    'x1', 'x2', 'x3', 'x4', 'x5', 'x6', 'x7',
    # Mercedes AMG
    'amg gt', 'a45', 'cla45', 'c43', 'c63', 'e43', 'e53', 'e63', 'gle63', 'glc63',
    'clase a', 'clase c', 'clase e',
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
    # Nissan
    'gt-r', 'gtr', 'nismo',
    'march', 'versa', 'sentra', 'kicks', 'x-trail', 'xtrail', 'note', 'frontier',
    # Mazda
    'mazda2', 'mazda3', 'mazda6', 'cx-3', 'cx3', 'cx-5', 'cx5', 'cx-9', 'cx9',
    # Citroen
    'c3', 'c4', 'c5', 'berlingo', 'xsara',
    # Jeep
    'renegade', 'compass', 'wrangler', 'gladiator',
    # Chevrolet
    'onix', 'tracker', 'cruze', 'equinox', 's10', 'spin',
    # Ford (incluyendo ST/RS)
    'focus rs', 'focus st', 'fiesta st', 'mustang gt',
    'focus', 'ecosport', 'ranger', 'territory', 'kuga', 'maverick', 'bronco',
    # Chinos
    'tiggo', 'jolion', 'h6', 'dolphin', 'song', 'yuan', 'atto',
]

def normalize_brand(brand):
    b = brand.lower().strip()
    return BRANDS_NORMALIZE.get(b, b).replace(' ', '_').replace('-', '_')

def find_brand_in_text(text):
    t = text.lower()
    for b in KNOWN_BRANDS:
        if b in t:
            return normalize_brand(b)
    return None

def find_model_in_text(text):
    t = text.lower()
    for m in KNOWN_MODELS:
        if m in t:
            return m.replace(' ', '_').replace('-', '_')
    return None

# Trims que afectan precio significativamente
TRIMS = [
    'amg line', 'm sport', 'm-sport', 'r line', 'r-line', 'n line', 'n-line',
    'gt line', 'gt-line', 'st line', 'st-line', 's line', 's-line',
    'sport', 'sportback', 'sportline', 'avantgarde', 'progressive', 'exclusive',
    'gti', 'gtd', 'gts', 'rs', 'st', 'gt',
    'highline', 'comfortline', 'trendline',
    'titanium', 'limited', 'platinum', 'premium', 'luxury',
    'ultimate', 'top', 'tope de gama',
    'xei', 'xls', 'xlt',
    'awd', '4x4', 'quattro', 'xdrive', '4motion', '4matic',
    'cabrio', 'coupe', 'sedan', 'hatchback',
]

def find_trim(text):
    if not text: return None
    t = text.lower()
    found = [trim for trim in TRIMS if trim in t]
    if not found: return None
    found.sort(key=len, reverse=True)
    return found[0].replace(' ', '_').replace('-', '_')

def make_model_key(brand, model, year, trim=None):
    b = brand or 'other'
    m = model or 'other'
    base = f"{b}_{m}_{year}"
    if trim:
        base += f"_{trim}"
    return base

# ─── ROSARIO GARAGE ───────────────────────────────────────────────────────────

def scrape_rg(marca, paginas=5):
    listings = []
    base_urls = [
        f"https://www.rosariogarage.com/Autos/{marca}",
        f"https://www.rosariogarage.com/autos/{marca}",
        f"https://www.rosariogarage.com/Autos/{marca.capitalize()}",
    ]

    url_ok = None
    for bu in base_urls:
        html = fetch(bu)
        if html and len(html) > 1000:
            url_ok = bu
            break
        time.sleep(0.5)

    if not url_ok:
        print(f"  RG {marca}: no se pudo acceder")
        return []

    for page in range(1, paginas + 1):
        url = url_ok if page == 1 else f"{url_ok}?page={page}"
        html_bytes = fetch(url)
        if not html_bytes:
            break

        html = None
        for enc in ['utf-8', 'latin-1', 'iso-8859-1']:
            try:
                html = html_bytes.decode(enc, errors='ignore')
                break
            except Exception:
                continue
        if not html:
            break

        parsed = _parse_rg_html(html, marca)
        listings.extend(parsed)
        print(f"  RG {marca} p{page}: {len(parsed)}")
        if len(parsed) == 0:
            break
        time.sleep(random.uniform(1.0, 2.5))

    return listings

def _parse_rg_html(html, marca_search):
    listings = []
    blocks = html.split('data-rel="')
    for block in blocks[1:]:
        item = _parse_rg_block(block, marca_search)
        if item:
            listings.append(item)
    return listings

def _parse_rg_block(block, marca_search):
    try:
        id_m = re.match(r'^(\d+)"', block)
        if not id_m:
            return None
        item_id = id_m.group(1)
        chunk = block[:5000]

        # Title
        title = None
        for pat in [
            r'class="list_type_anuncio">([^<]+)<',
            r'class="[^"]*titulo[^"]*">([^<]+)<',
            r'<h2[^>]*>([^<]+)<',
            r'alt="([^"]{10,80})"',
        ]:
            m = re.search(pat, chunk)
            if m:
                t = m.group(1).replace('...', '').strip()
                if len(t) > 3:
                    title = t
                    break
        if not title:
            return None

        # Year
        year_m = re.search(r'>(20\d{2}|19\d{2})</span>', chunk) or re.search(r'\b(20\d{2}|19[89]\d)\b', chunk)
        if not year_m:
            return None
        year = int(year_m.group(1))
        if year < 1990 or year > 2027:
            return None

        # KM
        km_m = re.search(r'>([\d.]+)\s*[Kk][Mm][\.<]', chunk) or re.search(r'([\d.]+)\s*km', chunk, re.I)
        km = int(km_m.group(1).replace('.', '')) if km_m else 0
        if km > 600000:
            return None

        # Trans
        trans_m = re.search(r'>(AT|MT)<', chunk)
        trans = trans_m.group(1) if trans_m else '?'

        # Fuel
        fuel_m = re.search(r'>(Nafta|Diesel|GNC|Eléctrico|Híbrido|Electrico|Hibrido)<', chunk, re.I)
        fuel = fuel_m.group(1) if fuel_m else '?'

        # Precio: buscar TODOS los precios y elegir el más razonable
        precio_usd = _parse_rg_price(chunk)
        if not precio_usd:
            return None

        if not is_realistic_price(precio_usd, year):
            return None

        # Marca + modelo: probar título primero, luego asumir marca de URL
        brand = find_brand_in_text(title) or normalize_brand(marca_search)
        model = find_model_in_text(title)
        trim = find_trim(title)

        full_title = title[:80]

        return {
            'id': item_id,
            'url': f"https://www.rosariogarage.com/index.php?action=carro/showProduct&itmId={item_id}",
            'title': full_title,
            'brand': brand,
            'model': model,
            'year': year, 'km': km,
            'fuel': fuel, 'trans': trans,
            'precio_usd': precio_usd,
            'fuente': 'rg',
            'trim': trim,
            'model_key': make_model_key(brand, model, year, trim),
        }
    except Exception:
        return None

def _parse_rg_price(chunk):
    """Busca precio en RG. Prioriza USD explícito; si no, descarta."""
    # 1) U$S explícito
    m = re.search(r'U\$S\s*([\d.,]+)', chunk, re.I)
    if m:
        p, _ = parse_price_smart('U$S ' + m.group(1), currency_hint='USD')
        if p:
            return p

    # 2) Bloque "precio" típico
    m = re.search(r'class="precio[^"]*">\s*<a[^>]*>\s*([^\n<]+)', chunk, re.I)
    if m:
        raw = m.group(1).strip()
        if 'consultar' not in raw.lower():
            p, _ = parse_price_smart(raw)
            if p:
                return p

    # 3) USD plano
    m = re.search(r'USD\s*([\d.,]+)', chunk, re.I)
    if m:
        p, _ = parse_price_smart('USD ' + m.group(1), currency_hint='USD')
        if p:
            return p

    return 0

# ─── AUTOCOSMOS ───────────────────────────────────────────────────────────────

def scrape_ac(marca, paginas=5):
    listings = []
    marca_url = marca.lower().replace(' ', '-').replace('_', '-')

    for page in range(1, paginas + 1):
        url = f"https://www.autocosmos.com.ar/auto/usado/{marca_url}"
        if page > 1:
            url += f"?p={page}"

        html_bytes = fetch(url)
        if not html_bytes:
            break

        html = html_bytes.decode('utf-8', errors='ignore')
        if not html or len(html) < 500:
            break

        parsed = _parse_ac_html(html, marca)
        listings.extend(parsed)
        print(f"  AC {marca} p{page}: {len(parsed)}")
        if len(parsed) == 0:
            break
        time.sleep(random.uniform(1.5, 3.0))

    return listings

def _parse_ac_html(html, marca_search):
    listings = []
    blocks = re.split(r'<article', html)
    for block in blocks[1:]:
        item = _parse_ac_block(block, marca_search)
        if item:
            listings.append(item)
    return listings

def _parse_ac_block(block, marca_search):
    try:
        chunk = block[:4000]

        # FILTRO CRÍTICO: descartar autos financiados (solo muestran anticipo, no precio total)
        chunk_lower = chunk.lower()
        if 'anticipo' in chunk_lower or 'financiado en cuotas' in chunk_lower or 'financiados' in chunk_lower:
            return None

        # URL del listing -- de acá sacamos marca y modelo confiable
        url_m = re.search(r'href="(/auto/usado/[^"?#]+)"', chunk)
        if not url_m:
            return None
        rel_url = url_m.group(1)
        # rel_url típico: /auto/usado/volkswagen/polo/13l-drive/abc123
        url_parts = [p for p in rel_url.split('/') if p]
        # ['auto', 'usado', 'marca', 'modelo', 'version', 'hash']
        url_brand = url_parts[2] if len(url_parts) > 2 else None
        url_model = url_parts[3] if len(url_parts) > 3 else None
        url_version = url_parts[4] if len(url_parts) > 4 else ''

        item_id = 'ac_' + re.sub(r'[^a-z0-9]', '_', rel_url)[:50]

        # Year
        year_m = re.search(r'\((\d{4})\)', chunk) or re.search(r'\b(20\d{2})\b', chunk)
        if not year_m:
            return None
        year = int(year_m.group(1))
        if year < 1990 or year > 2027:
            return None

        # Title -- combinar info del URL para que siempre tenga marca
        title_m = (re.search(r'title="([^"]{5,120})"', chunk) or
                   re.search(r'<h2[^>]*>([^<]{5,120})<', chunk) or
                   re.search(r'alt="([^"]{5,120})"', chunk))
        raw_title = title_m.group(1).strip() if title_m else ''

        if url_brand and url_model:
            full_title = f"{url_brand.capitalize()} {url_model.replace('-', ' ').title()} {url_version.replace('-', ' ').title()}".strip()[:80]
        else:
            full_title = raw_title[:80] or 'Auto usado'

        # PRECIO: enfoque robusto -- juntar TODOS los matches y elegir el más sano
        precio_usd = _parse_ac_price(chunk, year)
        if not precio_usd:
            return None

        # KM
        km_m = re.search(r'([\d.]+)\s*km', chunk, re.I)
        km = int(km_m.group(1).replace('.', '')) if km_m else 0
        if km > 600000:
            return None

        # Trans
        trans = 'AT' if re.search(r'autom|s.tronic|cvt|tiptronic|direct.shift|dsg', chunk, re.I) else '?'

        # Brand/model -- preferir URL (más confiable que título)
        brand = normalize_brand(url_brand) if url_brand else find_brand_in_text(full_title)
        if not brand:
            brand = normalize_brand(marca_search)
        model = find_model_in_text(url_model or '') or find_model_in_text(full_title)
        if not model and url_model:
            model = url_model.split('-')[0].lower()
        trim = find_trim(full_title)

        return {
            'id': item_id,
            'url': f"https://www.autocosmos.com.ar{rel_url}",
            'title': full_title,
            'brand': brand,
            'model': model,
            'year': year, 'km': km,
            'fuel': '?', 'trans': trans,
            'precio_usd': precio_usd,
            'fuente': 'ac',
            'trim': trim,
            'model_key': make_model_key(brand, model, year, trim),
        }
    except Exception:
        return None

def _parse_ac_price(chunk, year):
    """
    Solo aceptamos precios con marca explícita 'u$s' / 'usd'.
    Cualquier otro número (anticipos, cuotas, etc) se descarta.
    """
    candidates = []

    # 1) U$S explícito (única fuente confiable)
    for m in re.finditer(r'u\$s\s*([\d.,]+)', chunk, re.I):
        # Verificar que no esté en contexto de anticipo
        start = max(0, m.start() - 60)
        context = chunk[start:m.start()].lower()
        if 'anticipo' in context or 'cuota' in context:
            continue
        val = re.sub(r'[^\d]', '', m.group(1))
        if val:
            n = int(val)
            if 1500 <= n <= 500000:
                candidates.append(n)

    # 2) USD explícito
    for m in re.finditer(r'\busd\s*([\d.,]+)', chunk, re.I):
        start = max(0, m.start() - 60)
        context = chunk[start:m.start()].lower()
        if 'anticipo' in context or 'cuota' in context:
            continue
        val = re.sub(r'[^\d]', '', m.group(1))
        if val:
            n = int(val)
            if 1500 <= n <= 500000:
                candidates.append(n)

    # 3) Meta itemprop=price (a veces lo tienen, suele ser confiable si NO hay anticipo)
    if not candidates and 'anticipo' not in chunk.lower():
        for pat in [
            r'itemprop="price"[^>]*content="([\d.,]+)"',
            r'content="([\d.,]+)"[^>]*itemprop="price"',
        ]:
            for m in re.finditer(pat, chunk, re.I):
                val = re.sub(r'[^\d]', '', m.group(1))
                if val:
                    n = int(val)
                    if 1500 <= n <= 500000:
                        candidates.append(n)
                    elif n > 500000:
                        candidates.append(round(n / BLUE_RATE))

    if not candidates:
        return 0

    realistic = [c for c in candidates if is_realistic_price(c, year)]
    if not realistic:
        return 0

    realistic.sort()
    return realistic[len(realistic) // 2]

# ─── MERCADO LIBRE (carga desde ml_listings.json subido manualmente) ──────────
# La API de ML bloquea desde GitHub Actions (datacenter IP).
# Solución: corremos `ml_local.py` en una Mac y subimos ml_listings.json al repo.
# Acá lo cargamos y combinamos con RG/AC.

def load_ml_listings():
    """Carga ml_listings.json si existe en el repo. Devuelve lista de listings."""
    path = 'ml_listings.json'
    if not os.path.exists(path):
        print(f"  ML: {path} no existe (skip)")
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        listings = data.get('listings', [])
        updated = data.get('updated', 'desconocido')
        # Avisar si los datos son muy viejos (> 14 días)
        try:
            d = datetime.fromisoformat(updated.replace('Z', '+00:00'))
            age_days = (datetime.utcnow().replace(tzinfo=d.tzinfo) - d).days
            print(f"  ML: cargado de archivo ({len(listings)} listings, {age_days}d de antigüedad)")
            if age_days > 14:
                print(f"  ⚠️  ML data desactualizada ({age_days} días). Ejecutá ml_local.py y subí ml_listings.json")
        except Exception:
            print(f"  ML: cargado ({len(listings)} listings, fecha {updated})")
        return listings
    except Exception as e:
        print(f"  ML: error leyendo {path}: {e}")
        return []

# ─── KAVAK (carga desde kavak_listings.json subido manualmente) ───────────────
# Kavak tampoco se puede scrapear desde GitHub Actions (bloquea datacenters).
# Corremos kavak_local.py en la Mac y subimos kavak_listings.json al repo.

def load_kavak_listings():
    """Carga kavak_listings.json si existe. Devuelve lista de listings."""
    path = 'kavak_listings.json'
    if not os.path.exists(path):
        print(f"  KV: {path} no existe (skip)")
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        listings = data.get('listings', [])
        updated = data.get('updated', 'desconocido')
        try:
            d = datetime.fromisoformat(updated.replace('Z', '+00:00'))
            age_days = (datetime.utcnow().replace(tzinfo=d.tzinfo) - d).days
            print(f"  KV: cargado de archivo ({len(listings)} listings, {age_days}d de antigüedad)")
            if age_days > 14:
                print(f"  ⚠️  KV data desactualizada ({age_days} días). Ejecutá kavak_local.py y subí kavak_listings.json")
        except Exception:
            print(f"  KV: cargado ({len(listings)} listings, fecha {updated})")
        return listings
    except Exception as e:
        print(f"  KV: error leyendo {path}: {e}")
        return []

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    all_listings = []

    # Cargar histórico para preservar first_seen y price_history
    import os
    first_seen_map = {}
    price_history_map = {}
    prev = {}
    prev_by_id = {}
    today_iso = datetime.utcnow().date().isoformat()
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
                prev = json.load(f)
            for l in prev.get('listings', []):
                lid = l.get('id')
                if lid:
                    first_seen_map[lid] = l.get('first_seen', today_iso)
                    if l.get('price_history'):
                        price_history_map[lid] = l['price_history']
                    prev_by_id[lid] = l
            print(f"  ↺ Cargado histórico: {len(first_seen_map)} listings, {len(price_history_map)} con price history")
        except Exception as e:
            print(f"  (no pude leer histórico: {e})")

    marcas = [
        'audi', 'toyota', 'volkswagen', 'ford', 'chevrolet',
        'peugeot', 'renault', 'honda', 'fiat', 'bmw',
        'mercedes-benz', 'hyundai', 'kia', 'nissan', 'mazda',
        'citroen', 'jeep', 'mitsubishi', 'subaru', 'chery', 'haval', 'byd',
    ]

    stats = {'rg': 0, 'ac': 0, 'ml': 0, 'kv': 0}

    print("=" * 50)
    print("Scraping RosarioGarage...")
    print("=" * 50)
    for marca in marcas:
        results = scrape_rg(marca, paginas=5)
        all_listings.extend(results)
        stats['rg'] += len(results)
        print(f"  >> RG {marca}: {len(results)} total")
        time.sleep(random.uniform(2.0, 4.0))

    print("=" * 50)
    print("Scraping Autocosmos...")
    print("=" * 50)
    for marca in marcas:
        results = scrape_ac(marca, paginas=5)
        all_listings.extend(results)
        stats['ac'] += len(results)
        print(f"  >> AC {marca}: {len(results)} total")
        time.sleep(random.uniform(2.0, 4.0))

    print("=" * 50)
    print("Cargando MercadoLibre desde ml_listings.json...")
    print("=" * 50)
    ml_results = load_ml_listings()
    all_listings.extend(ml_results)
    stats['ml'] = len(ml_results)
    print(f"  >> ML: {len(ml_results)} total")

    print("=" * 50)
    print("Cargando Kavak desde kavak_listings.json...")
    print("=" * 50)
    kv_results = load_kavak_listings()
    all_listings.extend(kv_results)
    stats['kv'] = len(kv_results)
    print(f"  >> KV: {len(kv_results)} total")

    print(f"\nStats brutos: RG={stats['rg']} AC={stats['ac']} ML={stats['ml']} KV={stats['kv']}")

    # Dedup
    seen = set()
    unique = []
    for l in all_listings:
        if l['id'] not in seen:
            seen.add(l['id'])
            unique.append(l)

    print(f"Total único: {len(unique)}")

    # Filtros finales de calidad
    before = len(unique)
    unique = [l for l in unique if is_realistic_price(l.get('precio_usd', 0), l.get('year', 0))]
    print(f"Post-filtro precio: {len(unique)} (descartados: {before - len(unique)})")

    # Aplicar first_seen y price_history
    for l in unique:
        lid = l.get('id')
        l['first_seen'] = first_seen_map.get(lid, today_iso)
        l['is_new'] = (l['first_seen'] == today_iso)

        prev_history = price_history_map.get(lid, [])
        precio = l.get('precio_usd', 0)
        if not prev_history:
            l['price_history'] = [{'fecha': today_iso, 'precio_usd': precio}]
            l['price_changed'] = False
            l['price_drops'] = 0
            l['price_drop_pct'] = 0
            l['recent_price_drop'] = False
            l['recent_drop_pct'] = 0
        else:
            last_price = prev_history[-1]['precio_usd']
            if precio != last_price:
                l['price_history'] = prev_history + [{'fecha': today_iso, 'precio_usd': precio}]
                l['price_changed'] = True
            else:
                l['price_history'] = prev_history
                l['price_changed'] = False
            # Drops y bajada total
            hist = l['price_history']
            drops = sum(1 for k in range(1, len(hist)) if hist[k]['precio_usd'] < hist[k-1]['precio_usd'])
            l['price_drops'] = drops
            initial = hist[0]['precio_usd']
            l['price_drop_pct'] = round((1 - precio / initial) * 100, 1) if initial > 0 else 0
            # Movimiento del último run: solo cuenta si bajó (no subió)
            is_drop = precio > 0 and last_price > 0 and precio < last_price
            l['recent_price_drop'] = is_drop
            l['recent_drop_pct'] = round((1 - precio / last_price) * 100, 1) if is_drop else 0

    fuentes = {}
    marcas_count = {}
    for l in unique:
        fuentes[l.get('fuente', '?')] = fuentes.get(l.get('fuente', '?'), 0) + 1
        b = l.get('brand', 'other')
        marcas_count[b] = marcas_count.get(b, 0) + 1

    nuevas_hoy = sum(1 for l in unique if l.get('is_new'))
    bajaron_hoy = sum(1 for l in unique if l.get('recent_price_drop'))

    # ─── Detectar listings desaparecidos → fast_sales.json ──────────────────
    # Un listing que estuvo en el run anterior pero no en éste probablemente se vendió.
    # Si vivió poco (<=30 días), es señal de buen precio.
    current_ids = {l['id'] for l in unique}
    disappeared = [l for l in prev_by_id.values() if l['id'] not in current_ids]

    # Sanity check: si desapareció >30% del catálogo, fue scraper hiccup, no ventas
    prev_count = len(prev_by_id)
    skip_fast_sales = (
        prev_count > 0 and len(disappeared) / prev_count > 0.30
    )
    if skip_fast_sales:
        print(f"  ⚠️  {len(disappeared)} desaparecieron ({100*len(disappeared)/prev_count:.0f}% del catálogo previo) — probable scraper hiccup, no se registran fast_sales este run")

    FAST_SALES_FILE = 'fast_sales.json'
    fast_sales = []
    if os.path.exists(FAST_SALES_FILE):
        try:
            with open(FAST_SALES_FILE, 'r', encoding='utf-8') as f:
                fast_sales = json.load(f).get('events', [])
        except Exception as e:
            print(f"  (no pude leer fast_sales.json: {e})")

    new_events = 0
    if not skip_fast_sales:
        existing_ids = {e['id'] for e in fast_sales}
        today_dt = datetime.utcnow().date()
        for d in disappeared:
            lid = d.get('id')
            if not lid or lid in existing_ids:
                continue
            first_seen = d.get('first_seen')
            if not first_seen:
                continue
            try:
                days_lived = (today_dt - datetime.fromisoformat(first_seen).date()).days
            except Exception:
                continue
            # Skip: just appeared today (likely scraper miss), or stale (>30d = not a fast sale)
            if days_lived < 1 or days_lived > 30:
                continue
            if not d.get('precio_usd') or not d.get('model_key'):
                continue
            fast_sales.append({
                'id': lid,
                'model_key': d.get('model_key'),
                'brand': d.get('brand'),
                'model': d.get('model'),
                'year': d.get('year'),
                'last_price_usd': d.get('precio_usd'),
                'first_seen': first_seen,
                'last_seen_at': prev.get('updated', today_iso),
                'days_lived': days_lived,
                'fuente': d.get('fuente'),
            })
            new_events += 1

    # Prune: rolling 90 días
    cutoff = datetime.utcnow().date() - timedelta(days=90)
    def _keep(e):
        last = (e.get('last_seen_at') or '')
        try:
            return datetime.fromisoformat(last.replace('Z', '+00:00')).date() >= cutoff
        except Exception:
            return True
    fast_sales = [e for e in fast_sales if _keep(e)]

    with open(FAST_SALES_FILE, 'w', encoding='utf-8') as f:
        json.dump({
            'updated': datetime.utcnow().isoformat() + 'Z',
            'count': len(fast_sales),
            'events': fast_sales,
        }, f, ensure_ascii=False, indent=2)
    print(f"  Fast sales: +{new_events} nuevas, {len(fast_sales)} total (rolling 90d)")

    # ─── velocity_stats.json: estadísticas por model_key ────────────────────
    # Per modelo: cuántos vendieron rápido, mediana de días vividos, mediana del precio de venta.
    # El Worker usa esto como prior bayesiano para mejorar la detección.
    by_model = {}
    for e in fast_sales:
        mk = e.get('model_key')
        if mk:
            by_model.setdefault(mk, []).append(e)

    def _median(arr):
        s = sorted(arr)
        return s[len(s) // 2]

    velocity_stats = {}
    for mk, events in by_model.items():
        if len(events) < 3:
            continue
        days = [e['days_lived'] for e in events]
        prices = [e['last_price_usd'] for e in events if e.get('last_price_usd')]
        velocity_stats[mk] = {
            'n': len(events),
            'median_days_lived': _median(days),
            'p25_days_lived': sorted(days)[max(0, len(days) // 4)],
            'median_sale_price_usd': _median(prices) if prices else None,
        }

    with open('velocity_stats.json', 'w', encoding='utf-8') as f:
        json.dump({
            'updated': datetime.utcnow().isoformat() + 'Z',
            'count': len(velocity_stats),
            'stats': velocity_stats,
        }, f, ensure_ascii=False, indent=2)
    print(f"  Velocity stats: {len(velocity_stats)} model_keys con ≥3 fast sales")

    output = {
        'updated': datetime.utcnow().isoformat() + 'Z',
        'total': len(unique),
        'nuevas_hoy': nuevas_hoy,
        'bajaron_hoy': bajaron_hoy,
        'fuentes': fuentes,
        'marcas': marcas_count,
        'listings': unique,
    }

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✓ listings.json: {len(unique)} autos")
    print(f"  Fuentes: {fuentes}")
    print(f"  Nuevas hoy: {nuevas_hoy} · Bajaron hoy: {bajaron_hoy}")
    print(f"  Top marcas: {dict(sorted(marcas_count.items(), key=lambda x: -x[1])[:10])}")


if __name__ == '__main__':
    main()
