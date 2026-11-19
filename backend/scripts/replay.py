"""Re-run the app's per-store check on saved pools (no network) and compare with the recorded live answer.

usage: .venv/bin/python scripts/replay.py [ASIN ...]     (default: every saved pool)
"""

import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import service  # noqa: E402
from eval import pools  # noqa: E402


def replay(pool: dict, platform: str):
    """The app's own check_platform, fed from the pool instead of the store."""
    adapter = pools.ReplayAdapter(pool["platforms"][platform])
    real = service.ADAPTERS[platform]
    service.ADAPTERS[platform] = adapter
    try:
        return service.check_platform(pools.from_dict(pool["source"]), platform), adapter
    finally:
        service.ADAPTERS[platform] = real


def main():
    asins = sys.argv[1:] or sorted(os.path.basename(p).split(".")[0] for p in glob.glob(os.path.join(pools.POOL_DIR, "*.json.gz")))
    same = total = 0
    for asin in asins:
        pool = pools.load(asin)
        for platform, pp in pool["platforms"].items():
            res, ad = replay(pool, platform)
            live = pp["live"]
            ok = (res.status.value, res.url) == (live["status"], live["url"])
            same += ok
            total += 1
            if not ok or ad.missing_pages or ad.missing_searches:
                print(f"{'SAME' if ok else 'DIFF'} {asin} {platform:8} live={live['status']} {str(live['url'])[-45:]}")
                print(f"     replay={res.status.value} {str(res.url)[-45:]}  missing pages={len(ad.missing_pages)} searches={len(ad.missing_searches)}")
    print(f"\nreplay matches live on {same}/{total} link-store pairs ({same / max(total, 1):.0%})")


if __name__ == "__main__":
    main()
