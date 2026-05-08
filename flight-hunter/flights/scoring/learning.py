"""
Auto-learning baseline.

Each daily run appends every flight we saw to history. After enough samples
per route, we trust the empirical distribution over the hardcoded estimates.

History schema (one entry per flight per day):
{
  "EZE-MAD": [
    {"date": "2026-05-07", "price_usd": 640, "airline": "Iberia"},
    {"date": "2026-05-08", "price_usd": 720, "airline": "Air Europa"},
    ...
  ],
  ...
}

Constraints:
  - We keep only the last 90 days per route (rolling window).
  - We dedupe (route_key, date, price_usd) so re-runs the same day don't blow it up.
  - Learned stats override hardcoded only if sample count >= min_samples.
"""
from __future__ import annotations

import statistics
from datetime import date, timedelta


HISTORY_WINDOW_DAYS = 90


def update_history(history: dict, flights: list[dict], today: str) -> dict:
    """Append today's flights to per-route history, keep rolling window."""
    cutoff = (date.fromisoformat(today) - timedelta(days=HISTORY_WINDOW_DAYS)).isoformat()

    for f in flights:
        rk = f["route_key"]
        bucket = history.setdefault(rk, [])
        entry = {
            "date": today,
            "price_usd": f["price_usd"],
            "airline": f.get("airline", ""),
        }
        # Dedupe within the same day: don't store identical (date, price, airline) twice
        key = (entry["date"], round(entry["price_usd"]), entry["airline"])
        if any((e["date"], round(e["price_usd"]), e.get("airline", "")) == key for e in bucket):
            continue
        bucket.append(entry)

    # Trim each route to the rolling window
    for rk, bucket in history.items():
        history[rk] = [e for e in bucket if e["date"] >= cutoff]

    return history


def build_learned_baseline(history: dict, min_samples: int = 15) -> dict[str, dict]:
    """For each route with enough samples, derive baseline stats from history."""
    learned = {}
    for rk, entries in history.items():
        if len(entries) < min_samples:
            continue
        prices = sorted(e["price_usd"] for e in entries)
        n = len(prices)
        avg = statistics.mean(prices)
        median = statistics.median(prices)
        p25 = prices[max(0, n // 4)]
        # exceptional = best 10% seen
        exceptional = prices[max(0, n // 10)]
        learned[rk] = {
            "historical_avg": round(avg, 2),
            "historical_min": round(prices[0], 2),
            "expected_low": round(p25, 2),
            "exceptional_threshold": round(exceptional, 2),
            "samples": n,
            "median": round(median, 2),
            "_learned": True,
        }
    return learned


def merge_baselines(hardcoded: dict, learned: dict) -> dict:
    """Learned values override hardcoded for routes where they exist."""
    out = {}
    keys = set(hardcoded) | set(learned)
    for k in keys:
        if k in learned:
            base = dict(hardcoded.get(k, {}))
            base.update(learned[k])
            out[k] = base
        else:
            out[k] = dict(hardcoded[k])
            out[k]["_learned"] = False
    return out
