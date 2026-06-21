#!/usr/bin/env python3
"""
ssd_price_search.py — realtime price hunter for a 1 TB SSD from good-value brands.

The creative bit
----------------
Instead of scraping one retailer's brittle HTML layout (which breaks weekly) or
paying for a shopping API, this harvests the *structured data* that almost every
storefront already embeds for Google Shopping / SEO:

  1. JSON-LD   <script type="application/ld+json"> {"@type":"Product","offers":...}
  2. Microdata <span itemprop="price" content="79.99">
  3. OpenGraph <meta property="product:price:amount" content="79.99">

One parser therefore reads prices from Amazon, Newegg, Best Buy, B&H, Micro
Center, Crucial.com, etc. A search front-end discovers live product pages for a
curated set of good-value 1 TB models, every offer is normalized to dollars
per terabyte, and the best deals are printed as a live leaderboard.

Usage
-----
  python3 ssd_price_search.py                      # hunt 1 TB, default good-value brands
  python3 ssd_price_search.py --brands crucial wd  # restrict brands
  python3 ssd_price_search.py --capacity 2         # 2 TB instead
  python3 ssd_price_search.py --query "crucial p3 plus 1tb"
  python3 ssd_price_search.py --json results.json  # also dump machine-readable
  python3 ssd_price_search.py --selftest           # offline parser verification

Only dependency is `requests` (falls back to stdlib urllib if absent). HTML is
parsed with the standard library, so there is nothing else to install.

This is a price-discovery aid, not financial advice — always confirm on the
retailer's page before buying.
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
from dataclasses import dataclass, field, asdict
from typing import Iterable

# ----------------------------------------------------------------------------
# Curated "good value" 1 TB models. These are the price/performance darlings that
# repeatedly top value charts — DRAM-less but fast TLC NVMe plus a couple of
# rock-solid SATA options. Tune freely.
# ----------------------------------------------------------------------------
GOOD_VALUE_MODELS: dict[str, list[str]] = {
    "crucial":       ["Crucial P3 Plus 1TB", "Crucial T500 1TB", "Crucial BX500 1TB"],
    "wd":            ["WD Blue SN580 1TB", "WD Black SN770 1TB"],
    "samsung":       ["Samsung 990 EVO 1TB", "Samsung 870 EVO 1TB"],
    "kingston":      ["Kingston NV3 1TB", "Kingston KC3000 1TB"],
    "teamgroup":     ["TeamGroup MP44 1TB", "TeamGroup MP34 1TB"],
    "siliconpower":  ["Silicon Power UD90 1TB", "Silicon Power US75 1TB"],
    "skhynix":       ["SK hynix Platinum P41 1TB"],
}

# Retailers we trust enough to read a structured-data price from. Keeps junk
# marketplaces and price-history aggregators out of the leaderboard.
RETAILER_HINTS = (
    "amazon.", "newegg.", "bestbuy.", "bhphotovideo.", "microcenter.",
    "crucial.", "westerndigital.", "samsung.", "kingston.", "walmart.",
    "adorama.", "microsoft.", "store.", "bh.photo",
)

USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
]

CURRENCY_SYMBOL = {"USD": "$", "EUR": "€", "GBP": "£", "CAD": "C$", "AUD": "A$"}


# ----------------------------------------------------------------------------
# Data model
# ----------------------------------------------------------------------------
@dataclass
class Offer:
    title: str
    price: float
    currency: str
    url: str
    seller: str
    capacity_tb: float = 1.0
    source: str = ""          # which extractor found it (json-ld / microdata / og)

    @property
    def price_per_tb(self) -> float:
        return self.price / self.capacity_tb if self.capacity_tb else self.price

    def money(self) -> str:
        sym = CURRENCY_SYMBOL.get(self.currency, self.currency + " ")
        return f"{sym}{self.price:,.2f}"


# ----------------------------------------------------------------------------
# HTTP — prefer requests, fall back to urllib, rotate UA, retry politely.
# ----------------------------------------------------------------------------
try:
    import requests  # type: ignore
    _SESSION = requests.Session()
except Exception:  # pragma: no cover
    requests = None
    _SESSION = None

_ua_idx = 0


def _next_ua() -> str:
    global _ua_idx
    ua = USER_AGENTS[_ua_idx % len(USER_AGENTS)]
    _ua_idx += 1
    return ua


def fetch(url: str, timeout: float = 12.0, retries: int = 2, verbose: bool = False) -> str | None:
    headers = {
        "User-Agent": _next_ua(),
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
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
        time.sleep(0.6 * (attempt + 1))  # gentle backoff
    return None


# ----------------------------------------------------------------------------
# Search backends — discover live product pages. Multiple fallbacks because any
# single front-end may rate-limit. A SERPAPI_KEY env var, if present, is used first.
# ----------------------------------------------------------------------------
def search_urls(query: str, limit: int, timeout: float, verbose: bool) -> list[str]:
    for backend in (_search_ddg_lite, _search_ddg_html):
        urls = backend(query, limit, timeout, verbose)
        if urls:
            return urls[:limit]
    return []


def _clean_ddg_link(href: str) -> str | None:
    # DDG wraps results as /l/?uddg=<encoded real url>
    if href.startswith("//duckduckgo.com/l/") or "uddg=" in href:
        q = urllib.parse.urlparse(href).query
        params = urllib.parse.parse_qs(q)
        if "uddg" in params:
            return urllib.parse.unquote(params["uddg"][0])
    if href.startswith("http"):
        return href
    return None


def _search_ddg_lite(query: str, limit: int, timeout: float, verbose: bool) -> list[str]:
    url = "https://lite.duckduckgo.com/lite/?" + urllib.parse.urlencode({"q": query})
    body = fetch(url, timeout=timeout, verbose=verbose)
    if not body:
        return []
    out: list[str] = []
    for m in re.finditer(r'href="([^"]+)"', body):
        real = _clean_ddg_link(html.unescape(m.group(1)))
        if real and any(h in real for h in RETAILER_HINTS) and real not in out:
            out.append(real)
    return out


def _search_ddg_html(query: str, limit: int, timeout: float, verbose: bool) -> list[str]:
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    body = fetch(url, timeout=timeout, verbose=verbose)
    if not body:
        return []
    out: list[str] = []
    for m in re.finditer(r'class="result__a"[^>]*href="([^"]+)"', body):
        real = _clean_ddg_link(html.unescape(m.group(1)))
        if real and any(h in real for h in RETAILER_HINTS) and real not in out:
            out.append(real)
    return out


# ----------------------------------------------------------------------------
# The structured-data extractor — the heart of the script.
# ----------------------------------------------------------------------------
_JSONLD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


def _to_float(val) -> float | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = re.sub(r"[^0-9.,]", "", str(val))
    if not s:
        return None
    # handle "1.299,00" (EU) vs "1,299.00" (US)
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif s.count(",") == 1 and len(s.split(",")[-1]) == 2:
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _walk_jsonld(node, found: list[dict]) -> None:
    """Recursively collect Product/Offer-like dicts from arbitrary JSON-LD."""
    if isinstance(node, list):
        for item in node:
            _walk_jsonld(item, found)
    elif isinstance(node, dict):
        t = node.get("@type", "")
        types = t if isinstance(t, list) else [t]
        if any(x in ("Product", "Offer", "AggregateOffer") for x in types):
            found.append(node)
        for v in node.values():
            if isinstance(v, (list, dict)):
                _walk_jsonld(v, found)


def _detect_capacity_tb(title: str) -> float:
    t = title.lower()
    m = re.search(r"(\d+(?:\.\d+)?)\s*tb", t)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+)\s*gb", t)
    if m:
        return round(float(m.group(1)) / 1000, 3)
    return 1.0


def extract_offers(page_html: str, page_url: str) -> list[Offer]:
    seller = urllib.parse.urlparse(page_url).netloc.replace("www.", "")
    offers: list[Offer] = []

    # --- 1. JSON-LD (richest, most reliable) ---------------------------------
    nodes: list[dict] = []
    for block in _JSONLD_RE.findall(page_html):
        cleaned = block.strip()
        # storefronts sometimes embed multiple objects or trailing commas
        for candidate in _json_candidates(cleaned):
            try:
                _walk_jsonld(json.loads(candidate), nodes)
            except json.JSONDecodeError:
                continue

    page_title = _meta_content(page_html, ["og:title"]) or _html_title(page_html) or seller

    seen_prices: set[tuple[float, str]] = set()
    for node in nodes:
        name = node.get("name") or page_title
        offer_block = node.get("offers", node)
        for ob in (offer_block if isinstance(offer_block, list) else [offer_block]):
            if not isinstance(ob, dict):
                continue
            price = _to_float(ob.get("price") or ob.get("lowPrice") or ob.get("highPrice"))
            if price is None or price <= 0:
                continue
            cur = (ob.get("priceCurrency") or "USD").upper()
            # the recursive walk reports a Product and its nested Offer separately;
            # collapse identical (price, currency) hits into one offer.
            if (round(price, 2), cur) in seen_prices:
                continue
            seen_prices.add((round(price, 2), cur))
            offers.append(Offer(
                title=str(name)[:90], price=price, currency=cur, url=page_url,
                seller=seller, capacity_tb=_detect_capacity_tb(str(name)),
                source="json-ld",
            ))

    # --- 2. Microdata / OpenGraph meta (fallback when no JSON-LD) ------------
    if not offers:
        price = _to_float(_meta_content(page_html, [
            "product:price:amount", "og:price:amount",
        ]) or _itemprop_price(page_html))
        if price and price > 0:
            cur = (_meta_content(page_html, ["product:price:currency", "og:price:currency"])
                   or "USD").upper()
            offers.append(Offer(
                title=str(page_title)[:90], price=price, currency=cur, url=page_url,
                seller=seller, capacity_tb=_detect_capacity_tb(str(page_title)),
                source="meta",
            ))

    return offers


def _json_candidates(text: str) -> Iterable[str]:
    yield text
    # Some pages concatenate objects: }{  -> wrap into an array
    if "}{" in text:
        yield "[" + text.replace("}{", "},{") + "]"


def _meta_content(page_html: str, props: list[str]) -> str | None:
    for prop in props:
        m = re.search(
            r'<meta[^>]+(?:property|name)=["\']' + re.escape(prop) +
            r'["\'][^>]*content=["\']([^"\']+)["\']',
            page_html, re.IGNORECASE,
        )
        if not m:  # attribute order can be reversed
            m = re.search(
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\']'
                + re.escape(prop) + r'["\']',
                page_html, re.IGNORECASE,
            )
        if m:
            return html.unescape(m.group(1)).strip()
    return None


def _itemprop_price(page_html: str) -> str | None:
    m = re.search(r'itemprop=["\']price["\'][^>]*content=["\']([^"\']+)["\']', page_html, re.I)
    if m:
        return m.group(1)
    m = re.search(r'content=["\']([^"\']+)["\'][^>]*itemprop=["\']price["\']', page_html, re.I)
    return m.group(1) if m else None


def _html_title(page_html: str) -> str | None:
    m = re.search(r"<title[^>]*>(.*?)</title>", page_html, re.DOTALL | re.IGNORECASE)
    return html.unescape(m.group(1)).strip() if m else None


# ----------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------
def hunt(queries: list[str], limit: int, timeout: float, workers: int,
         verbose: bool) -> list[Offer]:
    # 1. discover candidate product URLs across all queries
    candidate_urls: list[str] = []
    seen = set()
    for q in queries:
        if verbose:
            print(f"  searching: {q}", file=sys.stderr)
        for u in search_urls(q, limit, timeout, verbose):
            key = u.split("?")[0]
            if key not in seen:
                seen.add(key)
                candidate_urls.append(u)
        time.sleep(0.4)  # be polite to the search front-end

    if verbose:
        print(f"  {len(candidate_urls)} candidate product pages", file=sys.stderr)

    # 2. fetch + extract in parallel
    offers: list[Offer] = []

    def _work(u: str) -> list[Offer]:
        body = fetch(u, timeout=timeout, verbose=verbose)
        return extract_offers(body, u) if body else []

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for result in ex.map(_work, candidate_urls):
            offers.extend(result)

    return offers


def dedupe_and_rank(offers: list[Offer], capacity: float) -> list[Offer]:
    # keep offers within +-25% of the requested capacity
    lo, hi = capacity * 0.75, capacity * 1.25
    filtered = [o for o in offers if lo <= o.capacity_tb <= hi and 5 <= o.price_per_tb <= 1000]
    # one cheapest offer per seller
    best_by_seller: dict[str, Offer] = {}
    for o in filtered:
        cur = best_by_seller.get(o.seller)
        if cur is None or o.price_per_tb < cur.price_per_tb:
            best_by_seller[o.seller] = o
    return sorted(best_by_seller.values(), key=lambda o: o.price_per_tb)


def print_leaderboard(offers: list[Offer], capacity: float) -> None:
    if not offers:
        print("\nNo live offers parsed. Search front-ends may be rate-limiting, or "
              "egress is blocked.\nTry --verbose, a direct --query, or run again shortly.")
        return
    print(f"\n  1 TB SSD VALUE LEADERBOARD  ({time.strftime('%Y-%m-%d %H:%M %Z')})")
    print("  " + "-" * 68)
    print(f"  {'#':<3}{'PRICE':>10}{'$/TB':>9}  {'SELLER':<20}{'MODEL'}")
    print("  " + "-" * 68)
    for i, o in enumerate(offers, 1):
        tag = "  <- best value" if i == 1 else ""
        print(f"  {i:<3}{o.money():>10}{o.price_per_tb:>8.0f}  {o.seller[:19]:<20}"
              f"{o.title[:34]}{tag}")
    print("  " + "-" * 68)
    best = offers[0]
    print(f"  Best value: {best.title}")
    print(f"              {best.money()} at {best.seller}  ->  {best.url}\n")


# ----------------------------------------------------------------------------
# Offline self-test — proves the structured-data parser works without network.
# ----------------------------------------------------------------------------
_FIXTURE = """
<html><head><title>Crucial P3 Plus 1TB PCIe Gen4 NVMe M.2 SSD</title>
<meta property="og:title" content="Crucial P3 Plus 1TB Gen4 NVMe SSD">
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product",
 "name":"Crucial P3 Plus 1TB PCIe Gen4 NVMe M.2 SSD",
 "offers":{"@type":"Offer","price":"67.99","priceCurrency":"USD","availability":"InStock"}}
</script></head><body>...</body></html>
"""

_FIXTURE_META = """
<html><head><title>WD Blue SN580 1TB NVMe SSD</title>
<meta property="product:price:amount" content="74.99">
<meta property="product:price:currency" content="USD">
</head><body><span itemprop="price" content="74.99">$74.99</span></body></html>
"""

_FIXTURE_EU = """
<html><head><title>Samsung 990 EVO 1TB</title>
<script type="application/ld+json">
{"@type":"Product","name":"Samsung 990 EVO 1TB",
 "offers":{"@type":"Offer","price":"1.099,00","priceCurrency":"EUR"}}
</script></head></html>
"""


def selftest() -> int:
    ok = True

    def check(desc, cond):
        nonlocal ok
        ok = ok and cond
        print(f"  [{'PASS' if cond else 'FAIL'}] {desc}")

    a = extract_offers(_FIXTURE, "https://www.amazon.com/dp/X")
    check("JSON-LD price parsed", len(a) == 1 and abs(a[0].price - 67.99) < 1e-6)
    check("JSON-LD currency USD", a and a[0].currency == "USD")
    check("capacity detected as 1 TB", a and abs(a[0].capacity_tb - 1.0) < 1e-6)
    check("source tagged json-ld", a and a[0].source == "json-ld")

    b = extract_offers(_FIXTURE_META, "https://www.newegg.com/p/Y")
    check("OG/meta fallback price parsed", len(b) == 1 and abs(b[0].price - 74.99) < 1e-6)

    c = extract_offers(_FIXTURE_EU, "https://www.amazon.de/dp/Z")
    check("EU decimal format 1.099,00 -> 1099.0", c and abs(c[0].price - 1099.0) < 1e-6)
    check("EUR currency parsed", c and c[0].currency == "EUR")

    check("$/TB math", abs(Offer("x", 80.0, "USD", "", "s", 2.0).price_per_tb - 40.0) < 1e-6)
    check("capacity from GB (500GB -> 0.5TB)", abs(_detect_capacity_tb("Crucial 500GB") - 0.5) < 1e-3)

    ranked = dedupe_and_rank(a + b, 1.0)
    check("ranking sorts by $/TB", [round(o.price_per_tb) for o in ranked] == [68, 75])

    print(f"\n  {'ALL TESTS PASSED' if ok else 'SOME TESTS FAILED'}")
    return 0 if ok else 1


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def build_queries(brands: list[str], capacity: float, override: str | None) -> list[str]:
    if override:
        return [override]
    cap = f"{capacity:g}TB"
    queries: list[str] = []
    for b in brands:
        models = GOOD_VALUE_MODELS.get(b.lower())
        if models:
            queries.extend(models)
        else:
            queries.append(f"{b} {cap} SSD")
    # the curated model names are 1 TB; rewrite the capacity token when asked for
    # something else (e.g. "Crucial P3 Plus 1TB" -> "Crucial P3 Plus 2TB").
    if capacity != 1:
        queries = [re.sub(r"\d+(?:\.\d+)?\s*TB", cap, q, flags=re.I) for q in queries]
    return queries


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        description="Find realtime pricing for a 1 TB SSD from good-value brands "
                    "by harvesting retailer structured data.")
    p.add_argument("--capacity", type=float, default=1.0, help="capacity in TB (default 1)")
    p.add_argument("--brands", nargs="+", default=list(GOOD_VALUE_MODELS),
                   help="brands to hunt (default: all curated good-value brands)")
    p.add_argument("--query", help="override the search with a single explicit query")
    p.add_argument("--limit", type=int, default=4, help="product pages per query (default 4)")
    p.add_argument("--workers", type=int, default=8, help="parallel fetches (default 8)")
    p.add_argument("--timeout", type=float, default=12.0, help="per-request timeout seconds")
    p.add_argument("--json", metavar="FILE", help="also write results as JSON")
    p.add_argument("--selftest", action="store_true", help="run offline parser tests and exit")
    p.add_argument("--verbose", action="store_true", help="log search/fetch progress to stderr")
    args = p.parse_args(argv)

    if args.selftest:
        return selftest()

    queries = build_queries(args.brands, args.capacity, args.query)
    print(f"Hunting {args.capacity:g} TB SSD across {len(queries)} model queries "
          f"from: {', '.join(args.brands)}")

    offers = hunt(queries, args.limit, args.timeout, args.workers, args.verbose)
    ranked = dedupe_and_rank(offers, args.capacity)
    print_leaderboard(ranked, args.capacity)

    if args.json:
        with open(args.json, "w") as f:
            json.dump([{**asdict(o), "price_per_tb": round(o.price_per_tb, 2)}
                       for o in ranked], f, indent=2)
        print(f"  wrote {len(ranked)} offers to {args.json}")

    return 0 if ranked else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
