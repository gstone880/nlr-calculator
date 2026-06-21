# SSD Deal Finder

Finds 1TB external SSDs under a price cap from well-known brands by
scraping Newegg's public search results page directly. No API key
required.

## Setup

```
pip install -r requirements.txt
```

## Usage

```
python crawler.py
```

Options:

```
python crawler.py --max-price 60 --brands Samsung,Crucial --output deals.json
```

| Flag          | Default                                            | Description                       |
|---------------|-----------------------------------------------------|-----------------------------------|
| `--query`     | `1tb external ssd`                                   | Search query sent to Newegg       |
| `--max-price` | `70`                                                 | Maximum price in USD              |
| `--brands`    | `Samsung,SanDisk,WD,Western Digital,Crucial,Seagate,Kingston` | Comma-separated brand allow-list  |
| `--html-file` | _(none)_                                             | Parse a locally saved page instead of fetching live (for offline debugging) |
| `--output`    | `results.json`                                       | Where to save JSON results        |

## How it works

- Checks `robots.txt` before every live request and refuses to scrape if
  it's disallowed or unreachable (fails closed).
- Parses listing cells for name, brand, and price, then filters to items
  whose name mentions `1TB`, `SSD`, and `external`/`portable`, whose price
  is at or under the cap, and whose brand is on the allow-list.
- Intended for light, manual use — you run it, it makes one request. Do
  **not** schedule this to run frequently or at scale; that would likely
  violate Newegg's terms of service. Scraping Amazon or other sites with
  strong anti-bot protections is out of scope for the same reason.

## Markup changes will break this

Newegg's HTML structure can change at any time, which will break the CSS
selectors in `parse_listings()`. `sample_newegg_page.html` is a synthetic
fixture (not real scraped content) used to test the parser offline:

```
python crawler.py --html-file sample_newegg_page.html
```

If a live run returns zero results, save a real search-results page
(`view-source` → save HTML) and run it through `--html-file` to see what
the parser is actually matching, then update the selectors in
`parse_listings()` to match the current markup.
