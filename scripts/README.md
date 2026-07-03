# Scripts

---

## Halifax Listings Search

`halifax_listings_search.py` — finds Halifax Metro Area (HRM) real estate listings
that have a **bedroom on the first/main floor at or near driveway level**.

### The problem it solves

Most Halifax homes are **split-entries**: you step up (or down) half a flight from
the front door before reaching any bedrooms. For aging-in-place, mobility needs, or
simply wanting to avoid interior stairs, you need the first floor you walk into from
the driveway to *already have* a bedroom.

### Target property types

| Type | Why it qualifies |
|------|-----------------|
| Bungalow / rancher | All living on one level; entry always at grade |
| One-storey | Same as bungalow |
| 1.5-storey | Main floor has bedroom(s); roof-space floor above |
| Ground-floor condo | Unit is at lobby / driveway level |

**Explicitly deprioritised:** split-entry (you go up/down stairs before bedrooms),
raised bungalow (main floor elevated above grade with exterior stairs).

### Usage

```bash
python3 halifax_listings_search.py                        # all HRM areas, all prices
python3 halifax_listings_search.py --area Halifax Dartmouth Bedford
python3 halifax_listings_search.py --min-beds 2 --max-price 600000
python3 halifax_listings_search.py --query "Dartmouth NS bungalow 3 bedroom"
python3 halifax_listings_search.py --json results.json    # also dump machine-readable
python3 halifax_listings_search.py --verbose              # log fetch progress
python3 halifax_listings_search.py --selftest             # offline unit tests (no network)
```

### How it works

Real estate listing sites block direct scraping (HTTP 403). The script uses the same
approach as `ssd_price_search.py`: it discovers listing URLs from search engine result
pages (DuckDuckGo, Bing, Mojeek, Startpage), then attempts to read structured-data /
meta tags from each listing page. Each listing is scored for two signals:

1. **First-floor bedroom** — keywords like "bungalow", "main floor bedroom", "one storey"
2. **Grade-level entry** — keywords like "level lot", "no steps", "at grade", "bungalow"

Split-entry / raised-foundation keywords subtract from the score. Results are ranked
highest-relevance first.

### Sample output

```
  HALIFAX METRO — FIRST-FLOOR BEDROOM / DRIVEWAY-LEVEL LISTINGS
  Criteria: bedroom on main/first floor · first floor at or near driveway grade
  Found 12 matches; showing top 12

  #  MATCH    PRICE      BEDS TYPE           MLS           ADDRESS / URL
  ──────────────────────────────────────────────────────────────────────────────────────────
  1  STRONG   $549,000   4    bungalow       202512345     613 Beaver Bank Road, Beaver Bank
     https://www.remaxnova.com/…
     Charming 4-bedroom bungalow on a level lot. All bedrooms on main floor, no steps…
  2  STRONG   $559,000   4    1.5 storey     202523004     190 Herring Cove Road, Halifax
     https://www.kentbraaten.com/…
     Main floor includes a flexible bedroom (study), 3-pc bath, direct driveway access…
```

### Requirements

Only `requests` (optional; falls back to `urllib`). No other dependencies.

```bash
pip install -r requirements.txt   # optional
```

---

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
- **Live link verification is ON by default.** Every finalist is pinged and any
  link that 404s, redirects to a homepage, or reads "currently unavailable" /
  "sold out" is dropped — so the leaderboard only shows links that work right
  now. It costs one request per row; skip it for a faster run with
  `--no-check-links`:
  ```bash
  python3 ssd_price_search.py --no-check-links   # faster, skips verification
  ```
- This is a price-discovery aid, not financial advice. Confirm on the
  retailer's page before buying.
```
