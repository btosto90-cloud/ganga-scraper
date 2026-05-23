"""Catálogo de marcas/modelos del mercado argentino + extracción desde títulos.

Compartido por scraper.py (RG/AC) y ml_local.py (ML) para NO duplicar la lógica
(antes estaba copiada en ambos, con el mismo bug en los dos lados).

Mejoras vs la versión vieja:
  - Modelos scopeados por marca → evita colisiones cross-marca
    (ej: "Toyota 4x4" ya no matchea el "x4" de BMW).
  - Matching por tokens (no substring) → "x4" no matchea dentro de "4x4",
    pero "118i"/"320d" sí matchean 118/320 (sufijo de motor tolerado).
  - Devuelve el modelo más específico (más largo): "corolla cross" > "corolla".
  - Lista de modelos AR mucho más completa.
"""

import re

BRANDS_NORMALIZE = {
    'mercedes-benz': 'mercedes', 'mercedes benz': 'mercedes', 'mercedesbenz': 'mercedes',
    'vw': 'volkswagen', 'citroën': 'citroen', 'land rover': 'land_rover',
    'land-rover': 'land_rover', 'volkswagen': 'volkswagen',
}

KNOWN_BRANDS = [
    'mercedes-benz', 'mercedes benz', 'mercedesbenz', 'mercedes',
    'audi', 'toyota', 'volkswagen', 'vw', 'ford', 'chevrolet',
    'peugeot', 'renault', 'honda', 'fiat', 'bmw',
    'hyundai', 'kia', 'nissan', 'mazda', 'citroën', 'citroen',
    'jeep', 'mitsubishi', 'subaru', 'chery', 'haval', 'byd',
    'ram', 'dodge', 'suzuki', 'volvo', 'land rover',
]

# Modelos por marca (orden no importa: se elige el match más largo).
MODELS_BY_BRAND = {
    'toyota': ['corolla cross', 'corolla', 'hilux', 'sw4', 'etios', 'yaris', 'rav4',
               'c-hr', 'chr', 'fortuner', 'prius', 'land cruiser', 'innova', 'hiace',
               'camry', 'supra', '86'],
    'volkswagen': ['golf gti', 'golf r', 'polo gti', 'amarok', 'tiguan allspace', 'tiguan',
                   'taos', 'nivus', 'virtus', 't-cross', 'tcross', 'saveiro', 'suran',
                   'vento', 'polo', 'golf', 'gol', 'up', 'fox', 'crossfox', 'spacefox',
                   'bora', 'passat', 'voyage', 'scirocco'],
    'ford': ['focus rs', 'focus st', 'fiesta st', 'mustang', 'focus', 'fiesta', 'ka',
             'ecosport', 'ranger', 'territory', 'kuga', 'maverick', 'bronco', 'mondeo',
             'f-100', 'f-150', 'escort', 'transit'],
    'chevrolet': ['onix', 'tracker', 'cruze', 'equinox', 's10', 'spin', 'prisma', 'cobalt',
                  'agile', 'corsa', 'classic', 'montana', 'captiva', 'sonic', 'aveo',
                  'astra', 'vectra', 'celta', 'meriva', 'trailblazer'],
    'peugeot': ['2008', '3008', '5008', '208', '308', '408', '508', 'partner', 'expert',
                '207', '206', '307', 'rcz', 'boxer', '301'],
    'renault': ['megane rs', 'clio rs', 'sandero rs', 'duster oroch', 'duster', 'sandero',
                'logan', 'kwid', 'captur', 'arkana', 'oroch', 'megane', 'clio', 'kangoo',
                'master', 'trafic', 'symbol', 'fluence', 'koleos', 'stepway', 'alaskan'],
    'fiat': ['cronos', 'argo', 'pulse', 'fastback', 'mobi', 'toro', 'strada', 'palio',
             'siena', 'uno', 'idea', 'punto', 'linea', 'qubo', '500', '147', 'duna',
             'spazio', 'fiorino', 'ducato', 'tipo'],
    'honda': ['civic type r', 'civic', 'hr-v', 'hrv', 'cr-v', 'crv', 'wr-v', 'wrv', 'fit',
              'accord', 'city'],
    'hyundai': ['santa fe', 'tucson', 'creta', 'venue', 'i30', 'i10', 'i20', 'elantra',
                'accent', 'hb20', 'grand i10', 'kona'],
    'kia': ['sportage', 'sorento', 'seltos', 'stinger', 'cerato', 'rio', 'picanto', 'soul',
            'carnival', 'carens'],
    'nissan': ['gt-r', 'gtr', 'x-trail', 'xtrail', 'kicks', 'frontier', 'sentra', 'versa',
               'march', 'note', 'tiida', 'murano', 'qashqai'],
    'mazda': ['mazda2', 'mazda3', 'mazda6', 'cx-3', 'cx3', 'cx-5', 'cx5', 'cx-9', 'cx9',
              'cx-30', 'bt-50'],
    'citroen': ['c3 aircross', 'c4 cactus', 'c4 lounge', 'c4 picasso', 'c3', 'c4', 'c5',
                'berlingo', 'xsara', 'c-elysee', 'ds3', 'ds4', 'aircross', 'c-3', 'c-4'],
    'jeep': ['grand cherokee', 'renegade', 'compass', 'wrangler', 'gladiator', 'cherokee',
             'commander'],
    'bmw': ['m135', 'm140', 'm235', 'm240', 'm340', 'm440', 'm550', 'm2', 'm3', 'm4', 'm5',
            'm6', 'm8', 'serie 1', 'serie 2', 'serie 3', 'serie 4', 'serie 5',
            'x1', 'x2', 'x3', 'x4', 'x5', 'x6', 'x7', '116', '118', '120', '125',
            '318', '320', '325', '328', '330', '335', '420', '428', '430',
            '520', '523', '525', '530', '535', 'z4'],
    'mercedes': ['amg gt', 'a45', 'cla45', 'c43', 'c63', 'clase a', 'clase c', 'clase e',
                 'cla', 'gla', 'glb', 'glc', 'gle', 'gls', 'a200', 'a250', 'c180', 'c200',
                 'c250', 'c300', 'e200', 'e250', 'sprinter', 'vito'],
    'audi': ['rs3', 'rs4', 'rs5', 'rs6', 'rs q3', 'rs q5', 'tt rs', 's3', 's4', 's5', 'sq5',
             'a1', 'a3', 'a4', 'a5', 'a6', 'a7', 'q2', 'q3', 'q5', 'q7', 'q8', 'tt', 'e-tron'],
    'mitsubishi': ['outlander', 'asx', 'montero', 'l200', 'eclipse', 'lancer', 'pajero'],
    'subaru': ['impreza', 'forester', 'outback', 'xv', 'wrx', 'legacy'],
    'chery': ['tiggo 2', 'tiggo 4', 'tiggo 7', 'tiggo 8', 'tiggo', 'arrizo', 'qq'],
    'haval': ['jolion', 'h6', 'h2'],
    'byd': ['dolphin mini', 'dolphin', 'song', 'yuan', 'atto', 'han', 'tang', 'seal'],
    'suzuki': ['grand vitara', 'swift', 'vitara', 'baleno', 'jimny', 'fun', 's-cross'],
    'volvo': ['xc40', 'xc60', 'xc90', 's60', 'v40'],
    'ram': ['rampage', '1500', '700'],
    'dodge': ['journey', 'ram'],
    'land_rover': ['range rover', 'evoque', 'discovery', 'defender', 'freelander'],
}

# Índice plano (modelo, marca) ordenado por especificidad, para cuando no conocemos la marca.
_ALL_MODELS = sorted(
    {(m, b) for b, ms in MODELS_BY_BRAND.items() for m in ms},
    key=lambda x: -len(x[0]),
)

TRIMS = [
    'amg line', 'm sport', 'm-sport', 'r line', 'r-line', 'n line', 'n-line',
    'gt line', 'gt-line', 'st line', 'st-line', 's line', 's-line',
    'sport', 'sportback', 'sportline', 'avantgarde', 'progressive', 'exclusive',
    'gti', 'gtd', 'gts', 'rs', 'st', 'gt',
    'highline', 'comfortline', 'trendline',
    'titanium', 'limited', 'platinum', 'premium', 'luxury',
    'ultimate', 'top', 'tope de gama',
    'xei', 'xls', 'xlt', 'xei plus', 'xls plus',
    'awd', '4x4', 'quattro', 'xdrive', '4motion', '4matic',
    'cabrio', 'coupe', 'sedan', 'hatchback', 'wagon', 'sw',
    'cvt', 'dsg', 'tiptronic', 'automatico', 'automatic', 'manual',
]


def normalize_brand(brand):
    if not brand:
        return 'other'
    b = brand.lower().strip()
    return BRANDS_NORMALIZE.get(b, b).replace(' ', '_').replace('-', '_')


def find_brand_in_text(text):
    if not text:
        return None
    t = text.lower()
    for b in KNOWN_BRANDS:
        if b in t:
            return normalize_brand(b)
    return None


def _tok_list(text):
    """Tokeniza el texto: solo letras/números separados por espacio."""
    return re.sub(r'[^a-z0-9]+', ' ', text.lower()).split()


def _model_matches(model, tokens):
    """¿El modelo aparece como secuencia de tokens contigua?

    El último token tolera un sufijo corto de letras si el modelo tiene dígitos
    (ej. '118' matchea token '118i', '320' matchea '320d') — pero '208' NO matchea
    '2080' (sufijo numérico no permitido).
    """
    parts = model.replace('-', ' ').split()
    n = len(parts)
    for i in range(len(tokens) - n + 1):
        window = tokens[i:i + n]
        if window[:-1] != parts[:-1]:
            continue
        last_tok, last_part = window[-1], parts[-1]
        if last_tok == last_part:
            return True
        if any(c.isdigit() for c in last_part) and last_tok.startswith(last_part):
            suffix = last_tok[len(last_part):]
            if 0 < len(suffix) <= 2 and suffix.isalpha():
                return True
    return False


def find_model_in_text(text, brand=None):
    """Detecta el modelo en el título. Si se conoce la marca, scopea a sus modelos
    (evita colisiones cross-marca). Devuelve el más específico (más largo) o None."""
    if not text:
        return None
    tokens = _tok_list(text)
    if not tokens:
        return None
    nb = normalize_brand(brand) if brand else None
    if nb and nb in MODELS_BY_BRAND:
        cands = [m for m in MODELS_BY_BRAND[nb] if _model_matches(m, tokens)]
    else:
        cands = [m for (m, _b) in _ALL_MODELS if _model_matches(m, tokens)]
    if not cands:
        return None
    cands.sort(key=len, reverse=True)
    return cands[0].replace(' ', '_').replace('-', '_')


def find_trim(text):
    if not text:
        return None
    tokens = _tok_list(text)
    found = [trim for trim in TRIMS if _model_matches(trim, tokens)]
    if not found:
        return None
    found.sort(key=len, reverse=True)
    return found[0].replace(' ', '_').replace('-', '_')


def make_model_key(brand, model, year, trim=None):
    base = f"{brand or 'other'}_{model or 'other'}_{year}"
    if trim:
        base += f"_{trim}"
    return base


# ─── Ubicación / región ───────────────────────────────────────────────────────
# La zona de Bruno (gestión comercial en Córdoba/NOA/Cuyo): gangas que puede ir a ver.

# provincia normalizada -> región. Zona de interés de Bruno: su territorio comercial
# (Córdoba/NOA/Cuyo) + Santa Fe y Buenos Aires (donde también compra/sigue mercado).
ZONA_BRUNO = {
    'cordoba': 'Centro',
    'mendoza': 'Cuyo', 'san juan': 'Cuyo', 'san luis': 'Cuyo',
    'salta': 'NOA', 'jujuy': 'NOA', 'tucuman': 'NOA',
    'santiago del estero': 'NOA', 'catamarca': 'NOA', 'la rioja': 'NOA',
    'santa fe': 'Litoral',
    'buenos aires': 'Buenos Aires', 'bs.as': 'Buenos Aires', 'g.b.a': 'Buenos Aires',
    'capital federal': 'CABA',
}

# slugs de provincia para escanear ML por URL (targeted): SOLO la zona que el scan
# nacional sub-muestra (Córdoba/NOA/Cuyo). Santa Fe y BsAs NO van acá (ya entran fuerte
# por el nacional, y agregarlas targeted sobrecargaba ML → throttling/colgadas). Igual
# siguen priorizadas vía ZONA_BRUNO cuando aparecen.
# Vacío a propósito: el scan NACIONAL (22 marcas) ya barre TODO el país. El scan
# extra por provincia era redundante y sobrecargaba ML (bloqueo de IP). Sin él, el
# radar cubre el país igual y la zona de Bruno sigue priorizada vía ZONA_BRUNO (en_zona).
PROVINCIAS_ZONA = []


def _sin_acentos(s):
    for a, b in (('á', 'a'), ('é', 'e'), ('í', 'i'), ('ó', 'o'), ('ú', 'u')):
        s = s.replace(a, b)
    return s


def clasificar_ubicacion(loc):
    """Desde 'Ciudad - Provincia' devuelve (provincia, region, en_zona).

    en_zona = True si la provincia está en la zona de Bruno (Córdoba/NOA/Cuyo).
    """
    if not loc:
        return (None, None, False)
    prov_raw = loc.split(' - ')[-1].strip()
    p = _sin_acentos(prov_raw.lower())
    for key, region in ZONA_BRUNO.items():
        if key in p:
            return (prov_raw, region, True)
    return (prov_raw, 'Otra', False)
