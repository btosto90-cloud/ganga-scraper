#!/usr/bin/env python3
"""ml_radar.py — Radar de gangas frescas de MercadoLibre.

Las gangas reales se venden en ~1 día (mediana de velocity_stats). El digest diario
llega tarde. Este radar escanea los avisos MÁS NUEVOS (página 1 por marca, ordenada
por recientes) cada pocas horas y alerta AL INSTANTE por Telegram cuando aparece una
super-ganga, para contactar al vendedor antes de que se venda.

Liviano: solo página 1 por marca (~22 fetches) vs el run diario completo (~220).
Reusa el parsing de ml_local, el scoring de scoring.py y el envío de notify.py.
Contexto de scoring (buckets/velocity) del listings.json del repo.

Estado en radar_state.json (ids ya alertados, para no repetir).
Telegram: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID (env o ~/.ganga-auto/telegram.env).
"""

import json
import os
import random
import time
from datetime import datetime

import ml_local   # EXTRACT_JS, parse_extracted, USER_AGENTS, MARCAS, UA_SAFARI
import scoring     # build_buckets/sold_index/velocity_index, compute_ganga_confidence
import notify      # send_telegram, fmt_listing
import vehicles    # PROVINCIAS_ZONA (zona de Bruno)

LISTINGS_FILE = 'listings.json'
VELOCITY_FILE = 'velocity_stats.json'
STATE_FILE = 'radar_state.json'

# Recordatorio one-shot por Telegram para armar el loop de calibración (data madura ~3 semanas)
REMINDER_CALIBRACION = '2026-06-12'

# Barra para alerta instantánea (moderada): super-ganga o ganga_v2 CONFIRMADA por
# ventas reales (no por bucket suelto) con descuento decente. Sigue evitando los
# falsos positivos de buckets chicos/contaminados (exige ancla de venta real).
ALERT_MIN_DISCOUNT = 20                              # % bajo el precio justo
ALERT_TAGS = ('super_ganga_v2', 'ganga_v2')          # super + ganga
ALERT_SOLD_SOURCES = ('venta_real', 'venta+pedido')  # ancla de venta real
MAX_ALERTS = 10                                      # tope por corrida


def is_alert_worthy(listing, result):
    """Alertar super-ganga o ganga_v2 + ancla de venta real + descuento >= umbral."""
    if result.get('tag') not in ALERT_TAGS:
        return False
    fair = result.get('fair') or {}
    if fair.get('source') not in ALERT_SOLD_SOURCES:
        return False
    price, fp = listing.get('precio_usd'), fair.get('fair')
    if not (price and fp):
        return False
    return (1 - price / fp) * 100 >= ALERT_MIN_DISCOUNT


def load_context():
    """Buckets/sold/velocity desde el listings.json del repo + set de ids ya conocidos."""
    listings = []
    if os.path.exists(LISTINGS_FILE):
        listings = json.load(open(LISTINGS_FILE)).get('listings', [])
    vstats = {}
    if os.path.exists(VELOCITY_FILE):
        vstats = json.load(open(VELOCITY_FILE)).get('stats', {})
    buckets = scoring.build_buckets(listings)
    sold_index = scoring.build_sold_index(vstats)
    velocity_index = scoring.build_velocity_index(vstats)
    existing_ids = {l.get('id') for l in listings if l.get('id')}
    return buckets, sold_index, velocity_index, existing_ids


def telegram_creds():
    tok = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    chat = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
    if tok and chat:
        return tok, chat
    envf = os.path.expanduser('~/.ganga-auto/telegram.env')
    if os.path.exists(envf):
        for line in open(envf):
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            if k.strip() == 'TELEGRAM_BOT_TOKEN' and not tok:
                tok = v.strip()
            elif k.strip() == 'TELEGRAM_CHAT_ID' and not chat:
                chat = v.strip()
    return tok, chat


def scrape_newest(pg, marca):
    """Página 1 de la marca ordenada por más recientes (con fallback a orden default)."""
    urls = [
        f"https://listado.mercadolibre.com.ar/autos-camionetas/{marca}-usado_OrderId_BEGINS*DESC_NoIndex_True",
        f"https://listado.mercadolibre.com.ar/autos-camionetas/{marca}-usado_NoIndex_True",
    ]
    for url in urls:
        try:
            pg.goto(url, wait_until='domcontentloaded', timeout=30000)
            time.sleep(2.5)
            try:
                pg.wait_for_selector('.poly-card, .ui-search-layout__item', timeout=12000)
            except Exception:
                pass
            pg.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
            time.sleep(0.8)
            items = pg.evaluate(ml_local.EXTRACT_JS)
            parsed = ml_local.parse_extracted(items, marca)
            if parsed:
                return parsed
        except Exception:
            continue
    return []


def scrape_region(pg, provincia):
    """Página 1 de TODAS las marcas en una provincia, ordenada por más recientes.
    Sirve para captar gangas frescas en la zona de Bruno (que el scan nacional casi no muestra).
    """
    urls = [
        f"https://listado.mercadolibre.com.ar/{provincia}/autos-camionetas-usado_OrderId_BEGINS*DESC_NoIndex_True",
        f"https://listado.mercadolibre.com.ar/{provincia}/autos-camionetas-usado_NoIndex_True",
    ]
    for url in urls:
        try:
            pg.goto(url, wait_until='domcontentloaded', timeout=30000)
            time.sleep(2.5)
            try:
                pg.wait_for_selector('.poly-card, .ui-search-layout__item', timeout=12000)
            except Exception:
                pass
            pg.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
            time.sleep(0.8)
            items = pg.evaluate(ml_local.EXTRACT_JS)
            parsed = ml_local.parse_extracted(items, '')
            if parsed:
                return parsed
        except Exception:
            continue
    return []


def annotate_fresh(l, result):
    """Pega los campos de scoring al listing (para fmt_listing / debug)."""
    l['ganga_confidence'] = result['score']
    l['ganga_tag'] = result['tag']
    l['ganga_breakdown'] = result['breakdown']
    fair = result.get('fair')
    if fair and l.get('precio_usd') and fair.get('fair'):
        l['precio_justo'] = fair['fair']
        l['ref_fuente'] = fair['source']
        l['descuento_justo_pct'] = round((1 - l['precio_usd'] / fair['fair']) * 100, 1)
        l['precio_cca'] = fair['fair']
        l['descuento_cca_pct'] = l['descuento_justo_pct']
    bucket = result.get('bucket')
    if bucket:
        l['bucket_n'] = bucket['n']
        l['bucket_median_usd'] = bucket['median']
        l['bucket_z_score'] = bucket['z_score']


def main():
    from playwright.sync_api import sync_playwright

    buckets, sold_index, velocity_index, existing_ids = load_context()
    state = json.load(open(STATE_FILE)) if os.path.exists(STATE_FILE) else {}
    alerted = set(state.get('alerted', []))
    today = datetime.utcnow().date().isoformat()

    print(f"Radar: contexto {len(existing_ids)} ids conocidos, {len(alerted)} ya alertados")

    hallazgos = []
    scanned = 0
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=[
            '--no-sandbox', '--disable-blink-features=AutomationControlled', '--disable-dev-shm-usage',
        ])
        ctx = b.new_context(
            user_agent=random.choice(ml_local.USER_AGENTS),
            locale='es-AR', timezone_id='America/Argentina/Buenos_Aires',
        )
        pg = ctx.new_page()
        try:
            pg.goto('https://www.mercadolibre.com.ar/', wait_until='domcontentloaded', timeout=20000)
            time.sleep(2)
        except Exception:
            pass

        def procesar(parsed):
            nonlocal scanned
            scanned += len(parsed)
            for l in parsed:
                lid = l.get('id')
                if not lid or lid in existing_ids or lid in alerted:
                    continue  # ya conocido o ya alertado → no es fresco
                l['first_seen'] = today
                l['is_new'] = True
                result = scoring.compute_ganga_confidence(l, buckets, sold_index, velocity_index)
                if is_alert_worthy(l, result):
                    annotate_fresh(l, result)
                    hallazgos.append(l)
                    alerted.add(lid)

        # 1) Scan nacional por marca (gangas en todo el país)
        for marca in ml_local.MARCAS:
            procesar(scrape_newest(pg, marca))
            time.sleep(random.uniform(3, 5))

        # 2) Scan regional: provincias de la zona de Bruno (Córdoba/NOA/Cuyo)
        for prov in vehicles.PROVINCIAS_ZONA:
            procesar(scrape_region(pg, prov))
            time.sleep(random.uniform(3, 5))
        b.close()

    # Prioridad: primero las de TU ZONA, después por confianza
    hallazgos.sort(key=lambda l: (not l.get('en_zona'), -(l.get('ganga_confidence') or 0)))
    en_zona_n = sum(1 for l in hallazgos if l.get('en_zona'))
    print(f"Radar: escaneados {scanned} avisos, {len(hallazgos)} gangas frescas nuevas "
          f"({en_zona_n} en tu zona)")

    if hallazgos:
        tok, chat = telegram_creds()
        hora = datetime.now().strftime('%H:%M')
        if tok and chat:
            parts = [f"🚨 <b>Radar de gangas · {hora}</b>",
                     f"{len(hallazgos)} super-ganga(s) recién publicada(s) — contactá rápido:", ""]
            parts += [notify.fmt_listing(l, {}) for l in hallazgos[:MAX_ALERTS]]
            try:
                notify.send_telegram(tok, chat, "\n\n".join(parts)[:4000])
                print(f"Telegram enviado: {min(len(hallazgos), MAX_ALERTS)}")
            except Exception as e:
                print(f"Telegram falló: {e}")
        else:
            print("Sin credenciales Telegram (~/.ganga-auto/telegram.env) — solo log:")
            for l in hallazgos[:MAX_ALERTS]:
                print(f"  [{l.get('ganga_confidence')}] {(l.get('title') or '')[:42]} "
                      f"${l.get('precio_usd')} ({l.get('descuento_justo_pct')}% bajo justo) — {l.get('url')}")

    # Recordatorio one-shot: armar el loop de calibración cuando haya data madura.
    reminder_sent = state.get('reminder_calibracion_sent', False)
    if not reminder_sent and datetime.utcnow().date().isoformat() >= REMINDER_CALIBRACION:
        tok, chat = telegram_creds()
        if tok and chat:
            try:
                notify.send_telegram(tok, chat,
                    "🔔 <b>Recordatorio Ganga Hunter</b>\n\nYa pasaron ~3 semanas y hay data "
                    "acumulada de ventas. Es buen momento para armar el <b>loop de calibración</b> "
                    "(que el sistema aprenda de qué gangas se vendieron y afine los umbrales solo).\n\n"
                    "Pedíselo a Claude cuando quieras 🚗")
                reminder_sent = True
                print("Recordatorio de calibración enviado a Telegram")
            except Exception as e:
                print(f"Recordatorio falló: {e}")

    # Persistir estado (cap para no crecer infinito)
    state = {'alerted': sorted(alerted)[-8000:], 'last_run': datetime.utcnow().isoformat() + 'Z',
             'reminder_calibracion_sent': reminder_sent}
    json.dump(state, open(STATE_FILE, 'w'), indent=2)


if __name__ == '__main__':
    main()
