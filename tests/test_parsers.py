"""Tests para los parsers HTML de RosarioGarage y Autocosmos.

Usa fixtures sintéticos que replican los patrones que el scraper espera.
Si una fuente cambia su HTML, estos tests fallarán antes de que se rompa
producción (complementa la alerta runtime de detect_source_drops).

NOTA: si actualizás un parser para soportar un cambio de markup, también
hay que actualizar el fixture acá para reflejar el nuevo formato.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Stub urlopen igual que en test_scraper_logic, para no salir a la red al importar
import urllib.request as _ureq
_orig_urlopen = _ureq.urlopen


class _FakeResponse:
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def read(self): return b'{"venta": 1400}'
    def info(self):
        class X:
            def get(self, k): return None
        return X()


_ureq.urlopen = lambda *a, **kw: _FakeResponse()
import scraper
_ureq.urlopen = _orig_urlopen


# ─── RosarioGarage fixtures ──────────────────────────────────────────────────
#
# El parser splittea por 'data-rel="' y cada bloque debe tener:
#   - id numérico al inicio: `<id>"`
#   - title (vía class="list_type_anuncio" o titulo o h2 o alt)
#   - year dentro de un <span> o como palabra suelta
#   - km (opcional, formato "X km" o ">X km<")
#   - trans (opcional, ">AT<" o ">MT<")
#   - fuel (opcional, ">Nafta<" etc)
#   - precio (U$S, USD, o class="precio")

RG_VALID_BLOCK = '''
<div data-rel="12345">
  <a class="list_type_anuncio">Volkswagen Golf GTI 2.0 TSI</a>
  <span class="year">2019</span>
  <span>45.000 Km.</span>
  <span>AT</span>
  <span>Nafta</span>
  <div class="precio"><a href="#">U$S 22.500</a></div>
</div>
'''

RG_NO_PRICE = '''
<div data-rel="99999">
  <a class="list_type_anuncio">Audi A3 1.4 TFSI</a>
  <span class="year">2018</span>
  <span>60.000 Km.</span>
  <div class="precio"><a href="#">Consultar</a></div>
</div>
'''

RG_NO_YEAR = '''
<div data-rel="11111">
  <a class="list_type_anuncio">Auto sin año</a>
  <div class="precio"><a href="#">U$S 15.000</a></div>
</div>
'''

RG_PRICE_IN_ARS = '''
<div data-rel="22222">
  <a class="list_type_anuncio">Fiat Cronos Drive 1.3</a>
  <span class="year">2021</span>
  <span>30.000 Km.</span>
  <div class="precio"><a href="#">$ 18.000.000</a></div>
</div>
'''


class TestRosarioGarageParser:
    def test_valid_block_extracts_all_fields(self):
        page = '<html><body>' + RG_VALID_BLOCK + '</body></html>'
        results = scraper._parse_rg_html(page, 'volkswagen')
        assert len(results) == 1
        item = results[0]
        assert item['id'] == '12345'
        assert item['year'] == 2019
        assert item['km'] == 45000
        assert item['trans'] == 'AT'
        assert item['fuel'].lower() == 'nafta'
        assert item['precio_usd'] == 22500
        assert item['fuente'] == 'rg'
        assert 'rosariogarage.com' in item['url']

    def test_no_price_discarded(self):
        page = '<html><body>' + RG_NO_PRICE + '</body></html>'
        assert scraper._parse_rg_html(page, 'audi') == []

    def test_no_year_discarded(self):
        page = '<html><body>' + RG_NO_YEAR + '</body></html>'
        assert scraper._parse_rg_html(page, 'audi') == []

    def test_ars_price_converted_to_usd(self):
        page = '<html><body>' + RG_PRICE_IN_ARS + '</body></html>'
        results = scraper._parse_rg_html(page, 'fiat')
        assert len(results) == 1
        # 18M ARS / 1400 ≈ 12857 USD (BLUE_RATE=1400 en tests)
        assert 12000 < results[0]['precio_usd'] < 14000

    def test_empty_html_returns_empty(self):
        assert scraper._parse_rg_html('<html></html>', 'audi') == []

    def test_multiple_blocks_all_extracted(self):
        page = '<html><body>' + RG_VALID_BLOCK + RG_VALID_BLOCK.replace('12345', '54321').replace('22.500', '19.900') + '</body></html>'
        results = scraper._parse_rg_html(page, 'volkswagen')
        assert len(results) == 2
        ids = {r['id'] for r in results}
        assert ids == {'12345', '54321'}


# ─── Autocosmos fixtures ─────────────────────────────────────────────────────
#
# El parser splittea por '<article' y cada bloque debe tener:
#   - href="/auto/usado/<marca>/<modelo>/<version>/<hash>"
#   - year en formato (2020) o como palabra suelta
#   - title atributo o <h2>
#   - precio "u$s X" o "usd X" (filtra anticipos y cuotas)
#   - km opcional ("X km")
#
# CRÍTICO: si el bloque contiene "anticipo" o "financiado en cuotas" se descarta
# (sería un precio engañoso, solo el anticipo y no el total).

AC_VALID_BLOCK = '''
<article class="listing-card">
  <a href="/auto/usado/toyota/corolla/cross-xei/abc123hash">
    <h2>Toyota Corolla Cross XEi (2022)</h2>
    <span>32.500 km</span>
    <span class="price">u$s 28.900</span>
  </a>
</article>
'''

AC_FINANCED_BLOCK_DISCARDED = '''
<article class="listing-card">
  <a href="/auto/usado/peugeot/208/active/xyz789">
    <h2>Peugeot 208 Active (2023)</h2>
    <span>15.000 km</span>
    <span class="financiado">Financiado en cuotas — Anticipo u$s 5.000</span>
  </a>
</article>
'''

AC_PRICE_FROM_ITEMPROP = '''
<article class="listing-card">
  <a href="/auto/usado/honda/civic/exl/qwe456">
    <h2>Honda Civic EXL (2020)</h2>
    <meta itemprop="price" content="19500" />
    <span>50.000 km</span>
  </a>
</article>
'''

AC_NO_PRICE = '''
<article class="listing-card">
  <a href="/auto/usado/ford/focus/se/noprice123">
    <h2>Ford Focus SE (2019)</h2>
    <span>80.000 km</span>
  </a>
</article>
'''

AC_NO_URL = '''
<article class="listing-card">
  <h2>Auto sin url (2020)</h2>
  <span class="price">u$s 15.000</span>
</article>
'''


class TestAutocosmosParser:
    def test_valid_block_extracts_all_fields(self):
        page = '<html><body>' + AC_VALID_BLOCK + '</body></html>'
        results = scraper._parse_ac_html(page, 'toyota')
        assert len(results) == 1
        item = results[0]
        assert item['year'] == 2022
        assert item['km'] == 32500
        assert item['precio_usd'] == 28900
        assert item['trans'] == '?'  # sin info de auto/cvt en el chunk
        assert item['fuente'] == 'ac'
        assert item['url'].startswith('https://www.autocosmos.com.ar/auto/usado/toyota/corolla/')
        assert item['id'].startswith('ac_')

    def test_financed_listing_discarded(self):
        """Críticamente importante: no debemos tomar el anticipo como precio."""
        page = '<html><body>' + AC_FINANCED_BLOCK_DISCARDED + '</body></html>'
        assert scraper._parse_ac_html(page, 'peugeot') == []

    def test_price_from_itemprop_meta(self):
        page = '<html><body>' + AC_PRICE_FROM_ITEMPROP + '</body></html>'
        results = scraper._parse_ac_html(page, 'honda')
        assert len(results) == 1
        assert results[0]['precio_usd'] == 19500

    def test_no_price_discarded(self):
        page = '<html><body>' + AC_NO_PRICE + '</body></html>'
        assert scraper._parse_ac_html(page, 'ford') == []

    def test_no_url_discarded(self):
        page = '<html><body>' + AC_NO_URL + '</body></html>'
        assert scraper._parse_ac_html(page, 'unknown') == []

    def test_empty_html_returns_empty(self):
        assert scraper._parse_ac_html('<html></html>', 'toyota') == []

    def test_multiple_blocks_all_extracted(self):
        page = '<html><body>' + AC_VALID_BLOCK + AC_PRICE_FROM_ITEMPROP + '</body></html>'
        results = scraper._parse_ac_html(page, 'mixed')
        assert len(results) == 2


# ─── Smoke test cross-parser ─────────────────────────────────────────────────

class TestParserSmokeTest:
    """Si algún día cambia drásticamente la estructura del scraper, queremos saber."""

    def test_rg_parser_exists_and_callable(self):
        assert callable(scraper._parse_rg_html)

    def test_ac_parser_exists_and_callable(self):
        assert callable(scraper._parse_ac_html)


if __name__ == '__main__':
    import pytest
    sys.exit(pytest.main([__file__, '-v']))
