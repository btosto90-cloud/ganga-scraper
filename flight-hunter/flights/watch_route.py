"""
Vigilante de UNA sola ruta — escanea a fondo el espacio de fechas de la ruta
configurada en watch.json y gasta toda la cuota de SerpApi solo en eso.

Por qué existe: pelearle a Turismo City como buscador general es inútil (ellos
tienen tarifas a escala; nosotros dependíamos de un blog + cuota chica). El único
nicho donde un tool propio gana: vigilar TU ruta a fondo y avisarte por Telegram
apenas toca su mejor precio, sin que entres a mirar.

Config: watch.json (origen, destino, ventanas de ida/vuelta, paso, precio objetivo).
Credenciales: SERPAPI_KEY (env) para precios, TELEGRAM_* (env) para alertas.

Salida:
  - public/data/watch.json : lo que lee el frontend (mejor precio + grilla + historial)
  - data/watch_state.json  : best histórico + historial + dedup de alertas
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from scoring.price_resolver import cheapest_for_route, has_key, MAX_RESOLVE
from scoring import notify

import os

BASE = Path(__file__).parent
CONFIG_FILE = BASE / "watch.json"
OUT_FILE = BASE / "public" / "data" / "watch.json"
STATE_FILE = BASE / "data" / "watch_state.json"

# Tope de pares (ida,vuelta) por corrida. Cuida la cuota de SerpApi.
# 25 pares/día ≈ 750/mes (entra en Starter 1.000 con margen). Los repetidos
# dentro del cache de SerpApi no recuentan.
MAX_PAIRS = int(os.environ.get("FLIGHT_WATCH_MAX_PAIRS", "25"))
ALERT_DEDUP_SEC = 24 * 3600


def _load_config() -> dict:
    cfg = json.loads(CONFIG_FILE.read_text())
    cfg.setdefault("trip", "round")
    cfg.setdefault("step_days", 2)
    cfg.setdefault("target_price_usd", None)
    # Penalización USD por escala: las escalas pesan en elegir el "mejor".
    # Un 2-escalas barato no le gana a un directo/1-escala apenas más caro.
    cfg.setdefault("stop_penalty_usd", 250)
    return cfg


def _effective_score(row: dict, penalty: float) -> float:
    """Precio ajustado por escalas (lo que usamos para rankear, no para mostrar).
    stops desconocido = se asume 1 escala."""
    stops = row.get("stops")
    if stops is None:
        stops = 1
    return row["price_usd"] + penalty * stops


def _date_range(start: str, end: str, step: int) -> list[str]:
    d0 = date.fromisoformat(start)
    d1 = date.fromisoformat(end)
    out = []
    d = d0
    while d <= d1:
        out.append(d.isoformat())
        d += timedelta(days=step)
    return out


def _build_pairs(cfg: dict) -> list[tuple[str, str | None]]:
    step = cfg["step_days"]
    outs = _date_range(cfg["outbound_start"], cfg["outbound_end"], step)
    if cfg["trip"] == "oneway":
        return [(o, None) for o in outs]
    rets = _date_range(cfg["return_start"], cfg["return_end"], step)
    return [(o, r) for o in outs for r in rets]


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"best_ever_usd": None, "history": [], "last_alert": {}}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def _fmt_alert(cfg: dict, best: dict, reason: str) -> str:
    o, d = cfg["origin"], cfg["destination"]
    p = best["price_usd"]
    tl, th = best.get("typical_low"), best.get("typical_high")
    typ = f" (típico USD {int(tl)}-{int(th)})" if tl and th else ""
    disc = ""
    if tl and th and p:
        mid = (tl + th) / 2
        disc = f" · ~{round((1 - p / mid) * 100)}% bajo lo normal"
    stops = "directo" if best.get("stops") == 0 else f"{best.get('stops', 1)} escala(s)"
    ret = f" → {best['return_date']}" if best.get("return_date") else ""
    link = best.get("link") or ""
    emoji = "🟢" if best.get("price_level") == "low" else "✈️"
    return (
        f"{emoji} <b>{reason} · {o} → {d}</b>\n"
        f"<b>USD {p}</b>{typ}{disc}\n"
        f"📅 {best.get('departure_date')}{ret} · {best.get('airline') or '?'} · {stops}\n"
        f"🔗 {link}"
    )


def main() -> None:
    cfg = _load_config()
    if not has_key():
        print("[watch] sin SERPAPI_KEY — no puedo traer precios reales. Abortando.")
        return

    pairs = _build_pairs(cfg)
    if len(pairs) > MAX_PAIRS:
        # Submuestreo uniforme para no pasarse del cap (mantiene los extremos).
        idx = [round(i * (len(pairs) - 1) / (MAX_PAIRS - 1)) for i in range(MAX_PAIRS)]
        pairs = [pairs[i] for i in sorted(set(idx))]
    print(f"[watch] {cfg['origin']}-{cfg['destination']} {cfg['trip']} · escaneando {len(pairs)} pares (cap {MAX_PAIRS})")

    results: list[dict] = []
    for out, ret in pairs:
        res = cheapest_for_route(cfg["origin"], cfg["destination"], out, ret)
        if not res:
            print(f"[watch]   {out} -> {ret}: sin datos")
            continue
        row = {
            "departure_date": out,
            "return_date": ret,
            "price_usd": res["real_price_usd"],
            "price_level": res.get("price_level"),
            "typical_low": res.get("typical_low"),
            "typical_high": res.get("typical_high"),
            "airline": res.get("airline"),
            "stops": res.get("stops"),
            "link": res.get("link"),
        }
        results.append(row)
        print(f"[watch]   {out} -> {ret}: USD {row['price_usd']} ({row['price_level']}, {row['stops']}esc)")

    if not results:
        print("[watch] ningún precio resuelto — no escribo nada nuevo.")
        return

    # Rankear por precio + penalización por escala (las escalas pesan); mostrar precio real.
    penalty = cfg["stop_penalty_usd"]
    for r in results:
        r["score"] = _effective_score(r, penalty)
    results.sort(key=lambda r: r["score"])
    best = results[0]
    print(f"[watch] (ranking con penalización USD {penalty}/escala)")
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    state = _load_state()
    prev_best = state.get("best_ever_usd")
    target = cfg.get("target_price_usd")

    # ¿Alertar? Nueva mínima histórica, o cruzó tu precio objetivo, o primera vez.
    new_low = prev_best is None or best["price_usd"] < prev_best
    hit_target = bool(target) and best["price_usd"] <= target
    first_run = not state.get("history")

    reason = None
    if hit_target:
        reason = "BAJO TU OBJETIVO"
    elif new_low and not first_run:
        reason = "NUEVA MÍNIMA"
    elif first_run:
        reason = "MEJOR PRECIO HOY"

    # Dedup: no re-alertar el mismo precio dentro de 24h.
    last = state.get("last_alert", {})
    dup = (last.get("price_usd") == best["price_usd"]
           and (time.time() - last.get("ts", 0)) < ALERT_DEDUP_SEC)

    if reason and not dup and notify.has_creds():
        if notify._send(_fmt_alert(cfg, best, reason)):
            state["last_alert"] = {"price_usd": best["price_usd"], "ts": int(time.time()), "reason": reason}
            print(f"[watch] alerta Telegram enviada: {reason} USD {best['price_usd']}")
    elif reason and not notify.has_creds():
        print(f"[watch] {reason} USD {best['price_usd']} (sin credenciales Telegram, no alerto)")
    else:
        print(f"[watch] mejor USD {best['price_usd']} — sin alerta (prev best {prev_best}, dup={dup})")

    # Actualizar estado
    if new_low:
        state["best_ever_usd"] = best["price_usd"]
        state["best_ever_detail"] = best
    state.setdefault("history", []).append({
        "checked_at": now_iso,
        "best_usd": best["price_usd"],
        "departure_date": best["departure_date"],
        "return_date": best.get("return_date"),
        "price_level": best.get("price_level"),
    })
    state["history"] = state["history"][-60:]
    _save_state(state)

    # Salida para el frontend
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps({
        "route": {"origin": cfg["origin"], "destination": cfg["destination"], "trip": cfg["trip"]},
        "window": {
            "outbound": [cfg["outbound_start"], cfg["outbound_end"]],
            "return": [cfg.get("return_start"), cfg.get("return_end")],
        },
        "generated_at": now_iso,
        "currency": "USD",
        "best": best,
        "best_ever_usd": state.get("best_ever_usd"),
        "results": results,
        "target_price_usd": target,
        "stop_penalty_usd": penalty,
        "history": state["history"],
    }, indent=2, ensure_ascii=False))
    print(f"[watch] mejor: USD {best['price_usd']} {best['departure_date']}→{best.get('return_date')} "
          f"({best.get('price_level')}). Escrito {OUT_FILE.name} con {len(results)} fechas.")


if __name__ == "__main__":
    main()
