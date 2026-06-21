#!/usr/bin/env python3
"""Find in-stock external SSDs (500GB - 8TB) across major retailers.

Uses the SerpAPI Google Shopping engine. A single API call per capacity
tier returns live, purchasable offers from across Amazon, Best Buy,
Walmart, Newegg, B&H and more -- with real prices, the selling retailer,
ratings, and a working link to buy. Results are filtered to reputable
SSD brands and trusted retailers, then ranked by price-per-terabyte.

Why an API instead of scraping: major retailers block scrapers and load
stock/price via JavaScript, so static scraping returns blocked pages or
stale stock. Google Shopping (via SerpAPI) surfaces only live, in-stock
offers and gives canonical links that work.

Setup:
    1. Get a free key at https://serpapi.com/ (free tier ~100 searches/mo).
    2. export SERPAPI_API_KEY=your_key_here

Usage:
    python3 crawler.py                          # all tiers, all trusted retailers
    python3 crawler.py --max-price 200
    python3 crawler.py --min-gb 1000 --max-gb 4000
    python3 crawler.py --brands Samsung,Crucial
    python3 crawler.py --input-file saved.json  # offline: parse a saved response

No third-party packages required (standard library only).
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

SERPAPI_ENDPOINT = "https://serpapi.com/search.json"

# Reputable SSD manufacturers (well-regarded for reliability/warranty).
DEFAULT_BRANDS = [
    "Samsung", "SanDisk", "Western Digital", "WD", "Crucial", "Seagate",
    "Kingston", "SK Hynix", "Sabrent", "Lexar", "ADATA", "Corsair",
]

# Major, legitimate retailers (plus manufacturer direct stores).
DEFAULT_RETAILERS = [
    "Amazon", "Best Buy", "Walmart", "Newegg", "B&H", "Adorama", "Target",
    "Costco", "Micro Center", "Dell", "Staples", "Office Depot",
    "Samsung", "Crucial", "Western Digital", "Seagate", "Kingston", "SanDisk",
]

TIERS_GB = [500, 1000, 2000, 4000, 8000]

SSD_RE = re.compile(r"\bSSD\b", re.IGNORECASE)
EXTERNAL_RE = re.compile(r"\b(external|portable)\b", re.IGNORECASE)
CAPACITY_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s?(TB|GB)\b", re.IGNORECASE)
OUT_OF_STOCK_RE = re.compile(r"out\s*of\s*stock|sold\s*out|unavailable", re.IGNORECASE)
URL_RE = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)


def tier_label(gb):
    return f"{gb // 1000}TB" if gb >= 1000 and gb % 1000 == 0 else f"{gb}GB"


def extract_capacity_gb(name):
    """Largest plausible storage value in the title, normalized to GB."""
    best = None
    for value, unit in CAPACITY_RE.findall(name or ""):
        gb = float(value) * (1000 if unit.upper() == "TB" else 1)
        if 100 <= gb <= 16000 and (best is None or gb > best):
            best = gb
    return best


def extract_price(item):
    """Prefer the numeric extracted_price; fall back to parsing the price string."""
    if isinstance(item.get("extracted_price"), (int, float)):
        return float(item["extracted_price"])
    match = re.search(r"([\d,]+\.\d{2}|\d[\d,]*)", str(item.get("price", "")))
    if match:
        try:
            return float(match.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


def pick_buy_link(item):
    """Return a working purchase link, preferring a direct merchant URL over
    the Google Shopping product page. Returns None if no valid link exists."""
    candidates = [item.get("link"), item.get("product_link"), item.get("offers_link")]
    direct = [u for u in candidates if u and URL_RE.match(u) and "google." not in u.split("/")[2]]
    if direct:
        return direct[0]
    for u in candidates:
        if u and URL_RE.match(u):
            return u
    return None


def in_stock(item):
    """Google Shopping surfaces live offers; exclude anything explicitly flagged
    out of stock in availability/delivery/snippet text."""
    blob = " ".join(str(item.get(k, "")) for k in ("availability", "delivery", "snippet", "tag"))
    return not OUT_OF_STOCK_RE.search(blob)


def normalize(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def filter_items(items, brands, retailers, min_gb, max_gb, max_price):
    """Return (deals, stats). stats explains why items were dropped."""
    stats = {"parsed": len(items), "not_ssd": 0, "not_external": 0,
             "bad_capacity": 0, "untrusted_retailer": 0, "off_brand": 0,
             "out_of_stock": 0, "no_price": 0, "over_price": 0, "bad_link": 0,
             "kept": 0}
    brands_n = [normalize(b) for b in brands]
    retailers_n = [normalize(r) for r in retailers]
    deals, seen = [], set()

    for it in items:
        title = it.get("title", "")
        if not SSD_RE.search(title):
            stats["not_ssd"] += 1
            continue
        if not EXTERNAL_RE.search(title):
            stats["not_external"] += 1
            continue
        cap = extract_capacity_gb(title)
        if cap is None or cap < min_gb or cap > max_gb:
            stats["bad_capacity"] += 1
            continue
        source_n = normalize(it.get("source", ""))
        if not any(r in source_n for r in retailers_n):
            stats["untrusted_retailer"] += 1
            continue
        title_n = normalize(title)
        brand_match = next((b for b in brands if normalize(b) in title_n), None)
        if not brand_match:
            stats["off_brand"] += 1
            continue
        if not in_stock(it):
            stats["out_of_stock"] += 1
            continue
        price = extract_price(it)
        if price is None:
            stats["no_price"] += 1
            continue
        if max_price is not None and price > max_price:
            stats["over_price"] += 1
            continue
        link = pick_buy_link(it)
        if not link:
            stats["bad_link"] += 1
            continue

        key = (normalize(title), it.get("source"), price)
        if key in seen:
            continue
        seen.add(key)

        deals.append({
            "title": title,
            "brand": brand_match,
            "retailer": it.get("source", "?"),
            "price": price,
            "price_per_tb": round(price / (cap / 1000), 2),
            "capacity_gb": cap,
            "tier": tier_label(int(cap)),
            "rating": it.get("rating"),
            "reviews": it.get("reviews"),
            "buy_link": link,
        })
        stats["kept"] += 1

    deals.sort(key=lambda d: d["price_per_tb"])
    return deals, stats


def serpapi_search(query, api_key):
    params = {"engine": "google_shopping", "q": query, "api_key": api_key,
              "gl": "us", "hl": "en"}
    url = f"{SERPAPI_ENDPOINT}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    if data.get("error"):
        raise RuntimeError(data["error"])
    return data.get("shopping_results", [])


def gather_live(api_key, brands, retailers, min_gb, max_gb, max_price):
    items = []
    tiers = [gb for gb in TIERS_GB if min_gb <= gb <= max_gb] or [min_gb]
    for gb in tiers:
        query = f"{tier_label(gb)} external ssd"
        print(f"  searching {tier_label(gb)} ...", file=sys.stderr)
        try:
            items.extend(serpapi_search(query, api_key))
        except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError) as e:
            reason = getattr(e, "reason", e)
            print(f"  warning: {tier_label(gb)} search failed ({reason}); skipping.",
                  file=sys.stderr)
        time.sleep(1)
    return filter_items(items, brands, retailers, min_gb, max_gb, max_price)


def print_report(deals, stats, min_gb, max_gb):
    print()
    if not deals:
        print("No matching in-stock external SSD deals found.\n")
        print("Why nothing matched (items dropped at each stage):")
        for k in ["parsed", "not_ssd", "not_external", "bad_capacity",
                  "untrusted_retailer", "off_brand", "out_of_stock", "no_price",
                  "over_price", "bad_link", "kept"]:
            print(f"  {k:<20} {stats[k]}")
        print("\nIf 'parsed' is 0, the API returned no results (check your key/quota).")
        print("If 'parsed' is high but all dropped, loosen --max-price, --brands, or --retailers.")
        return

    by_tier = {}
    for d in deals:
        by_tier.setdefault(d["tier"], []).append(d)

    print(f"In-stock external SSDs ({tier_label(min_gb)}-{tier_label(max_gb)}), "
          f"ranked by $/TB within each capacity:\n")
    for tier in sorted(by_tier, key=lambda t: by_tier[t][0]["capacity_gb"]):
        print(f"== {tier} ==")
        for d in sorted(by_tier[tier], key=lambda x: x["price"])[:5]:
            rating = f"{d['rating']}*" if d.get("rating") else "  -  "
            print(f"  ${d['price']:>8.2f}  (${d['price_per_tb']:>7.2f}/TB)  "
                  f"{rating:>5}  {d['brand']:<10}  @ {d['retailer']}")
            print(f"      {d['title'][:74]}")
            print(f"      BUY: {d['buy_link']}")
        print()

    best = deals[0]
    print(f"BEST OVERALL VALUE: {best['brand']} {best['tier']} -- ${best['price']:.2f} "
          f"(${best['price_per_tb']}/TB) at {best['retailer']}\n  BUY: {best['buy_link']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--min-gb", type=int, default=500, help="Minimum capacity in GB (default: 500)")
    parser.add_argument("--max-gb", type=int, default=8000, help="Maximum capacity in GB (default: 8000)")
    parser.add_argument("--max-price", type=float, default=None, help="Optional max price in USD")
    parser.add_argument("--brands", type=str, default=",".join(DEFAULT_BRANDS),
                        help="Comma-separated reputable-brand allow-list")
    parser.add_argument("--retailers", type=str, default=",".join(DEFAULT_RETAILERS),
                        help="Comma-separated trusted-retailer allow-list")
    parser.add_argument("--api-key", type=str, default=os.environ.get("SERPAPI_API_KEY"),
                        help="SerpAPI key (or set SERPAPI_API_KEY env var)")
    parser.add_argument("--input-file", type=str, default=None,
                        help="Parse a saved SerpAPI JSON response instead of calling the API")
    parser.add_argument("--output", type=str, default="results.json",
                        help="Path to write JSON results (default: results.json)")
    args = parser.parse_args()

    brands = [b.strip() for b in args.brands.split(",") if b.strip()]
    retailers = [r.strip() for r in args.retailers.split(",") if r.strip()]

    if args.input_file:
        try:
            with open(args.input_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"Could not read {args.input_file}: {e}", file=sys.stderr)
            sys.exit(1)
        items = data.get("shopping_results", data) if isinstance(data, dict) else data
        deals, stats = filter_items(items, brands, retailers,
                                    args.min_gb, args.max_gb, args.max_price)
    else:
        if not args.api_key:
            print("Error: no API key. Set SERPAPI_API_KEY or pass --api-key.", file=sys.stderr)
            print("Get a free key at https://serpapi.com/", file=sys.stderr)
            sys.exit(1)
        print("Searching Google Shopping via SerpAPI (one query per tier)...", file=sys.stderr)
        deals, stats = gather_live(args.api_key, brands, retailers,
                                   args.min_gb, args.max_gb, args.max_price)

    print_report(deals, stats, args.min_gb, args.max_gb)

    with open(args.output, "w") as f:
        json.dump({
            "queried_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "min_gb": args.min_gb, "max_gb": args.max_gb,
            "max_price": args.max_price, "brands": brands, "retailers": retailers,
            "stats": stats, "deals": deals,
        }, f, indent=2)
    print(f"\nSaved {len(deals)} in-stock deal(s) to {args.output}")


if __name__ == "__main__":
    main()
