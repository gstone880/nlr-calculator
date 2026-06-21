#!/usr/bin/env python3
"""Find 1TB external SSD deals under a price cap from a brand allow-list.

Queries the Best Buy Products API (https://developer.bestbuy.com/) — no
scraping involved, so it stays within each site's terms of service.

Usage:
    export BESTBUY_API_KEY=your_key_here
    python crawler.py
    python crawler.py --max-price 60 --brands Samsung,Crucial
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

API_BASE = "https://api.bestbuy.com/v1/products"
DEFAULT_BRANDS = ["Samsung", "SanDisk", "WD", "Western Digital", "Crucial", "Seagate", "Kingston"]
SHOW_FIELDS = "sku,name,manufacturer,salePrice,regularPrice,url,onlineAvailability,customerReviewAverage,customerReviewCount"
CAPACITY_RE = re.compile(r"\b1\s?TB\b", re.IGNORECASE)
EXTERNAL_RE = re.compile(r"\b(external|portable)\b", re.IGNORECASE)
SSD_RE = re.compile(r"\bSSD\b", re.IGNORECASE)


def build_query(max_price, brands):
    brand_filter = "|".join(b.replace(" ", "%20") for b in brands)
    parts = [
        "(search=external ssd 1tb)",
        f"(salePrice<={max_price})",
        f"(manufacturer={brand_filter})",
    ]
    return "".join(parts)


def fetch_products(api_key, max_price, brands, page_size=50):
    query = build_query(max_price, brands)
    params = {
        "apiKey": api_key,
        "format": "json",
        "show": SHOW_FIELDS,
        "pageSize": str(page_size),
        "sort": "salePrice.asc",
    }
    url = f"{API_BASE}({query})?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def matches_capacity_and_type(product):
    name = product.get("name", "")
    return bool(CAPACITY_RE.search(name) and SSD_RE.search(name) and EXTERNAL_RE.search(name))


def find_deals(api_key, max_price, brands):
    data = fetch_products(api_key, max_price, brands)
    products = data.get("products", [])
    deals = [p for p in products if matches_capacity_and_type(p)]
    deals.sort(key=lambda p: p.get("salePrice", float("inf")))
    return deals


def print_deals(deals):
    if not deals:
        print("No matching 1TB external SSD deals found.")
        return
    print(f"{'Price':>8}  {'Brand':<14}  {'Rating':<8}  Name")
    print("-" * 90)
    for d in deals:
        price = f"${d.get('salePrice', 0):.2f}"
        brand = d.get("manufacturer", "")[:14]
        rating = d.get("customerReviewAverage")
        rating_str = f"{rating:.1f}/5" if rating else "n/a"
        print(f"{price:>8}  {brand:<14}  {rating_str:<8}  {d.get('name')}")
        print(f"          {d.get('url')}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-price", type=float, default=70.0, help="Maximum price in USD (default: 70)")
    parser.add_argument("--brands", type=str, default=",".join(DEFAULT_BRANDS),
                         help="Comma-separated brand allow-list")
    parser.add_argument("--api-key", type=str, default=os.environ.get("BESTBUY_API_KEY"),
                         help="Best Buy API key (or set BESTBUY_API_KEY env var)")
    parser.add_argument("--output", type=str, default="results.json",
                         help="Path to write JSON results (default: results.json)")
    args = parser.parse_args()

    if not args.api_key:
        print("Error: no API key provided. Set BESTBUY_API_KEY or pass --api-key.", file=sys.stderr)
        print("Get a free key at https://developer.bestbuy.com/", file=sys.stderr)
        sys.exit(1)

    brands = [b.strip() for b in args.brands.split(",") if b.strip()]

    try:
        deals = find_deals(args.api_key, args.max_price, brands)
    except urllib.error.HTTPError as e:
        print(f"Best Buy API request failed: {e.code} {e.reason}", file=sys.stderr)
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
