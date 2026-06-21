# SSD Best-Value Finder

Finds the best-value external SSDs from **500GB to 8TB** across well-known
brands by scraping Newegg's public search results. No API key required.

For each capacity tier it runs a search, parses every listing, and ranks
results by **price-per-terabyte** — so you see genuine best value, not just
the lowest sticker price.

## Setup

```
pip3 install -r requirements.txt
```

## Usage

```
python3 crawler.py                       # live: all tiers, no price cap
python3 crawler.py --max-price 200       # only show deals at/under $200
python3 crawler.py --min-gb 1000 --max-gb 4000
python3 crawler.py --brands Samsung,Crucial
python3 crawler.py --html-file saved.html   # offline: parse a saved page
```

| Flag          | Default                                              | Description                          |
|---------------|------------------------------------------------------|--------------------------------------|
| `--min-gb`    | `500`                                                | Minimum capacity in GB               |
| `--max-gb`    | `8000`                                               | Maximum capacity in GB               |
| `--max-price` | _(none)_                                             | Optional max price in USD            |
| `--brands`    | `Samsung,SanDisk,WD,Western Digital,Crucial,Seagate,Kingston` | Comma-separated brand allow-list |
| `--html-file` | _(none)_                                             | Parse a saved page instead of fetching |
| `--output`    | `results.json`                                       | Where to save JSON results           |

## What makes this reliable

- **No bad links.** Every product URL is validated as a canonical Newegg
  product page (`https://www.newegg.com/.../p/<id>`) before it's shown.
  Anything that doesn't validate (relative links, ad slots, broken hrefs)
  is dropped.
- **Self-diagnosing.** If nothing matches, it prints exactly how many
  listings were dropped at each filter stage (not SSD, not external, wrong
  capacity, bad URL, no price, over price cap, brand mismatch). You never
  have to guess why a run came back empty:
  - `parsed = 0` → Newegg served a bot-check page instead of results.
  - `parsed` high but all dropped → loosen `--max-price` or `--brands`.
- **Robust parsing.** Brand is read from the product feature list, price
  handles both Newegg layouts, and capacity is parsed from the title and
  normalized to GB. Verified against live Newegg markup (2026-06-21).

## Offline testing

`sample_newegg_page.html` mirrors Newegg's real markup and is used to test
the parser without the network:

```
python3 crawler.py --html-file sample_newegg_page.html
```

## Notes

- Intended for light, personal use — it makes a handful of requests (one
  per capacity tier) and checks `robots.txt` first. Don't schedule it to
  run frequently or at scale; that would likely violate Newegg's terms.
- If Newegg changes its markup again, run with `--html-file` on a freshly
  saved page and check the diagnostic counts to see which selector in
  `parse_listings()` needs updating.
