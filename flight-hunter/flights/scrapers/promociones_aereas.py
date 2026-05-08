"""
Scraper for promociones-aereas.com.ar

Cascade:
  1. WordPress REST API (/wp-json/wp/v2/posts) — cleanest, structured JSON
  2. RSS feed (/feed/) — XML, almost always accessible
  3. HTML home page — last resort, fragile

Filters: only posts that look like actual flight offers (title contains "vuelo"
or starts with destination-style patterns, slug ends in -p.html, no
"paquete"/"hotel"/"asistencia"/"actividad" markers).
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from html import unescape
from typing import Iterable
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup

from .base import Source

BASE = "https://promociones-aereas.com.ar"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
}

# Permalinks of actual offer posts end in "-p.html"
POST_PATH_RE = re.compile(r"/\d{4}/\d{2}/[a-z0-9-]+-p\.html$")

# Reject these — paquetes, hoteles, etc. We only care about flights.
NON_FLIGHT_MARKERS = (
    "ho-p", "pa-p", "av-p", "ac-p", "au-p", "m.html",  # slug suffixes
)
NON_FLIGHT_TITLE_WORDS = (
    "paquete", "paquetes", "hotel ", "hoteles", "alojamiento", "asistencia",
    "alquiler de auto", "departamentos", "tickets para", "excursion",
)

POST_PER_PAGE = 50  # WP REST API page size


class PromocionesAereasSource(Source):
    name = "promociones_aereas"

    def __init__(self, max_offers: int = 80) -> None:
        self.max_offers = max_offers
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    # ------------------------------------------------------------------
    def fetch(self) -> list[dict]:
        strategies = (
            self._fetch_rest_api,
            self._fetch_rss,
            self._fetch_html,
            self._fetch_via_jina,  # last-resort proxy
        )
        for strategy in strategies:
            try:
                offers = strategy()
                if offers:
                    print(f"[{self.name}] strategy {strategy.__name__} → {len(offers)} raw offers")
                    return self._filter_flights(offers)[: self.max_offers]
            except Exception as e:
                print(f"[{self.name}] {strategy.__name__} failed: {type(e).__name__}: {e}")
                time.sleep(1.5)
        return []

    # ------------------------------------------------------------------
    # Strategy 4: r.jina.ai proxy — free, no auth, returns the page rendered.
    # Used only when direct access is blocked (e.g. datacenter IPs).
    # ------------------------------------------------------------------
    def _fetch_via_jina(self) -> list[dict]:
        proxy_url = f"https://r.jina.ai/{BASE}/"
        # Jina returns markdown by default; we ask for the raw HTML link list
        r = requests.get(
            proxy_url,
            headers={"Accept": "text/plain", "X-Return-Format": "markdown"},
            timeout=30,
        )
        r.raise_for_status()
        text = r.text
        # The markdown contains lines like:  ## [Title here](https://promociones-aereas.com.ar/2026/05/.../slug-p.html)
        out: dict[str, str] = {}
        link_re = re.compile(r"\[([^\]]+)\]\((https://promociones-aereas\.com\.ar/\d{4}/\d{2}/[^)]+-p(?:-\d+)?\.html)\)")
        for m in link_re.finditer(text):
            title = m.group(1).strip()
            url = m.group(2).strip()
            if len(title) < 20:
                continue
            if url not in out or len(title) > len(out[url]):
                out[url] = title
        offers = []
        for url, title in out.items():
            slug = url.rstrip("/").rsplit("/", 1)[-1].replace(".html", "")
            offers.append({
                "source": self.name,
                "title": title,
                "url": url,
                "slug": slug,
                "posted_at": None,
            })
        return offers

    # ------------------------------------------------------------------
    # Strategy 1: WordPress REST API
    # ------------------------------------------------------------------
    def _fetch_rest_api(self) -> list[dict]:
        url = f"{BASE}/wp-json/wp/v2/posts"
        params = {"per_page": POST_PER_PAGE, "_fields": "id,date,link,slug,title,excerpt"}
        r = self.session.get(url, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        out = []
        for p in data:
            link = p.get("link", "")
            slug = p.get("slug", "")
            title = unescape((p.get("title") or {}).get("rendered", "")).strip()
            posted = p.get("date") or None
            if not (link and slug and title):
                continue
            out.append({
                "source": self.name,
                "title": title,
                "url": link,
                "slug": slug,
                "posted_at": posted,
            })
        return out

    # ------------------------------------------------------------------
    # Strategy 2: RSS feed
    # ------------------------------------------------------------------
    def _fetch_rss(self) -> list[dict]:
        r = self.session.get(f"{BASE}/feed/", timeout=20)
        r.raise_for_status()
        # WP RSS is application/rss+xml — namespaces aren't needed for what we read
        root = ET.fromstring(r.content)
        items = root.findall(".//item")
        out = []
        for item in items:
            link = (item.findtext("link") or "").strip()
            title = unescape(item.findtext("title") or "").strip()
            posted = item.findtext("pubDate") or None
            slug = ""
            if link:
                slug = link.rstrip("/").rsplit("/", 1)[-1].replace(".html", "")
            if not (link and title):
                continue
            out.append({
                "source": self.name,
                "title": title,
                "url": link,
                "slug": slug,
                "posted_at": posted,
            })
        return out

    # ------------------------------------------------------------------
    # Strategy 3: HTML
    # ------------------------------------------------------------------
    def _fetch_html(self) -> list[dict]:
        r = self.session.get(f"{BASE}/", timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        seen: dict[str, str] = {}
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not POST_PATH_RE.search(href):
                continue
            text = " ".join(a.get_text().split())
            if len(text) < 20:
                continue
            # keep the longest title we see for that URL
            if href not in seen or len(text) > len(seen[href]):
                seen[href] = text
        out = []
        for url, title in seen.items():
            slug = url.rstrip("/").rsplit("/", 1)[-1].replace(".html", "")
            out.append({
                "source": self.name,
                "title": title,
                "url": url,
                "slug": slug,
                "posted_at": None,
            })
        return out

    # ------------------------------------------------------------------
    @staticmethod
    def _filter_flights(offers: Iterable[dict]) -> list[dict]:
        out = []
        for o in offers:
            slug = (o.get("slug") or "").lower()
            title_lc = (o.get("title") or "").lower()
            # Must end in -p.html style permalink (with version suffixes like -p-2)
            if not re.search(r"-p(?:-\d+)?$", slug):
                continue
            # Reject non-flight categories by slug suffix
            if any(slug.endswith(m) or m in slug for m in NON_FLIGHT_MARKERS):
                continue
            # Reject non-flight by title keywords
            if any(w in title_lc for w in NON_FLIGHT_TITLE_WORDS):
                continue
            out.append(o)
        return out


if __name__ == "__main__":
    # Quick sanity: print first few offers
    src = PromocionesAereasSource(max_offers=10)
    rows = src.fetch()
    print(f"\n{len(rows)} flight offers:\n")
    for o in rows[:10]:
        print(f"- {o['title'][:90]}")
        print(f"  slug: {o['slug'][:80]}")
