"""How much a word says about *which* product it is, measured on each category's catalogue.

background.json holds, per category, how many listings mention each name word (document frequency), counted
over the dev pools only (scripts/build_background.py). A word on most listings ("leather", "running", "galaxy",
"slim") says little; a word on few ("malden", "easyon", "s24", "essential") names a specific product.

Rarity is measured across the whole category, not within one search's results: every listing a search returns
contains the searched words, so inside a pool the model's own name would look common.
"""

from __future__ import annotations

import json
import math
import os
from functools import lru_cache

PATH = os.path.join(os.path.dirname(__file__), "background.json")


@lru_cache(maxsize=1)
def _table() -> dict:
    if not os.path.exists(PATH):
        return {}
    with open(PATH) as f:
        return json.load(f)


def rarity(word: str, category: str) -> float:
    """0 (on every listing) .. 1 (never seen). Smoothed inverse document frequency, scaled to 0..1."""
    t = _table().get(category)
    if not t:
        return 1.0
    n = t["_n"]
    df = t["df"].get(word, 0)
    return math.log((n + 1) / (df + 1)) / math.log(n + 1)
