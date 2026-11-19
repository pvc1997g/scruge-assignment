"""Score a matcher offline on saved pools against hand labels (eval/labels.jsonl).

  pair precision  of the listings the matcher accepts, how many are truly the same product
  pair recall     of the truly-same listings, how many it accepts
  link accuracy   per link and store, the app's final answer (run through the real check_platform on the
                  saved pool) is a truly-same listing, or Not listed when the pool has none

usage: .venv/bin/python scripts/evaluate.py --set dev|test|review|all --matcher v1|v2 [-v]
"""

import argparse
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import service  # noqa: E402
from app.normalize import brands_match  # noqa: E402
from eval import pools  # noqa: E402

EVAL = os.path.join(os.path.dirname(__file__), "..", "eval")


def load_labels() -> dict:
    """(asin, platform, url) -> 'same' | 'different' | 'unsure'"""
    out = {}
    path = os.path.join(EVAL, "labels.jsonl")
    if os.path.exists(path):
        for line in open(path):
            if line.strip():
                d = json.loads(line)
                out[(d["asin"], d["platform"], d["url"])] = d["label"]
    return out


def get_matcher(name: str):
    if name == "v1":
        from app.matcher import match
        return match
    if name == "v2-hard":
        # M6 check: v2's identifiers and hard rules only; everything that isn't rejected is accepted.
        from app.match2.engine import features
        from app.models import MatchVerdict

        def hard_only(src, cand):
            rejection, _, reasons = features(src, cand, src.category)
            return MatchVerdict(rejection is None, 0.0 if rejection else 0.5, reasons + ([rejection] if rejection else []))
        return hard_only
    from app.match2 import match  # noqa: F401  (v2, built in milestones M5-M8)
    return match


def run(asins: list[str], matcher, labels: dict, verbose: bool):
    original = service.match
    service.match = matcher
    pair = defaultdict(lambda: defaultdict(int))  # cat -> tp/fp/fn/tn/unlabelled_accepts
    link = defaultdict(lambda: defaultdict(int))  # cat -> right/total
    problems = []
    try:
        for asin in asins:
            pool = pools.load(asin)
            src = pools.from_dict(pool["source"])
            cat = src.category.value
            for platform, pp in pool["platforms"].items():
                cands = pools.all_candidates(pp)
                same_urls = {u for u in cands if labels.get((asin, platform, u)) == "same"}
                unsure_urls = {u for u in cands if labels.get((asin, platform, u)) == "unsure"}
                for url, c in cands.items():
                    lab = labels.get((asin, platform, url))
                    if lab is None and not (brands_match(src.brand, c.brand)
                                            or brands_match(src.brand, c.title.split()[0] if c.title else "")):
                        lab = "different"  # other brands aren't labelled by hand
                    if lab == "unsure":
                        continue
                    v = matcher(src, c)
                    if lab is None:
                        if v.is_match:
                            pair[cat]["unlabelled_accepts"] += 1
                            problems.append(f"UNLABELLED ACCEPT {asin} {platform} {c.title[:70]} {url}")
                        continue
                    truth = lab == "same"
                    key = {(True, True): "tp", (False, True): "fp", (True, False): "fn", (False, False): "tn"}[(truth, v.is_match)]
                    pair[cat][key] += 1
                    if key == "fp":
                        problems.append(f"WRONG ACCEPT {asin} {platform} {c.title[:70]} | {v.reasons[-1][:90]}")
                    elif key == "fn":
                        problems.append(f"MISSED       {asin} {platform} {c.title[:70]} | {v.reasons[-1][:90]}")
                # The whole per-store check, as the app runs it, on the saved pool.
                adapter = pools.ReplayAdapter(pp)
                real = service.ADAPTERS[platform]
                service.ADAPTERS[platform] = adapter
                try:
                    res = service.check_platform(pools.from_dict(pool["source"]), platform)
                finally:
                    service.ADAPTERS[platform] = real
                # With a confirmed same listing, the answer must be one. Without one, Not listed is right, and so
                # is a listing we couldn't decide either way (several near-identical garments, no style code).
                if same_urls:
                    right = res.url in same_urls
                else:
                    right = res.url is None or res.url in unsure_urls
                link[cat]["total"] += 1
                link[cat]["right"] += right
                if not right:
                    want = next(iter(same_urls), None)
                    problems.append(f"LINK WRONG   {asin} {platform} answered {res.status.value} "
                                    f"{(res.title or '')[:60]} | expected {cands[want].title[:60] if want else 'not listed'}")
    finally:
        service.match = original
    return pair, link, problems


def report(pair, link, problems, verbose: bool):
    print(f"{'category':12} {'precision':>9} {'recall':>7} {'links right':>12}   tp  fp  fn  unlabelled-accepts")
    tot = defaultdict(int)
    for cat in sorted(set(pair) | set(link)):
        p, l = pair[cat], link[cat]
        for k in ("tp", "fp", "fn", "unlabelled_accepts"):
            tot[k] += p[k]
        tot["right"] += l["right"]
        tot["total"] += l["total"]
        _line(cat, p, l)
    _line("ALL", tot, tot)
    if verbose:
        print()
        for line in sorted(problems):
            print(line)


def _line(name, p, l):
    prec = p["tp"] / (p["tp"] + p["fp"]) if p["tp"] + p["fp"] else float("nan")
    rec = p["tp"] / (p["tp"] + p["fn"]) if p["tp"] + p["fn"] else float("nan")
    print(f"{name:12} {prec:9.1%} {rec:7.1%} {l['right']:>5}/{l['total']:<6}   {p['tp']:3} {p['fp']:3} {p['fn']:3}  {p['unlabelled_accepts']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="dev", help="a split name from eval/splits.json (dev, test2, review, ...) or 'all'")
    ap.add_argument("--matcher", default="v1", choices=["v1", "v2", "v2-hard"])
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    splits = json.load(open(os.path.join(EVAL, "splits.json")))
    lists = {k: v for k, v in splits.items() if isinstance(v, list)}
    asins = sorted(set().union(*lists.values())) if a.set == "all" else lists[a.set]
    asins = [x for x in asins if os.path.exists(pools.pool_path(x))]
    print(f"{a.matcher} on {a.set}: {len(asins)} links\n")
    report(*run(asins, get_matcher(a.matcher), load_labels(), a.verbose), verbose=a.verbose)


if __name__ == "__main__":
    main()
