#!/usr/bin/env python3
"""Telegram notifier para Ganga Hunter.

Lee listings.json + cca_precios.json y manda un digest diario por Telegram:
  - Super gangas (>=25% bajo CCA) que aparecieron hoy por primera vez
  - Listings ganga-grade (>=15% bajo CCA) que bajaron >=10% desde el run previo

Estado persistido en notified.json para no re-notificar lo mismo.

Env vars:
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

Si faltan, exit 0 (no rompe la pipeline).
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime

LISTINGS_FILE = 'listings.json'
CCA_FILE = 'cca_precios.json'
STATE_FILE = 'notified.json'

GANGA_RATIO = 0.85          # <=85% del CCA = ganga
SUPER_GANGA_RATIO = 0.75    # <=75% del CCA = super ganga
MIN_DROP_PCT = 10           # solo bajadas >=10% disparan notificación
MAX_PER_SECTION = 5

def fmt_num(n):
    try:
        return f"{int(n):,}".replace(",", ".")
    except (TypeError, ValueError):
        return str(n)

def market_price(l, cca):
    return cca.get(l.get('model_key'))

def discount_pct(l, cca):
    m = market_price(l, cca)
    if not m or m <= 0:
        return None
    return round((1 - l['precio_usd'] / m) * 100, 1)

def tag(l, cca):
    m = market_price(l, cca)
    if not m or m <= 0 or not l.get('precio_usd'):
        return None
    ratio = l['precio_usd'] / m
    if ratio <= SUPER_GANGA_RATIO:
        return 'super_ganga'
    if ratio <= GANGA_RATIO:
        return 'ganga'
    return None

def fmt_listing(l, cca, show_drop=False):
    title = (l.get('title') or '?')[:60]
    km_raw = l.get('km') or 0
    km = f"{km_raw//1000}k km" if km_raw else "0 km"
    trans = l.get('trans') or '?'
    fuel = l.get('fuel') or '?'
    fuente = (l.get('fuente') or '').upper()
    precio = l['precio_usd']
    m = market_price(l, cca)
    pct = discount_pct(l, cca)
    lines = [f"<b>{title}</b>",
             f"  USD {fmt_num(precio)} · {km} · {trans} · {fuel} · {fuente}"]
    if show_drop:
        hist = l.get('price_history') or []
        prev = hist[-2]['precio_usd'] if len(hist) >= 2 else None
        if prev:
            lines.append(f"  📉 USD {fmt_num(prev)} → USD {fmt_num(precio)} (-{l.get('recent_drop_pct', 0)}%)")
    if pct is not None and m:
        lines.append(f"  ↓ {pct}% vs CCA (USD {fmt_num(m)})")
    lines.append(f"  {l.get('url', '')}")
    return '\n'.join(lines)

def send_telegram(token, chat_id, text):
    url = f'https://api.telegram.org/bot{token}/sendMessage'
    data = urllib.parse.urlencode({
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'HTML',
        'disable_web_page_preview': 'true',
    }).encode()
    req = urllib.request.Request(url, data=data, method='POST')
    with urllib.request.urlopen(req, timeout=15) as r:
        body = r.read().decode()
        if r.status != 200:
            raise RuntimeError(f"telegram {r.status}: {body[:200]}")

def main():
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
    if not token or not chat_id:
        print('TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID no configurados — skip notifier')
        return 0

    if not os.path.exists(LISTINGS_FILE):
        print(f'{LISTINGS_FILE} no existe — skip')
        return 0

    listings = json.load(open(LISTINGS_FILE)).get('listings', [])
    cca = json.load(open(CCA_FILE)).get('prices', {}) if os.path.exists(CCA_FILE) else {}
    if not cca:
        print('cca_precios.json no disponible — no puedo clasificar gangas')
        return 0

    bootstrap = not os.path.exists(STATE_FILE)
    if bootstrap:
        seed_new = sorted({l['id'] for l in listings if l.get('is_new')})
        seed_drops = {l['id']: l['precio_usd'] for l in listings if l.get('recent_price_drop')}
        json.dump({'new_seen': seed_new, 'drop_notified_price': seed_drops,
                   'last_run': datetime.utcnow().isoformat() + 'Z'},
                  open(STATE_FILE, 'w'), indent=2)
        print(f'Bootstrap: estado inicial ({len(seed_new)} ids semilla), sin notificar')
        return 0

    state = json.load(open(STATE_FILE))
    seen_ids = set(state.get('new_seen', []))
    drop_prices = state.get('drop_notified_price', {})

    new_gangas, drop_gangas = [], []
    for l in listings:
        t = tag(l, cca)
        if not t:
            continue
        lid = l['id']
        if l.get('is_new') and t == 'super_ganga' and lid not in seen_ids:
            new_gangas.append(l)
        if l.get('recent_price_drop') and l.get('recent_drop_pct', 0) >= MIN_DROP_PCT:
            last = drop_prices.get(lid)
            if last is None or l['precio_usd'] < last:
                drop_gangas.append(l)

    if not new_gangas and not drop_gangas:
        print('Sin nuevas super-gangas ni bajadas relevantes')
        return 0

    today = datetime.utcnow().date().isoformat()
    parts = [f"🔥 <b>Ganga Hunter · {today}</b>", ""]
    if new_gangas:
        new_gangas.sort(key=lambda l: discount_pct(l, cca) or 0, reverse=True)
        top = new_gangas[:MAX_PER_SECTION]
        parts.append(f"🆕 <b>Super gangas nuevas ({len(top)}/{len(new_gangas)})</b>")
        parts.extend(fmt_listing(l, cca) for l in top)
        parts.append("")
    if drop_gangas:
        drop_gangas.sort(key=lambda l: l.get('recent_drop_pct', 0), reverse=True)
        top = drop_gangas[:MAX_PER_SECTION]
        parts.append(f"📉 <b>Bajaron de precio ({len(top)}/{len(drop_gangas)})</b>")
        parts.extend(fmt_listing(l, cca, show_drop=True) for l in top)

    send_telegram(token, chat_id, '\n\n'.join(parts)[:4000])
    print(f'Telegram enviado: {len(new_gangas)} nuevas + {len(drop_gangas)} bajadas')

    for l in new_gangas:
        seen_ids.add(l['id'])
    for l in drop_gangas:
        drop_prices[l['id']] = l['precio_usd']
    json.dump({'new_seen': sorted(seen_ids),
               'drop_notified_price': drop_prices,
               'last_run': datetime.utcnow().isoformat() + 'Z'},
              open(STATE_FILE, 'w'), indent=2)
    return 0

if __name__ == '__main__':
    sys.exit(main())
