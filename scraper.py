import json
import re
import time
import random
import urllib.request
from datetime import datetime

BLUE_RATE = 1290
OUTPUT_FILE = "listings.json"
CCA_FILE = "cca_precios.json"
CCA_PDF_URL = "https://www.cca.org.ar/descargas/precios/Autos.pdf"

HEADERS_LIST = [
    {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
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

def fetch(url, headers=None, retries=3, delay=2):
    if headers is None:
        headers = random.choice(HEADERS_LIST)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as r:
                content = r.read()
                # Handle gzip
                if r.info().get('Content-Encoding') == 'gzip':
                    import gzip
                    content = gzip.decompress(content)
                return content
        except Exception as e:
            print(f"  [fetch] Error intento {attempt+1}/{retries} {url[:80]}: {e}")
            if attempt < retries - 1:
                time.sleep(delay * (attempt + 1))
    return b""

def parse_price(raw):
    if not raw or 'consultar' in raw.lower():
        return 0
    raw = raw.strip()
    num_str = re.sub(r'[^\d]', '', raw)
    if not num_str:
        return 0
    num = int(num_str)
    if not num:
        return 0
    if re.search(r'u\$s|usd|\$\s*u', raw, re.I):
        return num if num < 500000 else round(num / BLUE_RATE)
    # ARS
    if num > 5000000:
        return round(num / BLUE_RATE)
    if num > 500:
        return round(num / BLUE_RATE)
    return 0

def extract_model_key(title, year):
    t = title.lower()
    brands = [
        'mercedes benz', 'mercedes-benz', 'mercedes',
        'audi', 'toyota', 'volkswagen', 'ford', 'chevrolet',
        'peugeot', 'renault', 'honda', 'fiat', 'bmw',
        'hyundai', 'kia', 'nissan', 'mazda', 'citroen',
        'jeep', 'mitsubishi', 'subaru', 'chery', 'haval', 'byd',
    ]
    brand = 'other'
    for b in brands:
        if b in t:
            brand = b.replace(' ', '_').replace('-', '_')
            break

    models = [
        'corolla cross', 'corolla',
        'a1', 'a3', 'a4', 'a5', 'a6', 'q2', 'q3', 'q5', 'q7', 'tt',
        'yaris', 'hilux', 'rav4', 'sw4', 'chr', 'c-hr', 'etios', 'fortuner', 'prius',
        'polo', 'golf', 'vento', 'tiguan', 'amarok', 'taos', 'nivus', 'virtus', 'saveiro',
        '208', '308', '2008', '3008', '408', '508',
        'clio', 'sandero', 'duster', 'logan', 'kwid', 'captur', 'arkana', 'oroch',
        'fit', 'civic', 'hr-v', 'hrv', 'cr-v', 'crv', 'wr-v', 'wrv', 'accord',
        'cronos', 'argo', 'pulse', 'fastback', 'mobi', 'toro', 'strada',
        'serie 1', 'serie 2', 'serie 3', 'serie 4', 'serie 5',
        'x1', 'x2', 'x3', 'x4', 'x5',
        'clase a', 'clase c', 'clase e', 'gla', 'glb', 'glc',
        'tucson', 'santa fe', 'creta', 'venue', 'i30',
        'cerato', 'sportage', 'sorento', 'seltos', 'stinger', 'rio', 'picanto',
        'march', 'versa', 'sentra', 'kicks', 'x-trail', 'xtrail', 'note', 'frontier',
        'mazda2', 'mazda3', 'mazda6', 'cx-3', 'cx3', 'cx-5', 'cx5', 'cx-9', 'cx9',
        'c3', 'c4', 'c5', 'berlingo', 'xsara',
        'renegade', 'compass', 'wrangler', 'gladiator', 'grand cherokee',
        'onix', 'tracker', 'cruze', 'equinox', 's10', 'spin',
        'focus', 'ecosport', 'ranger', 'territory', 'kuga', 'maverick', 'bronco',
    ]
    model = 'other'
    for m in models:
        if m in t:
            model = m.replace(' ', '_').replace('-', '')
            break

    year_pair = (year // 2) * 2
    return f"{brand}_{model}_{year_pair}"

# ─── ROSARIO GARAGE ───────────────────────────────────────────────────────────

def scrape_rg(marca, paginas=5):
    listings = []
    # Intentar con distintos formatos de URL
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

        # Intentar distintos encodings
        html = None
        for enc in ['utf-8', 'latin-1', 'iso-8859-1']:
            try:
                html = html_bytes.decode(enc, errors='ignore')
                break
            except Exception:
                continue

        if not html:
            break

        parsed_page = _parse_rg_html(html, marca)
        listings.extend(parsed_page)
        print(f"  RG {marca} p{page}: {len(parsed_page)} listings")

        if len(parsed_page) == 0:
            break

        time.sleep(random.uniform(1.0, 2.5))

    return listings

def _parse_rg_html(html, marca):
    listings = []

    # Método 1: data-rel split (original)
    blocks = html.split('data-rel="')
    if len(blocks) > 1:
        for block in blocks[1:]:
            item = _parse_rg_block(block)
            if item:
                listings.append(item)

    # Método 2: buscar por itmId si el método 1 no encontró nada
    if not listings:
        ids = re.findall(r'itmId=(\d+)', html)
        seen = set()
        for item_id in ids:
            if item_id in seen:
                continue
            seen.add(item_id)
            # Encontrar el bloque alrededor de ese id
            idx = html.find(f'itmId={item_id}')
            if idx == -1:
                continue
            chunk = html[max(0, idx-500):idx+3000]
            item = _parse_rg_block_by_id(chunk, item_id)
            if item:
                listings.append(item)

    return listings

def _parse_rg_block(block):
    try:
        id_m = re.match(r'^(\d+)"', block)
        if not id_m:
            return None
        item_id = id_m.group(1)
        chunk = block[:5000]

        # Title - múltiples patrones
        title = None
        for pat in [
            r'class="list_type_anuncio">([^<]+)<',
            r'class="[^"]*titulo[^"]*">([^<]+)<',
            r'<h2[^>]*>([^<]+)<',
            r'alt="([^"]{10,60})"',
        ]:
            m = re.search(pat, chunk)
            if m:
                title = m.group(1).replace('...', '').strip()
                if len(title) > 3:
                    break

        if not title:
            return None

        # Year
        year_m = re.search(r'>(20\d{2}|19\d{2})</span>', chunk)
        if not year_m:
            year_m = re.search(r'\b(20\d{2}|19[89]\d)\b', chunk)
        if not year_m:
            return None
        year = int(year_m.group(1))
        if year < 1990 or year > 2027:
            return None

        # KM
        km_m = re.search(r'>([\d.]+)\s*[Kk][Mm][\.<]', chunk)
        if not km_m:
            km_m = re.search(r'([\d.]+)\s*km', chunk, re.I)
        km = int(km_m.group(1).replace('.', '')) if km_m else 0
        if km > 600000:
            return None

        # Transmisión
        trans_m = re.search(r'\b(AT|MT)\b', chunk)
        trans = trans_m.group(1) if trans_m else '?'

        # Combustible
        fuel_m = re.search(r'>(Nafta|Diesel|GNC|Eléctrico|Híbrido|Electrico|Hibrido)<', chunk, re.I)
        fuel = fuel_m.group(1) if fuel_m else '?'

        # Precio - múltiples patrones
        precio_usd = 0
        price_patterns = [
            r'class="precio[^"]*">\s*<a[^>]*>\s*([^\n<]+)',
            r'U\$S\s*([\d.,]+)',
            r'USD\s*([\d.,]+)',
            r'\$\s*([\d.,]+)',
            r'class="[^"]*price[^"]*"[^>]*>\s*([^\n<]+)',
        ]
        for pat in price_patterns:
            m = re.search(pat, chunk, re.I)
            if m:
                raw = m.group(1).strip()
                if 'consultar' in raw.lower():
                    continue
                precio_usd = parse_price(raw)
                if precio_usd:
                    break

        if not precio_usd or precio_usd < 500:
            return None

        return {
            'id': item_id,
            'url': f"https://www.rosariogarage.com/index.php?action=carro/showProduct&itmId={item_id}",
            'title': title[:60],
            'year': year, 'km': km,
            'fuel': fuel, 'trans': trans,
            'precio_usd': precio_usd,
            'fuente': 'rg',
            'model_key': extract_model_key(title, year)
        }
    except Exception as e:
        return None

def _parse_rg_block_by_id(chunk, item_id):
    try:
        title_m = re.search(r'(?:title|alt)="([^"]{5,60})"', chunk)
        if not title_m:
            return None
        title = title_m.group(1).strip()

        year_m = re.search(r'\b(20\d{2}|19[89]\d)\b', chunk)
        if not year_m:
            return None
        year = int(year_m.group(1))

        km_m = re.search(r'([\d.]+)\s*km', chunk, re.I)
        km = int(km_m.group(1).replace('.', '')) if km_m else 0

        price_m = re.search(r'U\$S\s*([\d.,]+)', chunk, re.I) or re.search(r'\$([\d.,]+)', chunk)
        if not price_m:
            return None
        precio_usd = parse_price(price_m.group(0))
        if not precio_usd:
            return None

        return {
            'id': item_id,
            'url': f"https://www.rosariogarage.com/index.php?action=carro/showProduct&itmId={item_id}",
            'title': title[:60],
            'year': year, 'km': km,
            'fuel': '?', 'trans': '?',
            'precio_usd': precio_usd,
            'fuente': 'rg',
            'model_key': extract_model_key(title, year)
        }
    except Exception:
        return None

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

        parsed_page = _parse_ac_html(html)
        listings.extend(parsed_page)
        print(f"  AC {marca} p{page}: {len(parsed_page)} listings")

        if len(parsed_page) == 0:
            break

        time.sleep(random.uniform(1.5, 3.0))

    return listings

def _parse_ac_html(html):
    listings = []

    # Método 1: por article tags
    blocks = re.split(r'<article', html)
    for block in blocks[1:]:
        item = _parse_ac_block(block)
        if item:
            listings.append(item)

    # Método 2: buscar links de autos usados si método 1 falla
    if not listings:
        urls_found = re.findall(r'href="(/auto/usado/[^"?#]{10,})"', html)
        seen_urls = set()
        for rel_url in urls_found:
            if rel_url in seen_urls:
                continue
            seen_urls.add(rel_url)
            idx = html.find(rel_url)
            if idx == -1:
                continue
            chunk = html[max(0, idx-200):idx+2000]
            item = _parse_ac_chunk(chunk, rel_url)
            if item:
                listings.append(item)

    return listings

def _parse_ac_block(block):
    try:
        chunk = block[:3000]

        url_m = re.search(r'href="(/auto/usado/[^"?#]+)"', chunk)
        if not url_m:
            return None
        rel_url = url_m.group(1)
        item_id = 'ac_' + re.sub(r'[^a-z0-9]', '_', rel_url)[:50]

        # Year
        year_m = re.search(r'\((\d{4})\)', chunk)
        if not year_m:
            year_m = re.search(r'\b(20\d{2})\b', chunk)
        if not year_m:
            return None
        year = int(year_m.group(1))
        if year < 1990 or year > 2027:
            return None

        # Title
        title_m = (re.search(r'title="([^"]{5,80})"', chunk) or
                   re.search(r'<h2[^>]*>([^<]{5,80})<', chunk) or
                   re.search(r'alt="([^"]{5,80})"', chunk))
        title = title_m.group(1).strip()[:60] if title_m else rel_url.split('/')[-2][:40].replace('-', ' ').title()

        # Price - buscar USD primero, luego ARS
        precio_usd = 0
        usd_m = re.search(r'u\$s\s*([\d.,]+)', chunk, re.I)
        if usd_m:
            val = int(re.sub(r'[^\d]', '', usd_m.group(1)))
            precio_usd = val if val < 500000 else round(val / BLUE_RATE)
        else:
            # Buscar precio en content meta o en texto
            price_patterns = [
                r'"price"[^>]*content="([\d.,]+)"',
                r'content="([\d.,]+)"[^>]*itemprop="price"',
                r'class="[^"]*price[^"]*"[^>]*>\s*\$\s*([\d.,]+)',
                r'\$\s*([\d.,]+)',
            ]
            for pat in price_patterns:
                m = re.search(pat, chunk, re.I)
                if m:
                    val_str = re.sub(r'[^\d]', '', m.group(1))
                    if val_str:
                        val = int(val_str)
                        if val > 1000:
                            precio_usd = round(val / BLUE_RATE)
                            break

        if not precio_usd or precio_usd < 500:
            return None

        # KM
        km_m = re.search(r'([\d.]+)\s*km', chunk, re.I)
        km = int(km_m.group(1).replace('.', '')) if km_m else 0

        # Trans
        trans = 'AT' if re.search(r'autom|s.tronic|cvt|tiptronic|direct.shift', chunk, re.I) else '?'

        return {
            'id': item_id,
            'url': f"https://www.autocosmos.com.ar{rel_url}",
            'title': title,
            'year': year, 'km': km,
            'fuel': '?', 'trans': trans,
            'precio_usd': precio_usd,
            'fuente': 'ac',
            'model_key': extract_model_key(title, year)
        }
    except Exception:
        return None

def _parse_ac_chunk(chunk, rel_url):
    try:
        item_id = 'ac_' + re.sub(r'[^a-z0-9]', '_', rel_url)[:50]
        year_m = re.search(r'\b(20\d{2})\b', chunk)
        if not year_m:
            return None
        year = int(year_m.group(1))

        usd_m = re.search(r'u\$s\s*([\d.,]+)', chunk, re.I)
        if not usd_m:
            return None
        precio_usd = int(re.sub(r'[^\d]', '', usd_m.group(1)))
        if not precio_usd:
            return None

        title = rel_url.split('/')[-2].replace('-', ' ').title()[:60]
        km_m = re.search(r'([\d.]+)\s*km', chunk, re.I)
        km = int(km_m.group(1).replace('.', '')) if km_m else 0

        return {
            'id': item_id,
            'url': f"https://www.autocosmos.com.ar{rel_url}",
            'title': title,
            'year': year, 'km': km,
            'fuel': '?', 'trans': '?',
            'precio_usd': precio_usd,
            'fuente': 'ac',
            'model_key': extract_model_key(title, year)
        }
    except Exception:
        return None

# ─── DEMOTORES ────────────────────────────────────────────────────────────────

def scrape_demotores(marca, paginas=3):
    listings = []
    marca_url = marca.lower().replace(' ', '-').replace('_', '-')

    for page in range(1, paginas + 1):
        url = f"https://www.demotores.com.ar/autos-usados/{marca_url}"
        if page > 1:
            url += f"?page={page}"

        html_bytes = fetch(url)
        if not html_bytes:
            break

        html = html_bytes.decode('utf-8', errors='ignore')
        if not html or len(html) < 500:
            break

        parsed_page = _parse_dm_html(html)
        listings.extend(parsed_page)
        print(f"  DM {marca} p{page}: {len(parsed_page)} listings")

        if len(parsed_page) == 0:
            break

        time.sleep(random.uniform(1.5, 3.0))

    return listings

def _parse_dm_html(html):
    listings = []

    # Buscar links de autos
    url_pattern = r'href="(https://www\.demotores\.com\.ar/[^"]+/\d+/[^"]+)"'
    urls = re.findall(url_pattern, html)

    if not urls:
        # Intentar links relativos
        urls_rel = re.findall(r'href="(/[^"]*\d{5,}[^"]*)"', html)
        urls = [f"https://www.demotores.com.ar{u}" for u in urls_rel if 'auto' in u or 'usado' in u]

    seen = set()
    for item_url in urls:
        if item_url in seen:
            continue
        seen.add(item_url)

        idx = html.find(item_url.replace('https://www.demotores.com.ar', ''))
        if idx == -1:
            idx = html.find(item_url)
        if idx == -1:
            continue

        chunk = html[max(0, idx-500):idx+3000]

        year_m = re.search(r'\b(20\d{2}|19[89]\d)\b', chunk)
        if not year_m:
            continue
        year = int(year_m.group(1))
        if year < 1990 or year > 2027:
            continue

        title_m = (re.search(r'(?:title|alt)="([^"]{5,80})"', chunk) or
                   re.search(r'<h\d[^>]*>([^<]{5,80})<', chunk))
        if not title_m:
            continue
        title = title_m.group(1).strip()[:60]

        price_m = re.search(r'(?:USD|U\$S|\$)\s*([\d.,]+)', chunk, re.I)
        if not price_m:
            continue
        precio_usd = parse_price(price_m.group(0))
        if not precio_usd or precio_usd < 500:
            continue

        km_m = re.search(r'([\d.]+)\s*[Kk][Mm]', chunk)
        km = int(km_m.group(1).replace('.', '')) if km_m else 0

        trans = 'AT' if re.search(r'autom|cvt|tiptronic', chunk, re.I) else '?'

        item_id = 'dm_' + re.sub(r'[^a-z0-9]', '_', item_url.split('/')[-1])[:40]

        listings.append({
            'id': item_id,
            'url': item_url,
            'title': title,
            'year': year, 'km': km,
            'fuel': '?', 'trans': trans,
            'precio_usd': precio_usd,
            'fuente': 'dm',
            'model_key': extract_model_key(title, year)
        })

    return listings

# ─── CCA PDF ──────────────────────────────────────────────────────────────────

def parse_cca_pdf():
    import subprocess, sys, tempfile, os
    try:
        from pdfminer.high_level import extract_text
    except ImportError:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'pdfminer.six', '-q'])
        from pdfminer.high_level import extract_text

    print("Descargando PDF CCA...")
    pdf_data = fetch(CCA_PDF_URL)
    if not pdf_data:
        print("No se pudo descargar PDF CCA")
        return {}

    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        f.write(pdf_data)
        tmp_path = f.name

    try:
        text = extract_text(tmp_path)
    finally:
        os.unlink(tmp_path)

    prices = {}

    BRAND_MODELS = {
        'TOYOTA': {
            'COROLLA': ['corolla'],
            'YARIS': ['yaris'],
            'HILUX': ['hilux'],
            'RAV4': ['rav4', 'rav 4'],
            'SW4': ['sw4'],
            'CAMRY': ['camry'],
            'CHR': ['chr', 'c-hr'],
            'ETIOS': ['etios'],
            'FORTUNER': ['fortuner'],
            'PRIUS': ['prius'],
        },
        'VOLKSWAGEN': {
            'POLO': ['polo'],
            'GOLF': ['golf'],
            'VENTO': ['vento'],
            'TIGUAN': ['tiguan'],
            'AMAROK': ['amarok'],
            'TAOS': ['taos'],
            'NIVUS': ['nivus'],
            'VIRTUS': ['virtus'],
            'SAVEIRO': ['saveiro'],
        },
        'PEUGEOT': {
            '208': ['208'],
            '308': ['308'],
            '2008': ['2008'],
            '3008': ['3008'],
            '408': ['408'],
            '508': ['508'],
        },
        'RENAULT': {
            'CLIO': ['clio'],
            'SANDERO': ['sandero'],
            'DUSTER': ['duster'],
            'LOGAN': ['logan'],
            'KWID': ['kwid'],
            'CAPTUR': ['captur'],
            'ARKANA': ['arkana'],
            'OROCH': ['oroch'],
        },
        'HONDA': {
            'CIVIC': ['civic'],
            'HRV': ['hrv', 'hr-v'],
            'CRV': ['crv', 'cr-v'],
            'FIT': ['fit'],
            'WRV': ['wrv', 'wr-v'],
            'ACCORD': ['accord'],
        },
        'FORD': {
            'FOCUS': ['focus'],
            'ECOSPORT': ['ecosport'],
            'RANGER': ['ranger'],
            'KA': ['ka'],
            'TERRITORY': ['territory'],
            'BRONCO': ['bronco'],
            'MAVERICK': ['maverick'],
            'KUGA': ['kuga'],
        },
        'CHEVROLET': {
            'ONIX': ['onix'],
            'TRACKER': ['tracker'],
            'CRUZE': ['cruze'],
            'EQUINOX': ['equinox'],
            'S10': ['s10', 's 10'],
            'SPIN': ['spin'],
        },
        'FIAT': {
            'CRONOS': ['cronos'],
            'ARGO': ['argo'],
            'PULSE': ['pulse'],
            'FASTBACK': ['fastback'],
            'MOBI': ['mobi'],
            'TORO': ['toro'],
            'STRADA': ['strada'],
        },
        'AUDI': {
            'A1': ['a1'],
            'A3': ['a3'],
            'A4': ['a4'],
            'A5': ['a5'],
            'A6': ['a6'],
            'Q2': ['q2'],
            'Q3': ['q3'],
            'Q5': ['q5'],
            'Q7': ['q7'],
            'TT': ['tt'],
        },
        'BMW': {
            'SERIE 1': ['116', '118', '120', '125', '130', '135', '140'],
            'SERIE 2': ['218', '220', '228', '230', '235', '240'],
            'SERIE 3': ['318', '320', '325', '328', '330', '335', '340'],
            'SERIE 4': ['420', '428', '430', '435', '440'],
            'SERIE 5': ['520', '523', '525', '528', '530', '535', '540'],
            'X1': ['x1'],
            'X2': ['x2'],
            'X3': ['x3'],
            'X4': ['x4'],
            'X5': ['x5'],
        },
        'MERCEDES BENZ': {
            'CLASE A': ['a 200', 'a200', 'a 250', 'a250'],
            'CLASE C': ['c 180', 'c180', 'c 200', 'c200', 'c 250', 'c250', 'c 300', 'c300'],
            'CLASE E': ['e 200', 'e200', 'e 250', 'e250', 'e 300', 'e300'],
            'GLA': ['gla'],
            'GLB': ['glb'],
            'GLC': ['glc'],
        },
        'HYUNDAI': {
            'TUCSON': ['tucson'],
            'SANTA FE': ['santa fe'],
            'CRETA': ['creta'],
            'VENUE': ['venue'],
            'I30': ['i30', 'i 30'],
        },
        'KIA': {
            'CERATO': ['cerato'],
            'SPORTAGE': ['sportage'],
            'SORENTO': ['sorento'],
            'SELTOS': ['seltos'],
            'STINGER': ['stinger'],
            'RIO': ['rio'],
            'PICANTO': ['picanto'],
        },
        'NISSAN': {
            'MARCH': ['march'],
            'VERSA': ['versa'],
            'SENTRA': ['sentra'],
            'KICKS': ['kicks'],
            'XTRAIL': ['x-trail', 'xtrail'],
            'NOTE': ['note'],
            'FRONTIER': ['frontier'],
        },
        'MAZDA': {
            'MAZDA2': ['mazda 2', 'mazda2', '2 sport'],
            'MAZDA3': ['mazda 3', 'mazda3', '3 sport'],
            'MAZDA6': ['mazda 6', 'mazda6'],
            'CX3': ['cx-3', 'cx3'],
            'CX5': ['cx-5', 'cx5'],
            'CX9': ['cx-9', 'cx9'],
        },
        'CITROEN': {
            'C3': ['c3'],
            'C4': ['c4'],
            'C5': ['c5'],
            'BERLINGO': ['berlingo'],
            'XSARA': ['xsara'],
        },
        'JEEP': {
            'RENEGADE': ['renegade'],
            'COMPASS': ['compass'],
            'WRANGLER': ['wrangler'],
            'GLADIATOR': ['gladiator'],
            'GRAND CHEROKEE': ['grand cherokee'],
        },
    }

    COL_YEARS = [0, 2025, 2024, 2023, 2022, 2021, 2020, 2019, 2018, 2017, 2016, 2015, 2014, 2013, 2012]
    text_upper = text.upper()

    for brand, models in BRAND_MODELS.items():
        brand_pos = text_upper.find(brand)
        if brand_pos == -1:
            continue

        next_brand_pos = len(text)
        for other_brand in BRAND_MODELS.keys():
            if other_brand == brand:
                continue
            pos = text_upper.find(other_brand, brand_pos + len(brand))
            if pos != -1 and pos < next_brand_pos:
                next_brand_pos = pos

        brand_text = text[brand_pos:next_brand_pos]
        brand_text_upper = brand_text.upper()

        for model_name, model_variants in models.items():
            model_pos = -1
            for variant in model_variants:
                pos = brand_text_upper.find(variant.upper())
                if pos != -1:
                    model_pos = pos
                    break

            if model_pos == -1:
                continue

            next_model_pos = len(brand_text)
            for other_model, other_variants in models.items():
                if other_model == model_name:
                    continue
                for variant in other_variants:
                    pos = brand_text_upper.find(variant.upper(), model_pos + 2)
                    if pos != -1 and pos < next_model_pos:
                        next_model_pos = pos

            model_text = brand_text[model_pos:next_model_pos]
            all_nums = re.findall(r'\b(\d{4,6})\b', model_text)

            if len(all_nums) < 2:
                continue

            year_totals = {}
            year_counts = {}

            i = 0
            while i < len(all_nums):
                row = []
                j = i
                while j < len(all_nums) and j < i + 14:
                    val = int(all_nums[j])
                    if 10000 <= val <= 999999:
                        row.append(val)
                        j += 1
                    else:
                        break

                if len(row) >= 1:
                    for idx, price in enumerate(row):
                        year_idx = idx + 1
                        if year_idx < len(COL_YEARS):
                            year = COL_YEARS[year_idx]
                            price_usd = round(price * 1000 / BLUE_RATE)
                            if 2000 < price_usd < 300000:
                                year_totals[year] = year_totals.get(year, 0) + price_usd
                                year_counts[year] = year_counts.get(year, 0) + 1

                i = max(i + 1, j)

            brand_key = brand.lower().replace(' ', '_')
            model_key = model_name.lower().replace(' ', '_')

            for year, total in year_totals.items():
                count = year_counts[year]
                avg = round(total / count)
                year_pair = (year // 2) * 2
                key = f"{brand_key}_{model_key}_{year_pair}"
                if key not in prices:
                    prices[key] = avg
                else:
                    prices[key] = round((prices[key] + avg) / 2)

        print(f"  CCA {brand}: OK")

    print(f"CCA total: {len(prices)} precios")
    return prices

def find_cca_price(listing, cca_prices):
    key = listing.get('model_key', '')
    if key in cca_prices:
        return cca_prices[key]
    parts = key.split('_')
    if len(parts) >= 3:
        brand = parts[0]
        model = '_'.join(parts[1:-1])
        year_pair = parts[-1]
        for k, v in cca_prices.items():
            if brand in k and model in k and year_pair in k:
                return v
    return None

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    all_listings = []

    marcas = [
        'audi', 'toyota', 'volkswagen', 'ford', 'chevrolet',
        'peugeot', 'renault', 'honda', 'fiat', 'bmw',
        'mercedes-benz', 'hyundai', 'kia', 'nissan', 'mazda',
        'citroen', 'jeep', 'mitsubishi', 'subaru', 'chery', 'haval', 'byd',
    ]

    stats = {'rg': 0, 'ac': 0, 'dm': 0}

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
    print("Scraping Demotores...")
    print("=" * 50)
    for marca in marcas:
        results = scrape_demotores(marca, paginas=3)
        all_listings.extend(results)
        stats['dm'] += len(results)
        print(f"  >> DM {marca}: {len(results)} total")
        time.sleep(random.uniform(2.0, 4.0))

    print(f"\nStats: RG={stats['rg']} AC={stats['ac']} DM={stats['dm']}")

    # Deduplicar
    seen = set()
    unique = []
    for l in all_listings:
        if l['id'] not in seen:
            seen.add(l['id'])
            unique.append(l)
    print(f"Total único: {len(unique)}")

    # Filtros de calidad
    unique = [l for l in unique if l.get('precio_usd', 0) >= 500]
    unique = [l for l in unique if l.get('year', 0) >= 1990]
    print(f"Post-filtro: {len(unique)}")

    # CCA
    print("\nParseando PDF CCA...")
    cca_prices = parse_cca_pdf()

    with open(CCA_FILE, 'w', encoding='utf-8') as f:
        json.dump({
            'updated': datetime.utcnow().isoformat() + 'Z',
            'total': len(cca_prices),
            'prices': cca_prices
        }, f, ensure_ascii=False, indent=2)

    # Match CCA
    matched = 0
    for l in unique:
        cca = find_cca_price(l, cca_prices)
        if cca:
            l['precio_cca'] = cca
            l['descuento_vs_cca'] = round((1 - l['precio_usd'] / cca) * 100)
            matched += 1

    print(f"Listings con CCA: {matched}/{len(unique)}")

    fuentes = {}
    for l in unique:
        f = l.get('fuente', '?')
        fuentes[f] = fuentes.get(f, 0) + 1

    output = {
        'updated': datetime.utcnow().isoformat() + 'Z',
        'total': len(unique),
        'fuentes': fuentes,
        'listings': unique
    }

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✓ listings.json: {len(unique)} autos")
    print(f"  Fuentes: {fuentes}")


if __name__ == '__main__':
    main()
