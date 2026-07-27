# wd-feed-cache

Public cache of the WaistDear supplier feed (SKU + availability only) for the Orlando
Modal stock sync. WaistDear hard-rate-limits Modal's datacenter egress IP, so a GitHub
Actions cron here (a non-banned IP) fetches the feed every 30 min and force-pushes a
reduced snapshot to the **`cache`** branch:

    https://raw.githubusercontent.com/AnandaTom/wd-feed-cache/cache/wd_feed_cache.json

Shape: `{"fetched_at": ISO8601, "count": N, "products": [{"handle", "variants":[{"sku","available"}]}]}`

Non-sensitive: derived from WaistDear's public storefront `products.json`. No credentials.
