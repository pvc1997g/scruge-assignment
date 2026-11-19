"""Build app/match2/background.json: per category, how many distinct product names use each word.

Counted over the dev pools only (eval/splits.json), so test links never shape the matcher.
usage: .venv/bin/python scripts/build_background.py
"""

import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.match2 import rarity  # noqa: E402
from app.match2.facts import extract  # noqa: E402
from eval import pools  # noqa: E402

EVAL = os.path.join(os.path.dirname(__file__), "..", "eval")


def main():
    dev = json.load(open(os.path.join(EVAL, "splits.json")))["dev"]
    df: dict[str, Counter] = defaultdict(Counter)
    n: Counter = Counter()
    seen: dict[str, set] = defaultdict(set)
    names_seen: dict[str, set] = defaultdict(set)
    for asin in dev:
        if not os.path.exists(pools.pool_path(asin)):
            continue
        pool = pools.load(asin)
        src = pools.from_dict(pool["source"])
        cat = src.category
        for pp in pool["platforms"].values():
            for url, c in pools.all_candidates(pp).items():
                if url in seen[cat.value]:
                    continue  # the same listing found for two Amazon products counts once
                seen[cat.value].add(url)
                # Each distinct product name counts once: forty colourways and sellers of one "574 Legacy"
                # would otherwise make "legacy" look like a common describing word.
                name = frozenset(extract(c, cat).name)
                key = (c.brand or "").lower(), name
                if not name or key in names_seen[cat.value]:
                    continue
                names_seen[cat.value].add(key)
                n[cat.value] += 1
                df[cat.value].update(name)
    out = {cat: {"_n": n[cat], "df": dict(df[cat].most_common())} for cat in df}
    with open(rarity.PATH, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    for cat, t in out.items():
        print(f"{cat:11} {t['_n']:5} listings, {len(t['df']):5} words")


if __name__ == "__main__":
    main()
