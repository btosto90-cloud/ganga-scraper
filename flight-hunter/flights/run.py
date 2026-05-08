"""
Flight Hunter — daily run.

Pipeline:
  1. Scrape sources (Promociones Aéreas).
  2. Normalize each raw offer into the unified flight schema.
  3. Update price history (rolling 90 days per route).
  4. Build hybrid route baseline (hardcoded + learned, learned wins after 15+ samples).
  5. Score every flight (Deal Score, Quality Score, error fare detection).
  6. Write data/flights.json (consumed by frontend) and data/price_history.json.

Run from CI or locally:
  python run.py
"""
from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from scrapers.promociones_aereas import PromocionesAereasSource
from scoring.normalize import normalize_offer
from scoring.route_baseline import HARDCODED_BASELINE
from scoring.learning import update_history, build_learned_baseline, merge_baselines
from scoring.score import enrich_flight

ROOT = Path(__file__).parent
PUBLIC_DATA = ROOT / "public" / "data"   # served by Netlify, read by frontend
INTERNAL_DATA = ROOT / "data"            # CI-only, accumulating history
PUBLIC_DATA.mkdir(parents=True, exist_ok=True)
INTERNAL_DATA.mkdir(exist_ok=True)

FLIGHTS_FILE = PUBLIC_DATA / "flights.json"
HISTORY_FILE = INTERNAL_DATA / "price_history.json"


def main() -> int:
    started = datetime.now(timezone.utc)
    print(f"[flight-hunter] start {started.isoformat()}")

    # 1. Scrape ----------------------------------------------------------
    sources = [PromocionesAereasSource()]
    raw_offers: list[dict] = []
    source_status: dict[str, dict] = {}

    for src in sources:
        try:
            offers = src.fetch()
            raw_offers.extend(offers)
            source_status[src.name] = {"ok": True, "count": len(offers)}
            print(f"[{src.name}] {len(offers)} offers")
        except Exception as e:
            traceback.print_exc()
            source_status[src.name] = {"ok": False, "error": str(e)}

    if not raw_offers:
        print("[flight-hunter] no offers scraped, aborting")
        # Still write a status file so frontend knows
        _write_empty(source_status, started)
        return 1

    # 2. Normalize -------------------------------------------------------
    flights = []
    for raw in raw_offers:
        try:
            f = normalize_offer(raw)
            if f:
                flights.append(f)
        except Exception as e:
            print(f"[normalize] skipped offer: {e}")

    print(f"[normalize] {len(flights)} flights normalized")

    # 3. Update history --------------------------------------------------
    history = _load_json(HISTORY_FILE) or {}
    history = update_history(history, flights, today=started.date().isoformat())
    _write_json(HISTORY_FILE, history)

    # 4. Hybrid baseline -------------------------------------------------
    learned = build_learned_baseline(history, min_samples=15)
    baseline = merge_baselines(HARDCODED_BASELINE, learned)

    # 5. Score every flight ---------------------------------------------
    enriched = [enrich_flight(f, baseline, flights) for f in flights]

    # 6. Write output ----------------------------------------------------
    output = {
        "generated_at": started.isoformat(),
        "total_flights": len(enriched),
        "sources": source_status,
        "stats": _build_stats(enriched),
        "flights": enriched,
    }
    _write_json(FLIGHTS_FILE, output)
    print(f"[flight-hunter] wrote {FLIGHTS_FILE} with {len(enriched)} flights")
    print(f"[flight-hunter] stats: {output['stats']}")
    return 0


def _build_stats(enriched: list[dict]) -> dict:
    if not enriched:
        return {}
    total = len(enriched)
    extraordinaria = sum(1 for f in enriched if f["dealScore"] >= 90)
    urgente = sum(1 for f in enriched if 80 <= f["dealScore"] < 90)
    error_fares = sum(1 for f in enriched if f["errorFare"]["is_error_fare"])
    early = sum(1 for f in enriched if f["earlyAlert"])
    avg = round(sum(f["dealScore"] for f in enriched) / total)
    return {
        "total": total,
        "ganga_extraordinaria": extraordinaria,
        "emitir_urgente": urgente,
        "top_oportunidades": extraordinaria + urgente,
        "error_fares": error_fares,
        "alertas_tempranas": early,
        "score_promedio": avg,
    }


def _write_empty(source_status: dict, started: datetime) -> None:
    output = {
        "generated_at": started.isoformat(),
        "total_flights": 0,
        "sources": source_status,
        "stats": {},
        "flights": [],
        "error": "no offers scraped — check source_status",
    }
    _write_json(FLIGHTS_FILE, output)


def _load_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
