# SSD Best-Value Finder (SerpAPI / Google Shopping)

Finds **in-stock external SSDs from 500GB to 8TB** across major retailers
(Amazon, Best Buy, Walmart, Newegg, B&H, and more), filtered to reputable
SSD brands and ranked by **price-per-terabyte**. Each result includes the
selling retailer, rating, and a working link to buy.

> **Heads up — you may not need this.** Websites already do this well:
> - **https://diskprices.com** — ranks storage by $/TB with direct buy links (best match)
> - **https://shopping.google.com** — all major retailers, in-stock, buy links
> - **https://pcpartpicker.com** — storage filters across retailers
>
> This script is for when you want programmatic/scheduled output (e.g. a
> cron job that emails you when a drive drops below a $/TB threshold) that
> a website can't give you.

## Why an API instead of scraping

Major retailers block scrapers and load price/stock via JavaScript, so
static scraping returns blocked pages or stale stock. SerpAPI's Google
Shopping engine surfaces only live, purchasable offers and returns
canonical links that work — which is what makes "truly in stock + working
buy link" achievable.

## Setup

1. Get a free key at https://serpapi.com/ (free tier ~100 searches/mo).
2. ```
   export SERPAPI_API_KEY=your_key_here
   ```

No third-party Python packages required (standard library only).

## Usage

```
python3 crawler.py                          # all tiers, all trusted retailers
python3 crawler.py --max-price 200
python3 crawler.py --min-gb 1000 --max-gb 4000
python3 crawler.py --brands Samsung,Crucial
python3 crawler.py --input-file sample_serpapi.json   # offline test
```

| Flag           | Default                          | Description                              |
|----------------|----------------------------------|------------------------------------------|
| `--min-gb`     | `500`                            | Minimum capacity in GB                   |
| `--max-gb`     | `8000`                           | Maximum capacity in GB                   |
| `--max-price`  | _(none)_                         | Optional max price in USD                |
| `--brands`     | Samsung, SanDisk, WD, Crucial, Seagate, Kingston, SK Hynix, Sabrent, Lexar, ADATA, Corsair | Reputable-brand allow-list |
| `--retailers`  | Amazon, Best Buy, Walmart, Newegg, B&H, Target, Costco, Micro Center, Dell, … | Trusted-retailer allow-list |
| `--api-key`    | `$SERPAPI_API_KEY`               | SerpAPI key                              |
| `--input-file` | _(none)_                         | Parse a saved SerpAPI JSON response      |
| `--output`     | `results.json`                   | Where to save JSON results               |

## Reliability features

- **In-stock only.** Google Shopping surfaces live offers; anything flagged
  out of stock is dropped.
- **No bad links.** Every result must have a valid `http(s)` buy link;
  direct merchant URLs are preferred over Google redirects.
- **Reputable brands + trusted retailers only.** Off-brand drives and
  no-name marketplace sellers are filtered out.
- **Self-diagnosing.** If nothing matches, it prints how many items were
  dropped at each stage (not SSD, not external, wrong capacity, untrusted
  retailer, off-brand, out of stock, no price, over price, bad link).

## Offline testing

`sample_serpapi.json` mirrors SerpAPI's real response structure and is used
to test the filtering logic without an API key:

```
python3 crawler.py --input-file sample_serpapi.json
```
