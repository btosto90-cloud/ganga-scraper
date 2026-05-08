"""
Flight Hunter scoring — Python port of the v1 logic.

For each flight we compute:
  - qualScore: itinerary quality 0-100 (stops, duration, baggage, airline...)
  - dealScore: overall opportunity 0-100 (weighted combination)
  - errorFare detection (flags + level)
  - earlyAlert: true if it just dropped agressively
  - category: tier label + emoji
  - mainReason: human-readable summary
  - searchLinks: deeplinks to Skyscanner / Google Flights / Kayak / Momondo
"""
from __future__ import annotations

from .deeplinks import build_search_links

GANGA_THRESHOLD = 0.85
SUPER_GANGA_THRESHOLD = 0.75

# Mode weights (same as v1)
MODE_WEIGHTS = {
    "viaje_personal":   {"hist": 0.35, "mkt": 0.20, "qual": 0.20, "rare": 0.10, "cond": 0.10, "conf": 0.05},
    "maximo_ahorro":    {"hist": 0.45, "mkt": 0.25, "qual": 0.10, "rare": 0.10, "cond": 0.05, "conf": 0.05},
    "error_fare":       {"hist": 0.30, "mkt": 0.10, "qual": 0.10, "rare": 0.40, "cond": 0.05, "conf": 0.05},
    "ejecutivo":        {"hist": 0.20, "mkt": 0.15, "qual": 0.40, "rare": 0.05, "cond": 0.15, "conf": 0.05},
    "escapadas":        {"hist": 0.30, "mkt": 0.20, "qual": 0.25, "rare": 0.10, "cond": 0.10, "conf": 0.05},
    "flexible_total":   {"hist": 0.40, "mkt": 0.25, "qual": 0.15, "rare": 0.10, "cond": 0.05, "conf": 0.05},
}


# ---------------------------------------------------------------------------
# Quality
# ---------------------------------------------------------------------------
def calculate_quality_score(f: dict, route: dict | None) -> tuple[int, list[dict]]:
    """Return (qualScore, reasons[])."""
    score = 100
    reasons: list[dict] = []

    # Stops
    if f["stops"] == 0:
        reasons.append({"kind": "good", "text": "Vuelo directo"})
    elif f["stops"] == 1:
        if f.get("is_partial_direct"):
            score -= 5
            reasons.append({"kind": "neutral", "text": "Un tramo directo, otro con escala"})
        else:
            score -= 8
            reasons.append({"kind": "neutral", "text": "1 escala"})
    elif f["stops"] == 2:
        score -= 28
        reasons.append({"kind": "bad", "text": "2 escalas"})
    else:
        score -= 50
        reasons.append({"kind": "bad", "text": f"{f['stops']} escalas"})

    # Duration vs route average (only if we have it)
    avg_dur = (route or {}).get("avg_duration_min", 0) or 0
    if avg_dur and f.get("duration_minutes"):
        ratio = f["duration_minutes"] / avg_dur
        if ratio > 1.6:
            score -= 18
            reasons.append({"kind": "bad", "text": f"Duración {round(f['duration_minutes']/60)}h, mucho más larga que el promedio"})
        elif ratio > 1.3:
            score -= 10
            reasons.append({"kind": "neutral", "text": "Duración un poco larga"})

    # Baggage on long route
    if not f.get("baggage_included") and (f.get("duration_minutes") or 0) > 240:
        score -= 16
        reasons.append({"kind": "bad", "text": "Sin equipaje en vuelo largo"})
    elif f.get("baggage_included"):
        reasons.append({"kind": "good", "text": "Equipaje incluido"})

    # Low cost
    if f.get("is_low_cost"):
        score -= 6
        reasons.append({"kind": "neutral", "text": "Aerolínea low-cost"})

    # Airline reputation
    aq = f.get("airline_quality", 6)
    if aq < 5:
        score -= 10
        reasons.append({"kind": "bad", "text": f"{f.get('airline','?')}: reputación pobre"})
    elif aq >= 8:
        reasons.append({"kind": "good", "text": f"{f.get('airline','?')}: aerolínea sólida"})

    # Tax included
    if not f.get("tax_included", True):
        score -= 12
        reasons.append({"kind": "bad", "text": "Precio sin impuestos finales"})

    return max(0, min(100, score)), reasons


# ---------------------------------------------------------------------------
# Deal score
# ---------------------------------------------------------------------------
def calculate_deal_score(f: dict, route: dict | None, mode: str, market_avg_usd: float | None) -> dict:
    w = MODE_WEIGHTS.get(mode, MODE_WEIGHTS["viaje_personal"])

    # 1. Discount vs historical avg
    hist_score = 50.0
    if route and route.get("historical_avg"):
        hist_avg = route["historical_avg"]
        ratio = f["price_usd"] / hist_avg
        if ratio >= 1.0:
            hist_score = max(0, 50 - (ratio - 1) * 100)
        elif ratio >= GANGA_THRESHOLD:
            hist_score = 50 + (1 - ratio) / (1 - GANGA_THRESHOLD) * 25
        elif ratio >= SUPER_GANGA_THRESHOLD:
            hist_score = 75 + (GANGA_THRESHOLD - ratio) / (GANGA_THRESHOLD - SUPER_GANGA_THRESHOLD) * 20
        else:
            hist_score = min(100, 95 + (SUPER_GANGA_THRESHOLD - ratio) * 20)

    # 2. Discount vs current market avg (other flights of same route in this run)
    mkt_score = 50.0
    if market_avg_usd and market_avg_usd > 0:
        ratio = f["price_usd"] / market_avg_usd
        if ratio >= 1.0:
            mkt_score = max(0, 50 - (ratio - 1) * 80)
        elif ratio >= 0.85:
            mkt_score = 50 + (1 - ratio) * 200
        elif ratio >= 0.70:
            mkt_score = 80 + (0.85 - ratio) * 100
        else:
            mkt_score = min(100, 95 + (0.70 - ratio) * 30)

    # 3. Quality
    qual_score, qual_reasons = calculate_quality_score(f, route)

    # 4. Rarity
    rare_score = 30.0
    if route:
        hist_min = route.get("historical_min", 0) or 0
        exc = route.get("exceptional_threshold", 0) or 0
        p25 = route.get("expected_low", 0) or 0
        if hist_min and f["price_usd"] <= hist_min:
            rare_score = 100
        elif exc and f["price_usd"] <= exc:
            rare_score = 85
        elif p25 and f["price_usd"] <= p25:
            rare_score = 60
        elif hist_min and f["price_usd"] <= hist_min * 1.3:
            rare_score = 45
        else:
            rare_score = 20

    # 5. Conditions
    cond_score = 50.0
    if f.get("baggage_included"):
        cond_score += 25
    if f.get("tax_included", True):
        cond_score += 15
    else:
        cond_score -= 30
    if f.get("refundable"):
        cond_score += 10
    cond_score = max(0, min(100, cond_score))

    # 6. Confidence
    conf_score = (f.get("confidence", 0.7)) * 100

    final = (
        hist_score * w["hist"]
        + mkt_score * w["mkt"]
        + qual_score * w["qual"]
        + rare_score * w["rare"]
        + cond_score * w["cond"]
        + conf_score * w["conf"]
    )

    # REGLA DE ORO: low quality limits the ceiling in non-aggressive modes
    if mode not in ("error_fare", "maximo_ahorro", "flexible_total"):
        if qual_score < 25:
            final = min(final, 55)
        elif qual_score < 40:
            final = min(final, 70)

    # Low confidence cap
    if f.get("confidence", 0.7) < 0.4:
        final = min(final, 75)

    return {
        "score": round(max(0, min(100, final))),
        "breakdown": {
            "hist": round(hist_score),
            "mkt": round(mkt_score),
            "qual": qual_score,
            "rare": round(rare_score),
            "cond": round(cond_score),
            "conf": round(conf_score),
        },
        "qualReasons": qual_reasons,
    }


# ---------------------------------------------------------------------------
# Error fare detection
# ---------------------------------------------------------------------------
def detect_error_fare(f: dict, route: dict | None) -> dict:
    if not route:
        return {"is_error_fare": False, "level": "none", "flags": []}
    hist_avg = route.get("historical_avg", 0) or 0
    hist_min = route.get("historical_min", 0) or 0
    if not hist_avg:
        return {"is_error_fare": False, "level": "none", "flags": []}

    ratio = f["price_usd"] / hist_avg
    flags = []
    if ratio < 0.6:
        flags.append("price_40pct_below_avg")
    if hist_min and f["price_usd"] < hist_min:
        flags.append("below_historical_min")
    if f.get("confidence", 0.8) < 0.5:
        flags.append("low_confidence_source")
    if not f.get("tax_included", True) and ratio < 0.75:
        flags.append("no_taxes_and_cheap")

    if len(flags) >= 2:
        level = "likely"
    elif "below_historical_min" in flags or "price_40pct_below_avg" in flags:
        level = "possible"
    else:
        level = "none"

    return {"is_error_fare": level != "none", "level": level, "flags": flags}


# ---------------------------------------------------------------------------
# Early alert
# ---------------------------------------------------------------------------
def detect_early_alert(f: dict, route: dict | None, deal_score: int) -> bool:
    if not route:
        return False
    hist_avg = route.get("historical_avg", 0) or 0
    hist_min = route.get("historical_min", 0) or 0
    if not hist_avg or not hist_min:
        return False
    discount = 1 - f["price_usd"] / hist_avg
    return (
        discount > 0.25
        and f["price_usd"] < hist_min * 1.15
        and deal_score >= 70
        and f.get("confidence", 0.8) >= 0.7
    )


# ---------------------------------------------------------------------------
# Categorization
# ---------------------------------------------------------------------------
def categorize(score: int) -> dict:
    if score >= 90:
        return {"tier": "GANGA EXTRAORDINARIA", "emoji": "🔥", "cls": "extraordinaria"}
    if score >= 80:
        return {"tier": "EMITIR URGENTE", "emoji": "⚡", "cls": "urgente"}
    if score >= 70:
        return {"tier": "MUY BUENA OPORTUNIDAD", "emoji": "⭐", "cls": "muy-buena"}
    if score >= 60:
        return {"tier": "BUEN PRECIO", "emoji": "✓", "cls": "buen-precio"}
    if score >= 50:
        return {"tier": "MIRAR PERO NO CORRER", "emoji": "👁", "cls": "mirar"}
    return {"tier": "NO PRIORIZAR", "emoji": "—", "cls": "no-priorizar"}


# ---------------------------------------------------------------------------
# Main reason text
# ---------------------------------------------------------------------------
def build_main_reason(f: dict, route: dict | None, error_fare: dict) -> str:
    if not route:
        return "Sin histórico de la ruta. Score basado en condiciones del itinerario."
    hist_avg = route.get("historical_avg", 0) or 0
    parts = []
    if hist_avg:
        discount = round((1 - f["price_usd"] / hist_avg) * 100)
        if discount > 0:
            parts.append(f"<strong>{discount}% debajo del histórico</strong> (avg ~USD {round(hist_avg)})")
        elif discount < -5:
            parts.append(f"<strong>{abs(discount)}% por encima del histórico</strong>")
        else:
            parts.append("precio en línea con el histórico")

    if f["stops"] == 0:
        parts.append("vuelo directo")
    elif f["stops"] == 1 and f.get("is_partial_direct"):
        parts.append("un tramo directo")
    elif f["stops"] == 1:
        parts.append("una escala")
    else:
        parts.append(f"{f['stops']} escalas")

    parts.append("equipaje incluido" if f.get("baggage_included") else "sin equipaje")

    if error_fare["is_error_fare"]:
        parts.append("posible tarifa error")

    return " · ".join(parts)


# ---------------------------------------------------------------------------
# Enrich
# ---------------------------------------------------------------------------
def enrich_flight(f: dict, baseline: dict, all_flights: list[dict], mode: str = "viaje_personal") -> dict:
    route = baseline.get(f["route_key"])

    # Current market avg = mean USD of other flights with same route_key
    same = [x for x in all_flights if x["route_key"] == f["route_key"] and x["id"] != f["id"]]
    market_avg_usd = (sum(x["price_usd"] for x in same) / len(same)) if same else None

    # Pre-compute deal score for every mode so the frontend can switch instantly
    deal_by_mode = {}
    for m in MODE_WEIGHTS:
        result = calculate_deal_score(f, route, m, market_avg_usd)
        deal_by_mode[m] = result["score"]

    # The headline score is the default mode (viaje_personal)
    deal = calculate_deal_score(f, route, mode, market_avg_usd)
    error_fare = detect_error_fare(f, route)
    cat = categorize(deal["score"])
    early = detect_early_alert(f, route, deal["score"])
    main_reason = build_main_reason(f, route, error_fare)

    return {
        **f,
        "route": route,
        "marketAvgUSD": round(market_avg_usd, 2) if market_avg_usd else None,
        "dealScore": deal["score"],
        "dealScoreByMode": deal_by_mode,
        "dealBreakdown": deal["breakdown"],
        "qualScore": deal["breakdown"]["qual"],
        "qualReasons": deal["qualReasons"],
        "category": cat,
        "errorFare": error_fare,
        "earlyAlert": early,
        "mainReason": main_reason,
        "searchLinks": build_search_links(f),
    }
