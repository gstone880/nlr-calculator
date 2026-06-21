#!/usr/bin/env python3
"""Find 1TB external SSD deals under a price cap from a brand allow-list.

Scrapes Newegg's public search results page directly -- no API key
required. Checks robots.txt before every live request and refuses to
scrape if it's disallowed (or unreachable).

Intended for light, manual/personal use (you run it, it makes one
request). Do not schedule this to run frequently or at scale -- that
would likely violate Newegg's terms of service.

Site markup changes over time and can break the selectors below. If a
run returns zero results, save the search page HTML and re-run with
--html-file to debug the parser without hitting the network, then
update SELECTORS / parse_listings() to match the new markup.

Usage:
    pip install -r requirements.txt
    python crawler.py
    python crawler.py --max-price 60 --brands Samsung,Crucial
    python crawler.py --html-file saved_page.html   # offline debugging
"""
import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser

from bs4 import BeautifulSoup

SEARCH_URL = "https://www.newegg.com/p/pl?d={query}"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_BRANDS = ["Samsung", "SanDisk", "WD", "Western Digital", "Crucial", "Seagate", "Kingston"]

CAPACITY_RE = re.compile(r"\b1\s?TB\b", re.IGNORECASE)
SSD_RE = re.compile(r"\bSSD\b", re.IGNORECASE)
EXTERNAL_RE = re.compile(r"\b(external|portable)\b", re.IGNORECASE)
PRICE_RE = re.compile(r"\$?([\d,]+\.\d{2})")


def robots_allow(url):
    """Fail closed: if robots.txt can't be read, treat scraping as disallowed."""
    parsed = urllib.parse.urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = urllib.robotparser.RobotFileParser()
    try:
        req = urllib.request.Request(robots_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as resp:
            lines = resp.read().decode("utf-8", errors="replace").splitlines()
        rp.parse(lines)
    except Exception:
        return False
    return rp.can_fetch(USER_AGENT, url)


def fetch_html(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _extract_price(price_el):
    if price_el is None:
        return None
    text = price_el.get_text(" ", strip=True).replace(",", "")
    match = PRICE_RE.search(text)
    if match:
        return float(match.group(1))
    strong = price_el.find("strong")
    sup = price_el.find("sup")
    if strong and sup:
        try:
            return float(f"{strong.get_text(strip=True)}.{sup.get_text(strip=True).lstrip('.')}")
        except ValueError:
            return None
    return None


def parse_listings(html):
    soup = BeautifulSoup(html, "html.parser")
    listings = []
    for cell in soup.select(".item-cell"):
        title_el = cell.select_one(".item-title")
        if not title_el:
            continue
        name = title_el.get_text(strip=True)
        url = title_el.get("href", "")
        price = _extract_price(cell.select_one(".price-current"))
        brand_el = cell.select_one(".item-brand img")
        brand = (brand_el.get("title") or brand_el.get("alt")) if brand_el else None
        listings.append({"name": name, "url": url, "price": price, "brand": brand})
    return listings


def matches_filters(listing, max_price, brands):
    if listing["price"] is None or listing["price"] > max_price:
        return False
    name = listing["name"] or ""
    if not (CAPACITY_RE.search(name) and SSD_RE.search(name) and EXTERNAL_RE.search(name)):
        return False
    haystack = f"{listing.get('brand') or ''} {name}".lower()
    return any(b.lower() in haystack for b in brands)


def find_deals(query, max_price, brands, html=None):
    if html is None:
        url = SEARCH_URL.format(query=urllib.parse.quote_plus(query))
        if not robots_allow(url):
            print(f"robots.txt disallows fetching {url}; aborting.", file=sys.stderr)
            sys.exit(1)
        html = fetch_html(url)
    listings = parse_listings(html)
    deals = [l for l in listings if matches_filters(l, max_price, brands)]
    deals.sort(key=lambda l: l["price"])
    return deals


def print_deals(deals):
    if not deals:
        print("No matching 1TB external SSD deals found.")
        return
    print(f"{'Price':>8}  {'Brand':<14}  Name")
    print("-" * 90)
    for d in deals:
        print(f"{'$' + format(d['price'], '.2f'):>8}  {(d['brand'] or '')[:14]:<14}  {d['name']}")
        print(f"          {d['url']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--query", type=str, default="1tb external ssd", help="Search query")
    parser.add_argument("--max-price", type=float, default=70.0, help="Maximum price in USD (default: 70)")
    parser.add_argument("--brands", type=str, default=",".join(DEFAULT_BRANDS),
                         help="Comma-separated brand allow-list")
    parser.add_argument("--html-file", type=str, default=None,
                         help="Parse a locally saved search-results page instead of fetching live")
    parser.add_argument("--output", type=str, default="results.json",
                         help="Path to write JSON results (default: results.json)")
    args = parser.parse_args()

    brands = [b.strip() for b in args.brands.split(",") if b.strip()]

    html = None
    if args.html_file:
        try:
            with open(args.html_file, "r", encoding="utf-8") as f:
                html = f.read()
        except OSError as e:
            print(f"Could not read {args.html_file}: {e}", file=sys.stderr)
            sys.exit(1)

    try:
        deals = find_deals(args.query, args.max_price, brands, html=html)
    except urllib.error.HTTPError as e:
        print(f"Request failed: {e.code} {e.reason}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Request failed: {e.reason}", file=sys.stderr)
        sys.exit(1)

    print_deals(deals)

    with open(args.output, "w") as f:
        json.dump({
            "queried_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "max_price": args.max_price,
            "brands": brands,
            "deals": deals,
        }, f, indent=2)
    print(f"\nSaved {len(deals)} deal(s) to {args.output}")


if __name__ == "__main__":
    main()
