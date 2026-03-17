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
        with urllib.request.urlopen(req, timeout=15) as r:
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
        print("No se pudo descargar el PDF CCA")
        return {}

    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        f.write(pdf_data)
        tmp_path = f.name

    try:
        text = extract_text(tmp_path)
    finally:
        os.unlink(tmp_path)

    prices = {}
    current_marca = ""
    current_modelo = ""
    col_years = [0, 2025, 2024, 2023, 2022, 2021, 2020, 2019, 2018, 2017, 2016, 2015, 2014, 2013, 2012]

    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue
        if 'Visite Nuestro' in line or 'Autos - Pick' in line or '0 Km' in line:
            continue

        # Brand: all caps, no digits
        if re.match(r'^[A-Z][A-Z\s\-]+$', line) and len(line) < 30 and not any(c.isdigit() for c in line):
            current_marca = line.strip()
            continue

        # Model name
        if re.match(r'^[A-Z][A-Za-z0-9\s]+$', line) and len(line) < 20 and not re.search(r'\d{4,}', line):
            current_modelo = line.strip()
            continue

        # Price line
        nums = re.findall(r'\b(\d{4,6})\b', line)
        if nums and current_marca and current_modelo:
            version_end = line.rfind(nums[0])
            version = line[:version_end].strip()
            trans = 'at' if re.search(r'\bAT\b|S-TRONIC|CVT|TIPTRONIC|DSG', version.upper()) else 'mt'

            for idx, num_str in enumerate(nums):
                if idx < len(col_years) and col_years[idx] > 0:
                    price_usd = round(int(num_str) * 1000 / BLUE_RATE)
                    year = col_years[idx]
                    key = re.sub(r'[^a-z0-9_]', '_', f"{current_marca.lower()}_{current_modelo.lower()}_{year}_{trans}")
                    key = re.sub(r'_+', '_', key).strip('_')
                    if price_usd > 500:
                        if key not in prices or price_usd > prices[key]:
                            prices[key] = price_usd

    print(f"CCA: {len(prices)} precios parseados")
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
    brands = ['audi','toyota','volkswagen','ford','chevrolet','peugeot','renault','honda','fiat','bmw','mercedes','hyundai','kia','nissan','mazda']
    brand = next((b for b in brands if b in t), 'other')
    models = ['a1','a3','a4','a5','a6','q2','q3','q5','q7','tt','yaris','corolla','hilux','rav4','polo','golf','vento','tiguan','focus','fiesta','ecosport','ranger','208','308','2008','3008','clio','sandero','duster','captur','fit','civic','hrv','crv','tracker','onix','cruze','etios','sienta','march','versa','sentra']
    model = next((m for m in models if m in t), 'other')
    return f"{brand}_{model}_{(year // 2) * 2}"

def find_cca_price(listing, cca_prices):
    t = listing['title'].lower()
    year = listing['year']
    trans = listing.get('trans', '?').lower()
    brands = ['audi','toyota','volkswagen','ford','chevrolet','peugeot','renault','honda','fiat','bmw','mercedes','hyundai','kia','nissan','mazda']
    brand = next((b for b in brands if b in t), None)
    if not brand:
        return None
    models = ['a1','a3','a4','a5','a6','q2','q3','q5','q7','tt','yaris','corolla','hilux','rav4','polo','golf','vento','tiguan','focus','fiesta','ecosport','208','308','2008','3008','clio','sandero','duster','captur','fit','civic','hrv','crv','tracker','onix','cruze']
    model = next((m for m in models if m in t), None)
    if not model:
        return None
    # Try exact match
    key = re.sub(r'[^a-z0-9_]', '_', f"{brand}_{model}_{year}_{trans}")
    if key in cca_prices:
        return cca_prices[key]
    # Try without trans
    for k, v in cca_prices.items():
        if brand in k and model in k and str(year) in k:
            return v
    return None

def main():
    all_listings = []
    marcas = ['audi','toyota','volkswagen','ford','chevrolet','peugeot','renault','honda','fiat','bmw','mercedes','hyundai','kia','nissan','mazda']

    print("Scraping RosarioGarage...")
    for marca in marcas:
        all_listings.extend(scrape_rg(marca, 3))

    print("Scraping Autocosmos...")
    for marca in marcas:
        all_listings.extend(scrape_ac(marca, 3))

    seen = set()
    unique = [l for l in all_listings if not (l['id'] in seen or seen.add(l['id']))]
    print(f"Total listings: {len(unique)}")

    cca_prices = parse_cca_pdf()

    with open(CCA_FILE, 'w', encoding='utf-8') as f:
        json.dump({'updated': datetime.utcnow().isoformat()+'Z', 'total': len(cca_prices), 'prices': cca_prices}, f, ensure_ascii=False)
    print(f"CCA guardado: {len(cca_prices)} precios")

    for l in unique:
        cca = find_cca_price(l, cca_prices)
        if cca:
            l['precio_cca'] = cca
            l['descuento_vs_cca'] = round((1 - l['precio_usd'] / cca) * 100)

    output = {'updated': datetime.utcnow().isoformat()+'Z', 'total': len(unique), 'listings': unique}
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"listings.json guardado: {len(unique)} autos")

if __name__ == '__main__':
    main()
