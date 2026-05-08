"""
Normalize raw scraped offers into the unified flight schema.

Input (from Source.fetch()):
    {source, title, url, slug, posted_at}

Output (per flight):
    {
      id, source, origin, destination, departure_date, return_date,
      airline, price, currency, price_usd, price_ars,
      stops, stops_detail, duration_minutes,
      baggage_included, tax_included, refundable, is_low_cost,
      cabin, booking_url, last_checked, confidence,
      route_key, raw_title, posted_at
    }

We extract what we can from the title (price/currency/origin/destination/direct)
and slug (airline/trip-type). Anything ambiguous becomes a sensible default.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
USD_TO_ARS = 1290           # mismo BLUE_RATE de Ganga Hunter Autos
EUR_TO_USD = 1.07
GBP_TO_USD = 1.27
BRL_TO_USD = 0.18
CLP_TO_USD = 0.0011
ARS_TO_USD = 1 / USD_TO_ARS

# IATA airport mapping. Origins (Argentina) vs destinations (rest).
ORIGIN_MAP = {
    # most generic first — order matters
    "buenos-aires": "EZE", "bs-as": "EZE", "ezeiza": "EZE",
    "aeroparque": "AEP", "bue": "EZE",
    "cordoba": "COR", "córdoba": "COR",
    "rosario": "ROS",
    "mendoza": "MDZ",
    "salta": "SLA",
    "tucuman": "TUC", "tucumán": "TUC",
}

DEST_MAP = {
    # USA
    "miami": "MIA", "nueva-york": "JFK", "new-york": "JFK", "ny": "JFK",
    "orlando": "MCO", "los-angeles": "LAX", "las-vegas": "LAS",
    "chicago": "ORD", "san-francisco": "SFO", "honolulu": "HNL",
    "boston": "BOS", "houston": "IAH", "dallas": "DFW", "atlanta": "ATL",
    "washington": "IAD",
    # Canada
    "toronto": "YYZ", "montreal": "YUL", "vancouver": "YVR",
    # Europa
    "madrid": "MAD", "barcelona": "BCN", "roma": "FCO", "milan": "MXP", "milán": "MXP",
    "paris": "CDG", "parís": "CDG", "londres": "LHR", "amsterdam": "AMS", "ámsterdam": "AMS",
    "lisboa": "LIS", "oporto": "OPO", "frankfurt": "FRA", "munich": "MUC",
    "florencia": "FLR", "venecia": "VCE", "atenas": "ATH", "estambul": "IST",
    "viena": "VIE", "praga": "PRG", "berlin": "BER", "berlín": "BER",
    "dublin": "DUB", "dublín": "DUB", "edimburgo": "EDI",
    # Caribe / México
    "cancun": "CUN", "cancún": "CUN", "punta-cana": "PUJ", "aruba": "AUA",
    "curazao": "CUR", "san-andres": "ADZ", "san-andrés": "ADZ",
    "cartagena-de-indias": "CTG", "cartagena": "CTG",
    "san-jose": "SJO", "panama": "PTY", "panamá": "PTY",
    "la-habana": "HAV", "cozumel": "CZM", "playa-del-carmen": "CZM",
    "mexico": "MEX", "méxico": "MEX",
    "santo-domingo": "SDQ", "puerto-rico": "SJU", "san-juan-puerto-rico": "SJU",
    # Brasil
    "rio-de-janeiro": "GIG", "san-pablo": "GRU", "sao-paulo": "GRU",
    "florianopolis": "FLN", "florianópolis": "FLN",
    "porto-seguro": "BPS", "salvador": "SSA", "salvador-de-bahia": "SSA",
    "natal": "NAT", "recife": "REC", "fortaleza": "FOR",
    "maceio": "MCZ", "maceió": "MCZ", "buzios": "BZC",
    "morro-de-san-pablo": "SSA", "jericoacoara": "JJD",
    # Sudamérica
    "santiago-de-chile": "SCL", "santiago": "SCL", "lima": "LIM",
    "bogota": "BOG", "bogotá": "BOG", "medellin": "MDE", "medellín": "MDE",
    "cuzco": "CUZ", "cusco": "CUZ", "asuncion": "ASU", "asunción": "ASU",
    "punta-del-este": "PDP", "montevideo": "MVD",
    "islas-galapagos": "GPS", "quito": "UIO", "guayaquil": "GYE",
    # Asia / Oceanía / África
    "tokio": "HND", "osaka": "KIX", "bangkok": "BKK", "dubai": "DXB",
    "tel-aviv": "TLV", "hong-kong": "HKG", "shanghai": "PVG", "beijing": "PEK",
    "delhi": "DEL", "abu-dhabi": "AUH",
    "sidney": "SYD", "auckland": "AKL", "melbourne": "MEL",
    "papeete": "PPT",
    "el-cairo": "CAI", "johannesburgo": "JNB", "ciudad-del-cabo": "CPT",
    # Argentina (domestic)
    "bariloche": "BRC", "iguazu": "IGR", "iguazú": "IGR", "puerto-iguazu": "IGR",
    "ushuaia": "USH", "el-calafate": "FTE", "puerto-madryn": "PMY",
    "neuquen": "NQN", "neuquén": "NQN", "mar-del-plata": "MDQ", "jujuy": "JUJ",
}

CITY_NAME = {v: k.replace("-", " ").title() for k, v in DEST_MAP.items()}
CITY_NAME.update({
    "EZE": "Buenos Aires", "AEP": "Buenos Aires", "COR": "Córdoba",
    "ROS": "Rosario", "MDZ": "Mendoza",
})

# Airline names → quality score (0-10) and low-cost flag
AIRLINES = {
    "aerolineas-argentinas": ("Aerolíneas Argentinas", 7, False),
    "latam": ("LATAM", 8, False),
    "iberia": ("Iberia", 8, False),
    "air-france": ("Air France", 8, False),
    "klm": ("KLM", 8, False),
    "lufthansa": ("Lufthansa", 9, False),
    "british-airways": ("British Airways", 8, False),
    "american-airlines": ("American Airlines", 7, False),
    "united": ("United", 7, False),
    "delta": ("Delta", 8, False),
    "copa": ("Copa Airlines", 7, False),
    "copa-airlines": ("Copa Airlines", 7, False),
    "air-europa": ("Air Europa", 6, False),
    "avianca": ("Avianca", 7, False),
    "gol": ("GOL", 6, False),
    "azul": ("Azul", 7, False),
    "jetsmart": ("JetSMART", 5, True),
    "flybondi": ("Flybondi", 4, True),
    "norwegian": ("Norwegian", 5, True),
    "level": ("Level", 5, True),
    "sky-airline": ("Sky Airline", 6, True),
    "turkish-airlines": ("Turkish Airlines", 9, False),
    "emirates": ("Emirates", 9, False),
    "qatar-airways": ("Qatar Airways", 9, False),
    "qatar": ("Qatar Airways", 9, False),
    "air-canada": ("Air Canada", 8, False),
    "arajet": ("Arajet", 5, True),
    "ita": ("ITA Airways", 7, False),
    "ita-airways": ("ITA Airways", 7, False),
    "el-al": ("El Al", 8, False),
    "el-al-israel-airlines": ("El Al", 8, False),
    "vueling": ("Vueling", 5, True),
    "ryanair": ("Ryanair", 4, True),
    "easyjet": ("EasyJet", 5, True),
    "wizz-air": ("Wizz Air", 4, True),
    "aeromexico": ("Aeroméxico", 7, False),
}

# Currency tokens in titles
CURRENCY_PATTERNS = [
    (re.compile(r"U\$D\s*([\d.,]+)", re.I), "USD"),
    (re.compile(r"USD\s*([\d.,]+)", re.I), "USD"),
    (re.compile(r"AR\$\s*([\d.,]+)", re.I), "ARS"),
    (re.compile(r"ARS\s*([\d.,]+)", re.I), "ARS"),
    (re.compile(r"€\s*([\d.,]+)"), "EUR"),
    (re.compile(r"EUR\s*([\d.,]+)", re.I), "EUR"),
    (re.compile(r"£\s*([\d.,]+)"), "GBP"),
    (re.compile(r"GBP\s*([\d.,]+)", re.I), "GBP"),
    (re.compile(r"R\$\s*([\d.,]+)"), "BRL"),
]

DIRECTO_RE = re.compile(r"\b(directo|directos)\b", re.I)
TRAMO_DIRECTO_RE = re.compile(r"tramo[s]?\s+directo[s]?", re.I)


def to_usd(amount: float, currency: str) -> float:
    if currency == "USD":
        return amount
    if currency == "ARS":
        return amount * ARS_TO_USD
    if currency == "EUR":
        return amount * EUR_TO_USD
    if currency == "GBP":
        return amount * GBP_TO_USD
    if currency == "BRL":
        return amount * BRL_TO_USD
    if currency == "CLP":
        return amount * CLP_TO_USD
    return amount


def _parse_price(title: str) -> tuple[Optional[float], Optional[str]]:
    """Return (price, currency_code) parsed from the title."""
    for pattern, currency in CURRENCY_PATTERNS:
        m = pattern.search(title)
        if m:
            raw = m.group(1).replace(".", "").replace(",", ".")
            try:
                # Handle Argentine number formats: "1.269" = 1269 (no decimals);
                # but "1.5" could be 1.5. Heuristic: if last group is 3 digits, it's a thousands separator.
                # Above we strip "." everywhere because in Argentine notation prices use "." as thousands sep.
                # That gives us "1269" → 1269 and "964" → 964. Sufficient for flight prices.
                return float(raw), currency
            except ValueError:
                continue
    return None, None


def _parse_origin(slug: str, title: str) -> Optional[str]:
    """Look for 'desde X' patterns in slug or title."""
    text = (slug + " " + title.lower()).replace(" ", "-")
    # Try most specific first: slug-style "desde-buenos-aires"
    for key in sorted(ORIGIN_MAP.keys(), key=len, reverse=True):
        if f"desde-{key}" in text:
            return ORIGIN_MAP[key]
    # Fallback: any origin keyword in slug
    for key, iata in ORIGIN_MAP.items():
        if f"-{key}-" in text or text.endswith(f"-{key}"):
            return iata
    return None


def _parse_destination(slug: str, title: str) -> Optional[str]:
    """Pull the destination IATA code from slug/title."""
    text = slug.lower()
    title_lc = title.lower()

    # Slugs typically start with 'vuelos-(directos-)?a-X' or 'X-desde-Y'
    # Try patterns with "a-X" first
    for key in sorted(DEST_MAP.keys(), key=len, reverse=True):
        # match -a-X- or vuelos-a-X- or vuelos-directos-a-X-
        if (f"-a-{key}-" in f"-{text}-") or text.startswith(f"a-{key}-") or text.startswith(f"{key}-"):
            return DEST_MAP[key]
        if f"a {key.replace('-', ' ')}" in title_lc:
            return DEST_MAP[key]

    # Last resort: any destination keyword anywhere
    for key, iata in DEST_MAP.items():
        if key in text:
            return iata
    return None


def _parse_airline(slug: str) -> tuple[str, int, bool]:
    """Return (airline_name, quality 0-10, is_low_cost). Default if not found."""
    text = slug.lower()
    # Order by length desc to catch multi-word keys first
    for key in sorted(AIRLINES.keys(), key=len, reverse=True):
        if key in text:
            return AIRLINES[key]
    return ("Desconocida", 6, False)


def _parse_trip_type(slug: str) -> str:
    """Return one of: 'rt' (round trip), 'md' (multi-destino), 'ow' (one-way), 'unknown'."""
    text = slug.lower()
    # The ad-hoc convention used in promociones-aereas slugs:
    # ...-rt-p / -md-p / -ow-p (sometimes -p-2, -p-3, etc.)
    if re.search(r"-rt-p(?:-\d+)?$", text):
        return "rt"
    if re.search(r"-md-p(?:-\d+)?$", text):
        return "md"
    if re.search(r"-ow-p(?:-\d+)?$", text):
        return "ow"
    return "unknown"


def _make_id(url: str) -> str:
    return "f_" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def normalize_offer(raw: dict) -> Optional[dict]:
    title = raw.get("title", "")
    slug = (raw.get("slug") or "").lower()
    url = raw.get("url", "")
    if not (title and slug and url):
        return None

    price, currency = _parse_price(title)
    if not price or not currency:
        # No price found = useless for scoring, skip
        return None

    origin = _parse_origin(slug, title)
    destination = _parse_destination(slug, title)
    if not origin or not destination or origin == destination:
        return None

    airline, airline_quality, is_low_cost = _parse_airline(slug)
    trip_type = _parse_trip_type(slug)

    # Heuristics for the rest of the schema
    is_direct = bool(DIRECTO_RE.search(title)) and not TRAMO_DIRECTO_RE.search(title)
    is_partial_direct = bool(TRAMO_DIRECTO_RE.search(title)) or "un tramo directo" in title.lower()

    if is_direct:
        stops = 0
    elif is_partial_direct:
        stops = 1
    else:
        # Without info, assume 1 stop for international (long routes), 0 for very short
        stops = 1

    # Crude duration heuristic — only used if we don't have it. Mostly placeholder
    # so the quality scorer can still run. The frontend hides it if zero.
    duration_minutes = 0

    # Confidence: source curates the offer, so high-ish; but no live data → not 1.0
    confidence = 0.85

    price_usd = round(to_usd(price, currency), 2)
    price_ars = round(price_usd * USD_TO_ARS)

    return {
        "id": _make_id(url),
        "source": raw.get("source", "unknown"),
        "origin": origin,
        "destination": destination,
        "route_key": f"{origin}-{destination}",
        "airline": airline,
        "airline_quality": airline_quality,
        "is_low_cost": is_low_cost,
        "price": price,
        "currency": currency,
        "price_usd": price_usd,
        "price_ars": price_ars,
        "stops": stops,
        "stops_detail": [],
        "duration_minutes": duration_minutes,
        "baggage_included": _guess_baggage(title),
        "tax_included": True,  # promociones-aereas typically posts final
        "refundable": False,
        "cabin": "economy",
        "booking_url": url,
        "trip_type": trip_type,
        "is_direct": is_direct,
        "is_partial_direct": is_partial_direct,
        "raw_title": title,
        "posted_at": raw.get("posted_at"),
        "last_checked": datetime.now(timezone.utc).date().isoformat(),
        "confidence": confidence,
    }


def _guess_baggage(title: str) -> bool:
    """Try to infer if bagging is included from the title text."""
    t = title.lower()
    if "carry on" in t or "carry-on" in t or "con valija" in t or "equipaje en bodega" in t:
        return True
    return False  # default conservative
