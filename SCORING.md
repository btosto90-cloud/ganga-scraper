# Ganga Hunter — Scoring v2 (precio justo auto-calibrado)

## Por qué este scoring

El Worker de Cloudflare hace scoring sobre la mediana de los OTROS listings del mismo modelo. Eso falla cuando todos los vendedores piden de más: una "ganga" termina siendo "menos inflada que el resto".

La versión anterior intentó arreglarlo con `cca_precios.json` (supuesta tabla de la Cámara del Comercio Automotor). **Ese archivo resultó ser data estimada/inflada, no oficial**: en el 64% de los modelos el "CCA" estaba por ENCIMA del precio pedido (un Renault Clio 2014 "valía" USD 19k cuando se pedía USD 6.9k), con curvas año→precio invertidas (un Corolla 2020 "valía" más que uno 2024). Resultado: fabricaba gangas falsas. **Quedó deprecado.**

El scoring vive en el **scraper** (no en el Worker), así iteramos sin redeployar Cloudflare. Cada listing en `listings.json` viene pre-anotado.

## El ancla central: precio justo auto-calibrado

En vez de una tabla externa, calculamos el "precio justo" por modelo+año **desde nuestra propia data**, en dos tiers:

1. **Venta real** (preferido) — `median_sale_price_usd` de `velocity_stats.json`, que se deriva de `fast_sales` (listings que desaparecieron antes de los 30 días = transacción real, no mero retiro). Es lo más cercano a "lo que la gente realmente paga".
2. **Pedido de comparables** — mediana de listings vivos del mismo `brand+model`, año±1, km±20% (n≥5).

```
precio_justo = 0.6 × venta_real + 0.4 × pedido_mediana   (si hay ambos)
             = venta_real                                  (si solo hay ventas)
             = pedido_mediana                              (si solo hay comparables)
             = None                                        (sin referencia)
```

El campo `model` ya viene limpio sin trim, así que el bucket agrupa bien (a diferencia de `model_key`, que trae `_cvt`, `_luxury`, etc.). Cobertura real: ~42% de los autos (vs 6% del CCA viejo), ~1.580 anclados a ventas reales.

## Pipeline

```
listings raw (RG + AC + ML + KV)
   │
   ├─ dedup · filtro is_realistic_price · first_seen + price_history
   ├─ is_new + recent_price_drop
   ├─ fast_sales detection (desaparecidos) → velocity_stats (días + median_sale_price_usd)
   │
   └─→ scoring.annotate_listings(listings, velocity_stats)
         ├─ build_buckets + build_sold_index + build_velocity_index
         ├─ Para cada listing calcula:
         │    precio_justo / ref_fuente / descuento_justo_pct
         │    precio_cca / descuento_cca_pct   (alias compat para frontend/notify)
         │    bucket_n / bucket_median_usd / bucket_z_score
         │    ganga_confidence (0-100) / ganga_tag / ganga_breakdown / fake_reason
         └─→ listings.json
```

## Las cuatro componentes (cada una 0-100)

### 1. Precio justo (peso 0.50) — **la señal central**
```
fair_score = clip( (1 - precio/precio_justo) × 350 , 0 , 100 )
```
- 30% bajo el precio justo → **100** · 15% bajo → **50** · al precio o encima → **0** · sin referencia → **None**

### 2. Outlier z-score (peso 0.30) — **señal local dentro del segmento**
```
bucket = listings mismo brand/model, año±1, km±20% (excluye self, n≥5)
z      = (precio - bucket_mean) / bucket_std
outlier_score = clip( -z × 40 , 0 , 100 )
```
- z=-2.5 → **100** · z=-1.0 → **40** · z≥0 → **0** · bucket <5 comp o std≈0 → **None**

### 3. Velocity (peso 0.10) — **demanda real**
| Mediana de días vividos | Score |
|---|---|
| ≤7 | 100 | ≤14 | 75 | ≤21 | 50 | ≤30 | 25 | >30 | 0 |

Lookup robusto al trim (`build_velocity_index` colapsa por base key). Arranca vacío y mejora con los runs.

### 4. Freshness (peso 0.10) — **oportunidad temporal**
| Estado | Score |
|---|---|
| `is_new` | 100 | drop ≥15% | 90 | ≥10% | 75 | ≥5% | 60 | otro | 30 |

## Combinación final
```
score_bruto = sum(componente × peso) / sum(pesos disponibles)
score_final = score_bruto × quality_multiplier
```
`quality_multiplier`: ×0.7 sin year, ×0.8 sin km, ×0.5 sin model.

**Si no hay precio justo NI outlier**, `ganga_confidence = None` y `ganga_tag = sin_referencia`.

## Filtro de fakes (corre primero)

Marca `ganga_tag = fake` (score 0, no notifica) si:
- keyword de plan/financiación en el título (`plan`, `cuotas`, `anticipo`, `a convenir`, …)
- precio irreal por año: 2022+ <7500 · 2019+ <5500 · 2018+ <4500
- **demasiado bueno para ser verdad**: precio <45% del precio justo (>55% off ≈ error de carga o bucket contaminado, no ganga)

## Tags resultantes
| Score | Tag |
|---|---|
| ≥80 | `super_ganga_v2` (notificable) |
| ≥65 | `ganga_v2` |
| ≥45 | `interesante` |
| <45 | `normal` |
| None | `sin_referencia` |

## Cómo iterar

### Debug de un listing
```bash
python3 debug_listing.py <id>
python3 debug_listing.py --top 10
python3 debug_listing.py --tag super_ganga_v2
```

### Cambiar pesos / umbrales
`WEIGHTS` y los thresholds de tag están en `scoring.py`. Después corré `pytest tests/` y el próximo run aplica los cambios. **Sin tocar el Worker.**

### Agregar una componente
1. `mi_componente(...) -> Optional[int]` en `scoring.py`
2. Agregar a `WEIGHTS`
3. Lookup en `compute_ganga_confidence`
4. Test en `tests/test_scoring.py`

Futuras: vendedor particular vs agencia, antigüedad de la publicación (>60d = vendedor flexible), ajuste fino por km dentro del bucket.

## Compatibilidad

El scraper sigue poblando `precio_cca`/`descuento_cca_pct` como **alias del precio justo** para no romper frontend ni notify. Nombres limpios nuevos: `precio_justo`, `descuento_justo_pct`, `ref_fuente`. El Worker hace `...listing`, así que todo viaja al frontend automáticamente.

## Tests
```bash
python3 -m pytest tests/ -v
```
75 tests: parsing, dedup, fast_sales, velocity, precio justo (sold index + blend), cada componente, fake filter (incl. guards extendidos), integración de `annotate_listings`, y notifier.
