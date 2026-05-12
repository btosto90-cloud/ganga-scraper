#!/usr/bin/env python3
"""debug_listing.py — debug de scoring por listing id.

Usage:
    python3 debug_listing.py <listing_id>
    python3 debug_listing.py --top 10              # top 10 ganga_confidence
    python3 debug_listing.py --tag super_ganga_v2  # listar todos los super_ganga_v2
    python3 debug_listing.py --model toyota_corolla_2020   # listar bucket
"""

import argparse
import json
import os
import sys

LISTINGS_FILE = 'listings.json'
CCA_FILE = 'cca_precios.json'
VELOCITY_FILE = 'velocity_stats.json'


def load():
    if not os.path.exists(LISTINGS_FILE):
        sys.exit(f"❌ {LISTINGS_FILE} no existe — corré scraper.py primero")
    with open(LISTINGS_FILE) as f:
        data = json.load(f)
    return data['listings']


def fmt_money(n):
    if n is None:
        return 'N/A'
    return f"USD {int(n):,}".replace(',', '.')


def show(l):
    print('━' * 70)
    print(f"  {l.get('title', '?')}")
    print(f"  ID: {l['id']}  · {l.get('fuente', '?').upper()}  · {l.get('url', '')}")
    print()
    print(f"  Año: {l.get('year')}  · KM: {l.get('km'):,}".replace(',', '.') if l.get('km') else f"  Año: {l.get('year')}  · KM: ?")
    print(f"  Trans: {l.get('trans')}  · Combustible: {l.get('fuel')}")
    print(f"  Precio pedido: {fmt_money(l.get('precio_usd'))}")
    print()

    # Anclas
    print("  ── ANCLAS ──")
    print(f"  CCA:        {fmt_money(l.get('precio_cca'))} "
          f"({'-' + str(l['descuento_cca_pct']) + '%' if l.get('descuento_cca_pct') is not None else 'sin match'})")
    if l.get('bucket_n'):
        print(f"  Bucket:     {l['bucket_n']} comparables · mediana {fmt_money(l['bucket_median_usd'])} "
              f"· z-score {l['bucket_z_score']}")
    else:
        print(f"  Bucket:     sin comparables suficientes")

    # Movimientos
    print()
    print("  ── MOVIMIENTOS ──")
    print(f"  Primer visto: {l.get('first_seen', '?')}  · Es nuevo hoy: {l.get('is_new', False)}")
    if l.get('price_history'):
        hist = l['price_history']
        print(f"  Historia precios: {len(hist)} entrada(s)")
        for h in hist[-3:]:
            print(f"    {h['fecha']}: {fmt_money(h['precio_usd'])}")
    if l.get('recent_price_drop'):
        print(f"  📉 Bajó {l.get('recent_drop_pct', 0)}% en el último run")
    print(f"  Bajadas totales: {l.get('price_drops', 0)} · Bajada acumulada: {l.get('price_drop_pct', 0)}%")

    # Score
    print()
    print("  ── GANGA CONFIDENCE ──")
    score = l.get('ganga_confidence')
    tag = l.get('ganga_tag', 'sin_referencia')
    if score is None:
        print(f"  Score: N/A ({tag})")
    else:
        bar = '█' * (score // 5) + '░' * (20 - score // 5)
        print(f"  Score: {score}/100  [{bar}]  → {tag}")
    breakdown = l.get('ganga_breakdown') or {}
    for k, v in breakdown.items():
        if v is None:
            print(f"    {k:<10}: N/A")
        else:
            mini = '▆' * (v // 10) + '·' * (10 - v // 10)
            print(f"    {k:<10}: {v:>3}/100 [{mini}]")
    print('━' * 70)


def cmd_top(listings, n=10):
    scored = [l for l in listings if l.get('ganga_confidence') is not None]
    scored.sort(key=lambda l: l['ganga_confidence'], reverse=True)
    for l in scored[:n]:
        show(l)


def cmd_tag(listings, tag):
    matched = [l for l in listings if l.get('ganga_tag') == tag]
    matched.sort(key=lambda l: l.get('ganga_confidence', 0), reverse=True)
    print(f"\n{len(matched)} listings con tag={tag}\n")
    for l in matched[:50]:
        show(l)


def cmd_model(listings, model_key):
    matched = [l for l in listings if l.get('model_key') == model_key]
    matched.sort(key=lambda l: l.get('precio_usd', 0))
    print(f"\n{len(matched)} listings de {model_key}\n")
    for l in matched:
        score = l.get('ganga_confidence')
        score_str = f"{score:>3}" if score is not None else " - "
        print(f"  [{score_str}] {fmt_money(l['precio_usd']):<14} "
              f"{l.get('km', 0):>7,} km".replace(',', '.') +
              f"  {l.get('title', '?')[:50]:<50} {l.get('url', '')}")


def cmd_id(listings, lid):
    for l in listings:
        if l.get('id') == lid:
            show(l)
            return
    print(f"No encontré listing con id={lid}")


def main():
    p = argparse.ArgumentParser(description='Inspector de scoring de Ganga Hunter')
    p.add_argument('id', nargs='?', help='ID del listing a inspeccionar')
    p.add_argument('--top', type=int, help='Top N por ganga_confidence')
    p.add_argument('--tag', help='Listar todos con un tag específico')
    p.add_argument('--model', help='Listar todos los listings de un model_key')
    args = p.parse_args()

    listings = load()
    if args.top:
        cmd_top(listings, args.top)
    elif args.tag:
        cmd_tag(listings, args.tag)
    elif args.model:
        cmd_model(listings, args.model)
    elif args.id:
        cmd_id(listings, args.id)
    else:
        p.print_help()


if __name__ == '__main__':
    main()
