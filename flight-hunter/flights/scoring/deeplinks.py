"""
Build deeplinks to flight search engines from the normalized flight schema.

For each flight we generate URLs to:
  - Skyscanner (Argentina edition, calendar view if no dates)
  - Google Flights (search view)
  - Kayak (Argentina, "anytime" if no dates)

When the title hints at specific months (e.g. "enero 2027", "en verano"), we
try to construct a dated URL. Otherwise we fall back to "any date" views which
show a calendar of prices — useful because the user can find the cheap day.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from urllib.parse import quote_plus

# Spanish month names → number
MONTHS = {
    "enero": 1, "ene": 1,
    "febrero": 2, "feb": 2,
    "marzo": 3, "mar": 3,
    "abril": 4, "abr": 4,
    "mayo": 5, "may": 5,
    "junio": 6, "jun": 6,
    "julio": 7, "jul": 7,
    "agosto": 8, "ago": 8,
    "septiembre": 9, "setiembre": 9, "sep": 9, "set": 9,
    "octubre": 10, "oct": 10,
    "noviembre": 11, "nov": 11,
    "diciembre": 12, "dic": 12,
}

# "Verano argentino" = dec-feb, "invierno" = jun-aug, etc.
SEASONS_AR = {
    "verano": (1, 15),     # mid-january is peak summer
    "invierno": (7, 15),   # mid-july is peak winter (school break)
    "primavera": (10, 15),
    "otoño": (4, 15),
    "otono": (4, 15),
}

CITY_NAMES = {
    "EZE": "Buenos Aires", "AEP": "Buenos Aires", "BUE": "Buenos Aires",
    "COR": "Córdoba", "ROS": "Rosario", "MDZ": "Mendoza",
    "MIA": "Miami", "JFK": "New York", "MCO": "Orlando",
    "MAD": "Madrid", "BCN": "Barcelona", "FCO": "Rome", "CDG": "Paris",
    "LHR": "London", "AMS": "Amsterdam", "LIS": "Lisbon",
    "CUN": "Cancun", "MEX": "Mexico City", "PUJ": "Punta Cana",
    "AUA": "Aruba", "ADZ": "San Andres",
    "GRU": "Sao Paulo", "GIG": "Rio de Janeiro", "FLN": "Florianopolis",
    "BPS": "Porto Seguro", "MCZ": "Maceio", "SSA": "Salvador",
    "SCL": "Santiago", "LIM": "Lima", "BOG": "Bogota",
    "TLV": "Tel Aviv", "DXB": "Dubai", "HND": "Tokyo",
}


def _guess_dates(raw_title: str) -> tuple[date | None, date | None]:
    """Parse the title best-effort. Return (depart_date, return_date) or (None, None)."""
    if not raw_title:
        return None, None
    t = raw_title.lower()
    today = date.today()

    # Try explicit "MES YYYY" pattern (e.g. "enero 2027", "en julio")
    for name, num in MONTHS.items():
        m = re.search(rf"\b{name}\b\s*(20\d{{2}})?", t)
        if m:
            year_str = m.group(1)
            year = int(year_str) if year_str else (
                today.year if num >= today.month else today.year + 1
            )
            depart = date(year, num, 15)  # mid-month as default
            ret = depart + timedelta(days=14)  # 2-week trip default
            return depart, ret

    # Season hints (Argentine seasons)
    for name, (month, day) in SEASONS_AR.items():
        if re.search(rf"\b{name}\b", t):
            year = today.year if month >= today.month else today.year + 1
            depart = date(year, month, day)
            ret = depart + timedelta(days=14)
            return depart, ret

    return None, None


def build_search_links(flight: dict) -> dict:
    origin = flight["origin"]
    dest = flight["destination"]
    trip_type = flight.get("trip_type", "rt")
    raw = flight.get("raw_title", "")

    # Priority 1: dates parsed from the post body table (most accurate)
    departure_date = flight.get("departure_date")
    return_date = flight.get("return_date")

    if departure_date:
        try:
            depart = date.fromisoformat(departure_date)
            ret = date.fromisoformat(return_date) if return_date else None
            date_source = "post_table"
        except (ValueError, TypeError):
            depart, ret = _guess_dates(raw)
            date_source = "title_guess" if depart else "none"
    else:
        # Priority 2: best-effort guess from the title
        depart, ret = _guess_dates(raw)
        date_source = "title_guess" if depart else "none"

    skys = _skyscanner(origin, dest, trip_type, depart, ret)
    google = _google_flights(origin, dest, trip_type, depart, ret)
    kayak = _kayak(origin, dest, trip_type, depart, ret)
    momondo = _momondo(origin, dest, trip_type, depart, ret)

    return {
        "skyscanner": skys,
        "google_flights": google,
        "kayak": kayak,
        "momondo": momondo,
        "guessed_dates": {
            "depart": depart.isoformat() if depart else None,
            "return": ret.isoformat() if ret else None,
            "source": date_source,
        },
    }


def _skyscanner(orig: str, dest: str, trip: str, depart: date | None, ret: date | None) -> str:
    # Skyscanner Argentina, lowercase IATA
    base = f"https://www.skyscanner.com.ar/transporte/vuelos/{orig.lower()}/{dest.lower()}/"
    if depart:
        d_str = depart.strftime("%y%m%d")
        if trip == "rt" and ret:
            r_str = ret.strftime("%y%m%d")
            return base + f"{d_str}/{r_str}/?adults=1&adultsv2=1&cabinclass=economy"
        return base + f"{d_str}/?adults=1"
    return base + "?adults=1"


def _google_flights(orig: str, dest: str, trip: str, depart: date | None, ret: date | None) -> str:
    # Google Flights search query — robust because it uses natural search
    o_name = CITY_NAMES.get(orig, orig)
    d_name = CITY_NAMES.get(dest, dest)
    if depart:
        date_str = f" on {depart.isoformat()}"
        if trip == "rt" and ret:
            date_str += f" returning {ret.isoformat()}"
    else:
        date_str = ""
    q = f"flights from {o_name} to {d_name}{date_str}"
    return f"https://www.google.com/travel/flights?q={quote_plus(q)}"


def _kayak(orig: str, dest: str, trip: str, depart: date | None, ret: date | None) -> str:
    # Kayak Argentina
    if depart:
        d_str = depart.isoformat()
        if trip == "rt" and ret:
            r_str = ret.isoformat()
            return f"https://www.kayak.com.ar/flights/{orig}-{dest}/{d_str}/{r_str}"
        return f"https://www.kayak.com.ar/flights/{orig}-{dest}/{d_str}"
    return f"https://www.kayak.com.ar/flights/{orig}-{dest}/anytime/anytime"


def _momondo(orig: str, dest: str, trip: str, depart: date | None, ret: date | None) -> str:
    # Momondo (often shows different airlines than Kayak even though same parent)
    if depart:
        d_str = depart.isoformat()
        if trip == "rt" and ret:
            r_str = ret.isoformat()
            return f"https://www.momondo.com/flight-search/{orig}-{dest}/{d_str}/{r_str}"
        return f"https://www.momondo.com/flight-search/{orig}-{dest}/{d_str}"
    return f"https://www.momondo.com/flight-search/{orig}-{dest}"
