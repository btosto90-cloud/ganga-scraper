import json
import re
import urllib.request
from datetime import datetime

BLUE_RATE = 1290
OUTPUT_FILE = "listings.json"

def fetch(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'es-AR,es;q=0.9',
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return ""

def parse_price(raw):
    if not raw or 'consultar' in raw.lower():
        return 0
    num_str = re.sub(r'[^\d]', '', raw)
    if not num_str:
        return 0
    num = int(num_str)
    if 'u$s' in raw.lower() or 'usd' in raw.lower():
        return num
    return round(num / BLUE_RATE)

def scrape_kavak(page=1):
    listings = []
    api_url = f"https://listings-api.kavak.com/car?countryCode=AR&page={page}&limit=48&sort=price_asc"
    html = fetch(api_url, headers={
        'User-Agent': 'Mozilla/5.0',
        'Accept': 'application/json',
        'Origin': 'https://www.kavak.com',
        'Referer': 'https://www.kavak.com/ar/usados',
    })
    try:
        data = json.loads(html)
        cars = data.get('data', data.get('cars', data.get('results', [])))
        for car in cars:
            title = f"{car.get('brand','')} {car.get('model','')} {car.get('version','')}".strip()
            year = int(car.get('year', 0))
            km = int(car.get('km', car.get('mileage', 0)))
            price = car.get('price', car.get('salePrice', 0))
            currency = car.get('currency', 'ARS')
            precio_usd = price if currency == 'USD' else round(price / BLUE_RATE)
            car_url = f"https://www.kavak.com/ar/usados/{car.get('brand','').lower()}/{car.get('id','')}"
            trans = 'AT' if 'auto' in str(car.get('transmission','')).lower() else 'MT'
            if year >= 2005 and precio_usd > 1000:
                listings.append({
                    'id': f"kv_{car.get('id', car.get('stockId', ''))}",
                    'url': car_url, 'title': title[:60],
                    'year': year, 'km': km,
                    'fuel': car.get('fuelType', '?'), 'trans': trans,
                    'precio_usd': precio_usd, 'fuente': 'kavak'
                })
    except Exception as e:
        print(f"Kavak parse error: {e}")
    return listings

def scrape_lavoz(marca='', page=1):
    listings = []
    base = "https://clasificadoslavoz.com.ar"
    url = f"{base}/autos{'/' + marca if marca else ''}?page={page}"
    html = fetch(url)
    if not html:
        return listings
    match = re.search(r'__NEXT_DATA__\s*=\s*({.+?})\s*</script>', html, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            props = data.get('props', {}).get('pageProps', {})
            items = props.get('listings', props.get('items', props.get('ads', [])))
            for item in items:
                title = item.get('title', '')
                price_raw = str(item.get('price', {}).get('amount', '') or item.get('price', ''))
                currency = item.get('price', {}).get('currency', 'ARS')
                precio_usd = int(price_raw) if currency == 'USD' else parse_price(price_raw)
                year_match = re.search(r'(20\d{2}|19\d{2})', title)
                year = int(year_match.group(1)) if year_match else 0
                km_raw = str(item.get('attributes', {}).get('km', item.get('km', '0')))
                km = int(re.sub(r'\D', '', km_raw) or '0')
                item_url = item.get('permalink', item.get('url', ''))
                if not item_url.startswith('http'):
                    item_url = base + item_url
                if year >= 2005 and precio_usd > 1000:
                    listings.append({
                        'id': f"lv_{item.get('id', '')}",
                        'url': item_url, 'title': title[:60],
                        'year': year, 'km': km,
                        'fuel': '?', 'trans': '?',
                        'precio_usd': precio_usd, 'fuente': 'lavoz'
                    })
        except Exception as e:
            print(f"La Voz parse error: {e}")
    return listings

def scrape_deconcesionarias(marca='', page=1):
    listings = []
    url = f"https://www.deconcesionarias.com.ar/autos-usados{'/' + marca if marca else ''}?pagina={page}"
    html = fetch(url)
    if not html:
        return listings
    blocks = re.split(r'class="[^"]*car[- _]card[^"]*"', html)
    for block in blocks[1:]:
        chunk = block[:1500]
        title_m = re.search(r'<h[23][^>]*>([^<]{5,60})</h[23]>', chunk)
        price_m = re.search(r'U\$[Ss]\s*([\d.,]+)|\$\s*([\d.]+)', chunk)
        year_m = re.search(r'\b(20\d{2}|19\d{2})\b', chunk)
        url_m = re.search(r'href="(/[^"]+autos[^"]+)"', chunk)
        km_m = re.search(r'([\d.]+)\s*km', chunk, re.IGNORECASE)
        if title_m and price_m and year_m:
            g = price_m.groups()
            price_str = g[0] or g[1] or '0'
            precio_usd = int(re.sub(r'\D', '', price_str)) if g[0] else parse_price('$' + price_str)
            year = int(year_m.group(1))
            km = int(re.sub(r'\.', '', km_m.group(1))) if km_m else 0
            item_url = 'https://www.deconcesionarias.com.ar' + url_m.group(1) if url_m else ''
            if year >= 2005 and precio_usd > 1000:
                listings.append({
                    'id': f"dc_{hash(item_url or title_m.group(1)) % 9999999}",
                    'url': item_url, 'title': title_m.group(1)[:60],
                    'year': year, 'km': km,
                    'fuel': '?', 'trans': '?',
                    'precio_usd': precio_usd, 'fuente': 'deconcesionarias'
                })
    return listings

def main():
    all_listings = []
    marcas = ['audi','toyota','volkswagen','ford','chevrolet','peugeot','renault','honda','bmw','mercedes-benz','hyundai','kia']

    print("Scraping Kavak...")
    for page in range(1, 5):
        l = scrape_kavak(page)
        print(f"  page {page}: {len(l)}")
        all_listings.extend(l)
        if not l: break

    print("Scraping La Voz...")
    for marca in marcas:
        for page in range(1, 3):
            l = scrape_lavoz(marca, page)
            print(f"  {marca} p{page}: {len(l)}")
            all_listings.extend(l)
            if not l: break

    print("Scraping deConcesionarias...")
    for marca in marcas:
        for page in range(1, 3):
            l = scrape_deconcesionarias(marca, page)
            print(f"  {marca} p{page}: {len(l)}")
            all_listings.extend(l)
            if not l: break

    seen = set()
    unique = [l for l in all_listings if not (l['id'] in seen or seen.add(l['id']))]

    output = {'updated': datetime.utcnow().isoformat()+'Z', 'total': len(unique), 'listings': unique}
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nTotal: {len(unique)} listings → {OUTPUT_FILE}")

if __name__ == '__main__':
    main()
