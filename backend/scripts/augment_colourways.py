"""Round 3 (C1): add Myntra colourway data to saved pools, without re-recording them.

For every Myntra listing in a shoe or clothing pool that either matcher accepts once colour is set aside, re-open
its page and store only its colourway list; then save the pages of the siblings whose colour fits Amazon's, under a
pseudo-search "__colourways__" so they can be labelled and replayed like any listing.

usage: .venv/bin/python scripts/augment_colourways.py [ASIN ...]   (default: every pool)
"""

import glob
import os
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import http, match2  # noqa: E402
from app import matcher as matcher_v1  # noqa: E402
from app.models import Category, Listing  # noqa: E402
from app.normalize import colours_match  # noqa: E402
from app.sources import myntra  # noqa: E402
from eval import pools  # noqa: E402

KEY = "__colourways__"


def model_matches(src, c) -> bool:
    probe = Listing(**{**c.__dict__, "colour": src.colour, "extra": {**c.extra, "brand_colour": None}})
    return match2.match(src, probe).is_match or matcher_v1.match(src, probe).is_match


def fetch(url):
    item = Listing(platform="myntra", title="", url=url)
    try:
        myntra.enrich(item)
    except http.FetchError:
        return None
    return item if item.title else None


def augment(asin: str) -> str:
    if not os.path.exists(pools.pool_path(asin)):
        return f"{asin} no pool saved, skipped"
    pool = pools.load(asin)
    src = pools.from_dict(pool["source"])
    pp = pool["platforms"].get("myntra")
    if not pp or src.category not in (Category.SNEAKERS, Category.APPAREL):
        return ""
    if KEY in pp["searches"]:
        return f"{asin} already done"
    cands = pools.all_candidates(pp)
    parents = [u for u, c in cands.items() if u in pp["pages"] and model_matches(src, c)]
    with ThreadPoolExecutor(4) as ex:
        fresh = dict(zip(parents, ex.map(fetch, parents)))
    wanted = []
    for u, item in fresh.items():
        if not item:
            continue
        pp["pages"][u].setdefault("extra", {})["colourways"] = item.extra.get("colourways", [])
        for w in item.extra.get("colourways", []):
            if w["url"] not in cands and w["url"] not in wanted and colours_match(src.colour, w["label"])[0] is not False:
                wanted.append(w["url"])
    with ThreadPoolExecutor(4) as ex:
        sibs = [s for s in ex.map(fetch, wanted) if s]
    for s in sibs:
        pp["pages"][s.url] = pools.to_dict(s)
    pp["searches"][KEY] = [pools.to_dict(Listing(platform="myntra", title=s.title, url=s.url, brand=s.brand,
                                                  colour=s.colour, gender=s.gender)) for s in sibs]
    pools.save(asin, pool)
    return f"{asin} {src.category.value:9} parents={len(parents)} siblings={len(sibs)}"


def main():
    asins = sys.argv[1:] or sorted(os.path.basename(p).split(".")[0] for p in glob.glob(os.path.join(pools.POOL_DIR, "*.json.gz")))
    for a in asins:
        line = augment(a)
        if line:
            print(line, flush=True)


if __name__ == "__main__":
    main()
