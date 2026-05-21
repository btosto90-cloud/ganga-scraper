"""Ganga Hunter scoring — pre-computed en el scraper, leído por el Worker.

Filosofía: el Worker compara cada listing contra la mediana de OTROS listings, así
que una "ganga" termina siendo "menos inflada que el resto". Para encontrar gangas
REALES anclamos cada precio a un **precio justo auto-calibrado desde la propia data**:

  1. PRECIO JUSTO (señal principal) — mezcla de:
       a) precio de venta real (median_sale_price_usd de velocity_stats, derivado de
          listings que desaparecieron = transacciones reales), y
       b) mediana de comparables vivos (mismo brand+model, año±1, km±20%).
     Reemplaza al viejo `cca_precios.json`, que era data estimada/inflada (en 64% de
     los modelos el "CCA" estaba por ENCIMA del precio pedido → fabricaba gangas falsas).

  2. OUTLIER z-score — qué tan bajo está el precio dentro de su segmento.
  3. VELOCITY — modelos que venden rápido = demanda real = más confianza.
  4. FRESHNESS — listings nuevos o recién bajados son más accionables.

Combinamos las cuatro en `ganga_confidence` (0-100). Solo es "verdadera ganga" cuando
varias señales convergen. Las funciones son puras y testeables.

Nota de compatibilidad: seguimos poblando `precio_cca`/`descuento_cca_pct` (ahora con
el precio justo) para no romper frontend ni notify; los nombres limpios nuevos son
`precio_justo`/`descuento_justo_pct`/`ref_fuente`.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date
from typing import Optional


# ─── Helpers de model_key ─────────────────────────────────────────────────────

def base_model_key(model_key: Optional[str]) -> Optional[str]:
    """brand_model_year — quita el trim que viene después del año.

    'honda_hr_v_2016_cvt' -> 'honda_hr_v_2016'
    'toyota_corolla_2020' -> 'toyota_corolla_2020'
    """
    if not model_key:
        return None
    parts = model_key.split('_')
    for i, p in enumerate(parts):
        if len(p) == 4 and p.isdigit():
            return '_'.join(parts[:i + 1])
    return None


# ─── Bucket stats ─────────────────────────────────────────────────────────────

def build_buckets(listings: list[dict]) -> dict:
    """Agrupa listings por (brand, model) para lookup rápido por bucket.

    Excluye fakes obvios (planes de ahorro / anticipos / precios irreales) del pool
    de comparables: si no, contaminan la mediana y la regresión por km de los reales.

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
        # Sin precio justo todavía: detecta fakes por keyword + precio/año irreal.
        if is_likely_fake(l)[0]:
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


# ─── Precio justo auto-calibrado ──────────────────────────────────────────────

def build_sold_index(velocity_stats: dict) -> dict:
    """{base_key: precio_venta_ponderado} desde velocity_stats.

    velocity_stats viene keyed por model_key (a veces con trim). Colapsamos por base
    (brand_model_year) ponderando por cantidad de ventas (n).
    """
    by_base: dict[str, list[tuple]] = defaultdict(list)
    for mk, v in (velocity_stats or {}).items():
        price = v.get('median_sale_price_usd')
        if not price or v.get('n', 0) < 3:
            continue
        base = base_model_key(mk)
        if base:
            by_base[base].append((v.get('n', 1), price))
    out = {}
    for base, arr in by_base.items():
        total_n = sum(n for n, _ in arr)
        out[base] = round(sum(n * p for n, p in arr) / total_n)
    return out


def build_velocity_index(velocity_stats: dict) -> dict:
    """{base_key: mejor_entry_velocity} (la de mayor n) para lookup robusto al trim."""
    by_base: dict[str, dict] = {}
    for mk, v in (velocity_stats or {}).items():
        base = base_model_key(mk)
        if not base:
            continue
        if base not in by_base or v.get('n', 0) > by_base[base].get('n', 0):
            by_base[base] = v
    return by_base


def km_predicted_price(listing: dict, buckets: dict, year_window: int = 1,
                       min_n: int = 8) -> Optional[int]:
    """Precio esperado ajustado por km: regresión lineal precio~km sobre el grupo
    (misma marca/modelo, año±1). Un mismo modelo+año pierde valor con los km
    (correlación ~-0.5), así que un auto de pocos km vale más que la mediana del grupo
    y uno de muchos, menos. Ayuda a detectar gangas en los extremos de km.

    Guardas anti-ruido: n≥min_n, pendiente negativa, spread de km ≥20.000, y se clampea
    al rango de precios observado (no extrapola). None si no aplica → cae a la mediana.
    """
    if not (listing.get('brand') and listing.get('model')
            and listing.get('year') and listing.get('km')):
        return None
    group = buckets.get((listing['brand'], listing['model']), [])
    if len(group) < min_n:
        return None
    yr, own = listing['year'], listing.get('id')
    pts = [(x['km'], x['precio']) for x in group
           if x.get('id') != own and abs(x['year'] - yr) <= year_window]
    if len(pts) < min_n:
        return None
    kms = [p[0] for p in pts]
    prs = [p[1] for p in pts]
    if max(kms) - min(kms) < 20000:
        return None  # poco spread de km → la regresión no aporta
    n = len(pts)
    mk = sum(kms) / n
    mp = sum(prs) / n
    den = sum((k - mk) ** 2 for k in kms)
    var_pr = sum((p - mp) ** 2 for p in prs)
    if den == 0 or var_pr == 0:
        return None
    num = sum((k - mk) * (p - mp) for k, p in zip(kms, prs))
    corr = num / (den ** 0.5 * var_pr ** 0.5)
    if corr > -0.3:
        return None  # km no predice bien el precio en este grupo (ruido) → cae a mediana
    slope = num / den
    pred = (mp - slope * mk) + slope * listing['km']
    pred = max(min(prs), min(max(prs), pred))  # clamp al rango observado (no extrapola)
    return round(pred)


def fair_price_for(listing: dict, bucket: Optional[dict], sold_index: dict,
                   km_pred: Optional[int] = None) -> Optional[dict]:
    """Precio justo del listing: mezcla venta real (60%) + referencia de pedidos (40%).

    La referencia de pedidos es el precio ajustado por km (km_pred) si está disponible;
    si no, la mediana del bucket. Devuelve {'fair', 'source', 'n'} o None.
    """
    base = base_model_key(listing.get('model_key'))
    sold = sold_index.get(base) if base else None
    if km_pred:
        asking, asking_src = km_pred, 'km'
    elif bucket:
        asking, asking_src = bucket.get('median'), 'p50'
    else:
        asking, asking_src = None, None

    if sold and asking:
        return {'fair': round(0.6 * sold + 0.4 * asking), 'source': 'venta+pedido',
                'n': bucket.get('n') if bucket else None}
    if sold:
        return {'fair': sold, 'source': 'venta_real', 'n': None}
    if asking:
        return {'fair': asking, 'source': f'pedido_{asking_src}',
                'n': bucket.get('n') if bucket else None}
    return None


# ─── Component scores (0-100 each) ────────────────────────────────────────────

def fair_price_component(listing: dict, fair: Optional[dict]) -> Optional[int]:
    """% bajo el precio justo, escalado: 30% bajo → 100. None si no hay precio justo."""
    if not fair or not listing.get('precio_usd'):
        return None
    fp = fair.get('fair') or 0
    if fp <= 0:
        return None
    pct = (1 - listing['precio_usd'] / fp) * 100
    if pct <= 0:
        return 0  # al precio o por encima: no es ganga
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


def days_on_market(listing: dict, today: Optional[date] = None) -> Optional[int]:
    """Días desde que vimos el listing por primera vez (first_seen).

    Es nuestra mejor señal de antigüedad: la API pública de ML que daba la fecha de
    publicación dejó de funcionar (401). Arranca en 0 y se vuelve precisa a medida que
    se acumulan corridas diarias. None si no hay first_seen.
    """
    fs = listing.get('first_seen')
    if not fs:
        return None
    try:
        seen = date.fromisoformat(fs[:10])
    except (ValueError, TypeError):
        return None
    return max(0, ((today or date.today()) - seen).days)


def negotiation_component(listing: dict) -> Optional[int]:
    """Listings que llevan mucho tiempo sin venderse = vendedor más negociable.

    Neutral (0) para publicaciones recientes; sube con la antigüedad. Lee
    `days_on_market` precalculado por annotate_listings. None si no se puede estimar.
    """
    d = listing.get('days_on_market')
    if d is None:
        return None
    if d < 45:
        return 0
    if d < 90:
        return 40
    if d < 180:
        return 70
    return 100


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


def is_likely_fake(listing: dict, fair_price: Optional[float] = None) -> tuple[bool, str]:
    """Detecta listings que NO son ofertas reales: planes de ahorro, errores de carga,
    publicaciones con precio anclado bajo (anticipo), o descuentos imposibles.

    Devuelve (is_fake, reason).
    """
    title = (listing.get('title') or '').lower()
    for kw in PLAN_KEYWORDS:
        if kw in title:
            return True, f'keyword: "{kw}"'

    precio = listing.get('precio_usd') or 0
    year = listing.get('year') or 0

    # Auto reciente con precio absurdo (escalonado por antigüedad)
    if year >= 2022 and precio < 7500:
        return True, f'año {year} con precio {precio} es irreal'
    if year >= 2019 and precio < 5500:
        return True, f'año {year} con precio {precio} es irreal'
    if year >= 2018 and precio < 4500:
        return True, f'año {year} con precio {precio} es irreal'

    # Demasiado bueno para ser verdad: >55% bajo el precio justo casi siempre es
    # error de carga, plan de ahorro o bucket contaminado, no una ganga real.
    if fair_price and precio > 0 and fair_price > 0:
        if precio < fair_price * 0.45:
            return True, f'descuento irreal: {precio} es <45% del precio justo {fair_price}'

    return False, ''


# ─── Final ganga_confidence ───────────────────────────────────────────────────

WEIGHTS = {
    'fair': 0.50,        # Precio justo auto-calibrado: la señal más confiable
    'outlier': 0.30,     # Bucket z-score, segundo en confianza
    'velocity': 0.10,    # Refuerzo cuando hay data de demanda
    'freshness': 0.10,   # Modificador de oportunidad temporal (nuevo/bajó)
    'negotiation': 0.05, # Antigüedad en mercado (vendedor negociable). Madura con el tiempo.
}


def compute_ganga_confidence(
    listing: dict,
    buckets: dict,
    sold_index: dict,
    velocity_index: dict,
) -> dict:
    """Devuelve dict con 'score' (0-100), 'tag', 'breakdown', 'fair', 'fake_reason'.

    Tag derivado:
      'fake'           si pasa el filtro is_likely_fake
      >= 80            super_ganga_v2
      >= 65            ganga_v2
      >= 45            interesante
      <  45            normal
      sin_referencia   si no hay precio justo ni bucket disponibles
    """
    bucket = bucket_stats_for(listing, buckets)
    km_pred = km_predicted_price(listing, buckets)
    fair = fair_price_for(listing, bucket, sold_index, km_pred)
    base = base_model_key(listing.get('model_key'))
    velocity = velocity_index.get(base) if (velocity_index and base) else None

    # Filtro fake-first: plan de ahorro, error de carga o descuento imposible.
    is_fake, fake_reason = is_likely_fake(listing, fair.get('fair') if fair else None)
    if is_fake:
        return {
            'score': 0,
            'tag': 'fake',
            'breakdown': {'fair': None, 'outlier': None, 'velocity': None,
                          'freshness': None, 'negotiation': None},
            'bucket': bucket,
            'fair': fair,
            'fake_reason': fake_reason,
        }

    components = {
        'fair': fair_price_component(listing, fair),
        'outlier': outlier_component(bucket),
        'velocity': velocity_component(velocity),
        'freshness': freshness_component(listing),
        'negotiation': negotiation_component(listing),
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

    # Si no hay precio justo NI outlier, no podemos opinar (solo freshness/velocity)
    has_anchor = components['fair'] is not None or components['outlier'] is not None
    if not has_anchor or total_weight == 0:
        return {
            'score': None,
            'tag': 'sin_referencia',
            'breakdown': components,
            'bucket': bucket,
            'fair': fair,
            'fake_reason': None,
        }

    base_score = total_score / total_weight
    base_score *= quality_multiplier(listing)
    score = max(0, min(100, round(base_score)))

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
        'fair': fair,
        'fake_reason': None,
    }


# ─── Helper para el scraper: anota cada listing in-place ──────────────────────

def annotate_listings(listings: list[dict], velocity_stats: dict,
                      cca_prices: Optional[dict] = None, today: Optional[date] = None) -> dict:
    """Calcula ganga_confidence para cada listing y lo anota in-place.

    `cca_prices` se acepta por compatibilidad pero ya NO se usa (era data inflada).
    `today` permite fijar la fecha de referencia en tests (default: hoy).

    Agrega a cada listing:
      - precio_justo, descuento_justo_pct, ref_fuente (nombres limpios)
      - precio_cca, descuento_cca_pct (alias del precio justo, para no romper frontend/notify)
      - bucket_n, bucket_median_usd, bucket_z_score
      - days_on_market (días desde first_seen)
      - ganga_confidence, ganga_tag, ganga_breakdown, fake_reason

    Devuelve resumen de stats agregadas.
    """
    today = today or date.today()
    buckets = build_buckets(listings)
    sold_index = build_sold_index(velocity_stats)
    velocity_index = build_velocity_index(velocity_stats)

    out_stats = {
        'total': len(listings),
        'with_ref': 0,
        'with_sold': 0,
        'with_bucket': 0,
        'with_velocity': 0,
        'super_ganga_v2': 0,
        'ganga_v2': 0,
        'interesante': 0,
        'sin_referencia': 0,
        'fake': 0,
    }
    for l in listings:
        # days_on_market debe estar seteado ANTES de scorear (negotiation_component lo lee)
        l['days_on_market'] = days_on_market(l, today)
        result = compute_ganga_confidence(l, buckets, sold_index, velocity_index)

        # Precio justo (+ alias de compatibilidad precio_cca)
        fair = result.get('fair')
        if fair:
            fp = fair['fair']
            disc = round((1 - l['precio_usd'] / fp) * 100, 1) if l.get('precio_usd') and fp else None
            l['precio_justo'] = fp
            l['ref_fuente'] = fair['source']
            l['descuento_justo_pct'] = disc
            l['precio_cca'] = fp                 # alias compat (frontend/notify)
            l['descuento_cca_pct'] = disc        # alias compat
            out_stats['with_ref'] += 1
            if fair['source'] in ('venta_real', 'venta+pedido'):
                out_stats['with_sold'] += 1
        else:
            l['precio_justo'] = None
            l['ref_fuente'] = None
            l['descuento_justo_pct'] = None
            l['precio_cca'] = None
            l['descuento_cca_pct'] = None

        base = base_model_key(l.get('model_key'))
        if velocity_index.get(base):
            out_stats['with_velocity'] += 1

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
