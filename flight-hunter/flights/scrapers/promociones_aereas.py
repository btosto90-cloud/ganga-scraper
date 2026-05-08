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
        offers: list[dict] = []
        for strategy in strategies:
            try:
                offers = strategy()
                if offers:
                    print(f"[{self.name}] strategy {strategy.__name__} → {len(offers)} raw offers")
                    break
            except Exception as e:
                print(f"[{self.name}] {strategy.__name__} failed: {type(e).__name__}: {e}")
                time.sleep(1.5)
        if not offers:
            return []

        offers = self._filter_flights(offers)[: self.max_offers]

        # Backfill content_html for any offer that doesn't have one
        # (REST API and HTML strategies don't return body — RSS does)
        offers = self._backfill_post_bodies(offers)

        return offers

    # ------------------------------------------------------------------
    def _backfill_post_bodies(self, offers: list[dict]) -> list[dict]:
        """For each offer with a missing/useless body, fetch the full post.

        The RSS feed only gives us a 200-500b summary — too small to contain the
        dates table. We re-fetch the full post for any offer where the body is
        smaller than 2KB or doesn't contain a date pattern.
        """
        def _is_useful_body(body: str) -> bool:
            if not body or len(body) < 2000:
                return False
            # A post body without a date pattern in DD/MM/YYYY form is not useful
            if not re.search(r"\d{1,2}/\d{1,2}/20\d{2}", body):
                return False
            return True

        missing = [o for o in offers if not _is_useful_body(o.get("content_html", ""))]
        if not missing:
            print(f"[{self.name}] all {len(offers)} offers already have useful body — no backfill needed")
            return offers
        print(f"[{self.name}] backfilling {len(missing)} post bodies (out of {len(offers)} offers)")
        success = 0
        for i, o in enumerate(missing):
            url = o.get("url", "")
            if not url:
                continue
            try:
                body = self._fetch_post_body(url)
                if body:
                    o["content_html"] = body
                    has_table = "<table" in body or "<tr" in body
                    has_dates = bool(re.search(r"\d{1,2}/\d{1,2}/20\d{2}", body))
                    print(f"[{self.name}] backfill OK [{i+1}/{len(missing)}]: {len(body)}b, table={has_table}, dates={has_dates}, slug={o.get('slug', '')[:50]}")
                    success += 1
                else:
                    print(f"[{self.name}] backfill EMPTY [{i+1}/{len(missing)}]: slug={o.get('slug', '')[:50]}")
            except Exception as e:
                print(f"[{self.name}] backfill FAILED [{i+1}/{len(missing)}]: {type(e).__name__}: {e}")
            if i < len(missing) - 1:
                time.sleep(0.4)  # be polite to Jina
        print(f"[{self.name}] backfill summary: {success}/{len(missing)} bodies retrieved")
        return offers

    def _fetch_post_body(self, url: str) -> str:
        """Fetch one post's full content. Strategy:
          1. Try Jina proxy first — it renders JS and bypasses Cloudflare blocks
          2. If that fails, try the direct URL (less likely to work from CI but worth trying)
        Returns the body as HTML-ish (Jina returns markdown wrapped in a div).
        """
        # Strategy 1: Jina proxy (most reliable from datacenter IPs)
        try:
            jina_url = f"https://r.jina.ai/{url}"
            r = self.session.get(
                jina_url,
                headers={"Accept": "text/plain", "X-Return-Format": "markdown"},
                timeout=25,
            )
            r.raise_for_status()
            text = r.text
            if len(text) > 1000:
                # Wrap markdown in a div so the parser can BeautifulSoup-it
                return f"<div>{text}</div>"
            print(f"[{self.name}]   jina returned only {len(text)} bytes for {url[-50:]}")
        except Exception as e:
            print(f"[{self.name}]   jina failed for {url[-50:]}: {type(e).__name__}: {str(e)[:80]}")

        # Strategy 2: Direct fetch (rarely works from CI, but free to try)
        try:
            r = self.session.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "lxml")
            article = soup.find("article") or soup.find(class_="entry-content") or soup.find("main")
            return str(article) if article else r.text[:50000]
        except Exception as e:
            print(f"[{self.name}]   direct also failed for {url[-50:]}: {type(e).__name__}")

        return ""

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
    # Strategy 1: WordPress REST API (no body — content field requires auth on this site)
    # ------------------------------------------------------------------
    def _fetch_rest_api(self) -> list[dict]:
        url = f"{BASE}/wp-json/wp/v2/posts"
        params = {"per_page": POST_PER_PAGE, "_fields": "id,date,link,slug,title,excerpt"}
        r = self.session.get(url, params=params, timeout=30)
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
                "content_html": "",  # REST API doesn't give us body without auth
            })
        return out

    # ------------------------------------------------------------------
    # Strategy 2: RSS feed (includes content:encoded with full body)
    # ------------------------------------------------------------------
    def _fetch_rss(self) -> list[dict]:
        r = self.session.get(f"{BASE}/feed/", timeout=20)
        r.raise_for_status()
        # WP RSS uses the namespace http://purl.org/rss/1.0/modules/content/ for the body
        ns = {"content": "http://purl.org/rss/1.0/modules/content/"}
        root = ET.fromstring(r.content)
        items = root.findall(".//item")
        out = []
        diag_logged = False
        for item in items:
            link = (item.findtext("link") or "").strip()
            title = unescape(item.findtext("title") or "").strip()
            posted = item.findtext("pubDate") or None
            # Extract the full body from content:encoded
            content_node = item.find("content:encoded", ns)
            content_html = (content_node.text or "") if content_node is not None else ""
            # Some sites use <description> with full HTML instead
            if not content_html:
                desc_node = item.find("description")
                content_html = (desc_node.text or "") if desc_node is not None else ""
            slug = ""
            if link:
                slug = link.rstrip("/").rsplit("/", 1)[-1].replace(".html", "")
            if not (link and title):
                continue
            # Diagnostic on first item: what does the RSS actually contain?
            if not diag_logged:
                has_table = "<table" in content_html or "<tr" in content_html
                has_dates = bool(re.search(r"\d{1,2}/\d{1,2}/20\d{2}", content_html))
                print(f"[{self.name}] RSS first item: title='{title[:60]}', body={len(content_html)}b, table={has_table}, dates={has_dates}")
                diag_logged = True
            out.append({
                "source": self.name,
                "title": title,
                "url": link,
                "slug": slug,
                "posted_at": posted,
                "content_html": content_html,
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
