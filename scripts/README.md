# SSD Price Search

`ssd_price_search.py` — a realtime price hunter for a 1 TB SSD from good-value
brands (Crucial, WD, Samsung, Kingston, TeamGroup, Silicon Power, SK hynix).

## The idea

Rather than scraping one retailer's brittle HTML (which breaks constantly) or
paying for a shopping API, the script harvests the **structured data every
storefront already publishes for Google Shopping / SEO**:

| Layer | What it reads |
|-------|----------------|
| JSON-LD | `<script type="application/ld+json">` → `Product` / `Offer` → `price` |
| Microdata | `<span itemprop="price" content="79.99">` |
| OpenGraph | `<meta property="product:price:amount" content="79.99">` |

One parser therefore reads prices from Amazon, Newegg, Best Buy, B&H, Micro
Center, Crucial.com, and more. A search front-end discovers live product pages
for a curated set of good-value 1 TB models, every offer is normalized to
**dollars per terabyte**, deduped to the cheapest per seller, and printed as a
live leaderboard.

## Usage

```bash
python3 ssd_price_search.py                      # hunt 1 TB across all good-value brands
python3 ssd_price_search.py --brands crucial wd  # restrict brands
python3 ssd_price_search.py --capacity 2         # 2 TB instead
python3 ssd_price_search.py --query "crucial p3 plus 1tb"
python3 ssd_price_search.py --json out.json      # also dump machine-readable
python3 ssd_price_search.py --verbose            # log search/fetch progress
python3 ssd_price_search.py --selftest           # offline parser verification (no network)
```

Sample output:

```
  1 TB SSD VALUE LEADERBOARD  (2026-06-21 14:02 UTC)
  --------------------------------------------------------------------
  #       PRICE     $/TB  SELLER              MODEL
  --------------------------------------------------------------------
  1      $67.99       68  amazon.com          Crucial P3 Plus 1TB Gen4 NVMe  <- best value
  2      $74.99       75  newegg.com          WD Blue SN580 1TB NVMe
  ...
```

## Requirements

Only [`requests`](https://pypi.org/project/requests/) (and it falls back to the
standard library `urllib` if `requests` is absent — so it can run with zero
installs). HTML is parsed with the standard library.

```bash
pip install -r requirements.txt   # optional
```

## Notes

- Run `--selftest` anytime to confirm the price parser is correct without
  touching the network.
- Search front-ends rate-limit aggressively. If a run comes back empty, wait a
  bit, add `--verbose`, or pass an explicit `--query`.
- This is a price-discovery aid, not financial advice. Confirm on the
  retailer's page before buying.
```
