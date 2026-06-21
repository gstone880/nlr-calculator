#!/usr/bin/env python3
"""Find the best-value external SSD deals (500GB - 8TB) from quality brands.

Scrapes Newegg's public search results -- no API key required. For each
capacity tier it runs a search, parses every listing, and ranks results
by price-per-terabyte so you can see the genuine best value across the
whole 500GB - 8TB range, not just the cheapest sticker price.

Design goals after earlier brittleness:
  * NO BAD LINKS -- every product URL is validated as a canonical Newegg
    product page (https://www.newegg.com/.../p/<id>) before it's shown.
    Anything that doesn't validate is dropped.
  * SELF-DIAGNOSING -- if nothing matches, it prints exactly how many
    listings failed each filter stage, so you never have to guess.
  * ROBUST -- price parsing handles both Newegg price layouts; brand is
    read from the product feature list (the current markup).

Usage:
    pip install -r requirements.txt
    python crawler.py                          # live, all tiers
    python crawler.py --max-price 200          # cap the price
    python crawler.py --min-gb 1000 --max-gb 4000
    python crawler.py --brands Samsung,Crucial
    python crawler.py --html-file saved.html   # offline, parse a saved page
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

# Capacity tiers we search for, in GB.
TIERS_GB = [500, 1000, 2000, 4000, 8000]

SSD_RE = re.compile(r"\bSSD\b", re.IGNORECASE)
EXTERNAL_RE = re.compile(r"\b(external|portable)\b", re.IGNORECASE)
CAPACITY_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s?(TB|GB)\b", re.IGNORECASE)
PRICE_RE = re.compile(r"([\d,]+\.\d{2})")
# A valid Newegg product link looks like .../p/N82E16820524013 (or similar).
VALID_URL_RE = re.compile(r"^https://www\.newegg\.com/[^\s]+/p/[A-Za-z0-9]+", re.IGNORECASE)


def tier_label(gb):
    return f"{gb // 1000}TB" if gb >= 1000 and gb % 1000 == 0 else f"{gb}GB"


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
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _extract_price(price_el):
    if price_el is None:
        return None
    # Collapse all whitespace so "$ 109 .99" becomes "$109.99".
    text = re.sub(r"\s+", "", price_el.get_text(" ", strip=True)).replace(",", "")
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


def _extract_brand(cell):
    """Brand is a 'Brand:' row inside .item-features in current Newegg markup."""
    for li in cell.select(".item-features li"):
        label_el = li.find("strong")
        if not label_el or label_el.get_text(strip=True).rstrip(":").lower() != "brand":
            continue
        return li.get_text(" ", strip=True).split(":", 1)[-1].strip()
    return None


def _extract_capacity_gb(name):
    """Return the storage capacity in GB parsed from the product name, or None.

    Picks the largest plausible storage value so '2-in-1 USB' style noise or a
    '1050MB/s' speed never gets mistaken for capacity."""
    best = None
    for value, unit in CAPACITY_RE.findall(name):
        gb = float(value) * (1000 if unit.upper() == "TB" else 1)
        if 100 <= gb <= 16000 and (best is None or gb > best):
            best = gb
    return best


def parse_listings(html):
    soup = BeautifulSoup(html, "html.parser")
    listings = []
    for cell in soup.select(".item-cell"):
        title_el = cell.select_one(".item-title")
        if not title_el:
            continue
        name = title_el.get_text(strip=True)
        listings.append({
            "name": name,
            "url": title_el.get("href", ""),
            "price": _extract_price(cell.select_one(".price-current")),
            "brand": _extract_brand(cell),
            "capacity_gb": _extract_capacity_gb(name),
        })
    return listings


def filter_listings(listings, brands, min_gb, max_gb, max_price):
    """Return (deals, stats) where stats counts why listings were dropped."""
    stats = {"parsed": len(listings), "not_ssd": 0, "not_external": 0,
             "bad_capacity": 0, "bad_url": 0, "no_price": 0, "over_price": 0,
             "brand_mismatch": 0, "kept": 0}
    brands_lc = [b.lower() for b in brands]
    deals = []
    seen = set()
    for l in listings:
        name = l["name"] or ""
        if not SSD_RE.search(name):
            stats["not_ssd"] += 1
            continue
        if not EXTERNAL_RE.search(name):
            stats["not_external"] += 1
            continue
        cap = l["capacity_gb"]
        if cap is None or cap < min_gb or cap > max_gb:
            stats["bad_capacity"] += 1
            continue
        if not VALID_URL_RE.match(l["url"] or ""):
            stats["bad_url"] += 1
            continue
        if l["price"] is None:
            stats["no_price"] += 1
            continue
        if max_price is not None and l["price"] > max_price:
            stats["over_price"] += 1
            continue
        haystack = f"{l.get('brand') or ''} {name}".lower()
        if not any(b in haystack for b in brands_lc):
            stats["brand_mismatch"] += 1
            continue
        url = l["url"].split("?")[0]
        if url in seen:
            continue
        seen.add(url)
        l = dict(l, url=url, price_per_tb=round(l["price"] / (cap / 1000), 2),
                 tier=tier_label(int(cap)))
        deals.append(l)
        stats["kept"] += 1
    deals.sort(key=lambda d: d["price_per_tb"])
    return deals, stats


def gather_live(brands, min_gb, max_gb, max_price):
    """Search one query per capacity tier in range and aggregate results."""
    all_listings = []
    tiers = [gb for gb in TIERS_GB if min_gb <= gb <= max_gb] or [min_gb]
    for gb in tiers:
        query = f"{tier_label(gb)} external ssd"
        url = SEARCH_URL.format(query=urllib.parse.quote_plus(query))
        if not robots_allow(url):
            print(f"robots.txt disallows fetching {url}; aborting.", file=sys.stderr)
            sys.exit(1)
        print(f"  searching {tier_label(gb)} ...", file=sys.stderr)
        try:
            all_listings.extend(parse_listings(fetch_html(url)))
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            reason = getattr(e, "reason", e)
            print(f"  warning: {tier_label(gb)} search failed ({reason}); skipping.",
                  file=sys.stderr)
        time.sleep(1)  # be polite between requests
    return filter_listings(all_listings, brands, min_gb, max_gb, max_price)


def print_report(deals, stats, min_gb, max_gb):
    print()
    if not deals:
        print("No matching external SSD deals found.\n")
        print("Why nothing matched (listings dropped at each stage):")
        for key in ["parsed", "not_ssd", "not_external", "bad_capacity",
                    "bad_url", "no_price", "over_price", "brand_mismatch", "kept"]:
            print(f"  {key:<16} {stats[key]}")
        print("\nIf 'parsed' is 0, Newegg likely served a bot-check page instead "
              "of results.\nIf 'parsed' is high but everything dropped, loosen "
              "--max-price or the brand list.")
        return

    by_tier = {}
    for d in deals:
        by_tier.setdefault(d["tier"], []).append(d)

    print(f"Best-value external SSDs ({tier_label(min_gb)}-{tier_label(max_gb)}), "
          f"ranked by $/TB within each capacity:\n")
    for tier in sorted(by_tier, key=lambda t: by_tier[t][0]["capacity_gb"]):
        items = sorted(by_tier[tier], key=lambda d: d["price"])
        print(f"== {tier} ==")
        for d in items[:5]:
            print(f"  ${d['price']:>7.2f}  (${d['price_per_tb']:>6.2f}/TB)  "
                  f"{(d['brand'] or '?')[:12]:<12}  {d['name'][:62]}")
            print(f"           {d['url']}")
        print()

    best = deals[0]
    print(f"BEST OVERALL VALUE: {best['brand']} {best['tier']} at ${best['price']:.2f} "
          f"(${best['price_per_tb']}/TB)\n  {best['url']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--min-gb", type=int, default=500, help="Minimum capacity in GB (default: 500)")
    parser.add_argument("--max-gb", type=int, default=8000, help="Maximum capacity in GB (default: 8000)")
    parser.add_argument("--max-price", type=float, default=None,
                        help="Optional maximum price in USD (default: no cap)")
    parser.add_argument("--brands", type=str, default=",".join(DEFAULT_BRANDS),
                        help="Comma-separated brand allow-list")
    parser.add_argument("--html-file", type=str, default=None,
                        help="Parse a locally saved search page instead of fetching live")
    parser.add_argument("--output", type=str, default="results.json",
                        help="Path to write JSON results (default: results.json)")
    args = parser.parse_args()

    brands = [b.strip() for b in args.brands.split(",") if b.strip()]

    if args.html_file:
        try:
            with open(args.html_file, "r", encoding="utf-8") as f:
                html = f.read()
        except OSError as e:
            print(f"Could not read {args.html_file}: {e}", file=sys.stderr)
            sys.exit(1)
        deals, stats = filter_listings(parse_listings(html), brands,
                                       args.min_gb, args.max_gb, args.max_price)
    else:
        print("Searching Newegg (one query per capacity tier)...", file=sys.stderr)
        deals, stats = gather_live(brands, args.min_gb, args.max_gb, args.max_price)

    print_report(deals, stats, args.min_gb, args.max_gb)

    with open(args.output, "w") as f:
        json.dump({
            "queried_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "min_gb": args.min_gb, "max_gb": args.max_gb,
            "max_price": args.max_price, "brands": brands,
            "stats": stats, "deals": deals,
        }, f, indent=2)
    print(f"\nSaved {len(deals)} deal(s) to {args.output}")


if __name__ == "__main__":
    main()
