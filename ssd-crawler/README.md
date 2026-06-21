# SSD Deal Finder

Finds 1TB external SSDs under a price cap from well-known brands, using the
[Best Buy Products API](https://developer.bestbuy.com/) (no scraping — stays
within the retailer's terms of service).

## Setup

1. Get a free API key at https://developer.bestbuy.com/ (instant signup, no
   approval wait — unlike Amazon's Product Advertising API).
2. Set it as an environment variable:
   ```
   export BESTBUY_API_KEY=your_key_here
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
| `--max-price` | `70`                                                 | Maximum price in USD              |
| `--brands`    | `Samsung,SanDisk,WD,Western Digital,Crucial,Seagate,Kingston` | Comma-separated brand allow-list  |
| `--api-key`   | `$BESTBUY_API_KEY`                                   | Best Buy API key                  |
| `--output`    | `results.json`                                       | Where to save JSON results        |

## Notes

- Only covers Best Buy's catalog. Extending to other retailers (Amazon,
  Newegg, B&H) would require their own APIs/credentials, since direct HTML
  scraping of major retail sites generally violates their terms of service.
- Results are filtered post-query by name matching (`1TB`, `SSD`,
  `external`/`portable`) since the API's free-text search isn't exact.
