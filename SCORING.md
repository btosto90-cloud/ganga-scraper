# Ganga Hunter — Scoring v2

## Por qué un scoring nuevo

El Worker de Cloudflare hace scoring sobre la mediana de los OTROS listings del mismo modelo. Eso falla cuando todos los vendedores piden de más: una "ganga" termina siendo "menos inflada que el resto", y las verdaderas oportunidades (cerca o bajo el precio CCA) compiten contra una mediana inflada y nunca cruzan los umbrales.

El nuevo scoring vive en el **scraper** (no en el Worker), así podemos iterar sin redeployar Cloudflare. Cada listing en `listings.json` viene pre-anotado con campos que el Worker, el frontend y el notificador pueden usar directo.

## Pipeline

```
listings raw (RG + AC + ML + KV)
   │
   ├─ dedup
   ├─ filtro is_realistic_price
   ├─ first_seen + price_history
   ├─ is_new + recent_price_drop
   ├─ fast_sales detection (desaparecidos)
   ├─ velocity_stats por model_key
   │
   └─→ scoring.annotate_listings()
         │
         ├─ Para cada listing, calcula:
         │    precio_cca           USD del CCA si hay match
         │    descuento_cca_pct    % bajo CCA
         │    bucket_n             count de comparables (modelo+año±1+km±20%)
         │    bucket_median_usd    mediana del bucket
         │    bucket_z_score       z-score del precio dentro del bucket
         │    ganga_confidence     0-100 final
         │    ganga_tag            super_ganga_v2 | ganga_v2 | interesante | normal | sin_referencia
         │    ganga_breakdown      {cca, outlier, velocity, freshness}
         │
         └─→ listings.json
```

## Las cuatro componentes (cada una 0-100)

### 1. CCA discount (peso 0.50) — **la señal más confiable cuando existe**

```
cca_score = clip( (1 - precio/precio_cca) × 350 , 0 , 100 )
```

- 30% bajo CCA → **100**
- 15% bajo CCA → **50**
- Sobre CCA → **0**
- Sin match en CCA → **None** (no contribuye)

CCA = Cámara del Comercio Automotor. Es ground truth porque viene de transacciones reales, no de pretensiones de venta. Tu `cca_precios.json` tiene 501 modelos. Cuando el listing tiene match (`model_key`), esto reemplaza al "descuento vs mediana inflada" del Worker viejo.

### 2. Outlier z-score (peso 0.30) — **señal local dentro del segmento**

```
bucket = listings con misma marca/modelo, año ±1, km ±20% (excluye self)
z      = (precio - bucket_mean) / bucket_std
outlier_score = clip( -z × 40 , 0 , 100 )
```

- z = -2.5 → **100** (precio extremadamente bajo dentro del bucket)
- z = -1.0 → **40**
- z ≥ 0 → **0** (no es outlier bajo)
- Bucket con < 5 comparables o std=0 → **None**

Captura gangas dentro del segmento: un Corolla 2020 con 50k km a USD 14k cuando el bucket promedia USD 19k, aunque CCA no exista para ese año exacto.

### 3. Velocity (peso 0.10) — **demanda real, basada en ventas pasadas**

```
velocity_score = f(median_days_lived del modelo en fast_sales)
```

| Mediana de días vividos | Score |
|---|---|
| ≤ 7 días  | 100 |
| ≤ 14 días | 75 |
| ≤ 21 días | 50 |
| ≤ 30 días | 25 |
| > 30 días | 0 |

`fast_sales.json` registra listings que desaparecieron antes de los 30 días → señal de venta real (no mero retiro). `velocity_stats.json` agrega por `model_key` (necesita ≥3 fast sales para ser estadísticamente significativo).

**Esta señal arranca vacía** y mejora a medida que pasan los runs. ~14 días después de empezar a trackear desaparecidos, va a tener data útil para los modelos populares.

### 4. Freshness (peso 0.10) — **modificador de oportunidad temporal**

| Estado | Score |
|---|---|
| `is_new == true` | 100 |
| `recent_price_drop` con drop ≥15% | 90 |
| `recent_price_drop` con drop ≥10% | 75 |
| `recent_price_drop` con drop ≥5%  | 60 |
| Otro | 30 |

Listings nuevos o con bajadas recientes son más accionables (todavía no fueron vistos por todo el mundo).

## Combinación final

```
score_bruto = sum(componente × peso) / sum(pesos disponibles)
score_final = score_bruto × quality_multiplier
```

`quality_multiplier`:
- × 0.7 si falta `year`
- × 0.8 si falta `km`
- × 0.5 si falta `model`

**Si no hay CCA NI outlier disponibles**, `ganga_confidence = None` y `ganga_tag = sin_referencia`. Honestamente no podemos opinar.

## Tags resultantes

| Score | Tag | Significado |
|---|---|---|
| ≥ 80 | `super_ganga_v2` | Múltiples señales convergen. Notificable. |
| ≥ 65 | `ganga_v2` | Buena oportunidad. |
| ≥ 45 | `interesante` | Mirar pero no urgente. |
| < 45 | `normal` | No prioridad. |
| `null` | `sin_referencia` | Sin data suficiente para opinar. |

## Cómo iterar

### Ver el scoring de un listing puntual
```bash
python3 debug_listing.py <id>            # Detalle full de un listing
python3 debug_listing.py --top 10        # Top 10 ganga_confidence
python3 debug_listing.py --tag super_ganga_v2  # Todos los super_ganga_v2
python3 debug_listing.py --model toyota_corolla_2020  # Bucket de un modelo
```

### Cambiar pesos / umbrales

Editás en `scoring.py`:

```python
WEIGHTS = {
    'cca': 0.50,
    'outlier': 0.30,
    'velocity': 0.10,
    'freshness': 0.10,
}
```

O los thresholds de tag dentro de `compute_ganga_confidence`:

```python
if score >= 80:  tag = 'super_ganga_v2'
elif score >= 65: tag = 'ganga_v2'
elif score >= 45: tag = 'interesante'
else:             tag = 'normal'
```

Después corrés los tests (`pytest tests/`) y el próximo run del scraper aplica los nuevos pesos. **Sin tocar el Worker.**

### Agregar una componente nueva

1. Definir `mi_componente(listing, ...) -> Optional[int]` en `scoring.py`
2. Agregarla a `WEIGHTS` con su peso
3. Agregar la lookup en `compute_ganga_confidence`
4. Test unitario en `tests/test_scoring.py`

Ejemplos de componentes futuras:
- **Vendedor type**: si es "particular" → +bonus, si es "agencia plan" → penalty
- **Antigüedad de la publicación**: pegado >60 días = vendedor flexible (urgencia)
- **Cohort comparison**: comparar contra ventas reales (Kavak data) por bucket

## Compatibilidad

El scoring v2 es **aditivo**. Los campos nuevos coexisten con los del Worker:

| Worker (server-side) | Scraper v2 (pre-computado) |
|---|---|
| `tag` | `ganga_tag` |
| `descuento_pct` (vs mediana inflada) | `descuento_cca_pct` (vs CCA real) |
| `score_combinado` (no existe acá) | `ganga_confidence` |
| `precio_referencia` (mediana del modelo) | `bucket_median_usd` (mediana del segmento) |

El Worker hace `...listing` en su response, así que todos los campos v2 viajan al frontend automáticamente. El notifier los usa directamente.

## Tests

```bash
pip install pytest
python3 -m pytest tests/ -v
```

56 tests cubren: parsing de precios, dedup, fast_sales, velocity, cada componente del scoring, integración end-to-end de `annotate_listings`, y la lógica del notifier.
