#!/usr/bin/env python3
"""Fetch supplier feeds (WaistDear + VRActive) and write reduced cache JSONs for the
Modal Orlando stock sync.

Both suppliers hard-rate-limit Modal's datacenter egress IP (429 local_rate_limited).
This runs from a NON-banned IP (GitHub Actions cron) and publishes one cache file per
supplier to the `cache` branch; Modal reads them from raw.githubusercontent.

Output shape per file is the CONTRACT consumed by app._fetch_supplier_cache():
  {"fetched_at": ISO8601, "count": N, "products": [{"handle", "variants":[{"sku","available"}]}]}
Only the fields Modal's feed path consumes are kept (handle + variant sku/available,
order preserved for the scraper's positional match).

ALL-OR-NOTHING publish: if ANY supplier is below its floor (blocked/partial fetch),
NOTHING is written and the script exits non-zero, so the workflow skips the publish
step and the last-good cache on the `cache` branch is preserved (never publish a
catalog-zeroing snapshot).
"""
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

MAX_PAGES = 50

SUPPLIERS = [
    {"key": "waistdear",
     "base": "https://www.waistdear.com/collections/all/products.json?limit=250",
     "min": 150, "out": "wd_feed_cache.json"},
    {"key": "vractive",
     "base": "https://www.vractivewholesale.com/products.json?limit=250",
     "min": 40, "out": "vr_feed_cache.json"},
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none", "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


def _get_page(base: str, page: int) -> list:
    req = urllib.request.Request(f"{base}&page={page}", headers=HEADERS)
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
            if attempt < 3:
                print(f"  transient error ({type(e).__name__}); retry", file=sys.stderr)
                time.sleep(5)
                continue
            raise
    return []


def _fetch_supplier(base: str) -> list:
    products: list = []
    page = 1
    while page <= MAX_PAGES:
        batch = _get_page(base, page)
        products.extend(batch)
        if len(batch) < 250:
            break
        page += 1
    return [
        {
            "handle": p.get("handle"),
            "variants": [
                {"sku": v.get("sku"), "available": bool(v.get("available", False))}
                for v in p.get("variants", [])
            ],
        }
        for p in products
    ]


def main() -> int:
    built = []  # (out_path, payload)
    for s in SUPPLIERS:
        try:
            reduced = _fetch_supplier(s["base"])
        except Exception as e:
            print(f"ERROR: {s['key']} fetch failed ({type(e).__name__}: {e})", file=sys.stderr)
            return 1
        if len(reduced) < s["min"]:
            print(f"ERROR: {s['key']} only {len(reduced)} products (< {s['min']}); "
                  f"NOT publishing (last-good preserved)", file=sys.stderr)
            return 1
        avail = sum(1 for p in reduced for v in p["variants"] if v["available"])
        total = sum(len(p["variants"]) for p in reduced)
        if total and (avail / total) < 0.05:
            print(f"ERROR: {s['key']} availability implausibly low: {avail}/{total} < 5% "
                  f"(suspected feed-shape bug); NOT publishing (last-good preserved)", file=sys.stderr)
            return 1
        payload = {"fetched_at": datetime.now(timezone.utc).isoformat(),
                   "count": len(reduced), "products": reduced}
        built.append((s["out"], payload))
        print(f"{s['key']}: {len(reduced)} products, {total} variants, {avail} available")

    # Every supplier passed its floor -> write all files (only after all validated).
    for out_path, payload in built:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, separators=(",", ":"))
        print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
