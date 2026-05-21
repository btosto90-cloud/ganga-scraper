"""Tests para scoring.py — no requiere data real."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import scoring


def make_listing(**kwargs):
    """Helper para construir listings de prueba con defaults razonables."""
    base = {
        'id': 'test-1',
        'brand': 'toyota',
        'model': 'corolla',
        'model_key': 'toyota_corolla_2020',
        'year': 2020,
        'km': 80000,
        'precio_usd': 18000,
        'fuente': 'rg',
        'is_new': False,
        'recent_price_drop': False,
        'recent_drop_pct': 0,
    }
    base.update(kwargs)
    return base


# ─── base_model_key ───────────────────────────────────────────────────────────

class TestBaseModelKey:
    def test_strips_trim(self):
        assert scoring.base_model_key('honda_hr_v_2016_cvt') == 'honda_hr_v_2016'

    def test_no_trim_unchanged(self):
        assert scoring.base_model_key('toyota_corolla_2020') == 'toyota_corolla_2020'

    def test_none(self):
        assert scoring.base_model_key(None) is None

    def test_no_year(self):
        assert scoring.base_model_key('toyota_corolla') is None


# ─── fair_price_for / fair_price_component ────────────────────────────────────

class TestFairPriceFor:
    def test_sold_only(self):
        fair = scoring.fair_price_for(make_listing(), None, {'toyota_corolla_2020': 17000})
        assert fair['fair'] == 17000
        assert fair['source'] == 'venta_real'

    def test_asking_only(self):
        fair = scoring.fair_price_for(make_listing(), {'median': 20000, 'n': 8}, {})
        assert fair['fair'] == 20000
        assert fair['source'] == 'pedido_p50'

    def test_blend(self):
        fair = scoring.fair_price_for(make_listing(), {'median': 20000, 'n': 8}, {'toyota_corolla_2020': 15000})
        # 0.6*15000 + 0.4*20000 = 17000
        assert fair['fair'] == 17000
        assert fair['source'] == 'venta+pedido'

    def test_none(self):
        assert scoring.fair_price_for(make_listing(), None, {}) is None


class TestFairPriceComponent:
    def test_no_fair_returns_none(self):
        assert scoring.fair_price_component(make_listing(), None) is None

    def test_at_fair_price_returns_zero(self):
        assert scoring.fair_price_component(make_listing(precio_usd=20000), {'fair': 20000}) == 0

    def test_above_fair_returns_zero(self):
        assert scoring.fair_price_component(make_listing(precio_usd=22000), {'fair': 20000}) == 0

    def test_15pct_below(self):
        # 15% bajo → 100/30 * 15 = 50
        assert scoring.fair_price_component(make_listing(precio_usd=17000), {'fair': 20000}) == 50

    def test_30pct_below_caps_at_100(self):
        assert scoring.fair_price_component(make_listing(precio_usd=14000), {'fair': 20000}) == 100

    def test_no_precio_returns_none(self):
        assert scoring.fair_price_component(make_listing(precio_usd=0), {'fair': 20000}) is None


# ─── build_sold_index / build_velocity_index ──────────────────────────────────

class TestSoldIndex:
    def test_collapses_trim_weighted(self):
        vs = {
            'toyota_corolla_2020_xei': {'n': 4, 'median_sale_price_usd': 18000},
            'toyota_corolla_2020_seg': {'n': 6, 'median_sale_price_usd': 21000},
        }
        idx = scoring.build_sold_index(vs)
        # ponderado por n: (4*18000 + 6*21000)/10 = 19800
        assert idx['toyota_corolla_2020'] == 19800

    def test_skips_low_n(self):
        vs = {'toyota_corolla_2020': {'n': 2, 'median_sale_price_usd': 18000}}
        assert scoring.build_sold_index(vs) == {}

    def test_skips_no_price(self):
        vs = {'toyota_corolla_2020': {'n': 5, 'median_sale_price_usd': None}}
        assert scoring.build_sold_index(vs) == {}


class TestVelocityIndex:
    def test_picks_highest_n(self):
        vs = {
            'toyota_corolla_2020_xei': {'n': 4, 'median_days_lived': 10},
            'toyota_corolla_2020_seg': {'n': 6, 'median_days_lived': 5},
        }
        idx = scoring.build_velocity_index(vs)
        assert idx['toyota_corolla_2020']['median_days_lived'] == 5


# ─── outlier_component ────────────────────────────────────────────────────────

class TestOutlierComponent:
    def test_none_bucket(self):
        assert scoring.outlier_component(None) is None

    def test_zero_std(self):
        assert scoring.outlier_component({'std': 0, 'z_score': -2}) is None

    def test_positive_z(self):
        assert scoring.outlier_component({'std': 1000, 'z_score': 1.5}) == 0

    def test_strong_outlier(self):
        assert scoring.outlier_component({'std': 1000, 'z_score': -2}) == 80

    def test_extreme_outlier_caps_at_100(self):
        assert scoring.outlier_component({'std': 1000, 'z_score': -5}) == 100


# ─── velocity_component ──────────────────────────────────────────────────────

class TestVelocityComponent:
    def test_none(self):
        assert scoring.velocity_component(None) is None

    def test_fast_seller(self):
        assert scoring.velocity_component({'median_days_lived': 5}) == 100

    def test_medium_seller(self):
        assert scoring.velocity_component({'median_days_lived': 14}) == 75

    def test_slow_seller(self):
        assert scoring.velocity_component({'median_days_lived': 25}) == 25

    def test_very_slow(self):
        assert scoring.velocity_component({'median_days_lived': 60}) == 0


# ─── freshness_component ─────────────────────────────────────────────────────

class TestFreshnessComponent:
    def test_new_listing(self):
        assert scoring.freshness_component(make_listing(is_new=True)) == 100

    def test_big_drop(self):
        assert scoring.freshness_component(make_listing(recent_price_drop=True, recent_drop_pct=20)) == 90

    def test_small_drop(self):
        assert scoring.freshness_component(make_listing(recent_price_drop=True, recent_drop_pct=6)) == 60

    def test_neither(self):
        assert scoring.freshness_component(make_listing()) == 30


# ─── bucket_stats_for ────────────────────────────────────────────────────────

class TestBucketStats:
    def test_insufficient_data(self):
        listings = [make_listing(id=f'{i}', precio_usd=18000) for i in range(3)]
        buckets = scoring.build_buckets(listings)
        assert scoring.bucket_stats_for(make_listing(), buckets) is None

    def test_sufficient_data(self):
        listings = []
        for i, p in enumerate([16000, 17000, 17500, 18000, 18000, 18500, 19000, 19500, 20000, 21000]):
            listings.append(make_listing(id=f'c-{i}', precio_usd=p, km=80000))
        buckets = scoring.build_buckets(listings)

        target = make_listing(id='target', precio_usd=14000, km=80000)
        stats = scoring.bucket_stats_for(target, buckets)
        assert stats is not None
        assert stats['n'] == 10
        assert 17000 < stats['mean'] < 19500
        assert stats['z_score'] < -1

    def test_missing_data_returns_none(self):
        buckets = {('toyota', 'corolla'): [{'year': 2020, 'km': 80000, 'precio': 18000}] * 10}
        assert scoring.bucket_stats_for(make_listing(km=None), buckets) is None
        assert scoring.bucket_stats_for(make_listing(year=None), buckets) is None

    def test_excludes_self(self):
        listings = [make_listing(id='target', km=80000)]
        for i, p in enumerate([16000, 17000, 17500, 18000, 18500, 19000, 19500, 20000, 21000]):
            listings.append(make_listing(id=f'c-{i}', precio_usd=p, km=80000))
        buckets = scoring.build_buckets(listings)
        target = listings[0]
        stats = scoring.bucket_stats_for(target, buckets)
        assert stats['n'] == 9


# ─── compute_ganga_confidence ────────────────────────────────────────────────

class TestGangaConfidence:
    def test_no_anchors_returns_sin_referencia(self):
        result = scoring.compute_ganga_confidence(
            make_listing(model_key='unknown_x_2020'),
            buckets={}, sold_index={}, velocity_index={},
        )
        assert result['score'] is None
        assert result['tag'] == 'sin_referencia'

    def test_super_ganga_with_strong_fair_and_outlier(self):
        # 30%+ bajo precio justo + outlier extremo + nuevo + vende rápido = score muy alto
        listings_in_bucket = [
            make_listing(id=f'c-{i}', precio_usd=p, km=80000)
            for i, p in enumerate([18000, 18000, 18500, 19000, 19500, 20000, 20000, 20500, 21000, 22000])
        ]
        buckets = scoring.build_buckets(listings_in_bucket)
        target = make_listing(id='target', precio_usd=13000, km=80000, is_new=True)
        result = scoring.compute_ganga_confidence(
            target, buckets=buckets,
            sold_index={'toyota_corolla_2020': 19000},
            velocity_index={'toyota_corolla_2020': {'median_days_lived': 7}},
        )
        assert result['score'] >= 80
        assert result['tag'] == 'super_ganga_v2'
        assert result['breakdown']['fair'] == 100
        assert result['breakdown']['outlier'] == 100

    def test_overpriced_listing_low_score(self):
        listings_in_bucket = [
            make_listing(id=f'c-{i}', precio_usd=p, km=80000)
            for i, p in enumerate([18000, 18000, 18500, 19000, 19500, 20000, 20000, 20500, 21000, 22000])
        ]
        buckets = scoring.build_buckets(listings_in_bucket)
        target = make_listing(id='target', precio_usd=24000, km=80000)
        result = scoring.compute_ganga_confidence(
            target, buckets=buckets, sold_index={'toyota_corolla_2020': 19000}, velocity_index={},
        )
        assert result['score'] is not None
        assert result['score'] < 30
        assert result['tag'] == 'normal'

    def test_normal_priced_with_no_signals(self):
        listings_in_bucket = [
            make_listing(id=f'c-{i}', precio_usd=p, km=80000)
            for i, p in enumerate([18000, 18500, 19000, 19500, 20000, 20000, 20500, 21000, 21500, 22000])
        ]
        buckets = scoring.build_buckets(listings_in_bucket)
        target = make_listing(id='target', precio_usd=19500, km=80000)
        result = scoring.compute_ganga_confidence(
            target, buckets=buckets, sold_index={'toyota_corolla_2020': 19500}, velocity_index={},
        )
        assert result['score'] is not None
        assert result['score'] < 35

    def test_quality_penalty_for_missing_year(self):
        listings_in_bucket = [
            make_listing(id=f'c-{i}', precio_usd=p, km=80000)
            for i, p in enumerate([18000, 18500, 19000, 19500, 20000, 20000, 20500, 21000, 21500, 22000])
        ]
        buckets = scoring.build_buckets(listings_in_bucket)
        target_with_year = make_listing(id='t1', precio_usd=14000, km=80000, year=2020)
        target_no_year = make_listing(id='t2', precio_usd=14000, km=80000, year=None)
        r1 = scoring.compute_ganga_confidence(target_with_year, buckets, {}, {})
        r2 = scoring.compute_ganga_confidence(target_no_year, buckets, {}, {})
        assert r2['score'] is None or r2['score'] < r1['score']


# ─── annotate_listings (integration) ─────────────────────────────────────────

class TestAnnotateListings:
    def test_annotates_in_place(self):
        listings = [
            make_listing(id=f'c-{i}', precio_usd=p, km=80000)
            for i, p in enumerate([18000, 18500, 19000, 19500, 20000, 20000, 20500, 21000, 21500, 22000])
        ]
        listings.append(make_listing(id='super', precio_usd=12000, km=80000, is_new=True))

        stats = scoring.annotate_listings(listings, velocity_stats={})

        super_listing = next(l for l in listings if l['id'] == 'super')
        assert super_listing['ganga_confidence'] is not None
        assert super_listing['ganga_confidence'] >= 70
        assert super_listing['precio_justo'] is not None
        assert super_listing['precio_cca'] == super_listing['precio_justo']  # alias compat
        assert super_listing['descuento_justo_pct'] is not None
        assert super_listing['descuento_justo_pct'] > 30
        assert super_listing['bucket_n'] >= 5
        assert super_listing['ganga_breakdown']['fair'] is not None

        assert stats['total'] == 11
        assert stats['with_ref'] == 11
        assert stats['super_ganga_v2'] >= 1

    def test_uses_sold_price_when_available(self):
        # Sin bucket (pocos comparables) pero con venta real → igual hay referencia
        listings = [make_listing(id='solo', precio_usd=12000, model_key='toyota_corolla_2020')]
        vs = {'toyota_corolla_2020': {'n': 4, 'median_days_lived': 6, 'median_sale_price_usd': 18000}}
        scoring.annotate_listings(listings, velocity_stats=vs)
        l = listings[0]
        assert l['precio_justo'] == 18000
        assert l['ref_fuente'] == 'venta_real'
        assert l['ganga_confidence'] is not None  # 33% bajo venta real


# ─── is_likely_fake ──────────────────────────────────────────────────────────

class TestIsLikelyFake:
    def test_normal_listing_not_fake(self):
        is_fake, _ = scoring.is_likely_fake(
            make_listing(title='Toyota Corolla XEI 2020', precio_usd=18000, year=2020),
            fair_price=19000,
        )
        assert is_fake is False

    def test_plan_keyword_marks_fake(self):
        is_fake, reason = scoring.is_likely_fake(
            make_listing(title='Toyota Corolla 2024 Plan de ahorro 84 cuotas'),
        )
        assert is_fake is True
        assert 'plan' in reason.lower()

    def test_recent_year_with_low_price_is_fake(self):
        is_fake, reason = scoring.is_likely_fake(
            make_listing(title='Toyota Corolla', year=2024, precio_usd=5000),
        )
        assert is_fake is True
        assert '2024' in reason

    def test_2019_too_cheap_is_fake(self):
        # Nuevo guard extendido: un 2019 a USD 5000 es irreal
        is_fake, reason = scoring.is_likely_fake(
            make_listing(title='Peugeot 208 Feline', year=2019, precio_usd=5000),
        )
        assert is_fake is True
        assert '2019' in reason

    def test_too_good_to_be_true_is_fake(self):
        # >55% bajo el precio justo → probable error/bucket contaminado
        is_fake, reason = scoring.is_likely_fake(
            make_listing(title='Real listing', year=2016, precio_usd=5000),
            fair_price=20000,  # 5000/20000 = 25%
        )
        assert is_fake is True
        assert 'irreal' in reason.lower()

    def test_legit_below_fair_not_fake(self):
        # 20% bajo el precio justo es legítimo, no fake
        is_fake, _ = scoring.is_likely_fake(
            make_listing(title='Real ganga', year=2016, precio_usd=16000),
            fair_price=20000,
        )
        assert is_fake is False


class TestComputeGangaConfidenceWithFakes:
    def test_fake_returns_tag_fake(self):
        result = scoring.compute_ganga_confidence(
            make_listing(title='Plan de ahorro', precio_usd=5000),
            buckets={}, sold_index={}, velocity_index={},
        )
        assert result['tag'] == 'fake'
        assert result['score'] == 0
        assert result['fake_reason'] is not None


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
