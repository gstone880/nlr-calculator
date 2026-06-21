# SSD Price Search

`ssd_price_search.py` — a realtime price hunter for a 1 TB SSD from good-value
brands, covering both **internal** drives (M.2 NVMe / 2.5" SATA) and
**external/portable** USB-C drives (Samsung T7/T9, Crucial X9/X10, SanDisk
Extreme, WD My Passport, Kingston XS1000/XS2000, ADATA SE880, …).

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
python3 ssd_price_search.py                       # 1 TB, internal + external, top 20
python3 ssd_price_search.py --type external       # portable USB drives only
python3 ssd_price_search.py --type internal       # bare M.2 / SATA only
python3 ssd_price_search.py --brands crucial wd   # restrict brands
python3 ssd_price_search.py --capacity 0.5         # 500 GB instead of 1 TB
python3 ssd_price_search.py --capacity 2          # 2 TB instead
python3 ssd_price_search.py --top 30              # show 30 rows instead of 20
python3 ssd_price_search.py --query "crucial p3 plus 1tb"
python3 ssd_price_search.py --json out.json       # also dump machine-readable
python3 ssd_price_search.py --verbose             # log search/fetch progress
python3 ssd_price_search.py --selftest            # offline parser verification (no network)
```

Sample output (each row shows the live link, so a dead "best value" listing is
easy to skip):

```
  1 TB SSD VALUE LEADERBOARD — top 20  (2026-06-21 14:02 UTC)
  --------------------------------------------------------------------------------------------
  #      PRICE   $/TB  TYPE     SELLER          MODEL                         LINK
  --------------------------------------------------------------------------------------------
  1     $67.99    68  internal amazon.com      Crucial P3 Plus 1TB Gen4 NVM  https://www.amazon.com/dp/B0C...
  2     $69.99    70  internal bestbuy.com     Kingston NV3 1TB              https://www.bestbuy.com/site/...
  4     $84.99    85  external bhphotovideo.co SanDisk Extreme Portable 1TB  https://www.bhphotovideo.com/...
  ...
  Best internal : $67.99 (68 $/TB)  Crucial P3 Plus 1TB @ amazon.com
  Best external : $84.99 (85 $/TB)  SanDisk Extreme Portable 1TB @ bhphotovideo.com
```

## Requirements

Only [`requests`](https://pypi.org/project/requests/) (and it falls back to the
standard library `urllib` if `requests` is absent — so it can run with zero
installs). HTML is parsed with the standard library.

```bash
pip install -r requirements.txt   # optional
```

## Search engines

Product pages are discovered across several independent engines and the results
are aggregated, so one engine throttling your IP (common on mobile data) just
gets topped up by the others. Default order: `ddg-lite, bing, mojeek, ddg-html,
brave, startpage`. Pick a subset with `--engines`:

```bash
python3 ssd_price_search.py --engines bing mojeek      # skip DuckDuckGo entirely
python3 ssd_price_search.py --engines ddg-lite --verbose
```

## Notes

- Run `--selftest` anytime to confirm the parser + link handling are correct
  without touching the network.
- Search front-ends rate-limit aggressively, especially over mobile data. If a
  run comes back thin, add `--verbose`, try different `--engines`, pass an
  explicit `--query`, or run on Wi-Fi.
- **Dead / out-of-stock listings are hidden by default.** Search engines keep
  indexing discontinued product pages; the script reads each offer's Schema.org
  `availability` and drops anything flagged out-of-stock/discontinued, and skips
  pages whose title reads like a 404. Pass `--include-unavailable` to see them.
- This is a price-discovery aid, not financial advice. Confirm on the
  retailer's page before buying.
```
