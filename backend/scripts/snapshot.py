"""Save candidate pools for Amazon links (see eval/pools.py), so matchers can be scored offline.

For each link: run v1 live through recording adapters (that's the 'live' answer), then run any of v1's
queries it skipped, and open the product page of every same-brand listing (up to EXTRA_PAGES per store).

usage: .venv/bin/python scripts/snapshot.py scripts/test_links.txt [more files or links] [--force]
"""

import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import http, service  # noqa: E402
from app.models import PLATFORMS_BY_CATEGORY  # noqa: E402
from app.normalize import brands_match  # noqa: E402
from app.sources import amazon  # noqa: E402
from eval import pools  # noqa: E402

EXTRA_PAGES = 25
REAL = dict(service.ADAPTERS)


def links_from(args: list[str]) -> list[str]:
    out = []
    for a in args:
        if a.startswith("http"):
            out.append(a)
        elif os.path.isfile(a):
            for line in open(a):
                m = re.match(r"\s*(https?://\S+)", line)
                if m:
                    out.append(m.group(1))
    return out


def same_brand(src, c) -> bool:
    return brands_match(src.brand, c.brand) or brands_match(src.brand, c.title.split()[0] if c.title else "")


def record_platform(src, platform: str) -> dict:
    rec = pools.RecordingAdapter(REAL[platform])
    service.ADAPTERS[platform] = rec
    try:
        live = service.check_platform(src, platform)
    finally:
        service.ADAPTERS[platform] = REAL[platform]
    for q in service.build_queries(src, platform):
        if q not in rec.searches:
            try:
                rec.search(q)
            except http.FetchError:
                pass
    cands = pools.all_candidates({"searches": rec.searches, "pages": rec.pages})
    todo = [c for url, c in cands.items() if url not in rec.pages and same_brand(src, c)][:EXTRA_PAGES]

    def open_page(c):
        try:
            rec.enrich(c)
        except http.FetchError:
            pass

    with ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(open_page, todo))
    return {
        "searches": rec.searches,
        "pages": rec.pages,
        "live": {"status": live.status.value, "url": live.url, "title": live.title, "error": live.error},
    }


def main():
    force = "--force" in sys.argv
    links = links_from([a for a in sys.argv[1:] if a != "--force"])
    for i, url in enumerate(links, 1):
        asin = amazon.resolve_asin(url)
        if os.path.exists(pools.pool_path(asin)) and not force:
            print(f"[{i}/{len(links)}] {asin} already saved")
            continue
        t0 = time.time()
        src = None
        for attempt in range(2):
            try:
                src = amazon.fetch_product(url)
                break
            except Exception as e:
                print(f"[{i}/{len(links)}] {asin} Amazon failed ({type(e).__name__}: {e})")
                http.reset_session("amazon")
                time.sleep(2)
        if src is None:
            continue
        platforms = PLATFORMS_BY_CATEGORY[src.category]
        with ThreadPoolExecutor(max_workers=2) as ex:
            recorded = dict(zip(platforms, ex.map(lambda p: record_platform(src, p), platforms)))
        pools.save(asin, {"asin": asin, "url": url, "recorded": time.strftime("%Y-%m-%d %H:%M"),
                          "source": pools.to_dict(src), "platforms": recorded})
        summary = "  ".join(f"{p}: {r['live']['status']} ({len(pools.all_candidates(r))} listings, "
                            f"{len(r['pages'])} pages)" for p, r in recorded.items())
        print(f"[{i}/{len(links)}] {asin} {src.category.value:10} {time.time() - t0:4.0f}s  {summary}")


if __name__ == "__main__":
    main()
