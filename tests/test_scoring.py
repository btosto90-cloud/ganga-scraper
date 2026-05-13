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


# ─── cca_component ────────────────────────────────────────────────────────────

class TestCcaComponent:
    def test_no_cca_match_returns_none(self):
        assert scoring.cca_component(make_listing(model_key='unknown_x_y'), {}) is None

    def test_at_cca_price_returns_zero(self):
        result = scoring.cca_component(
            make_listing(precio_usd=20000),
            {'toyota_corolla_2020': 20000},
        )
        assert result == 0

    def test_above_cca_returns_zero(self):
        # Precio sobre CCA: no es ganga, score 0
        result = scoring.cca_component(
            make_listing(precio_usd=22000),
            {'toyota_corolla_2020': 20000},
        )
        assert result == 0

    def test_15pct_below_cca(self):
        # 15% bajo CCA → 100/30 * 15 = 50
        result = scoring.cca_component(
            make_listing(precio_usd=17000),
            {'toyota_corolla_2020': 20000},
        )
        assert result == 50

    def test_30pct_below_cca_caps_at_100(self):
        result = scoring.cca_component(
            make_listing(precio_usd=14000),
            {'toyota_corolla_2020': 20000},
        )
        assert result == 100

    def test_50pct_below_cca_caps_at_100(self):
        result = scoring.cca_component(
            make_listing(precio_usd=10000),
            {'toyota_corolla_2020': 20000},
        )
        assert result == 100

    def test_no_precio_returns_none(self):
        assert scoring.cca_component(make_listing(precio_usd=0), {'toyota_corolla_2020': 20000}) is None


# ─── outlier_component ────────────────────────────────────────────────────────

class TestOutlierComponent:
    def test_none_bucket(self):
        assert scoring.outlier_component(None) is None

    def test_zero_std(self):
        assert scoring.outlier_component({'std': 0, 'z_score': -2}) is None

    def test_positive_z(self):
        # Precio sobre la media → no es outlier bajo
        assert scoring.outlier_component({'std': 1000, 'z_score': 1.5}) == 0

    def test_strong_outlier(self):
        # z=-2 → 80
        assert scoring.outlier_component({'std': 1000, 'z_score': -2}) == 80

    def test_extreme_outlier_caps_at_100(self):
        # z=-5 → cap 100
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
        assert scoring.freshness_component(
            make_listing(recent_price_drop=True, recent_drop_pct=20)
        ) == 90

    def test_small_drop(self):
        assert scoring.freshness_component(
            make_listing(recent_price_drop=True, recent_drop_pct=6)
        ) == 60

    def test_neither(self):
        assert scoring.freshness_component(make_listing()) == 30


# ─── bucket_stats_for ────────────────────────────────────────────────────────

class TestBucketStats:
    def test_insufficient_data(self):
        listings = [make_listing(id=f'{i}', precio_usd=18000) for i in range(3)]
        buckets = scoring.build_buckets(listings)
        # Solo 3 listings — necesitamos >=6 en grupo y >=5 comparables
        assert scoring.bucket_stats_for(make_listing(), buckets) is None

    def test_sufficient_data(self):
        # 10 corollas 2020 con km similares, precios alrededor de 18k
        listings = []
        for i, p in enumerate([16000, 17000, 17500, 18000, 18000, 18500, 19000, 19500, 20000, 21000]):
            listings.append(make_listing(id=f'c-{i}', precio_usd=p, km=80000))
        buckets = scoring.build_buckets(listings)

        target = make_listing(id='target', precio_usd=14000, km=80000)
        stats = scoring.bucket_stats_for(target, buckets)
        assert stats is not None
        assert stats['n'] == 10
        assert 17000 < stats['mean'] < 19500
        assert stats['z_score'] < -1  # 14000 está bien debajo de 18.4k mean

    def test_missing_data_returns_none(self):
        buckets = {('toyota', 'corolla'): [{'year': 2020, 'km': 80000, 'precio': 18000}] * 10}
        assert scoring.bucket_stats_for(make_listing(km=None), buckets) is None
        assert scoring.bucket_stats_for(make_listing(year=None), buckets) is None

    def test_excludes_self(self):
        # Si solo está el listing target en el bucket, no hay comparables
        listings = [make_listing(id='target', km=80000)]
        # Agregamos 10 más para que el grupo tenga >=6
        for i, p in enumerate([16000, 17000, 17500, 18000, 18500, 19000, 19500, 20000, 21000]):
            listings.append(make_listing(id=f'c-{i}', precio_usd=p, km=80000))
        buckets = scoring.build_buckets(listings)
        target = listings[0]
        stats = scoring.bucket_stats_for(target, buckets)
        # n debería ser 9 (10 menos el propio)
        assert stats['n'] == 9


# ─── compute_ganga_confidence ────────────────────────────────────────────────

class TestGangaConfidence:
    def test_no_anchors_returns_sin_referencia(self):
        result = scoring.compute_ganga_confidence(
            make_listing(model_key='unknown'),
            cca_prices={},
            buckets={},
            velocity_stats={},
        )
        assert result['score'] is None
        assert result['tag'] == 'sin_referencia'

    def test_super_ganga_v2_with_strong_cca_and_outlier(self):
        # 30% bajo CCA + outlier extremo + listing nuevo + modelo vende rápido = score muy alto
        listings_in_bucket = [
            make_listing(id=f'c-{i}', precio_usd=p, km=80000)
            for i, p in enumerate([18000, 18000, 18500, 19000, 19500, 20000, 20000, 20500, 21000, 22000])
        ]
        buckets = scoring.build_buckets(listings_in_bucket)
        target = make_listing(id='target', precio_usd=13000, km=80000, is_new=True)
        result = scoring.compute_ganga_confidence(
            target,
            cca_prices={'toyota_corolla_2020': 19000},
            buckets=buckets,
            velocity_stats={'toyota_corolla_2020': {'median_days_lived': 7}},
        )
        assert result['score'] >= 80
        assert result['tag'] == 'super_ganga_v2'
        assert result['breakdown']['cca'] == 100  # 31% bajo CCA → cap 100
        assert result['breakdown']['outlier'] == 100  # extremo

    def test_overpriced_listing_low_score(self):
        listings_in_bucket = [
            make_listing(id=f'c-{i}', precio_usd=p, km=80000)
            for i, p in enumerate([18000, 18000, 18500, 19000, 19500, 20000, 20000, 20500, 21000, 22000])
        ]
        buckets = scoring.build_buckets(listings_in_bucket)
        target = make_listing(id='target', precio_usd=24000, km=80000)  # caro
        result = scoring.compute_ganga_confidence(
            target,
            cca_prices={'toyota_corolla_2020': 19000},
            buckets=buckets,
            velocity_stats={},
        )
        assert result['score'] is not None
        assert result['score'] < 30
        assert result['tag'] == 'normal'

    def test_normal_priced_with_no_signals(self):
        # Justo al precio CCA, no outlier, no nuevo → low score
        listings_in_bucket = [
            make_listing(id=f'c-{i}', precio_usd=p, km=80000)
            for i, p in enumerate([18000, 18500, 19000, 19500, 20000, 20000, 20500, 21000, 21500, 22000])
        ]
        buckets = scoring.build_buckets(listings_in_bucket)
        target = make_listing(id='target', precio_usd=19000, km=80000)
        result = scoring.compute_ganga_confidence(
            target,
            cca_prices={'toyota_corolla_2020': 19000},
            buckets=buckets,
            velocity_stats={},
        )
        # Sin descuento ni outlier ni novedad: score bajo
        assert result['score'] is not None
        assert result['score'] < 35

    def test_quality_penalty_for_missing_year(self):
        listings_in_bucket = [
            make_listing(id=f'c-{i}', precio_usd=p, km=80000)
            for i, p in enumerate([18000, 18500, 19000, 19500, 20000, 20000, 20500, 21000, 21500, 22000])
        ]
        buckets = scoring.build_buckets(listings_in_bucket)
        # Mismo precio bajo, pero sin year → penalización × 0.7
        target_with_year = make_listing(id='t1', precio_usd=14000, km=80000, year=2020)
        target_no_year = make_listing(id='t2', precio_usd=14000, km=80000, year=None)
        r1 = scoring.compute_ganga_confidence(target_with_year, {'toyota_corolla_2020': 19000}, buckets, {})
        r2 = scoring.compute_ganga_confidence(target_no_year, {'toyota_corolla_2020': 19000}, buckets, {})
        # El sin year tiene también bucket=None (porque bucket requiere year), pero CCA sigue
        # Lo que más importa es que el quality multiplier penaliza
        assert r2['score'] is None or r2['score'] < r1['score']


# ─── annotate_listings (integration) ─────────────────────────────────────────

class TestAnnotateListings:
    def test_annotates_in_place(self):
        listings = [
            make_listing(id=f'c-{i}', precio_usd=p, km=80000)
            for i, p in enumerate([18000, 18500, 19000, 19500, 20000, 20000, 20500, 21000, 21500, 22000])
        ]
        # Agregamos un super-ganga
        listings.append(make_listing(id='super', precio_usd=12000, km=80000, is_new=True))

        cca = {'toyota_corolla_2020': 19000}
        stats = scoring.annotate_listings(listings, cca, {})

        super_listing = next(l for l in listings if l['id'] == 'super')
        assert super_listing['ganga_confidence'] is not None
        assert super_listing['ganga_confidence'] >= 70
        assert super_listing['precio_cca'] == 19000
        assert super_listing['descuento_cca_pct'] is not None
        assert super_listing['descuento_cca_pct'] > 30
        assert super_listing['bucket_n'] >= 5
        assert super_listing['ganga_breakdown']['cca'] is not None

        assert stats['total'] == 11
        assert stats['with_cca'] == 11
        assert stats['super_ganga_v2'] >= 1


# ─── is_likely_fake ──────────────────────────────────────────────────────────

class TestIsLikelyFake:
    def test_normal_listing_not_fake(self):
        is_fake, _ = scoring.is_likely_fake(
            make_listing(title='Toyota Corolla XEI 2020', precio_usd=18000, year=2020),
            cca_prices={'toyota_corolla_2020': 19000},
        )
        assert is_fake is False

    def test_plan_keyword_marks_fake(self):
        is_fake, reason = scoring.is_likely_fake(
            make_listing(title='Toyota Corolla 2024 Plan de ahorro 84 cuotas'),
            cca_prices={},
        )
        assert is_fake is True
        assert 'plan' in reason.lower()

    def test_recent_year_with_low_price_is_fake(self):
        is_fake, reason = scoring.is_likely_fake(
            make_listing(title='Toyota Corolla', year=2024, precio_usd=5000),
            cca_prices={},
        )
        assert is_fake is True
        assert '2024' in reason

    def test_below_40pct_cca_is_fake(self):
        is_fake, reason = scoring.is_likely_fake(
            make_listing(title='Real listing', year=2018, precio_usd=5000),
            cca_prices={'toyota_corolla_2020': 20000},  # 5000/20000 = 25%
        )
        assert is_fake is True
        assert 'CCA' in reason

    def test_legit_below_cca_not_fake(self):
        # 20% bajo CCA es legítimo, no fake
        is_fake, _ = scoring.is_likely_fake(
            make_listing(title='Real ganga', year=2018, precio_usd=16000),
            cca_prices={'toyota_corolla_2020': 20000},
        )
        assert is_fake is False


class TestComputeGangaConfidenceWithFakes:
    def test_fake_returns_tag_fake(self):
        result = scoring.compute_ganga_confidence(
            make_listing(title='Plan de ahorro', precio_usd=5000),
            cca_prices={'toyota_corolla_2020': 19000},
            buckets={},
            velocity_stats={},
        )
        assert result['tag'] == 'fake'
        assert result['score'] == 0
        assert result['fake_reason'] is not None


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
