"""Train v2's scoring (M8): one small logistic regression per category, on dev pairs only.

Only pairs that survive v2's hard rules are used (the model never sees a pair the rules already reject).
The decision threshold is picked by grouped cross-validation (folds split by Amazon link, so the same product
never sits on both sides): the threshold with the best out-of-fold F0.5 (precision weighted twice).
Writes app/match2/weights.json. Plain Python; no new dependencies.

usage: .venv/bin/python scripts/train_v2.py
"""

import json
import math
import os
import random
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.match2.engine import FEATURES, WEIGHTS_PATH, features  # noqa: E402
from eval import pools  # noqa: E402

EVAL = os.path.join(os.path.dirname(__file__), "..", "eval")
L2 = 0.01
MIN_NEGATIVES = 20
FOLDS = 5


def load_labels() -> dict:
    out = {}
    for line in open(os.path.join(EVAL, "labels.jsonl")):
        if line.strip():
            d = json.loads(line)
            out[(d["asin"], d["platform"], d["url"])] = d["label"]
    return out


def dataset():
    """category -> list of (asin, x vector, y)"""
    labels = load_labels()
    dev = json.load(open(os.path.join(EVAL, "splits.json")))["dev"]
    data = defaultdict(list)
    seen = defaultdict(set)
    for asin in dev:
        if not os.path.exists(pools.pool_path(asin)):
            continue
        pool = pools.load(asin)
        src = pools.from_dict(pool["source"])
        for platform, pp in pool["platforms"].items():
            for url, cand in pools.all_candidates(pp).items():
                lab = labels.get((asin, platform, url))
                if lab not in ("same", "different"):
                    continue
                rejection, x, _ = features(src, cand, src.category)
                if rejection:
                    continue
                row = (asin, tuple(round(x[f], 4) for f in FEATURES), 1 if lab == "same" else 0)
                # Within one Amazon product, listings with identical evidence (fourteen "Unisex 574 Casual Shoes",
                # a listing's sizes and sellers) count once: copies add weight, not information.
                if row not in seen[src.category.value]:
                    seen[src.category.value].add(row)
                    data[src.category.value].append((asin, list(row[1]), row[2]))
    return data


def _solve(a, b):
    """Gaussian elimination with partial pivoting: solve a x = b."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(m[r][c]))
        m[c], m[piv] = m[piv], m[c]
        if abs(m[c][c]) < 1e-12:
            continue
        for r in range(n):
            if r != c:
                f = m[r][c] / m[c][c]
                m[r] = [x - f * y for x, y in zip(m[r], m[c])]
    return [m[i][n] / m[i][i] if abs(m[i][i]) > 1e-12 else 0.0 for i in range(n)]


def fit(rows, iters=25, l2=L2):
    """L2-regularised logistic regression by Newton's method (IRLS), with balanced class weights.
    rows: [(x, y)]. Returns (weights, bias)."""
    n = len(FEATURES) + 1                      # last coefficient is the bias
    beta = [0.0] * n
    pos = sum(y for _, y in rows) or 1
    neg = (len(rows) - pos) or 1
    cw = {1: len(rows) / (2 * pos), 0: len(rows) / (2 * neg)}
    xs = [list(x) + [1.0] for x, _ in rows]
    for _ in range(iters):
        grad = [0.0] * n
        hess = [[0.0] * n for _ in range(n)]
        for xi, (_, y) in zip(xs, rows):
            z = sum(b * v for b, v in zip(beta, xi))
            p = 1 / (1 + math.exp(-max(-30, min(30, z))))
            wgt = cw[y]
            g = (p - y) * wgt
            h = p * (1 - p) * wgt
            for i in range(n):
                grad[i] += g * xi[i]
                hi = h * xi[i]
                for j in range(i, n):
                    hess[i][j] += hi * xi[j]
        for i in range(n):
            for j in range(i):
                hess[i][j] = hess[j][i]
            if i < n - 1:                      # don't shrink the bias
                grad[i] += l2 * len(rows) * beta[i]
                hess[i][i] += l2 * len(rows)
            hess[i][i] += 1e-6
        step = _solve(hess, grad)
        beta = [b - s for b, s in zip(beta, step)]
        if max(abs(s) for s in step) < 1e-6:
            break
    return beta[:-1], beta[-1]


def predict(w, b, x):
    z = b + sum(wi * xi for wi, xi in zip(w, x))
    return 1 / (1 + math.exp(-max(-30, min(30, z))))


def pick_threshold(scored, beta=0.5):
    """Threshold with the best out-of-fold F-beta (beta 0.5: precision counts twice as much as recall).
    A fixed precision target fails where some different products look identical to the features
    (two colourways the listings don't tell apart); F-beta still prefers precision without that cliff."""
    best_t, best_f = 0.5, -1.0
    for t in sorted({round(p, 3) for p, _ in scored}):
        tp = sum(y for p, y in scored if p >= t)
        fp = sum(1 - y for p, y in scored if p >= t)
        fn = sum(y for p, y in scored if p < t)
        if tp == 0:
            continue
        prec, rec = tp / (tp + fp), tp / (tp + fn)
        f = (1 + beta ** 2) * prec * rec / (beta ** 2 * prec + rec)
        if f > best_f:
            best_t, best_f = t, f
    return min(max(best_t, 0.3), 0.95)


def main():
    data = dataset()
    out = {}
    for cat, rows in sorted(data.items()):
        asins = sorted({a for a, _, _ in rows})
        random.Random(1).shuffle(asins)
        fold_of = {a: i % FOLDS for i, a in enumerate(asins)}
        scored = []
        for k in range(FOLDS):
            train = [(x, y) for a, x, y in rows if fold_of[a] != k]
            test = [(x, y) for a, x, y in rows if fold_of[a] == k]
            if not train or not test or len({y for _, y in train}) < 2:
                continue
            neg_train = sum(1 - y for _, y in train)
            w, b = fit(train, l2=L2 * max(1.0, MIN_NEGATIVES / max(neg_train, 1)))
            scored += [(predict(w, b, x), y) for x, y in test]
        negatives = sum(1 - y for _, y in scored)
        # With only a handful of different-product pairs left after the hard rules, a fitted threshold is noise;
        # 0.5 is the natural cut for a class-balanced model.
        threshold = pick_threshold(scored) if negatives >= MIN_NEGATIVES else 0.5
        acc = [(p, y) for p, y in scored if p >= threshold]
        tp = sum(y for _, y in acc)
        pos = sum(y for _, y in scored)
        # Fewer different-product pairs than MIN_NEGATIVES: shrink the weights harder, so a handful of examples
        # can't teach that one missing umbrella word ("Galaxy") outweighs an exact model number.
        l2 = L2 * max(1.0, MIN_NEGATIVES / max(negatives, 1))
        w, b = fit([(x, y) for _, x, y in rows], l2=l2)
        out[cat] = {"weights": {"bias": round(b, 4), **{f: round(v, 4) for f, v in zip(FEATURES, w)}},
                    "threshold": threshold, "trained_on": len(rows)}
        print(f"{cat:11} pairs={len(rows):4} same={pos:3}  cv precision={tp / max(len(acc), 1):.1%} "
              f"recall={tp / max(pos, 1):.1%}  threshold={threshold}")
        print("            " + "  ".join(f"{k}={v:+.2f}" for k, v in out[cat]["weights"].items()))
    with open(WEIGHTS_PATH, "w") as f:
        json.dump(out, f, indent=1)


if __name__ == "__main__":
    main()
