"""Compare two listings' Facts. The same steps for every category; the category only picks the schema table.

1. Identifiers first: the same manufacturer code settles identity; a clashing code of the same kind rejects.
2. Hard attributes from the schema: a conflict rejects; a required attribute that's unknown rejects.
3. Versions (8 vs 8 EasyOn, S24 vs S24 FE, 24/25 vs 25/26) must agree when the listing states any.
4. Everything else becomes evidence, weighted by word rarity, and a small learned model turns it into a score.
"""

from __future__ import annotations

import json
import math
import os
import re
from functools import lru_cache
from typing import Optional

from ..models import Category, Listing, MatchVerdict
from ..normalize import brands_match, codes_overlap
from .facts import Facts, extract
from .rarity import rarity
from .schema import SPECS, shades

WEIGHTS_PATH = os.path.join(os.path.dirname(__file__), "weights.json")

# Hand-set starting weights, replaced by weights.json once trained (scripts/train_v2.py).
DEFAULT_WEIGHTS = {
    "bias": 0.5, "ident_exact": 4.0, "ident_variant": 1.5, "ident_series": 1.0, "versions_unstated": -1.5,
    "missing_sum": -3.0, "missing_max": -2.0, "extra_sum": -1.0, "extra_max": -3.0, "shared_sum": 1.0,
    "colour_exact": 0.5, "soft_conflicts": -1.5, "soft_agree": 0.3, "no_name": -1.0,
    "name_exact": 1.0, "versions_match": 1.0,
}
FEATURES = list(DEFAULT_WEIGHTS)[1:]


@lru_cache(maxsize=1)
def _weights() -> dict:
    if os.path.exists(WEIGHTS_PATH):
        with open(WEIGHTS_PATH) as f:
            return json.load(f)
    return {}


def weights_for(category: Category) -> tuple[dict, float]:
    w = _weights().get(category.value)
    if w:
        return w["weights"], w["threshold"]
    return DEFAULT_WEIGHTS, 0.5


# ----------------------------------------------------------------------------- identifiers

_SIZED = re.compile(r"^[a-z]{0,3}(\d{2,3})[a-z]")
_YEAR = re.compile(r"\b(20[12]\d)\b")


def _code_shape(code: str) -> str:
    return re.sub(r"\d+", "9", re.sub(r"[a-z]+", "a", code))


def _one_letter_apart(a: str, b: str) -> bool:
    """One letter added, removed or changed, and no digit touched: K55S25M2 / K55S25BM2 / K55S25EM2."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diff = [(x, y) for x, y in zip(a, b) if x != y]
        return len(diff) == 1 and diff[0][0].isalpha() and diff[0][1].isalpha()
    short, long_ = sorted([a, b], key=len)
    for i, ch in enumerate(long_):
        if long_[:i] + long_[i + 1:] == short:
            return ch.isalpha()
    return False


def _tv_identifier(src: Listing, cand: Listing, sf: Facts, cf: Facts):
    """Full manufacturer codes carry the screen size (K55S25BM2, UA55UE85AHULXL)."""
    sized = lambda codes, screen: [c for c in codes if (m := _SIZED.match(c)) and screen and abs(int(m.group(1)) - screen) <= 1]
    a_full, b_full = sized(sf.codes, src.screen_in)[:1], sized(cf.codes, cand.screen_in)
    if a_full and b_full:
        a = a_full[0]
        for b in b_full:
            if a == b:
                return "exact", a.upper()
        for b in b_full:
            short, long_ = sorted([a, b], key=len)
            if long_.startswith(short) and not re.search(r"\d", long_[len(short):]):
                return "exact", f"{a.upper()} ~ {b.upper()} (region suffix)"
            years = set(_YEAR.findall(src.title)), set(_YEAR.findall(cand.title))
            one_letter = _one_letter_apart(a, b)
            if one_letter and not (years[0] and years[1] and not years[0] & years[1]) and not re.match(r"^[uq]a\d", a):
                return "variant", f"{a.upper()} vs {b.upper()} (one-letter sales variant)"
        return "conflict", f"{a.upper()} vs {b_full[0].upper()}"
    shared = codes_overlap(sf.codes, cf.codes)
    if shared:
        return "series", shared.upper()
    if sf.codes and cf.codes:
        return "conflict", f"{sf.codes[0].upper()} vs {cf.codes[0].upper()}"
    return None, None


def _style_identifier(src: Listing, cand: Listing, sf: Facts, cf: Facts):
    if not sf.codes:
        return None, None
    a = sf.codes[0]
    for b in cf.codes:
        if a == b:
            return "exact", a.upper()
        if len(a) >= 6 and len(b) >= 6 and (a.startswith(b) or b.startswith(a)):
            return "exact", f"{a.upper()} ~ {b.upper()} (colour suffix)"
        if len(a) >= 6 and len(b) >= 6 and _code_shape(a) == _code_shape(b):
            return "conflict", f"{a.upper()} vs {b.upper()}"
    # The code written in the listing's own text ("Style code: IU1397" in a description).
    hay = re.sub(r"[^a-z0-9]", "", " ".join(filter(None, [cand.title, cand.model_number, cand.extra.get("model_name"),
                                                          cand.extra.get("text")])).lower())
    if len(a) >= 6 and a in hay:
        return "exact", a.upper()
    return None, None


IDENTIFIERS = {"model_code": _tv_identifier, "style_code": _style_identifier}


# ----------------------------------------------------------------------------- comparison

def features(src: Listing, cand: Listing, category: Category) -> tuple[Optional[str], dict, list[str]]:
    """Returns (rejection or None, feature values, reasons)."""
    reasons: list[str] = []
    if not (brands_match(src.brand, cand.brand) or brands_match(src.brand, cand.title.split()[0] if cand.title else "")):
        return f"brand differs ({src.brand} vs {cand.brand})", {}, reasons
    reasons.append(f"brand {src.brand} matches")
    sf, cf = extract(src, category, is_source=True), extract(cand, category)
    cat = category.value

    spec = SPECS[category]
    ident, detail = IDENTIFIERS[spec.identifier](src, cand, sf, cf) if spec.identifier else (None, None)
    if ident == "conflict":
        return f"different model code ({detail})", {}, reasons
    if ident:
        reasons.append(f"model code {detail} matches" if ident == "exact" else f"model code {detail}")

    soft_conflicts, soft_agree = [], []
    for name, attr in spec.attrs.items():
        a, b = sf.attrs.get(name), cf.attrs.get(name)
        verdict = attr.compare(a, b)
        if name == "colour_family" and shades(sf.attrs.get("colour_name"), cf.attrs.get("colour_name")):
            verdict = True   # the store repeats the brand's own shade name ("DESERT KHAKI/DARK HAZEL-SAIL")
        if verdict is False:
            if attr.hard:
                return f"different {name} ({a} vs {b})", {}, reasons
            soft_conflicts.append(f"{name} {a} vs {b}")
        stated = a is not None or (name == "colour_family" and sf.attrs.get("colour_name"))
        listing_silent = b is None and not (name == "colour_family" and cf.attrs.get("colour_name"))
        if verdict is None and attr.need and ident != "exact" and stated and listing_silent:
            return f"{name} not stated on the listing (Amazon: {a or ' '.join(sorted(sf.attrs.get('colour_name') or []))})", {}, reasons
        elif verdict is None and attr.need and ident != "exact" and a is not None and b is None:
            # Required when Amazon states it. If Amazon's own value is unreadable ("COOL MATCHA"), it can't decide.
            return f"{name} not stated ({a} vs {b or '?'})", {}, reasons
        elif verdict:
            reasons.append(f"{name} {b} matches" if a == b else f"{name} {a} ≈ {b}")
            if not attr.hard:
                soft_agree.append(name)

    sv, cv = (sf.versions, cf.versions) if spec.versions else (set(), set())
    # A version the listing states anywhere in its own text counts as stated ("Levi's 025" in Myntra's description).
    cv = cv | {v for v in sv if v in cf.words}
    if spec.versions_required and sv and not cv and ident != "exact":
        return f"listing names no model number ({' '.join(sorted(sv))} on Amazon)", {}, reasons
    if cv and sv != cv and ident != "exact":
        return f"different model version ({' '.join(sorted(sv)) or '-'} vs {' '.join(sorted(cv))})", {}, reasons

    src_words = sf.words | set(sf.name)
    missing = [w for w in sf.name if w not in cf.words and w not in sv]
    extra = [w for w in cf.name if w not in src_words and w not in cv and not (re.search(r"\d", w) and len(w) > 5)]
    shared = [w for w in sf.name if w in cf.words]
    r = lambda ws: [rarity(w, cat) for w in ws]
    x = {
        "ident_exact": float(ident == "exact"), "ident_variant": float(ident == "variant"),
        "ident_series": float(ident == "series"), "versions_unstated": float(bool(sv) and not cv),
        "missing_sum": sum(r(missing)), "missing_max": max(r(missing), default=0.0),
        "extra_sum": sum(r(extra)), "extra_max": max(r(extra), default=0.0), "shared_sum": sum(r(shared)),
        "colour_exact": float(bool(shades(sf.attrs.get("colour_name"), cf.attrs.get("colour_name")))),
        "soft_conflicts": float(len(soft_conflicts)), "soft_agree": float(len(soft_agree)), "no_name": float(not sf.name),
        "name_exact": float(bool(sf.name) and not missing and not extra),   # nothing missing, nothing added
        "versions_match": float(bool(sv) and sv == cv),
    }
    if sv and sv == cv:
        reasons.append(f"model version {' '.join(sorted(sv))} matches")
    if shared:
        reasons.append("name words in common: " + " ".join(shared[:6]))
    if missing:
        reasons.append("Amazon name words not on this listing: " + " ".join(missing[:6]))
    if extra:
        reasons.append("extra name words on this listing: " + " ".join(extra[:6]))
    if soft_conflicts:
        reasons.append("details differ: " + ", ".join(soft_conflicts))
    return None, x, reasons


def score(x: dict, category: Category) -> tuple[float, float]:
    w, threshold = weights_for(category)
    z = w.get("bias", 0.0) + sum(w.get(k, 0.0) * v for k, v in x.items())
    return 1 / (1 + math.exp(-z)), threshold


def match(src: Listing, cand: Listing) -> MatchVerdict:
    category = src.category
    rejection, x, reasons = features(src, cand, category)
    if rejection:
        return MatchVerdict(False, 0.0, reasons + [rejection])
    p, threshold = score(x, category)
    if x.get("ident_exact"):
        # The same manufacturer code is the same article; the hard rules (colour, wearer, pack, size) have passed.
        return MatchVerdict(True, round(max(p, 0.99), 3), reasons)
    if p < threshold:
        return MatchVerdict(False, round(p, 3), reasons + [f"not enough evidence it's the same product (score {p:.2f})"])
    return MatchVerdict(True, round(p, 3), reasons)
