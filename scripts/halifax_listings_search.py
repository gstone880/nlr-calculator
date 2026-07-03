#!/usr/bin/env python3
"""
halifax_listings_search.py — search engine–based hunter for Halifax Metro Area
(HRM) real estate listings that have a bedroom on the first/main floor at or
near driveway level.

Why this matters
----------------
Most Halifax homes are split-entries: you step up (or down) half a flight from
the front door before reaching any bedrooms. For aging-in-place, mobility
needs, or simply avoiding stairs, you want a home where the *first floor* (the
floor you walk into from the driveway) already has a bedroom.

Target property types
---------------------
  bungalow      — all living on one level, entry at grade
  1.5 storey    — main floor has bedroom(s), roof-space upper floor
  ranch         — same as bungalow, term used in newer builds
  ground-floor  — condo / stacked unit with bedroom at grade or lobby level

Explicitly filtered OUT
-----------------------
  split-entry   — you go up/down stairs to reach any bedrooms from the foyer
  raised bungalow — main floor is elevated; you climb exterior stairs from driveway

How it works
------------
Real estate listing sites block direct scraping with 403s, so this script uses
the same strategy as ssd_price_search.py: harvest listing details from search
engine result snippets (JSON-LD / HTML), which are public and unprotected. Each
engine gives a different slice of the listing corpus.

  1. Run targeted queries across DuckDuckGo, Bing, Mojeek, Startpage.
  2. Collect URLs from NSAR-member sites (viewpoint.ca, realtor.ca, remaxnova.com, …).
  3. Attempt to fetch each listing page and extract price / address / bedrooms /
     description from structured data or meta tags.
  4. Score each hit for the two key signals: (a) bedroom mentioned on main/first
     floor, (b) entry appears to be at grade (no "split entry", no raised foyer).
  5. Print a ranked shortlist with direct links.

Usage
-----
  python3 halifax_listings_search.py               # default run
  python3 halifax_listings_search.py --area dartmouth bedford sackville
  python3 halifax_listings_search.py --min-beds 2 --max-price 600000
  python3 halifax_listings_search.py --verbose     # show fetch/parse progress
  python3 halifax_listings_search.py --json out.json
  python3 halifax_listings_search.py --selftest    # offline unit tests

Only stdlib + (optional) requests needed.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from typing import Iterable


# ---------------------------------------------------------------------------
# Search configuration
# ---------------------------------------------------------------------------

# HRM sub-areas the user can restrict to; default searches all.
HRM_AREAS: list[str] = [
    "Halifax",
    "Dartmouth",
    "Bedford",
    "Sackville",
    "Lower Sackville",
    "Cole Harbour",
    "Eastern Passage",
    "Fall River",
    "Timberlea",
    "Hammonds Plains",
    "Waverley",
    "Wellington",
    "Beaver Bank",
    "Herring Cove",
    "Spryfield",
    "Fairview",
    "Clayton Park",
    "Woodlawn",
    "Portland Hills",
    "Lake Echo",
]

# Search-engine URL templates.  {q} is replaced with the URL-encoded query.
SEARCH_ENGINES: dict[str, str] = {
    "ddg-lite":  "https://lite.duckduckgo.com/lite/?q={q}",
    "ddg-html":  "https://html.duckduckgo.com/html/?q={q}",
    "bing":      "https://www.bing.com/search?q={q}&count=20",
    "mojeek":    "https://www.mojeek.com/search?q={q}",
    "startpage": "https://www.startpage.com/sp/search?query={q}",
}
DEFAULT_ENGINE_ORDER = ["ddg-lite", "ddg-html", "mojeek", "startpage"]

# NSAR / HRM listing-site hostnames we trust.
LISTING_SITE_HINTS: tuple[str, ...] = (
    "viewpoint.ca", "realtor.ca", "remaxnova.com", "remaxnova.ca",
    "royallepage.ca", "remax.ca", "zolo.ca", "zillow.com",
    "redfin.ca", "keyhomes.ca", "livingsnovascotia.com", "livingnovascotia.com",
    "kijiji.ca", "halifaxcondos.co", "halifaxmetrorealestate.com",
    "centrepoint.ca", "novascotiahomefinder.ca", "lify.ca",
    "bryantrealty.ca", "prescott.ltd", "soldbyperkins.com",
    "tgrealestate.ca", "kentbraaten.com", "kwhalifax.com",
    "thinkhalifax.com", "real-estate.ca", "pine.ca",
    "remaxparkplace.com", "homeseh.ca", "scottrobinson.ca",
)

# Phrases in the description that indicate the FIRST FLOOR has a bedroom.
FIRST_FLOOR_BED_SIGNALS: tuple[str, ...] = (
    "bedroom on the main",
    "bedroom on main",
    "main floor bedroom",
    "main level bedroom",
    "bedroom on the first floor",
    "first floor bedroom",
    "bedroom on first floor",
    "bedroom on the ground",
    "ground floor bedroom",
    "main floor has a bedroom",
    "bedroom on main level",
    "bungalow",          # by definition all bedrooms are on the main floor
    "one storey",
    "one-storey",
    "single storey",
    "single-storey",
    "one level",
    "one-level",
    "ranch",
    "rancher",
    "all on one floor",
    "all bedrooms on main",
)

# Phrases that suggest the entry IS at grade / driveway level.
GRADE_ENTRY_SIGNALS: tuple[str, ...] = (
    "level lot",
    "at grade",
    "ground level entry",
    "no steps",
    "step free",
    "step-free",
    "accessible entry",
    "wheelchair",
    "no stairs to entry",
    "walk in from driveway",
    "bungalow",           # bungalow entry is always at grade
    "one storey",
    "one-storey",
    "single storey",
    "single-storey",
    "one level",
    "one-level",
    "ranch",
    "rancher",
    "grade level",
    "paved driveway",     # weak signal but helpful context
    "main floor entry",
)

# Phrases that strongly suggest this is NOT at driveway level.
GRADE_ENTRY_NEGATIVE: tuple[str, ...] = (
    "split entry",
    "split-entry",
    "raised bungalow",
    "raised foundation",
    "upper level",
    "go upstairs for bedrooms",
    "bedrooms on upper",
    "all bedrooms upstairs",
)

# User-agent rotation.
_USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
]
_ua_idx = 0


def _next_ua() -> str:
    global _ua_idx
    ua = _USER_AGENTS[_ua_idx % len(_USER_AGENTS)]
    _ua_idx += 1
    return ua


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Listing:
    address: str
    price: float | None
    beds: int | None
    baths: float | None
    sqft: int | None
    property_type: str       # bungalow, 1.5 storey, split entry, …
    description: str
    url: str
    source: str              # which site / engine snippet
    mls_id: str              # MLS number if parsed, else ""

    # Scored in post-processing
    first_floor_bed_score: int = 0    # 0-3 — how strongly first-floor bed is signalled
    grade_entry_score: int = 0        # 0-3 — how strongly grade-level entry is signalled
    negative_score: int = 0           # deduction for split-entry / raised signals

    @property
    def relevance(self) -> int:
        return self.first_floor_bed_score + self.grade_entry_score - self.negative_score * 2

    def price_str(self) -> str:
        if self.price is None:
            return "price n/a"
        return f"${self.price:,.0f}"


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

try:
    import requests as _req
    _SESSION = _req.Session()
except Exception:
    _req = None       # type: ignore
    _SESSION = None


def fetch(url: str, timeout: float = 12.0, retries: int = 1, verbose: bool = False) -> str | None:
    headers = {
        "User-Agent": _next_ua(),
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-CA,en;q=0.9",
    }
    for attempt in range(retries + 1):
        try:
            if _SESSION is not None:
                r = _SESSION.get(url, headers=headers, timeout=timeout)
                if r.status_code == 200:
                    return r.text
                if verbose:
                    print(f"    [http {r.status_code}] {url}", file=sys.stderr)
            else:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.read().decode("utf-8", "replace")
        except Exception as e:
            if verbose:
                print(f"    [err {type(e).__name__}] {url}", file=sys.stderr)
        time.sleep(0.5 * (attempt + 1))
    return None


# ---------------------------------------------------------------------------
# Search engine URL discovery
# ---------------------------------------------------------------------------

_ENGINE_HOSTS = ("duckduckgo.com", "bing.com", "mojeek.com", "startpage.com",
                 "google.com", "yahoo.com")


def _is_listing_url(url: str) -> bool:
    host = urllib.parse.urlparse(url).netloc.lower()
    if not host or any(e in host for e in _ENGINE_HOSTS):
        return False
    return any(h.rstrip(".") in host for h in LISTING_SITE_HINTS)


def _clean_redirect(href: str) -> str | None:
    if "uddg=" in href:
        params = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
        if "uddg" in params:
            return urllib.parse.unquote(params["uddg"][0])
    if href.startswith("http"):
        for param in ("piurl", "url", "u3"):
            if f"{param}=" in href:
                params = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                cand = params.get(param, [""])[0]
                if cand.startswith("http"):
                    return urllib.parse.unquote(cand)
        return href
    return None


def _search_one(engine: str, query: str, timeout: float, verbose: bool) -> list[str]:
    template = SEARCH_ENGINES.get(engine)
    if not template:
        return []
    url = template.format(q=urllib.parse.quote_plus(query))
    body = fetch(url, timeout=timeout, retries=1, verbose=verbose)
    if not body:
        return []
    out: list[str] = []
    for m in re.finditer(r'href=["\']([^"\']+)["\']', body):
        real = _clean_redirect(html.unescape(m.group(1)))
        if real and _is_listing_url(real) and real not in out:
            out.append(real)
    return out


def discover_listing_urls(queries: list[str], limit: int, timeout: float,
                          verbose: bool, engines: list[str] | None = None) -> list[str]:
    order = engines or DEFAULT_ENGINE_ORDER
    out: list[str] = []
    seen: set[str] = set()
    for q in queries:
        if verbose:
            print(f"  searching: {q}", file=sys.stderr)
        for name in order:
            for u in _search_one(name, q, timeout, verbose):
                key = u.split("?")[0]
                if key not in seen:
                    seen.add(key)
                    out.append(u)
            if len(out) >= limit:
                break
        time.sleep(0.4)
    return out[:limit]


# ---------------------------------------------------------------------------
# Listing page parser — Schema.org RealEstateListing / Product / generic meta
# ---------------------------------------------------------------------------

_JSONLD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)
_MLS_RE = re.compile(r'\b(MLS[®\s#]*|MLS:?\s*)(\d{6,12})\b', re.IGNORECASE)
_PRICE_RE = re.compile(r'\$\s?([\d,]+(?:\.\d{2})?)')
_BED_RE = re.compile(r'(\d+)\s*(?:bed(?:room)?s?|BR)\b', re.IGNORECASE)
_BATH_RE = re.compile(r'(\d+(?:\.\d)?)\s*(?:bath(?:room)?s?|BA)\b', re.IGNORECASE)
_SQFT_RE = re.compile(r'([\d,]+)\s*(?:sq\.?\s*ft\.?|sqft|square feet)', re.IGNORECASE)


def _to_float(val) -> float | None:
    if val is None:
        return None
    s = re.sub(r"[^0-9.,]", "", str(val))
    if not s:
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    else:
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _html_text(html_body: str, max_chars: int = 3000) -> str:
    text = re.sub(r'<[^>]+>', ' ', html_body)
    text = html.unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:max_chars]


def _html_title(body: str) -> str:
    m = re.search(r'<title[^>]*>(.*?)</title>', body, re.DOTALL | re.IGNORECASE)
    return html.unescape(m.group(1)).strip() if m else ""


def _meta_content(body: str, props: list[str]) -> str | None:
    for prop in props:
        m = re.search(
            r'<meta[^>]+(?:property|name)=["\']' + re.escape(prop) +
            r'["\'][^>]*content=["\']([^"\']+)["\']',
            body, re.IGNORECASE)
        if not m:
            m = re.search(
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\']'
                + re.escape(prop) + r'["\']',
                body, re.IGNORECASE)
        if m:
            return html.unescape(m.group(1)).strip()
    return None


def _detect_property_type(text: str) -> str:
    t = text.lower()
    for kw in ("split entry", "split-entry"):
        if kw in t:
            return "split entry"
    for kw in ("raised bungalow",):
        if kw in t:
            return "raised bungalow"
    for kw in ("bungalow", "rancher", "ranch"):
        if kw in t:
            return "bungalow"
    for kw in ("1.5 storey", "1.5-storey", "one and a half"):
        if kw in t:
            return "1.5 storey"
    for kw in ("two storey", "two-storey", "2 storey", "2-storey"):
        if kw in t:
            return "2 storey"
    for kw in ("one storey", "one-storey", "single storey", "single-storey", "one level", "one-level"):
        if kw in t:
            return "one storey"
    return "house"


def parse_listing(page_html: str, page_url: str) -> Listing | None:
    title = _html_title(page_html)
    desc_meta = _meta_content(page_html, ["og:description", "description"]) or ""
    plain = _html_text(page_html)
    combined = (title + " " + desc_meta + " " + plain).lower()

    # Price
    price: float | None = None
    m_price = _PRICE_RE.search(plain)
    if m_price:
        price = _to_float(m_price.group(1))
        # Sanity-check: Halifax listings are typically $200k–$3M
        if price and not (150_000 <= price <= 5_000_000):
            price = None

    # Beds / baths / sqft
    beds: int | None = None
    m_bed = _BED_RE.search(plain)
    if m_bed:
        beds = int(m_bed.group(1))
        if beds > 20:
            beds = None

    baths: float | None = None
    m_bath = _BATH_RE.search(plain)
    if m_bath:
        baths = _to_float(m_bath.group(1))

    sqft: int | None = None
    m_sqft = _SQFT_RE.search(plain)
    if m_sqft:
        v = _to_float(m_sqft.group(1))
        if v and 200 <= v <= 20_000:
            sqft = int(v)

    # Address — try og:title, og:street_address, or page title
    address = (
        _meta_content(page_html, ["og:street-address", "og:street_address"]) or
        _meta_content(page_html, ["og:title"]) or
        title or
        page_url
    )
    address = address[:120]

    # MLS ID
    mls_id = ""
    m_mls = _MLS_RE.search(combined)
    if m_mls:
        mls_id = m_mls.group(2)

    # Property type
    prop_type = _detect_property_type(combined)

    return Listing(
        address=address,
        price=price,
        beds=beds,
        baths=baths,
        sqft=sqft,
        property_type=prop_type,
        description=(desc_meta or plain[:400]),
        url=page_url,
        source=urllib.parse.urlparse(page_url).netloc.replace("www.", ""),
        mls_id=mls_id,
    )


# ---------------------------------------------------------------------------
# Relevance scoring
# ---------------------------------------------------------------------------

def score_listing(listing: Listing) -> None:
    combined = (listing.address + " " + listing.description + " " + listing.property_type).lower()

    # First-floor bedroom signals
    fb = sum(1 for sig in FIRST_FLOOR_BED_SIGNALS if sig in combined)
    listing.first_floor_bed_score = min(3, fb)

    # Grade-entry signals
    ge = sum(1 for sig in GRADE_ENTRY_SIGNALS if sig in combined)
    listing.grade_entry_score = min(3, ge)

    # Negative signals
    neg = sum(1 for sig in GRADE_ENTRY_NEGATIVE if sig in combined)
    listing.negative_score = neg


def passes_filters(listing: Listing, min_beds: int | None, max_price: float | None) -> bool:
    if min_beds is not None and listing.beds is not None and listing.beds < min_beds:
        return False
    if max_price is not None and listing.price is not None and listing.price > max_price:
        return False
    # Must have at least some signal for either criterion
    return listing.relevance > 0


# ---------------------------------------------------------------------------
# Query builder
# ---------------------------------------------------------------------------

def build_queries(areas: list[str], min_beds: int | None, extra: str | None) -> list[str]:
    if extra:
        return [extra]
    bed_str = f"{min_beds}+" if min_beds else ""
    queries: list[str] = []
    for area in areas:
        queries += [
            f"{area} Nova Scotia bungalow {bed_str} bedroom for sale MLS",
            f"{area} NS \"main floor bedroom\" OR \"bedroom on main\" for sale",
            f"{area} Nova Scotia \"one storey\" OR \"one level\" bedroom for sale",
            f"{area} NS real estate \"no steps\" OR \"level lot\" bedroom main floor",
        ]
    return queries


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def hunt(queries: list[str], limit: int, timeout: float, workers: int,
         verbose: bool, engines: list[str] | None = None) -> list[Listing]:
    urls = discover_listing_urls(queries, limit, timeout, verbose, engines)
    if verbose:
        print(f"  {len(urls)} candidate listing pages found", file=sys.stderr)

    listings: list[Listing] = []

    def _work(u: str) -> Listing | None:
        body = fetch(u, timeout=timeout, retries=0, verbose=verbose)
        if not body:
            return None
        listing = parse_listing(body, u)
        if listing:
            score_listing(listing)
        return listing

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for result in ex.map(_work, urls):
            if result is not None:
                listings.append(result)

    return listings


def rank_and_filter(listings: list[Listing], min_beds: int | None,
                    max_price: float | None) -> list[Listing]:
    scored = [l for l in listings if passes_filters(l, min_beds, max_price)]
    # Dedup by URL base
    seen: set[str] = set()
    unique: list[Listing] = []
    for l in scored:
        key = l.url.split("?")[0].rstrip("/")
        if key not in seen:
            seen.add(key)
            unique.append(l)
    unique.sort(key=lambda l: -l.relevance)
    return unique


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _relevance_label(r: int) -> str:
    if r >= 5:
        return "STRONG"
    if r >= 3:
        return "GOOD"
    if r >= 1:
        return "POSSIBLE"
    return "WEAK"


def print_results(listings: list[Listing], top: int = 20) -> None:
    if not listings:
        print(
            "\nNo listings matched. Search engines may be throttling, or try --area,"
            " --verbose, or a direct --query."
        )
        return
    shown = listings[:top]
    print(f"\n  HALIFAX METRO — FIRST-FLOOR BEDROOM / DRIVEWAY-LEVEL LISTINGS")
    print(f"  Criteria: bedroom on main/first floor · first floor at or near driveway grade")
    print(f"  Found {len(listings)} matches; showing top {len(shown)}\n")
    print(f"  {'#':<3}{'MATCH':<9}{'PRICE':>10}  {'BEDS':<5}{'TYPE':<15}{'MLS':<14}ADDRESS / URL")
    print("  " + "-" * 110)
    for i, l in enumerate(shown, 1):
        bed_s = str(l.beds) if l.beds else "?"
        mls_s = l.mls_id or "—"
        label = _relevance_label(l.relevance)
        print(f"  {i:<3}{label:<9}{l.price_str():>10}  {bed_s:<5}{l.property_type[:14]:<15}{mls_s:<14}"
              f"{l.address[:34]}")
        print(f"     {l.url[:100]}")
        if l.description:
            print(f"     {l.description[:110].strip()}")
        print()
    print("  " + "-" * 110)
    print(
        "\n  Tip: 'STRONG' = bungalow/one-level + explicit grade-level entry signals."
        "\n       'GOOD'   = one or both signals present in description."
        "\n       Always verify with the listing agent that the first floor is truly at driveway grade.\n"
    )


# ---------------------------------------------------------------------------
# Offline self-test
# ---------------------------------------------------------------------------

_FIXTURE_BUNGALOW = """
<html><head>
<title>613 Beaver Bank Road, Beaver Bank, NS | MLS® 202512345</title>
<meta name="description" content="Charming 4-bedroom bungalow on a level lot with paved driveway. All bedrooms on the main floor, no steps from driveway to front door. Close to Dartmouth Crossing.">
<meta property="og:description" content="4-bedroom bungalow, level lot, paved driveway, main floor bedrooms.">
</head><body>
<span>$549,000</span><span>4 bedrooms</span><span>2 bathrooms</span><span>1400 sq ft</span>
</body></html>
"""

_FIXTURE_SPLIT = """
<html><head>
<title>42 Oak Street, Lower Sackville, NS | MLS® 202598765</title>
<meta name="description" content="Split entry home, 3 bedrooms upstairs and 1 downstairs. Large paved driveway, attached garage.">
</head><body>
<span>$475,000</span><span>4 bedrooms</span><span>2 bathrooms</span>
</body></html>
"""

_FIXTURE_NOPRICE = """
<html><head><title>Bungalow Halifax NS</title>
<meta name="description" content="Beautiful one-storey bungalow near driveway level. Bedroom on main floor.">
</head><body>No price listed.</body></html>
"""


def selftest() -> int:
    ok = True

    def check(desc: str, cond: bool) -> None:
        nonlocal ok
        ok = ok and cond
        print(f"  [{'PASS' if cond else 'FAIL'}] {desc}")

    # Bungalow fixture
    l1 = parse_listing(_FIXTURE_BUNGALOW, "https://example.ca/1")
    assert l1 is not None
    score_listing(l1)
    check("bungalow: price parsed", l1.price == 549_000.0)
    check("bungalow: beds parsed", l1.beds == 4)
    check("bungalow: property type detected", l1.property_type == "bungalow")
    check("bungalow: MLS parsed", l1.mls_id == "202512345")
    check("bungalow: first_floor_bed_score > 0", l1.first_floor_bed_score > 0)
    check("bungalow: grade_entry_score > 0", l1.grade_entry_score > 0)
    check("bungalow: negative_score == 0", l1.negative_score == 0)
    check("bungalow: relevance > 0", l1.relevance > 0)

    # Split-entry fixture
    l2 = parse_listing(_FIXTURE_SPLIT, "https://example.ca/2")
    assert l2 is not None
    score_listing(l2)
    check("split entry: type detected", l2.property_type == "split entry")
    check("split entry: negative_score > 0", l2.negative_score > 0)
    check("split entry: excluded by default", not passes_filters(l2, None, None) or l2.relevance <= 0)

    # No-price fixture
    l3 = parse_listing(_FIXTURE_NOPRICE, "https://example.ca/3")
    assert l3 is not None
    score_listing(l3)
    check("no-price: price is None", l3.price is None)
    check("no-price: one-storey signals score", l3.first_floor_bed_score > 0)
    check("no-price: passes filter with no price constraint", passes_filters(l3, None, None))

    # Filter: min beds
    check("min-beds filter: 4bd listing passes >=3", passes_filters(l1, 3, None))
    check("min-beds filter: 4bd listing fails >=5", not passes_filters(l1, 5, None))

    # Filter: max price
    check("max-price filter: $549k passes $600k", passes_filters(l1, None, 600_000))
    check("max-price filter: $549k fails $500k", not passes_filters(l1, None, 500_000))

    # Property-type detection
    check("detect split entry", _detect_property_type("split-entry home 3 bed") == "split entry")
    check("detect bungalow", _detect_property_type("4-bedroom bungalow on level lot") == "bungalow")
    check("detect 1.5 storey", _detect_property_type("charming 1.5 storey home") == "1.5 storey")
    check("detect one storey", _detect_property_type("lovely one-storey house") == "one storey")

    # Ranking: bungalow should outrank split entry
    ranked = rank_and_filter([l1, l2], None, None)
    check("ranking: bungalow outranks split entry", ranked[0].url == l1.url if ranked else True)

    print(f"\n  {'ALL TESTS PASSED' if ok else 'SOME TESTS FAILED'}")
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        description="Find Halifax Metro real estate listings with a bedroom on the "
                    "first/main floor at or near driveway level.")
    p.add_argument("--area", nargs="+", default=HRM_AREAS, metavar="AREA",
                   help="HRM sub-areas to search (default: all). "
                        "Examples: Halifax Dartmouth Bedford Sackville")
    p.add_argument("--min-beds", type=int, default=None, metavar="N",
                   help="minimum number of bedrooms")
    p.add_argument("--max-price", type=float, default=None, metavar="PRICE",
                   help="maximum price in dollars (e.g. 600000)")
    p.add_argument("--query", metavar="QUERY",
                   help="override with a single explicit search query")
    p.add_argument("--limit", type=int, default=40,
                   help="max listing URLs to fetch (default 40)")
    p.add_argument("--workers", type=int, default=8,
                   help="parallel fetch threads (default 8)")
    p.add_argument("--engines", nargs="+", default=None, metavar="ENGINE",
                   choices=list(SEARCH_ENGINES),
                   help="search engines to use, in order. "
                        "Choices: " + ", ".join(SEARCH_ENGINES))
    p.add_argument("--timeout", type=float, default=12.0,
                   help="per-request timeout in seconds (default 12)")
    p.add_argument("--top", type=int, default=20,
                   help="number of results to show (default 20)")
    p.add_argument("--json", metavar="FILE",
                   help="also write results as JSON to FILE")
    p.add_argument("--selftest", action="store_true",
                   help="run offline unit tests and exit")
    p.add_argument("--verbose", action="store_true",
                   help="log search/fetch progress to stderr")
    args = p.parse_args(argv)

    if args.selftest:
        return selftest()

    queries = build_queries(args.area, args.min_beds, args.query)

    areas_str = ", ".join(args.area[:5])
    if len(args.area) > 5:
        areas_str += f" + {len(args.area) - 5} more"
    print(f"Searching for first-floor bedroom / driveway-level listings in HRM")
    print(f"Areas: {areas_str}")
    if args.min_beds:
        print(f"Min bedrooms: {args.min_beds}")
    if args.max_price:
        print(f"Max price: ${args.max_price:,.0f}")
    print(f"Running {len(queries)} queries across {len(args.engines or DEFAULT_ENGINE_ORDER)} engines…\n")

    raw = hunt(queries, args.limit, args.timeout, args.workers, args.verbose, args.engines)
    ranked = rank_and_filter(raw, args.min_beds, args.max_price)
    print_results(ranked, args.top)

    if args.json:
        with open(args.json, "w") as f:
            json.dump(
                [{**asdict(l), "relevance": l.relevance} for l in ranked[:args.top]],
                f, indent=2
            )
        print(f"  wrote {min(len(ranked), args.top)} listings to {args.json}")

    return 0 if ranked else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
