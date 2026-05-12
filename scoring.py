"""Ganga Hunter scoring — pre-computed en el scraper, leído por el Worker.

Filosofía: el Worker hoy compara cada listing contra la mediana de OTROS listings.
Eso significa que si todos los vendedores piden de más, una "ganga" es solo "menos
inflada que el resto". Este módulo agrega tres anclas independientes:

  1. CCA — ground truth del mercado (precio CCA por modelo+año, 501 modelos).
  2. Bucket — dentro del segmento (modelo+año±1+km±20%), z-score del precio.
  3. Velocity — modelos que venden rápido = demanda real = más confianza.

Combinamos las tres en `ganga_confidence` (0-100). Solo se considera una "verdadera
ganga" cuando varias señales convergen.

Las funciones son puras y testeables. El scraper las llama después de dedup+filtros.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Optional


# ─── Bucket stats ─────────────────────────────────────────────────────────────

def build_buckets(listings: list[dict]) -> dict:
    """Agrupa listings por (brand, model) para lookup rápido por bucket.

    Devuelve dict (brand, model) -> [{'year', 'km', 'precio'}].
    """
    buckets: dict[tuple, list[dict]] = defaultdict(list)
    for l in listings:
        if not (l.get('precio_usd') and l.get('year') and l.get('km')):
            continue
        if not (l.get('brand') and l.get('model')):
            continue
        if l['precio_usd'] < 1500:  # mismo guard que el Worker
            continue
        buckets[(l['brand'], l['model'])].append({
            'year': l['year'],
            'km': l['km'],
            'precio': l['precio_usd'],
            'id': l.get('id'),
        })
    return buckets


def bucket_stats_for(listing: dict, buckets: dict, year_window: int = 1, km_pct: float = 0.2) -> Optional[dict]:
    """Stats del bucket comparable a este listing.

    Comparables = misma marca/modelo, año ±year_window, km dentro del km_pct.
    Excluye el propio listing. Retorna None si <5 comparables o si listing carece de datos.
    """
    if not (listing.get('brand') and listing.get('model') and listing.get('year') and listing.get('km')):
        return None
    if not listing.get('precio_usd') or listing['precio_usd'] < 1500:
        return None
    group = buckets.get((listing['brand'], listing['model']), [])
    if len(group) < 6:
        return None
    target_km = listing['km']
    km_min = target_km * (1 - km_pct)
    km_max = target_km * (1 + km_pct)
    target_year = listing['year']
    own_id = listing.get('id')

    comparables = [
        x['precio'] for x in group
        if x.get('id') != own_id
        and abs(x['year'] - target_year) <= year_window
        and km_min <= x['km'] <= km_max
    ]
    if len(comparables) < 5:
        return None

    n = len(comparables)
    mean = sum(comparables) / n
    variance = sum((p - mean) ** 2 for p in comparables) / n
    std = math.sqrt(variance)
    sorted_p = sorted(comparables)
    median = sorted_p[n // 2]
    p25 = sorted_p[n // 4]
    p75 = sorted_p[3 * n // 4]
    z = (listing['precio_usd'] - mean) / std if std > 1 else 0.0
    return {
        'n': n,
        'mean': round(mean),
        'std': round(std),
        'median': median,
        'p25': p25,
        'p75': p75,
        'z_score': round(z, 2),
    }


# ─── Component scores (0-100 each) ────────────────────────────────────────────

def cca_component(listing: dict, cca_prices: dict) -> Optional[int]:
    """% bajo CCA, escalado: 30% bajo → 100. None si no hay CCA para el modelo."""
    if not listing.get('model_key') or not listing.get('precio_usd'):
        return None
    cca = cca_prices.get(listing['model_key'])
    if not cca or cca <= 0:
        return None
    pct = (1 - listing['precio_usd'] / cca) * 100
    if pct <= 0:
        return 0  # no es ganga, está al precio o sobre
    return min(100, round(pct * 100 / 30))


def outlier_component(bucket: Optional[dict]) -> Optional[int]:
    """Z-score dentro del bucket: z=-2.5 → 100. None si bucket no disponible."""
    if not bucket or bucket.get('std', 0) <= 1:
        return None
    z = bucket.get('z_score', 0)
    if z >= 0:
        return 0  # precio sobre la media, no es outlier bajo
    return min(100, round(-z * 40))


def velocity_component(velocity_for_model: Optional[dict]) -> Optional[int]:
    """Modelos que venden rápido (median <14d) → confianza alta de demanda.

    Sin data acumulada (primeras semanas) retorna None.
    """
    if not velocity_for_model:
        return None
    days = velocity_for_model.get('median_days_lived')
    if days is None:
        return None
    if days <= 7:
        return 100
    if days <= 14:
        return 75
    if days <= 21:
        return 50
    if days <= 30:
        return 25
    return 0


def freshness_component(listing: dict) -> int:
    """Listings nuevos o recién bajados son más interesantes para actuar.

    Siempre devuelve algo (no es señal de ganga sino de oportunidad temporal).
    """
    if listing.get('is_new'):
        return 100
    if listing.get('recent_price_drop'):
        # Bajadas profundas valen más
        drop = listing.get('recent_drop_pct', 0)
        if drop >= 15:
            return 90
        if drop >= 10:
            return 75
        if drop >= 5:
            return 60
        return 50
    return 30


def quality_multiplier(listing: dict) -> float:
    """Penalización multiplicativa por data faltante/sospechosa."""
    m = 1.0
    if not listing.get('year'):
        m *= 0.7
    if not listing.get('km'):
        m *= 0.8
    if not listing.get('model'):
        m *= 0.5
    # Km en cero pero auto no-nuevo: sospechoso (mismo criterio que Worker)
    age = 2026 - (listing.get('year') or 2026)
    if age >= 3 and not listing.get('km'):
        m *= 0.7
    return m


# ─── Detección de fakes / plan de ahorro / errores de carga ──────────────────

PLAN_KEYWORDS = (
    'plan ', 'plan de ahorro', 'cuotas', 'cuota', 'anticipo', 'entrega',
    'financiado', 'financiacion', 'financiación', 'prenda', 'a convenir',
    'consultar', 'desde usd', 'desde $', 'bono', 'descuento especial',
    'permuta sin cargo', 'tomamos tu auto',
)


def is_likely_fake(listing: dict, cca_prices: dict) -> tuple[bool, str]:
    """Detecta listings que NO son ofertas reales: planes de ahorro, errores de carga,
    publicaciones de agencia con precio anclado bajo (anticipo). Replica y extiende la
    lógica del Worker.

    Devuelve (is_fake, reason).
    """
    title = (listing.get('title') or '').lower()
    for kw in PLAN_KEYWORDS:
        if kw in title:
            return True, f'keyword: "{kw}"'

    precio = listing.get('precio_usd') or 0
    year = listing.get('year') or 0

    # Auto reciente con precio absurdo (2022+ < 7500, 2020+ < 5500)
    if year >= 2022 and precio < 7500:
        return True, f'año {year} con precio {precio} es irreal'
    if year >= 2020 and precio < 5500:
        return True, f'año {year} con precio {precio} es irreal'

    # Precio sospechosamente bajo vs CCA (>60% de descuento es muy raro)
    cca = cca_prices.get(listing.get('model_key'))
    if cca and precio > 0:
        if precio < cca * 0.40:
            return True, f'precio < 40% del CCA ({precio} vs {cca})'

    return False, ''


# ─── Final ganga_confidence ───────────────────────────────────────────────────

WEIGHTS = {
    'cca': 0.50,        # CCA es la señal más confiable cuando existe
    'outlier': 0.30,    # Bucket z-score, segundo en confianza
    'velocity': 0.10,   # Refuerzo cuando hay data de demanda
    'freshness': 0.10,  # Modificador de oportunidad temporal
}


def compute_ganga_confidence(
    listing: dict,
    cca_prices: dict,
    buckets: dict,
    velocity_stats: dict,
) -> dict:
    """Devuelve dict con 'score' (0-100), 'tag', 'breakdown', 'fake_reason'.

    Tag derivado:
      'fake'           si pasa el filtro is_likely_fake
      >= 80            super_ganga_v2
      >= 65            ganga_v2
      >= 45            interesante
      <  45            normal
      sin_referencia   si no hay CCA ni bucket disponibles
    """
    bucket = bucket_stats_for(listing, buckets)
    velocity = velocity_stats.get(listing.get('model_key', '')) if velocity_stats else None

    # Filtro fake-first: si parece plan de ahorro o error de carga, no scoreamos.
    is_fake, fake_reason = is_likely_fake(listing, cca_prices)
    if is_fake:
        return {
            'score': 0,
            'tag': 'fake',
            'breakdown': {'cca': None, 'outlier': None, 'velocity': None, 'freshness': None},
            'bucket': bucket,
            'fake_reason': fake_reason,
        }

    components = {
        'cca': cca_component(listing, cca_prices),
        'outlier': outlier_component(bucket),
        'velocity': velocity_component(velocity),
        'freshness': freshness_component(listing),
    }

    # Combinación ponderada de componentes disponibles
    total_score = 0.0
    total_weight = 0.0
    for k, v in components.items():
        if v is None:
            continue
        w = WEIGHTS.get(k, 0)
        total_score += v * w
        total_weight += w

    # Si no hay CCA NI outlier, no podemos opinar (solo tenemos freshness/velocity)
    has_anchor = components['cca'] is not None or components['outlier'] is not None
    if not has_anchor or total_weight == 0:
        return {
            'score': None,
            'tag': 'sin_referencia',
            'breakdown': components,
            'bucket': bucket,
            'fake_reason': None,
        }

    base = total_score / total_weight
    base *= quality_multiplier(listing)
    score = max(0, min(100, round(base)))

    if score >= 80:
        tag = 'super_ganga_v2'
    elif score >= 65:
        tag = 'ganga_v2'
    elif score >= 45:
        tag = 'interesante'
    else:
        tag = 'normal'

    return {
        'score': score,
        'tag': tag,
        'breakdown': components,
        'bucket': bucket,
        'fake_reason': None,
    }


# ─── Helper para el scraper: anota cada listing in-place ──────────────────────

def annotate_listings(listings: list[dict], cca_prices: dict, velocity_stats: dict) -> dict:
    """Calcula ganga_confidence para cada listing y lo anota in-place.

    Agrega a cada listing los campos:
      - precio_cca (USD del CCA si hay match, None si no)
      - descuento_cca_pct (% bajo CCA)
      - bucket_n, bucket_median_usd, bucket_z_score (stats del bucket)
      - ganga_confidence (0-100 o None)
      - ganga_tag ('super_ganga_v2' | 'ganga_v2' | 'interesante' | 'normal' | 'sin_referencia')
      - ganga_breakdown (dict con cada componente)

    Devuelve resumen de stats agregadas.
    """
    buckets = build_buckets(listings)
    out_stats = {
        'total': len(listings),
        'with_cca': 0,
        'with_bucket': 0,
        'with_velocity': 0,
        'super_ganga_v2': 0,
        'ganga_v2': 0,
        'interesante': 0,
        'sin_referencia': 0,
        'fake': 0,
    }
    for l in listings:
        # CCA
        cca = cca_prices.get(l.get('model_key'))
        if cca and cca > 0:
            l['precio_cca'] = cca
            l['descuento_cca_pct'] = round((1 - l.get('precio_usd', 0) / cca) * 100, 1) if l.get('precio_usd') else None
            out_stats['with_cca'] += 1
        else:
            l['precio_cca'] = None
            l['descuento_cca_pct'] = None

        # Velocity
        v = velocity_stats.get(l.get('model_key', '')) if velocity_stats else None
        if v:
            out_stats['with_velocity'] += 1

        # Confidence (incluye bucket internamente)
        result = compute_ganga_confidence(l, cca_prices, buckets, velocity_stats or {})
        l['ganga_confidence'] = result['score']
        l['ganga_tag'] = result['tag']
        l['ganga_breakdown'] = result['breakdown']
        l['fake_reason'] = result.get('fake_reason')
        bucket = result.get('bucket')
        if bucket:
            l['bucket_n'] = bucket['n']
            l['bucket_median_usd'] = bucket['median']
            l['bucket_z_score'] = bucket['z_score']
            out_stats['with_bucket'] += 1
        else:
            l['bucket_n'] = None
            l['bucket_median_usd'] = None
            l['bucket_z_score'] = None

        if result['tag'] in out_stats:
            out_stats[result['tag']] += 1

    return out_stats
