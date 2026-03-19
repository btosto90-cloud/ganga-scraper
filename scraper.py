import json
import re
import urllib.request
from datetime import datetime

BLUE_RATE = 1290
OUTPUT_FILE = "listings.json"
CCA_FILE = "cca_precios.json"
CCA_PDF_URL = "https://www.cca.org.ar/descargas/precios/Autos.pdf"

def fetch(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'es-AR,es;q=0.9',
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read()
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return b""

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
            print(f"  Brand not found: {brand}")
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
                                if year not in year_totals:
                                    year_totals[year] = 0
                                    year_counts[year] = 0
                                year_totals[year] += price_usd
                                year_counts[year] += 1

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

            print(f"  {brand} {model_name}: {len(year_totals)} años")

    print(f"CCA total: {len(prices)} precios")
    return prices

def scrape_rg(marca, paginas=3):
    listings = []
    base_url = f"https://www.rosariogarage.com/Autos/{marca}"
    for page in range(1, paginas + 1):
        url = base_url if page == 1 else f"{base_url}?page={page}"
        html = fetch(url).decode('latin-1', errors='ignore')
        if not html:
            break
        blocks = html.split('data-rel="')
        parsed = 0
        for block in blocks[1:]:
            id_m = re.match(r'^(\d+)"', block)
            if not id_m:
                continue
            item_id = id_m.group(1)
            chunk = block[:4000]
            title_m = re.search(r'class="list_type_anuncio">([^<]+)<', chunk)
            if not title_m:
                continue
            title = title_m.group(1).replace('...', '').strip()
            year_m = re.search(r'>(20\d{2}|19\d{2})</span>', chunk)
            if not year_m:
                continue
            year = int(year_m.group(1))
            km_m = re.search(r'>([\d.]+)\s*km\.</span>', chunk, re.I)
            if not km_m:
                continue
            km = int(km_m.group(1).replace('.', ''))
            if year < 2000 or km > 400000:
                continue
            trans_m = re.search(r'>(AT|MT)</span>', chunk, re.I)
            trans = trans_m.group(1).upper() if trans_m else '?'
            fuel_m = re.search(r'>(Nafta|Diesel|GNC|Eléctrico|Híbrido)</span>', chunk, re.I)
            fuel = fuel_m.group(1) if fuel_m else '?'
            price_m = re.search(r'class="precio[^"]*">\s*<a[^>]*>\s*([^\n<]+)', chunk, re.I)
            price_raw = price_m.group(1).strip() if price_m else ''
            if not price_raw or 'consultar' in price_raw.lower():
                continue
            precio_usd = parse_price(price_raw)
            if not precio_usd:
                continue
            listings.append({
                'id': item_id,
                'url': f"https://www.rosariogarage.com/index.php?action=carro/showProduct&itmId={item_id}",
                'title': title[:60], 'year': year, 'km': km,
                'fuel': fuel, 'trans': trans,
                'precio_usd': precio_usd, 'fuente': 'rg',
                'model_key': extract_model_key(title, year)
            })
            parsed += 1
        print(f"  RG {marca} p{page}: {parsed}")
        if parsed == 0:
            break
    return listings

def scrape_ac(marca, paginas=3):
    listings = []
    for page in range(1, paginas + 1):
        url = f"https://www.autocosmos.com.ar/auto/usado/{marca}" + (f"?p={page}" if page > 1 else "")
        html = fetch(url).decode('utf-8', errors='ignore')
        if not html:
            break
        blocks = html.split('<article')
        parsed = 0
        for block in blocks[1:]:
            chunk = block[:2000]
            url_m = re.search(r'href="(/auto/usado/[^"]+)"', chunk)
            if not url_m:
                continue
            rel_url = url_m.group(1)
            item_id = 'ac_' + re.sub(r'[^a-z0-9]', '_', rel_url)[:40]
            desc_m = re.search(r'content="([^"]*usado[^"]*)"', chunk) or re.search(r'description[^>]*content="([^"]+)"', chunk)
            if not desc_m:
                continue
            desc = desc_m.group(1)
            year_m = re.search(r'\((\d{4})\)', desc)
            if not year_m:
                continue
            year = int(year_m.group(1))
            if year < 2000:
                continue
            title_m = re.search(r'title="([^"]+)"', chunk)
            title = title_m.group(1)[:60] if title_m else desc[:40]
            usd_m = re.search(r'u\$s([\d.,]+)', desc, re.I)
            precio_usd = 0
            if usd_m:
                precio_usd = int(usd_m.group(1).replace(',','').replace('.',''))
                if precio_usd > 500000:
                    precio_usd = round(precio_usd / BLUE_RATE)
            else:
                ars_m = re.search(r'content="(\d{6,9})"', chunk)
                if ars_m:
                    precio_usd = round(int(ars_m.group(1)) / BLUE_RATE)
            if not precio_usd or precio_usd < 1000:
                continue
            km_m = re.search(r'([\d.]+)\s*km', desc, re.I)
            km = int(km_m.group(1).replace('.','')) if km_m else 0
            trans = 'AT' if re.search(r'autom|s.tronic|cvt|tiptronic', desc, re.I) else 'MT'
            listings.append({
                'id': item_id,
                'url': f"https://www.autocosmos.com.ar{rel_url}",
                'title': title, 'year': year, 'km': km,
                'fuel': '?', 'trans': trans,
                'precio_usd': precio_usd, 'fuente': 'ac',
                'model_key': extract_model_key(title, year)
            })
            parsed += 1
        print(f"  AC {marca} p{page}: {parsed}")
        if parsed == 0:
            break
    return listings

def fetch_ml(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'es-AR,es;q=0.9,en;q=0.8',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Cache-Control': 'max-age=0',
    }
    try:
        import requests as req_lib
        r = req_lib.get(url, headers=headers, timeout=20)
        return r.text
    except Exception as e:
        print(f"  ML fetch error: {e}")
        return ''

def scrape_ml(marca, modelo='', paginas=5):
    listings = []
    marca_url = marca.replace(' ', '-').lower()
    modelo_url = ('-' + modelo.replace(' ', '-').lower()) if modelo else ''
    base = f"https://listado.mercadolibre.com.ar/{marca_url}{modelo_url}-usado"

    for page in range(paginas):
        offset = page * 48
        url = base if page == 0 else f"{base}_Desde_{offset + 1}"
        html = fetch_ml(url)
        if not html:
            break

        # DEBUG: guardar primer HTML de ML
        if not hasattr(scrape_ml, '_debug_saved'):
            scrape_ml._debug_saved = True
            with open('ml_debug.html', 'w', encoding='utf-8') as f:
                f.write(html)
            print(f"  ML DEBUG html_len={len(html)} layout={'ui-search-layout__item' in html}")
            idx = html.find('layout__item')
            print(f"  ML DEBUG snippet: {repr(html[max(0,idx-20):idx+200]) if idx>-1 else 'NOT FOUND'}")

        parsed = parse_ml_listings(html, marca)
        print(f"  ML {marca}{modelo_url} p{page+1}: {len(parsed)}")
        listings.extend(parsed)
        if len(parsed) < 10:
            break

    return listings

def parse_ml_listings(html, marca):
    listings = []

    # ML 2024+ structure: items are <li class="ui-search-layout__item">
    # Split by li items
    blocks = html.split('<li class="ui-search-layout__item')
    if len(blocks) < 2:
        # fallback: try old wrapper
        blocks = html.split('ui-search-layout__item')

    for block in blocks[1:]:
        chunk = block[:4000]

        # Title: inside <h2> or class containing "title"
        title_m = (re.search(r'<h2[^>]*>([^<]+)</h2>', chunk) or
                   re.search(r'class="[^"]*title[^"]*"[^>]*>([^<]+)<', chunk) or
                   re.search(r'poly-component__title[^>]*>([^<]+)<', chunk))
        if not title_m:
            continue
        title = title_m.group(1).strip()[:60]
        if not title or len(title) < 5:
            continue

        # Year: 4-digit year in attributes or title
        year_m = re.search(r'\b(20\d{2}|19\d{2})\b', chunk)
        if not year_m:
            continue
        year = int(year_m.group(1))
        if year < 2000 or year > 2026:
            continue

        # KM: number followed by km
        km_m = re.search(r'([\d.]+)\s*[Kk][Mm]', chunk)
        km = int(km_m.group(1).replace('.', '').replace(',', '')) if km_m else 0
        if km > 500000:
            continue

        # Price: USD preferred, then ARS converted
        precio_usd = 0
        usd_m = re.search(r'U[Ss][Dd]?\s*[\$]?\s*([\d.,]+)', chunk)
        ars_m = re.search(r'price__fraction[^>]*>([\d.,]+)<', chunk)
        if not ars_m:
            ars_m = re.search(r'\$\s*([\d.,]+)', chunk)

        if usd_m:
            precio_usd = int(usd_m.group(1).replace('.', '').replace(',', ''))
        elif ars_m:
            ars_raw = ars_m.group(1).replace('.', '').replace(',', '')
            ars = int(ars_raw) if ars_raw.isdigit() else 0
            if ars > 500000:
                precio_usd = round(ars / BLUE_RATE)

        if not precio_usd or precio_usd < 1000 or precio_usd > 500000:
            continue

        # URL: auto.mercadolibre.com.ar or mercadolibre.com.ar
        url_m = re.search(r'href="(https://[^"]*(?:auto\.)?mercadolibre\.com\.ar/[^"?]+)"', chunk)
        item_url = url_m.group(1) if url_m else ''
        # Extract MLA id from url
        mla_m = re.search(r'MLA-?(\d+)', item_url)
        item_id = f"ml_{mla_m.group(1)}" if mla_m else f"ml_{abs(hash(title+str(year))) % 9999999}"

        trans = 'AT' if re.search(r'autom|cvt|tiptronic|s.tronic|secuencial', chunk, re.I) else '?'
        fuel_m = re.search(r'(nafta|diesel|gnc|el[eé]ctrico|h[ií]brido)', chunk, re.I)
        fuel = fuel_m.group(1).capitalize() if fuel_m else '?'

        listings.append({
            'id': item_id,
            'url': item_url,
            'title': title,
            'year': year, 'km': km,
            'fuel': fuel, 'trans': trans,
            'precio_usd': precio_usd,
            'fuente': 'ml',
            'model_key': extract_model_key(title, year)
        })

    return listings

def parse_ml_item(item):
    try:
        title = item.get('title', '')[:60]
        year_m = re.search(r'\b(20\d{2}|19\d{2})\b', title)
        year = int(year_m.group(1)) if year_m else 0

        for attr in item.get('attributes', []):
            if attr.get('id') == 'VEHICLE_YEAR':
                year = int(attr.get('value_name', year))

        if year < 2000:
            return None

        price = item.get('price', 0)
        currency = item.get('currency_id', 'ARS')
        precio_usd = price if currency == 'USD' else round(price / BLUE_RATE)

        if not precio_usd or precio_usd < 1000 or precio_usd > 500000:
            return None

        km = 0
        for attr in item.get('attributes', []):
            if attr.get('id') == 'KILOMETERS':
                km_str = re.sub(r'\D', '', str(attr.get('value_name', '0')))
                km = int(km_str) if km_str else 0

        return {
            'id': f"ml_{item.get('id', '')}",
            'url': item.get('permalink', ''),
            'title': title,
            'year': year, 'km': km,
            'fuel': '?', 'trans': '?',
            'precio_usd': precio_usd,
            'fuente': 'ml',
            'model_key': extract_model_key(title, year)
        }
    except:
        return None

def parse_price(raw):
    if not raw or 'consultar' in raw.lower():
        return 0
    num = int(re.sub(r'[^\d]', '', raw) or '0')
    if not num:
        return 0
    if re.search(r'u\$s', raw, re.I):
        return num
    return round(num / BLUE_RATE)

def extract_model_key(title, year):
    t = title.lower()
    brands = ['audi','toyota','volkswagen','ford','chevrolet','peugeot','renault','honda','fiat','bmw','mercedes','hyundai','kia','nissan','mazda','citroen','jeep','mitsubishi','subaru','chery','haval','byd']
    brand = next((b for b in brands if b in t), 'other')
    models = ['a1','a3','a4','a5','a6','q2','q3','q5','q7','tt',
              'yaris','corolla','hilux','rav4','sw4','chr','etios','fortuner','prius',
              'polo','golf','vento','tiguan','amarok','taos','nivus','virtus',
              '208','308','2008','3008','408',
              'clio','sandero','duster','logan','kwid','captur','arkana',
              'fit','civic','hrv','crv','wrv','accord',
              'focus','ecosport','ranger','territory','kuga','maverick',
              'onix','tracker','cruze','equinox','s10',
              'cronos','argo','pulse','fastback','mobi','toro','strada',
              'tucson','santa fe','creta','venue','i30',
              'cerato','sportage','sorento','seltos','stinger','rio',
              'march','versa','sentra','kicks','note','frontier',
              'renegade','compass','wrangler','gladiator',
              'c3','c4','berlingo']
    model = next((m for m in models if m in t), 'other')
    return f"{brand}_{model}_{(year // 2) * 2}"

def find_cca_price(listing, cca_prices):
    key = listing.get('model_key', '')
    if key in cca_prices:
        return cca_prices[key]
    parts = key.split('_')
    if len(parts) >= 3:
        brand, model = parts[0], parts[1]
        year_pair = parts[2] if len(parts) > 2 else ''
        for k, v in cca_prices.items():
            if brand in k and model in k and year_pair in k:
                return v
    return None

def main():
    all_listings = []
    marcas_rg_ac = ['audi','toyota','volkswagen','ford','chevrolet','peugeot','renault',
              'honda','fiat','bmw','mercedes','hyundai','kia','nissan','mazda',
              'citroen','jeep','mitsubishi','subaru','chery','haval','byd']

    marcas_ml = [
        ('audi', ''), ('toyota', 'corolla'), ('toyota', 'yaris'), ('toyota', 'hilux'),
        ('volkswagen', 'polo'), ('volkswagen', 'golf'), ('volkswagen', 'vento'), ('volkswagen', 'tiguan'),
        ('ford', 'focus'), ('ford', 'ecosport'), ('ford', 'ranger'), ('ford', 'territory'),
        ('chevrolet', 'onix'), ('chevrolet', 'tracker'), ('chevrolet', 'cruze'),
        ('peugeot', '208'), ('peugeot', '308'), ('peugeot', '2008'), ('peugeot', '3008'),
        ('renault', 'clio'), ('renault', 'sandero'), ('renault', 'duster'), ('renault', 'captur'),
        ('honda', 'civic'), ('honda', 'hr-v'), ('honda', 'cr-v'),
        ('fiat', 'cronos'), ('fiat', 'argo'), ('fiat', 'pulse'),
        ('bmw', ''), ('mercedes-benz', ''),
        ('hyundai', 'tucson'), ('hyundai', 'creta'),
        ('kia', 'sportage'), ('kia', 'cerato'), ('kia', 'seltos'),
        ('nissan', 'versa'), ('nissan', 'kicks'), ('nissan', 'march'),
        ('mazda', ''), ('jeep', 'renegade'), ('jeep', 'compass'),
    ]

    print("Scraping RosarioGarage...")
    for marca in marcas_rg_ac:
        all_listings.extend(scrape_rg(marca, 3))

    print("Scraping Autocosmos...")
    for marca in marcas_rg_ac:
        all_listings.extend(scrape_ac(marca, 3))

    print("Scraping MercadoLibre...")
    for marca, modelo in marcas_ml:
        all_listings.extend(scrape_ml(marca, modelo, 5))

    seen = set()
    unique = [l for l in all_listings if not (l['id'] in seen or seen.add(l['id']))]
    print(f"Total listings: {len(unique)}")

    print("Parseando PDF CCA...")
    cca_prices = parse_cca_pdf()

    with open(CCA_FILE, 'w', encoding='utf-8') as f:
        json.dump({'updated': datetime.utcnow().isoformat()+'Z',
                   'total': len(cca_prices), 'prices': cca_prices}, f, ensure_ascii=False, indent=2)
    print(f"CCA guardado: {len(cca_prices)} precios")

    matched = 0
    for l in unique:
        cca = find_cca_price(l, cca_prices)
        if cca:
            l['precio_cca'] = cca
            l['descuento_vs_cca'] = round((1 - l['precio_usd'] / cca) * 100)
            matched += 1

    print(f"Listings con CCA: {matched}/{len(unique)}")

    output = {'updated': datetime.utcnow().isoformat()+'Z', 'total': len(unique), 'listings': unique}
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"listings.json: {len(unique)} autos")


if __name__ == '__main__':
    main()
