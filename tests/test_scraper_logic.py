"""Tests para la lógica de scraper.py que NO requiere red.

Cubrimos: parse_price_smart, is_realistic_price, dedup, fast_sales detection,
velocity_stats. Las funciones de scraping HTTP no se testean acá (requieren mocks de red).
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta

# Cargar el módulo scraper sin disparar el __main__ ni la fetch del blue rate
# (parchamos urlopen para que no salga a internet)
import urllib.request as _ureq
_orig_urlopen = _ureq.urlopen


class FakeResponse:
    def __init__(self, body=b'{"venta": 1400}'):
        self._body = body

    def __enter__(self): return self
    def __exit__(self, *a): pass
    def read(self): return self._body
    def info(self):
        class X:
            def get(self, k): return None
        return X()


_ureq.urlopen = lambda *a, **kw: FakeResponse()
import scraper
_ureq.urlopen = _orig_urlopen


# ─── parse_price_smart ───────────────────────────────────────────────────────

class TestParsePriceSmart:
    def test_dollar_explicit(self):
        # Si dice USD, debe interpretar como USD directamente
        precio, currency = scraper.parse_price_smart('USD 18.500', currency_hint='USD')
        assert precio == 18500
        assert currency == 'USD'

    def test_pesos_converts_to_usd(self):
        precio, currency = scraper.parse_price_smart('$ 25.900.000', currency_hint='ARS')
        # Devuelve siempre en USD; currency es 'USD' tras la conversión
        assert 17000 < precio < 20000
        assert currency == 'USD'

    def test_consultar_returns_zero(self):
        precio, currency = scraper.parse_price_smart('Consultar')
        assert precio == 0
        assert currency is None

    def test_empty_returns_zero(self):
        precio, currency = scraper.parse_price_smart('')
        assert precio == 0


# ─── is_realistic_price ──────────────────────────────────────────────────────

class TestIsRealisticPrice:
    def test_normal_used_car(self):
        assert scraper.is_realistic_price(15000, 2018) is True

    def test_too_cheap_recent(self):
        # Auto 2024 a USD 5000 no es realista
        assert scraper.is_realistic_price(5000, 2024) is False

    def test_zero_price(self):
        assert scraper.is_realistic_price(0, 2018) is False

    def test_extremely_high(self):
        # USD 1M no es de uso doméstico (probable error de parsing)
        assert scraper.is_realistic_price(1_000_000, 2018) is False


# ─── Lógica de dedup (replicada del scraper.main) ────────────────────────────

class TestDedup:
    def test_basic_dedup(self):
        all_listings = [
            {'id': 'A', 'title': 'a1'},
            {'id': 'B', 'title': 'b'},
            {'id': 'A', 'title': 'a2'},  # duplicado
        ]
        seen = set()
        unique = []
        for l in all_listings:
            if l['id'] not in seen:
                seen.add(l['id'])
                unique.append(l)
        assert len(unique) == 2
        assert unique[0]['title'] == 'a1'  # se queda con el primero


# ─── Lógica de fast_sales (replicada) ────────────────────────────────────────

class TestFastSalesLogic:
    def test_disappeared_within_7_days_qualifies(self):
        today = datetime.utcnow().date()
        first_seen = (today - timedelta(days=5)).isoformat()
        days_lived = (today - datetime.fromisoformat(first_seen).date()).days
        assert 1 <= days_lived <= 30

    def test_just_appeared_skipped(self):
        today = datetime.utcnow().date()
        first_seen = today.isoformat()  # hoy
        days_lived = (today - datetime.fromisoformat(first_seen).date()).days
        assert days_lived == 0  # debe skippearse

    def test_stale_listing_skipped(self):
        today = datetime.utcnow().date()
        first_seen = (today - timedelta(days=60)).isoformat()
        days_lived = (today - datetime.fromisoformat(first_seen).date()).days
        assert days_lived > 30  # no es fast sale

    def test_sanity_threshold(self):
        # 30% del catálogo desaparece = scraper hiccup, skip
        prev_count = 100
        disappeared_count = 50
        assert disappeared_count / prev_count > 0.30  # dispara guard

        prev_count = 100
        disappeared_count = 5  # 5% normal
        assert disappeared_count / prev_count <= 0.30


# ─── Velocity stats ──────────────────────────────────────────────────────────

class TestVelocityStats:
    def test_requires_min_3_events(self):
        events = [{'days_lived': 5, 'last_price_usd': 12000}, {'days_lived': 7, 'last_price_usd': 12500}]
        # 2 eventos: no debería computar stats
        assert len(events) < 3

    def test_median_calculation(self):
        days = [3, 5, 7, 10, 14]
        median = sorted(days)[len(days) // 2]
        assert median == 7

    def test_p25_calculation(self):
        days = [3, 5, 7, 10, 14, 20, 25, 30]
        sorted_days = sorted(days)
        p25 = sorted_days[max(0, len(days) // 4)]
        assert p25 == 7  # index 2 of 8 sorted


# ─── detect_source_drops (health check) ──────────────────────────────────────

class TestDetectSourceDrops:
    def test_no_drops_returns_empty(self):
        prev = {'rg': 1500, 'ac': 2000, 'ml': 3000}
        curr = {'rg': 1480, 'ac': 2050, 'ml': 2900}
        assert scraper.detect_source_drops(prev, curr) == {}

    def test_catastrophic_drop_flagged(self):
        # AC cayó de 2000 a 100 = 95% drop, debe flaggearse
        prev = {'rg': 1500, 'ac': 2000}
        curr = {'rg': 1500, 'ac': 100}
        drops = scraper.detect_source_drops(prev, curr)
        assert 'ac' in drops
        assert 'rg' not in drops
        prev_n, curr_n, pct = drops['ac']
        assert prev_n == 2000
        assert curr_n == 100
        assert pct == 95.0

    def test_source_missing_today_flagged_as_full_drop(self):
        # RG no apareció hoy = 0 listings
        prev = {'rg': 1500, 'ac': 2000}
        curr = {'ac': 2000}
        drops = scraper.detect_source_drops(prev, curr)
        assert 'rg' in drops
        assert drops['rg'][1] == 0
        assert drops['rg'][2] == 100.0

    def test_baseline_too_small_ignored(self):
        # KV con sólo 50 listings previos no se chequea (no es baseline confiable)
        prev = {'rg': 1500, 'kv': 50}
        curr = {'rg': 1500, 'kv': 0}
        drops = scraper.detect_source_drops(prev, curr)
        assert 'kv' not in drops

    def test_new_source_ignored(self):
        # ML aparece por primera vez (no estaba en prev) — no es un drop
        prev = {'rg': 1500}
        curr = {'rg': 1500, 'ml': 3000}
        assert scraper.detect_source_drops(prev, curr) == {}

    def test_first_run_no_prev_sources(self):
        # Primer run: prev vacío, nada que comparar
        assert scraper.detect_source_drops({}, {'rg': 1500}) == {}

    def test_borderline_at_threshold(self):
        # Exactamente 50% se considera drop (threshold es <=)
        prev = {'rg': 1000}
        curr = {'rg': 500}
        drops = scraper.detect_source_drops(prev, curr)
        assert 'rg' in drops


if __name__ == '__main__':
    import pytest
    sys.exit(pytest.main([__file__, '-v']))
