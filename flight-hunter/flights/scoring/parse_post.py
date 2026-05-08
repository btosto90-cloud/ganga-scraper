"""
Parse the HTML content of a Promociones Aéreas post body.

What we want from each post:
  1. List of (depart_date, return_date) tuples from the prices table
  2. Whether each row is direct or has connections
  3. Any direct booking link ("Ver oferta" buttons in the table)

The table rows look roughly like:
    Dom 24/05/2026  Sab 06/06/2026  13  Conexiones  [Ver oferta]
    Lun 25/05/2026  Dom 07/06/2026  13  Directo     [Ver oferta]
    ...

We work from the rendered HTML, looking for rows containing two date-like
strings in DD/MM/YYYY format. Robust to layout changes.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional

from bs4 import BeautifulSoup

DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(20\d{2})")
DAY_NAMES = ("lun", "mar", "mié", "mie", "jue", "vie", "sáb", "sab", "dom")


def parse_post_body(html: str) -> dict:
    """Extract dates and booking URLs from a post's content HTML.

    Returns:
        {
          "dates_available": [{"depart": "YYYY-MM-DD", "return": "YYYY-MM-DD"|None,
                                "is_direct": bool, "days": int|None,
                                "booking_url": str|None}, ...],
          "first_depart": "YYYY-MM-DD" | None,
          "first_return": "YYYY-MM-DD" | None,
          "direct_booking_url": str | None,    # the first table link if any
          "total_dates": int,
        }
    """
    if not html:
        return _empty()

    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        return _empty()

    rows: list[dict] = []
    seen_keys: set[tuple] = set()

    # Look at every <tr> first (most reliable)
    for tr in soup.find_all("tr"):
        row = _parse_row(tr)
        if not row:
            continue
        key = (row["depart"], row.get("return"))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        rows.append(row)

    # Fallback: parse div-based layouts by scanning the text + linked anchors
    if not rows:
        rows = _parse_text_fallback(soup)

    if not rows:
        return _empty()

    # Sort by depart date ascending — earliest first is usually the cheapest/displayed
    rows.sort(key=lambda r: r["depart"])

    first = rows[0]
    booking = next((r["booking_url"] for r in rows if r.get("booking_url")), None)

    return {
        "dates_available": rows,
        "first_depart": first["depart"],
        "first_return": first.get("return"),
        "first_is_direct": first.get("is_direct", False),
        "direct_booking_url": booking,
        "total_dates": len(rows),
    }


def _empty() -> dict:
    return {
        "dates_available": [],
        "first_depart": None,
        "first_return": None,
        "first_is_direct": False,
        "direct_booking_url": None,
        "total_dates": 0,
    }


def _parse_row(tr) -> Optional[dict]:
    """Parse one <tr> looking for two dates plus optional booking link/direct flag."""
    text = " ".join(tr.get_text(" ", strip=True).split())
    matches = list(DATE_RE.finditer(text))
    if len(matches) < 1:
        return None

    depart = _to_iso(matches[0])
    if not depart:
        return None

    ret = _to_iso(matches[1]) if len(matches) >= 2 else None

    text_lc = text.lower()
    is_direct = "directo" in text_lc and "conexion" not in text_lc and "conexiones" not in text_lc

    # Days count between depart and return, or pulled from text
    days = _extract_days(text)

    # Find any booking link in this row
    booking = None
    for a in tr.find_all("a", href=True):
        href = a["href"]
        # Skip internal anchors
        if href.startswith("#") or href.startswith("javascript:"):
            continue
        booking = href
        break

    return {
        "depart": depart,
        "return": ret,
        "is_direct": is_direct,
        "days": days,
        "booking_url": booking,
    }


def _parse_text_fallback(soup) -> list[dict]:
    """When there's no <tr>, scan paragraphs/divs for date pairs."""
    rows: list[dict] = []
    seen: set[tuple] = set()
    text = soup.get_text(" ", strip=True)
    matches = list(DATE_RE.finditer(text))
    # Pair consecutive matches as (depart, return) when reasonable
    i = 0
    while i + 1 < len(matches):
        d1 = _to_iso(matches[i])
        d2 = _to_iso(matches[i + 1])
        if d1 and d2 and d2 >= d1:
            key = (d1, d2)
            if key not in seen:
                seen.add(key)
                rows.append({"depart": d1, "return": d2, "is_direct": False, "days": None, "booking_url": None})
            i += 2
        else:
            i += 1
    return rows


def _to_iso(match) -> Optional[str]:
    try:
        d, m, y = int(match.group(1)), int(match.group(2)), int(match.group(3))
        return date(y, m, d).isoformat()
    except (ValueError, AttributeError):
        return None


def _extract_days(text: str) -> Optional[int]:
    m = re.search(r"\b(\d{1,3})\s*(?:día|dias|dia|días)\b", text.lower())
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return None
