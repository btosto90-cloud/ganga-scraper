"""Ganga Hunter scoring — pre-computed en el scraper, leído por el Worker.

Filosofía: el Worker hoy compara cada listing contra la mediana de OTROS listings.
Eso significa que si todos los vendedores piden de más, una "ganga" es solo "menos
inflada que el resto". Este módulo agrega cinco anclas independientes:

  1. CCA — guía oficial CCA (cuando hay match en cca_precios.json).
  2. Kavak — mediana de precios Kavak por modelo+año (reseller profesional).
     Más cercana a "valor real de transacción" que tenemos en AR sin scrapear
     cotizaciones privadas. Solo activa cuando hay kavak_listings.json.
  3. ML p25 — percentil 25 de precios ML por modelo+año (piso de mercado robusto,
     filtra el inflado de concesionarias). Cubre la mayoría del catálogo.
  4. Bucket — z-score dentro del segmento (modelo+año±1+km±20%).
  5. Velocity — modelos que venden rápido = demanda real = más confianza.

Combinamos en `ganga_confidence` (0-100) con cross-check: solo se considera una
"verdadera ganga" cuando MÚLTIPLES anclas convergen. Una sola ancla = sospechoso.

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


# ─── Índices de precio por fuente (anclas alternativas) ──────────────────────

def build_kavak_index(listings: list[dict]) -> dict:
    """Mediana de precios Kavak por model_key.

    Kavak es un reseller profesional — sus precios son los más cercanos a
    "precio real de transacción" sin acceder a cotizaciones privadas.

    Necesita ≥2 listings Kavak por model_key para dar señal estable.
    Devuelve {model_key: median_price_usd}.
    """
    by_mk: dict[str, list[int]] = defaultdict(list)
    for l in listings:
        if l.get('fuente') != 'kv':
            continue
        if not l.get('precio_usd') or l['precio_usd'] < 1500:
            continue
        mk = l.get('model_key')
        if mk:
            by_mk[mk].append(l['precio_usd'])
    out = {}
    for mk, prices in by_mk.items():
        if len(prices) < 2:
            continue
        s = sorted(prices)
        out[mk] = s[len(s) // 2]
    return out


def build_ml_p25_index(listings: list[dict]) -> dict:
    """Percentil 25 de precios ML por model_key.

    p25 captura el "piso" del mercado público — más robusto que la mediana
    porque ignora las concesionarias que listan caro para negociar abajo.
    Cuando un listing está debajo del p25 de su modelo, es genuinamente barato.

    Necesita ≥4 listings ML para dar señal. Cubre la mayoría del catálogo
    porque ML es la fuente con más volumen.
    """
    by_mk: dict[str, list[int]] = defaultdict(list)
    for l in listings:
        if l.get('fuente') != 'ml':
            continue
        if not l.get('precio_usd') or l['precio_usd'] < 1500:
            continue
        mk = l.get('model_key')
        if mk:
            by_mk[mk].append(l['precio_usd'])
    out = {}
    for mk, prices in by_mk.items():
        if len(prices) < 4:
            continue
        s = sorted(prices)
        # Percentile 25
        idx = max(0, min(len(s) - 1, len(s) // 4))
        out[mk] = s[idx]
    return out


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


def kavak_component(listing: dict, kavak_index: dict) -> Optional[int]:
    """% bajo mediana Kavak, escalado: 20% bajo → 100. None si no hay match.

    Threshold más agresivo que CCA (20% vs 30%) porque Kavak ya es precio
    de reseller — todo lo que esté significativamente debajo es ganga real.
    """
    if not listing.get('model_key') or not listing.get('precio_usd'):
        return None
    kv = kavak_index.get(listing['model_key'])
    if not kv or kv <= 0:
        return None
    pct = (1 - listing['precio_usd'] / kv) * 100
    if pct <= 0:
        return 0
    return min(100, round(pct * 100 / 20))


def ml_p25_component(listing: dict, ml_p25_index: dict) -> Optional[int]:
    """% bajo p25 de ML, escalado: 15% bajo → 100. None si no hay match.

    El p25 ya es el piso del mercado. Estar significativamente bajo p25 es
    señal de ganga real o de listing con problemas (km, accidente, etc.).
    """
    if not listing.get('model_key') or not listing.get('precio_usd'):
        return None
    # No comparar un listing de ML contra el p25 de ML (sería circular)
    if listing.get('fuente') == 'ml':
        return None
    p25 = ml_p25_index.get(listing['model_key'])
    if not p25 or p25 <= 0:
        return None
    pct = (1 - listing['precio_usd'] / p25) * 100
    if pct <= 0:
        return 0
    return min(100, round(pct * 100 / 15))


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


def is_likely_fake(
    listing: dict,
    cca_prices: dict,
    kavak_index: Optional[dict] = None,
    ml_p25_index: Optional[dict] = None,
) -> tuple[bool, str]:
    """Detecta listings que NO son ofertas reales: planes de ahorro, errores de carga,
    publicaciones de agencia con precio anclado bajo (anticipo).

    Hace cross-check con Kavak y ML p25: un precio sospechosamente bajo según CCA
    PERO razonable comparado con Kavak/ML es CCA desactualizado, no fake.

    Devuelve (is_fake, reason).
    """
    title = (listing.get('title') or '').lower()
    for kw in PLAN_KEYWORDS:
        if kw in title:
            return True, f'keyword: "{kw}"'

    precio = listing.get('precio_usd') or 0
    year = listing.get('year') or 0
    model_key = listing.get('model_key')
    kavak_index = kavak_index or {}
    ml_p25_index = ml_p25_index or {}

    # Auto reciente con precio absurdo (2022+ < 7500, 2020+ < 5500)
    if year >= 2022 and precio < 7500:
        return True, f'año {year} con precio {precio} es irreal'
    if year >= 2020 and precio < 5500:
        return True, f'año {year} con precio {precio} es irreal'

    # Precio sospechosamente bajo: chequeamos contra CCA primero, después
    # cross-check con Kavak/ML para confirmar que NO es solo CCA desactualizado.
    cca = cca_prices.get(model_key)
    if cca and precio > 0 and precio < cca * 0.40:
        # Confirmar contra Kavak: si Kavak también dice precio normal, no es fake
        kavak = kavak_index.get(model_key)
        if kavak and precio >= kavak * 0.50:
            return False, ''  # CCA pifio, Kavak confirma precio razonable
        # Confirmar contra ML p25
        ml_p25 = ml_p25_index.get(model_key)
        if ml_p25 and precio >= ml_p25 * 0.50:
            return False, ''  # CCA pifio, ML confirma precio razonable
        return True, f'precio < 40% del CCA ({precio} vs {cca}), sin cross-check de mercado'

    # Si NO hay CCA pero Kavak/ML dicen que es absurdamente bajo, también fake
    if not cca and precio > 0:
        kavak = kavak_index.get(model_key)
        if kavak and precio < kavak * 0.35:
            return True, f'precio < 35% de mediana Kavak ({precio} vs {kavak})'
        ml_p25 = ml_p25_index.get(model_key)
        if ml_p25 and precio < ml_p25 * 0.40:
            return True, f'precio < 40% del p25 ML ({precio} vs {ml_p25})'

    return False, ''


# ─── Final ganga_confidence ───────────────────────────────────────────────────

WEIGHTS = {
    'kavak': 0.35,     # Kavak retail = lo más cercano a precio real de transacción
    'cca': 0.25,       # CCA = guía oficial, robusta pero a veces desactualizada
    'ml_p25': 0.15,    # ML p25 = piso de mercado público, cubre amplitud
    'outlier': 0.15,   # Bucket z-score, comparación local
    'velocity': 0.05,  # Refuerzo con data de demanda (cuando hay)
    'freshness': 0.05, # Modificador de oportunidad temporal
}

# Anchors "fuertes" que dan ground truth de precio (vs anchors "locales" como
# bucket/outlier que solo comparan contra otros listings). Para clasificar como
# super_ganga_v2 (≥80), exigimos al menos un anchor fuerte.
PRICE_ANCHORS = ('kavak', 'cca', 'ml_p25')


def _consensus_count(components: dict, threshold: int = 60) -> int:
    """Cuántos PRICE_ANCHORS tienen score ≥ threshold.

    Cuando dos o más anchors independientes coinciden en marcar el listing
    como barato, la confianza salta. Una sola ancla puede ser ruido.
    """
    return sum(1 for k in PRICE_ANCHORS if components.get(k) is not None and components[k] >= threshold)


def compute_ganga_confidence(
    listing: dict,
    cca_prices: dict,
    buckets: dict,
    velocity_stats: dict,
    kavak_index: Optional[dict] = None,
    ml_p25_index: Optional[dict] = None,
) -> dict:
    """Devuelve dict con 'score' (0-100), 'tag', 'breakdown', 'fake_reason', 'consensus'.

    Tag derivado:
      'fake'           si pasa el filtro is_likely_fake con consenso
      >= 80            super_ganga_v2 (requiere consensus ≥1 entre price anchors)
      >= 65            ganga_v2
      >= 45            interesante
      <  45            normal
      sin_referencia   si no hay ningún anchor disponible

    Consensus = count de price anchors (kavak/cca/ml_p25) que marcan el listing
    como barato (≥60 cada uno). Más consenso = más confiable.
    """
    bucket = bucket_stats_for(listing, buckets)
    velocity = velocity_stats.get(listing.get('model_key', '')) if velocity_stats else None
    kavak_index = kavak_index or {}
    ml_p25_index = ml_p25_index or {}

    # Filtro fake-first: si parece plan de ahorro o error de carga, no scoreamos.
    # Pasamos también Kavak/ML para cross-check (evita falsos positivos cuando
    # CCA está desactualizado pero Kavak/ML confirman que el precio es razonable).
    is_fake, fake_reason = is_likely_fake(listing, cca_prices, kavak_index, ml_p25_index)
    if is_fake:
        return {
            'score': 0,
            'tag': 'fake',
            'breakdown': {k: None for k in WEIGHTS},
            'bucket': bucket,
            'fake_reason': fake_reason,
            'consensus': 0,
        }

    components = {
        'kavak': kavak_component(listing, kavak_index),
        'cca': cca_component(listing, cca_prices),
        'ml_p25': ml_p25_component(listing, ml_p25_index),
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

    # Necesitamos al menos UN anchor (price o bucket) para opinar.
    has_anchor = any(components.get(k) is not None for k in PRICE_ANCHORS) or components.get('outlier') is not None
    if not has_anchor or total_weight == 0:
        return {
            'score': None,
            'tag': 'sin_referencia',
            'breakdown': components,
            'bucket': bucket,
            'fake_reason': None,
            'consensus': 0,
        }

    base = total_score / total_weight
    base *= quality_multiplier(listing)
    score = max(0, min(100, round(base)))

    # Consensus: cuántos price anchors agree
    consensus = _consensus_count(components)

    # Tag: para super_ganga_v2 exigimos ≥1 price anchor agree (no solo bucket)
    if score >= 80 and consensus >= 1:
        tag = 'super_ganga_v2'
    elif score >= 80:
        # Score alto pero sin price anchor convergente → degradar a ganga_v2
        tag = 'ganga_v2'
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
        'consensus': consensus,
    }


# ─── Helper para el scraper: anota cada listing in-place ──────────────────────

def annotate_listings(listings: list[dict], cca_prices: dict, velocity_stats: dict) -> dict:
    """Calcula ganga_confidence para cada listing y lo anota in-place.

    Agrega a cada listing los campos:
      - precio_cca, descuento_cca_pct
      - precio_kavak, descuento_kavak_pct  (cuando hay listings Kavak)
      - precio_ml_p25, descuento_ml_p25_pct (cuando hay ≥4 ML del modelo)
      - bucket_n, bucket_median_usd, bucket_z_score
      - ganga_confidence (0-100 o None)
      - ganga_tag ('super_ganga_v2' | 'ganga_v2' | 'interesante' | 'normal' | 'sin_referencia' | 'fake')
      - ganga_breakdown (dict con cada componente)
      - ganga_consensus (count de price anchors que concuerdan)

    Devuelve resumen de stats agregadas.
    """
    buckets = build_buckets(listings)
    kavak_index = build_kavak_index(listings)
    ml_p25_index = build_ml_p25_index(listings)

    out_stats = {
        'total': len(listings),
        'with_cca': 0,
        'with_kavak': 0,
        'with_ml_p25': 0,
        'with_bucket': 0,
        'with_velocity': 0,
        'kavak_models': len(kavak_index),
        'ml_p25_models': len(ml_p25_index),
        'super_ganga_v2': 0,
        'ganga_v2': 0,
        'interesante': 0,
        'sin_referencia': 0,
        'fake': 0,
        'consensus_2_plus': 0,  # listings con ≥2 anchors agree
    }

    def _pct(price, ref):
        return round((1 - price / ref) * 100, 1) if ref and price else None

    for l in listings:
        precio = l.get('precio_usd') or 0
        mk = l.get('model_key')

        # CCA
        cca = cca_prices.get(mk)
        if cca and cca > 0:
            l['precio_cca'] = cca
            l['descuento_cca_pct'] = _pct(precio, cca)
            out_stats['with_cca'] += 1
        else:
            l['precio_cca'] = None
            l['descuento_cca_pct'] = None

        # Kavak
        kavak = kavak_index.get(mk)
        if kavak:
            l['precio_kavak'] = kavak
            l['descuento_kavak_pct'] = _pct(precio, kavak)
            out_stats['with_kavak'] += 1
        else:
            l['precio_kavak'] = None
            l['descuento_kavak_pct'] = None

        # ML p25
        ml_p25 = ml_p25_index.get(mk)
        if ml_p25:
            l['precio_ml_p25'] = ml_p25
            l['descuento_ml_p25_pct'] = _pct(precio, ml_p25)
            out_stats['with_ml_p25'] += 1
        else:
            l['precio_ml_p25'] = None
            l['descuento_ml_p25_pct'] = None

        # Velocity
        v = velocity_stats.get(mk) if velocity_stats else None
        if v:
            out_stats['with_velocity'] += 1

        # Confidence
        result = compute_ganga_confidence(l, cca_prices, buckets, velocity_stats or {},
                                          kavak_index, ml_p25_index)
        l['ganga_confidence'] = result['score']
        l['ganga_tag'] = result['tag']
        l['ganga_breakdown'] = result['breakdown']
        l['ganga_consensus'] = result.get('consensus', 0)
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
        if l['ganga_consensus'] >= 2:
            out_stats['consensus_2_plus'] += 1

    return out_stats
