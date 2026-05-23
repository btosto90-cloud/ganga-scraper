"""
Resolver de precio REAL por vuelo vía SerpApi (motor Google Flights).

promociones-aereas publica un precio "desde" (gancho) sin precio por fecha.
Este módulo consulta Google Flights (vía SerpApi) para la ruta+fechas reales del
deal y trae el precio REAL más barato, en USD, mercado AR (incluye low-cost).

Bonus: Google Flights devuelve "price_insights" con:
  - lowest_price   : el más barato real
  - price_level    : "low" | "typical" | "high"  (la propia opinión de Google)
  - typical_price_range : [min, max] histórico de la ruta
Eso nos deja decir, honestamente, si es ganga de verdad.

Key: variable de entorno SERPAPI_KEY.
  - Si NO hay key, todas las funciones devuelven None → el pipeline sigue igual
    (precio "desde", comportamiento actual). No rompe nada.

Presupuesto: el free tier de SerpApi son 250 búsquedas/mes. El pipeline solo
resuelve los MEJORES deals del día (ver resolve_top_flights) para no pasarse.

Docs: https://serpapi.com/google-flights-api
"""
from __future__ import annotations

import functools
import json
import os
import urllib.parse
import urllib.request

KEY = os.environ.get("SERPAPI_KEY", "").strip()
ENDPOINT = "https://serpapi.com/search.json"
CURRENCY = "USD"

# Cuántos vuelos como máximo resolvemos por corrida (cuida el free tier de 250/mes).
MAX_RESOLVE = int(os.environ.get("FLIGHT_PRICE_MAX_RESOLVE", "8"))


def has_key() -> bool:
    return bool(KEY)


def _get(params: dict) -> dict:
    url = ENDPOINT + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "flight-hunter/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


@functools.lru_cache(maxsize=512)
def cheapest_for_route(
    origin: str,
    destination: str,
    outbound_date: str,
    return_date: str | None = None,
) -> dict | None:
    """Precio real más barato (USD) para la ruta en las fechas dadas, vía Google Flights.

    outbound_date / return_date: 'YYYY-MM-DD' exactas (Google Flights necesita día).
    Devuelve {real_price_usd, price_level, typical_low, typical_high, airline,
              stops, link, source} o None.
    """
    if not KEY or not origin or not destination or not outbound_date:
        return None

    params = {
        "engine": "google_flights",
        "departure_id": origin,
        "arrival_id": destination,
        "outbound_date": outbound_date,
        "currency": CURRENCY,
        "hl": "es",
        "gl": "ar",
        "api_key": KEY,
    }
    if return_date:
        params["return_date"] = return_date
        params["type"] = "1"   # round trip
    else:
        params["type"] = "2"   # one way

    try:
        data = _get(params)
    except Exception as e:
        print(f"[price_resolver] {origin}-{destination} {outbound_date}: {type(e).__name__}: {str(e)[:90]}")
        return None

    if data.get("error"):
        print(f"[price_resolver] {origin}-{destination}: API error: {str(data['error'])[:90]}")
        return None

    best = (data.get("best_flights") or []) + (data.get("other_flights") or [])
    insights = data.get("price_insights") or {}

    # Precio real: el menor entre las ofertas; si no hay, el lowest_price de insights.
    prices = [b.get("price") for b in best if isinstance(b.get("price"), (int, float))]
    real_price = min(prices) if prices else insights.get("lowest_price")
    if not real_price:
        return None

    # Tomar metadata del vuelo más barato si existe
    cheapest = min((b for b in best if b.get("price")), key=lambda b: b["price"], default=None)
    airline = None
    stops = None
    if cheapest and cheapest.get("flights"):
        legs = cheapest["flights"]
        airline = legs[0].get("airline")
        stops = max(0, len(legs) - 1)

    rng = insights.get("typical_price_range") or [None, None]
    return {
        "real_price_usd": round(float(real_price)),
        "price_level": insights.get("price_level"),          # low | typical | high
        "typical_low": rng[0],
        "typical_high": rng[1],
        "airline": airline,
        "stops": stops,
        "link": data.get("search_metadata", {}).get("google_flights_url"),
        "source": "google_flights",
    }


def resolve_flight(f: dict) -> dict | None:
    """Resuelve el precio real para un flight normalizado (usa sus fechas reales)."""
    dep = f.get("departure_date")
    ret = f.get("return_date")
    if not dep:
        return None
    return cheapest_for_route(f.get("origin"), f.get("destination"), dep, ret)


def resolve_top_flights(flights: list[dict], rank_key=lambda f: f.get("dealScore", 0)) -> int:
    """Resuelve el precio real SOLO de los mejores `MAX_RESOLVE` vuelos (cuida la cuota).

    Muta cada flight in-place agregando: real_price_usd, price_level, typical_low/high,
    real_link, real_source, has_real_price. Devuelve cuántos resolvió.
    """
    if not has_key():
        return 0
    ordered = sorted(flights, key=rank_key, reverse=True)
    done = 0
    for f in ordered:
        if done >= MAX_RESOLVE:
            break
        res = resolve_flight(f)
        if not res:
            continue
        f["real_price_usd"] = res["real_price_usd"]
        f["price_level"] = res["price_level"]
        f["typical_low"] = res["typical_low"]
        f["typical_high"] = res["typical_high"]
        f["real_link"] = res["link"]
        f["real_source"] = res["source"]
        f["has_real_price"] = True

        # El veredicto REAL de Google manda sobre el score/tier del gancho, así la
        # tarjeta es coherente (nada de "EMITIR URGENTE" + "precio alto").
        lvl = res.get("price_level")
        if lvl == "low":
            f["dealScore"] = max(f.get("dealScore", 0), 90)
            f["category"] = {"tier": "GANGA VERIFICADA", "emoji": "🟢", "cls": "extraordinaria"}
        elif lvl == "high":
            f["dealScore"] = 30
            f["category"] = {"tier": "PRECIO ALTO (verificado)", "emoji": "🔴", "cls": "no-priorizar"}
        else:  # typical (o sin nivel)
            f["dealScore"] = 58
            f["category"] = {"tier": "PRECIO NORMAL (verificado)", "emoji": "🟡", "cls": "buen-precio"}
        done += 1
    print(f"[price_resolver] precio real resuelto en {done} vuelos (cap {MAX_RESOLVE})")
    return done


if __name__ == "__main__":
    # Prueba rápida (necesita SERPAPI_KEY):
    #   SERPAPI_KEY=xxx python3 -m scoring.price_resolver
    if not has_key():
        print("⚠️  No hay SERPAPI_KEY seteado. Exportalo y reintenta.")
        raise SystemExit(1)
    tests = [
        ("COR", "MIA", "2026-06-15", "2026-06-25"),
        ("EZE", "JFK", "2026-06-08", "2026-06-16"),
        ("EZE", "MAD", "2026-07-10", "2026-07-24"),
    ]
    for o, d, ob, rb in tests:
        print(f"{o}-{d} {ob}->{rb}:", cheapest_for_route(o, d, ob, rb))
