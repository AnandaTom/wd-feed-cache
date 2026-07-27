#!/usr/bin/env python3
"""Fetch the WaistDear feed and write a reduced cache JSON for the Modal sync.

WaistDear hard-rate-limits Modal's datacenter egress IP (429 local_rate_limited,
verified 2026-07-24). This runs from a NON-banned IP (GitHub Actions cron, see
.github/workflows/wd-feed-cache.yml) and publishes the cache to the `wd-feed-cache`
branch; Modal reads it from raw.githubusercontent instead of hitting waistdear.com.

Output shape is the CONTRACT consumed by app._fetch_waistdear_cache():
  {"fetched_at": ISO8601, "count": N, "products": [{"handle", "variants":[{"sku","available"}]}]}
Only the fields Modal's WaistDear feed path consumes are kept (handle + variant
sku/available, order preserved for the scraper's positional match).

Exits non-zero (does NOT overwrite the cache) if the feed is below MIN_PRODUCTS, so
a partial/blocked fetch can never publish a catalog-zeroing snapshot.
"""
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

BASE = "https://www.waistdear.com/collections/all/products.json?limit=250"
MIN_PRODUCTS = 150
MAX_PAGES = 50
OUT_PATH = "wd_feed_cache.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none", "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


def _get_page(page: int) -> list:
    req = urllib.request.Request(f"{BASE}&page={page}", headers=HEADERS)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read()).get("products", [])
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < 3:
                try:
                    wait = min(max(int(e.headers.get("Retry-After") or 5), 0), 30)
                except (ValueError, TypeError):
                    wait = 5
                time.sleep(wait or 5)
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            # DNS / connection reset / socket timeout are transient; retry, else fail
            # the run (build_wd_cache only writes on success, so no bad cache ships).
            if attempt < 3:
                print(f"  transient error page {page} ({type(e).__name__}); retry", file=sys.stderr)
                time.sleep(5)
                continue
            raise
    return []


def main() -> int:
    products: list = []
    page = 1
    while page <= MAX_PAGES:
        batch = _get_page(page)
        products.extend(batch)
        if len(batch) < 250:
            break
        page += 1

    reduced = [
        {
            "handle": p.get("handle"),
            "variants": [
                {"sku": v.get("sku"), "available": bool(v.get("available", False))}
                for v in p.get("variants", [])
            ],
        }
        for p in products
    ]

    if len(reduced) < MIN_PRODUCTS:
        print(f"ERROR: only {len(reduced)} products (< {MIN_PRODUCTS}); NOT writing cache",
              file=sys.stderr)
        return 1

    out = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "count": len(reduced),
        "products": reduced,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    avail = sum(1 for p in reduced for v in p["variants"] if v["available"])
    total = sum(len(p["variants"]) for p in reduced)
    print(f"wrote {OUT_PATH}: {len(reduced)} products, {total} variants, {avail} available")
    return 0


if __name__ == "__main__":
    sys.exit(main())
