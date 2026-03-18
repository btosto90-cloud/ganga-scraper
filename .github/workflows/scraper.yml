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

    # The PDF text comes concatenated. We need to find brand sections.
    # Key insight: brands appear as all-caps words before model names.
    # Models appear as short words/numbers before spec lines with prices.
    
    prices = {}
    
    # Known brands and their model mappings
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

    # Column positions: 0Km=col0, 2025=col1, 2024=col2, ... 2012=col14
    COL_YEARS = [0, 2025, 2024, 2023, 2022, 2021, 2020, 2019, 2018, 2017, 2016, 2015, 2014, 2013, 2012]

    text_upper = text.upper()
    
    for brand, models in BRAND_MODELS.items():
        # Find brand position in text
        brand_pos = text_upper.find(brand)
        if brand_pos == -1:
            print(f"  Brand not found: {brand}")
            continue
        
        # Find next brand to limit search area
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
            # Find model in brand section
            model_pos = -1
            for variant in model_variants:
                pos = brand_text_upper.find(variant.upper())
                if pos != -1:
                    model_pos = pos
                    break
            
            if model_pos == -1:
                continue
            
            # Find next model to limit search
            next_model_pos = len(brand_text)
            for other_model, other_variants in models.items():
                if other_model == model_name:
                    continue
                for variant in other_variants:
                    pos = brand_text_upper.find(variant.upper(), model_pos + 2)
                    if pos != -1 and pos < next_model_pos:
                        next_model_pos = pos
            
            model_text = brand_text[model_pos:next_model_pos]
            
            # Extract all 4-6 digit numbers (prices in thousands ARS)
            all_nums = re.findall(r'\b(\d{4,6})\b', model_text)
            
            if len(all_nums) < 2:
                continue
            
            # Group numbers into rows of up to 15 (one per column)
            # Each row = one version line
            # We calculate average price per year across all versions
            year_totals = {}
            year_counts = {}
            
            # Process in chunks that could be price rows
            i = 0
            while i < len(all_nums):
                # A price row has between 1 and 14 prices (years with data)
                row = []
                j = i
                while j < len(all_nums) and j < i + 14:
                    val = int(all_nums[j])
                    # Valid price range: 10000-999999 (in thousands ARS)
                    if 10000 <= val <= 999999:
                        row.append(val)
                        j += 1
                    else:
                        break
                
                if len(row) >= 1:
                    # Map to years - skip column 0 (0km)
                    for idx, price in enumerate(row):
                        year_idx = idx + 1  # skip 0km column
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
            
            # Store average price per year
            brand_key = brand.lower().replace(' ', '_')
            model_key = model_name.lower().replace(' ', '_')
            
            for year, total in year_totals.items():
                count = year_counts[year]
                avg = round(total / count)
                # Use same key format as scraper: brand_model_year_pair
                year_pair = (year // 2) * 2
                key = f"{brand_key}_{model_key}_{year_pair}"
                # Keep median-ish: if multiple years map to same pair, average them
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
    # Try partial match
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
    
    # ML uses different URL format for some brands
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

# ---- MercadoLibre scraper ----
def scrape_ml(marca, modelo='', paginas=5):
    listings = []
    BLUE_RATE = 1290
    
    # Build URL - ML uses hyphenated names
    marca_url = marca.replace(' ', '-').lower()
    modelo_url = ('-' + modelo.replace(' ', '-').lower()) if modelo else ''
    base = f"https://listado.mercadolibre.com.ar/{marca_url}{modelo_url}-usado"
    
    for page in range(paginas):
        offset = page * 48
        url = base if page == 0 else f"{base}_Desde_{offset + 1}"
        html = fetch(url).decode('utf-8', errors='ignore')
        if not html:
            break
        
        parsed = parse_ml_listings(html, marca, BLUE_RATE)
        print(f"  ML {marca}{modelo_url} p{page+1}: {len(parsed)}")
        listings.extend(parsed)
        if len(parsed) < 10:
            break
    
    return listings

def parse_ml_listings(html, marca, BLUE_RATE=1290):
    listings = []
    import json as json_mod
    
    # ML embeds data in __PRELOADED_STATE__ or similar JSON
    # Try to find the JSON data blob
    match = re.search(r'window\.__PRELOADED_STATE__\s*=\s*({.+?});\s*</script>', html, re.DOTALL)
    if match:
        try:
            data = json_mod.loads(match.group(1))
            results = data.get('initialState', {}).get('results', [])
            for item in results:
                listing = parse_ml_item(item, BLUE_RATE)
                if listing:
                    listings.append(listing)
            if listings:
                return listings
        except:
            pass
    
    # Fallback: parse HTML directly
    # ML listing cards have class "ui-search-result"
    blocks = html.split('ui-search-result__wrapper')
    for block in blocks[1:]:
        chunk = block[:3000]
        
        # Title
        title_m = re.search(r'class="poly-component__title[^"]*">([^<]+)<', chunk)
        if not title_m:
            title_m = re.search(r'ui-search-item__title[^>]*>([^<]+)<', chunk)
        if not title_m:
            continue
        title = title_m.group(1).strip()[:60]
        
        # Year
        year_m = re.search(r'\b(20\d{2}|19\d{2})\b', chunk)
        if not year_m:
            continue
        year = int(year_m.group(1))
        if year < 2000:
            continue
        
        # KM
        km_m = re.search(r'([\d.]+)\s*[Kk][Mm]', chunk)
        km = int(km_m.group(1).replace('.','')) if km_m else 0
        
        # Price - ML shows USD or ARS
        price_usd_m = re.search(r'US\$\s*([\d.,]+)', chunk)
        price_ars_m = re.search(r'\$\s*([\d.,]+)', chunk)
        
        precio_usd = 0
        if price_usd_m:
            precio_usd = int(price_usd_m.group(1).replace('.','').replace(',',''))
        elif price_ars_m:
            ars = int(price_ars_m.group(1).replace('.','').replace(',',''))
            if ars > 100000:  # sanity check - must be real ARS price
                precio_usd = round(ars / BLUE_RATE)
        
        if not precio_usd or precio_usd < 1000 or precio_usd > 500000:
            continue
        
        # URL
        url_m = re.search(r'href="(https://[^"]*mercadolibre\.com\.ar/[^"]+)"', chunk)
        item_url = url_m.group(1) if url_m else ''
        item_id = 'ml_' + re.sub(r'[^a-z0-9]', '_', item_url.split('/')[-1])[:40] if item_url else f"ml_{hash(title+str(year)) % 9999999}"
        
        # Trans
        trans = 'AT' if re.search(r'autom|cvt|tiptronic|s.tronic', chunk, re.I) else '?'
        
        listings.append({
            'id': item_id,
            'url': item_url,
            'title': title,
            'year': year, 'km': km,
            'fuel': '?', 'trans': trans,
            'precio_usd': precio_usd,
            'fuente': 'ml',
            'model_key': extract_model_key(title, year)
        })
    
    return listings

def parse_ml_item(item, BLUE_RATE):
    try:
        title = item.get('title', '')[:60]
        year_m = re.search(r'\b(20\d{2}|19\d{2})\b', title)
        year = int(year_m.group(1)) if year_m else 0
        
        # Try attributes for year
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
