"""Run the matcher on one or more Amazon links from the terminal.

usage: .venv/bin/python scripts/try_link.py <amazon-url> [<amazon-url> ...]
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.service import compare  # noqa: E402

ICON = {"in_stock": "●", "out_of_stock": "◐", "not_listed": "○"}

for url in sys.argv[1:]:
    try:
        res = compare(url, use_cache=False)
    except Exception as e:
        print(f"\n!! {url}\n   {type(e).__name__}: {e}")
        continue
    s = res["source"]
    print(f"\n=== {s['title'][:100]}")
    print(f"    {s['category']} | brand={s['brand']} | colour={s['colour']} | ram={s['ram_gb']} | storage={s['storage_gb']} "
          f"| screen={s['screen_in']} | model#={s['model_number']} | gender={s['gender']}  ({res['elapsed_ms']} ms)")
    for r in res["results"]:
        print(f"  {ICON[r['status']]} {r['platform']:9} {r['status']:13} conf={r['confidence']}  q='{r['query']}'  checked={r['candidates_checked']}")
        if r["title"]:
            print(f"      {r['title'][:100]}")
            print(f"      {r['url']}")
        for why in r["reasons"][:5]:
            print(f"      - {why}")
        if r.get("note"):
            print(f"      NOTE: {r['note']}")
        if r["error"]:
            print(f"      (site error: {r['error']})")
    if os.environ.get("JSON"):
        print(json.dumps(res, indent=1)[:3000])
