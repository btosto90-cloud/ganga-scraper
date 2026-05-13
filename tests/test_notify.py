"""Tests para notify.py — sin tocar Telegram real."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notify


def make_listing(**kwargs):
    base = {
        'id': 'x',
        'precio_usd': 18000,
        'model_key': 'toyota_corolla_2020',
        'is_new': False,
        'recent_price_drop': False,
        'recent_drop_pct': 0,
        'fuente': 'rg',
        'title': 'Test',
        'km': 80000,
        'trans': 'AT',
        'fuel': 'Nafta',
        'year': 2020,
    }
    base.update(kwargs)
    return base


class TestV2Detection:
    def test_with_v2_field(self):
        listings = [make_listing(ganga_confidence=85), make_listing(ganga_confidence=None)]
        assert notify.has_v2_scoring(listings) is True

    def test_without_v2_field(self):
        # listings sin ganga_confidence (scraper viejo)
        listings = [make_listing()]
        assert notify.has_v2_scoring(listings) is False


class TestV2Filters:
    def test_super_ganga_v2_threshold(self):
        assert notify.is_super_ganga_v2(make_listing(ganga_confidence=80)) is True
        assert notify.is_super_ganga_v2(make_listing(ganga_confidence=79)) is False
        assert notify.is_super_ganga_v2(make_listing(ganga_confidence=None)) is False

    def test_ganga_or_better_threshold(self):
        assert notify.is_ganga_or_better_v2(make_listing(ganga_confidence=65)) is True
        assert notify.is_ganga_or_better_v2(make_listing(ganga_confidence=64)) is False


class TestFallbackFilters:
    def test_super_ganga_fallback(self):
        cca = {'toyota_corolla_2020': 24000}
        # 75% de 24000 = 18000 → exactamente en el umbral
        assert notify.is_super_ganga_fallback(make_listing(precio_usd=18000), cca) is True
        # Sobre el umbral
        assert notify.is_super_ganga_fallback(make_listing(precio_usd=20000), cca) is False
        # Sin CCA
        assert notify.is_super_ganga_fallback(make_listing(model_key='xx'), cca) is False


class TestFmtListing:
    def test_includes_url(self):
        l = make_listing(url='https://test.com/abc', precio_usd=14000, ganga_confidence=85,
                         precio_cca=20000, descuento_cca_pct=30)
        out = notify.fmt_listing(l, {})
        assert 'https://test.com/abc' in out
        assert '85' in out  # confidence score
        assert '14.000' in out  # AR-style number
        assert 'CCA' in out

    def test_drop_format(self):
        l = make_listing(precio_usd=12000, recent_price_drop=True, recent_drop_pct=20,
                         price_history=[{'fecha': '2026-05-01', 'precio_usd': 15000},
                                        {'fecha': '2026-05-12', 'precio_usd': 12000}])
        out = notify.fmt_listing(l, {}, show_drop=True)
        assert '15.000' in out  # precio anterior
        assert '12.000' in out  # precio nuevo
        assert '-20' in out


class TestFmtNum:
    def test_argentine_format(self):
        assert notify.fmt_num(15000) == '15.000'
        assert notify.fmt_num(1234567) == '1.234.567'
        assert notify.fmt_num(0) == '0'

    def test_invalid_input(self):
        assert notify.fmt_num(None) == 'None'
        assert notify.fmt_num('abc') == 'abc'


if __name__ == '__main__':
    import pytest
    sys.exit(pytest.main([__file__, '-v']))
