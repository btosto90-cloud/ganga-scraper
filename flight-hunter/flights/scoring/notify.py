"""
Alertas de Telegram cuando aparece una 🟢 ganga verificada por Google.

Reusa el mismo bot/chat que el radar de autos (@Taste90Bot). Lee credenciales
de env: TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID. Si no están, no falla — el
pipeline sigue normal sin alertas.

Dedup: mantiene un state file con (route_key, depart, return) → timestamp.
No re-alerta una misma ganga dentro de las 24h (evita spam si baja+sube+baja).
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

STATE_FILE = Path(__file__).parent.parent / "data" / "flight_alerts_state.json"
DEDUP_WINDOW_SEC = 24 * 3600   # no re-alertar la misma ganga dentro de 24h


def has_creds() -> bool:
    return bool(TOKEN and CHAT_ID)


def _send(text: str, max_retries: int = 3) -> bool:
    """Manda un mensaje a Telegram. Devuelve True si fue OK."""
    if not has_creds():
        return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode()
    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": "flight-hunter/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                resp = json.loads(r.read())
                if resp.get("ok"):
                    return True
                print(f"[notify] Telegram no-OK: {resp}")
        except Exception as e:
            print(f"[notify] intento {attempt}/{max_retries} falló: {type(e).__name__}: {str(e)[:80]}")
            if attempt < max_retries:
                time.sleep(2 * attempt)
    return False


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _key(f: dict) -> str:
    return f"{f.get('route_key')}|{f.get('departure_date')}|{f.get('return_date')}"


def _format_flight(f: dict) -> str:
    """Mensaje conciso y legible en HTML para Telegram."""
    price = f.get("real_price_usd")
    typ_lo = f.get("typical_low") or 0
    typ_hi = f.get("typical_high") or 0
    discount_pct = ""
    if typ_lo and price:
        discount_pct = f" · ~{round((1 - price / ((typ_lo + typ_hi) / 2 if typ_hi else typ_lo)) * 100)}% bajo el típico"
    stops = "directo" if f.get("stops") == 0 else f"{f.get('stops', 1)} escala(s)"
    is_lc = f.get("is_low_cost")
    bag_est = (160 if (price or 0) > 700 else 100) if is_lc else 0
    bag_line = (f"\n🧳 + valija ~USD {bag_est} (low-cost) → con valija ≈ USD {price + bag_est}"
                if is_lc else "\n🧳 valija despachada típicamente incluida")
    dep = f.get("departure_date", "?")
    ret = f.get("return_date") or "?"
    dates_count = f.get("total_dates") or 1
    link = f.get("real_link") or f.get("booking_url") or ""
    return (
        f"🟢 <b>GANGA CONFIRMADA · {f.get('origin')} → {f.get('destination')}</b>\n"
        f"<b>USD {price}</b> (típico {int(typ_lo)}-{int(typ_hi)}){discount_pct}\n"
        f"✈️ {f.get('airline') or '?'} · {stops}{bag_line}\n"
        f"📅 {dep} → {ret} · {dates_count} fechas disponibles\n"
        f"🔗 {link}"
    )


def alert_new_gangas(flights: list[dict]) -> int:
    """Alerta por Telegram las 🟢 (price_level='low') que no se hayan alertado en 24h.

    Devuelve cuántas alertas mandó.
    """
    if not has_creds():
        print("[notify] sin TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID — no alerto")
        return 0
    state = _load_state()
    now = int(time.time())
    # limpiar entries viejas (más de 24h) del state
    state = {k: v for k, v in state.items() if (now - v) < DEDUP_WINDOW_SEC}
    sent = 0
    for f in flights:
        if not f.get("has_real_price"):
            continue
        if f.get("price_level") != "low":
            continue
        k = _key(f)
        if k in state:
            continue
        msg = _format_flight(f)
        if _send(msg):
            state[k] = now
            sent += 1
        else:
            print(f"[notify] falló enviar alerta para {k}")
    _save_state(state)
    print(f"[notify] alertas enviadas: {sent} (state ahora {len(state)} entries)")
    return sent
