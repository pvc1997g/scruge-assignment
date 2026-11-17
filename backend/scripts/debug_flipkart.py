"""Debug helper: search Flipkart, show parsed cards, and enrich the first N matching a brand."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.sources import flipkart  # noqa: E402

q, brand, n = sys.argv[1], sys.argv[2].lower(), int(sys.argv[3]) if len(sys.argv) > 3 else 2
items = flipkart.search(q)
print(len(items), "cards")
for it in items[:12]:
    print(f"  {it.title[:90]!r} brand={it.brand} ram={it.ram_gb} sto={it.storage_gb} scr={it.screen_in} avail={it.available}")
done = 0
for it in items:
    if done >= n:
        break
    if (it.brand or "").lower().startswith(brand):
        flipkart.enrich(it)
        print("\nENRICHED", it.title, it.url)
        print("  colour", it.colour, "brand", it.brand, "avail", it.available, it.extra.get("availability_status"))
        for k, v in it.extra.get("specs", {}).items():
            print(f"    {k}: {v}")
        done += 1
