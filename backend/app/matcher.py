"""Decide whether a candidate listing is the *same product* as the Amazon source.

Rules (from the assignment): brand + model must match, plus
  smartphones -> RAM and storage
  TVs         -> screen size
  sneakers    -> colour
  apparel     -> colour

Every rule is a hard gate: if any gate fails the candidate is rejected, with a reason.
Candidates that pass all gates get a similarity score, and the best one wins.
"""

from __future__ import annotations

import re

from .models import Category, Listing, MatchVerdict
from .normalize import (
    VARIANT_WORDS, apparel_facts, brands_match, codes_overlap, colours_match, genders_compatible,
    is_distinguishing, model_codes, model_tokens,
)


def source_model_tokens(src: Listing) -> list[str]:
    """Prefer Amazon's structured 'Model Name' field (e.g. 'iPhone 16') over the marketing title."""
    mn = src.extra.get("model_name")
    if mn:
        toks = model_tokens(mn, src.brand)
        if any(is_distinguishing(t) for t in toks):
            return toks
    return model_tokens(src.title, src.brand)


def _dice(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return 2 * len(sa & sb) / (len(sa) + len(sb))


def _model_check_strict(src: Listing, cand: Listing, reasons: list[str]) -> tuple[bool, float]:
    """Phones: the distinguishing tokens (s24, ultra, pro, 15, plus...) must be identical."""
    st = source_model_tokens(src)
    ct = model_tokens(cand.title, cand.brand)
    if not st:
        reasons.append(f"could not find a model name in '{src.title}'")
        return False, 0.0
    sd = {t for t in st if is_distinguishing(t)}
    cd = {t for t in ct if is_distinguishing(t)}
    if not sd:
        # Names without numbers or variant words ("iPhone Duo", "Pixel Fold"): every model word must match exactly.
        if set(st) != set(ct):
            reasons.append(f"different model ({' '.join(st)} vs {' '.join(ct) or '?'})")
            return False, 0.0
        reasons.append(f"model {' '.join(st)} matches")
        return True, 1.0
    missing, extra = sd - cd, cd - sd
    if missing or extra:
        bits = []
        if missing:
            bits.append(f"missing {sorted(missing)}")
        if extra:
            bits.append(f"extra {sorted(extra)}")
        reasons.append(f"different model ({', '.join(bits)}): {' '.join(st)} vs {' '.join(ct)}")
        return False, 0.0
    sim = _dice(st, ct)
    reasons.append(f"model {' '.join(sorted(sd))} matches")
    return True, sim


def _model_check_tv(src: Listing, cand: Listing, reasons: list[str]) -> tuple[bool, float]:
    """TVs: match on manufacturer model code (full 'UA55U8500HULXL' or series 'U8500H')."""
    src_codes = model_codes(" ".join(filter(None, [src.model_number or "", src.title])), src.screen_in)
    cand_codes = model_codes(" ".join(filter(None, [cand.model_number or "", cand.title])), cand.screen_in)
    shared = codes_overlap(src_codes, cand_codes)
    if shared:
        full_src = src_codes[0] if src_codes else ""
        full_cand = next((c for c in cand_codes if shared in c), shared)
        if full_src == full_cand or shared == full_src:
            reasons.append(f"model code {shared.upper()} matches")
            return True, 1.0
        # e.g. Croma names the series (UE85AH) while Amazon shows the full code (UA55UE85AHULXL),
        # or a revision suffix differs (K-55S25B vs K-55S25BM2) - likely, not certain.
        reasons.append(f"model series {shared.upper()} matches (full codes {full_src.upper()} vs {full_cand.upper()})")
        return True, 0.75
    if src_codes and cand_codes:
        reasons.append(f"different model code ({', '.join(src_codes[:2]).upper()} vs {', '.join(cand_codes[:2]).upper()})")
        return False, 0.0
    # No codes on one side: fall back to the series name words ("crystal 4k vivid pro").
    st, ct = model_tokens(src.title, src.brand, cut_at_paren=False), model_tokens(cand.title, cand.brand, cut_at_paren=False)
    sim = _dice(st, ct)
    if sim >= 0.6:
        reasons.append(f"no model code to compare; series name {sim:.0%} similar")
        return True, sim * 0.8
    reasons.append(f"no model code to compare and names differ ({sim:.0%} similar)")
    return False, 0.0


# Words that turn one shoe model into another (Smashic vs Smashic Comfort, AF1 Low vs Mid).
SNEAKER_VARIANTS = VARIANT_WORDS | set(
    "comfort mid low high lv8 premium retro og next nature elite react slip knit sl l v1 v2 v3 v4 v5 nitro".split()
)


def _style_code_hit(src: Listing, cand: Listing) -> bool:
    if not src.model_number:
        return False
    code = re.sub(r"[^a-z0-9]", "", src.model_number.lower())
    hay = re.sub(r"[^a-z0-9]", "", " ".join([cand.title, cand.extra.get("description", "")]).lower())
    return len(code) >= 6 and code in hay


def _model_check_sneakers(src: Listing, cand: Listing, reasons: list[str]) -> tuple[bool, float]:
    """Model-name words must agree; numbers ('07, 574, v2) and variant words (mid, comfort) must be identical."""
    if _style_code_hit(src, cand):
        reasons.append(f"style code {src.model_number} found")
        return True, 1.0
    st = model_tokens(src.title, src.brand)
    ct = model_tokens(cand.title, cand.brand)
    if not st:
        reasons.append("couldn't find a model name on the Amazon page")
        return False, 0.0
    sd = {t for t in st if is_distinguishing(t) or t in SNEAKER_VARIANTS}
    cd = {t for t in ct if is_distinguishing(t) or t in SNEAKER_VARIANTS}
    if sd != cd:
        reasons.append(f"different model version ({sorted(sd) or '-'} vs {sorted(cd) or '-'})")
        return False, 0.0
    sim = _dice(st, ct)
    if sim < 0.6:
        reasons.append(f"model name too different ({sim:.0%} similar): '{' '.join(st)}' vs '{' '.join(ct)}'")
        return False, 0.0
    reasons.append(f"model '{' '.join(st)}' matches ({sim:.0%})")
    return True, sim


def _model_check_apparel(src: Listing, cand: Listing, reasons: list[str]) -> tuple[bool, float]:
    """Clothes rarely have model names, so 'model' = garment type + pattern + fit + sleeve + neck."""
    if _style_code_hit(src, cand):
        reasons.append(f"style code {src.model_number} found")
        return True, 1.0
    sf = apparel_facts(src.title, src.brand)
    cf = apparel_facts(cand.title, cand.brand)
    if "type" in sf and "type" in cf and sf["type"] != cf["type"]:
        reasons.append(f"different garment ({sf['type']} vs {cf['type']})")
        return False, 0.0
    agree = []
    for k in ("pattern", "fit", "sleeve", "neck", "material"):
        if k in sf and k in cf:
            if sf[k] != cf[k]:
                reasons.append(f"different {k} ({sf[k]} vs {cf[k]})")
                return False, 0.0
            agree.append(f"{k}={sf[k]}")
    if sf.get("type") and cf.get("type"):
        agree.insert(0, sf["type"])
    st = model_tokens(src.title, src.brand, cut_at_paren=False)
    ct = model_tokens(cand.title, cand.brand, cut_at_paren=False)
    sim = _dice(st, ct)
    # Jerseys / licensed tees are identified by their name words (India T20, Real Madrid 25/26 Away).
    shared_name = sorted(set(st) & set(ct) - {"printed", "print", "solid", "cotton", "polyester", "regular", "slim", "fit"})
    if len(agree) < 2 and not (sim >= 0.45 and len(shared_name) >= 3):
        reasons.append(f"too little detail to be sure it's the same garment ({', '.join(agree) or 'nothing comparable'})")
        return False, 0.0
    if sf.get("type") == "jersey" and st and sim < 0.3:
        reasons.append(f"different jersey ({' '.join(st[:6])} vs {' '.join(ct[:6])})")
        return False, 0.0
    detail = ", ".join(agree) if agree else ""
    if shared_name and sim >= 0.45:
        detail = (detail + "; " if detail else "") + "name words: " + " ".join(shared_name[:6])
    reasons.append(f"same garment: {detail}")
    # Apparel matches are inherently less certain than a model number, so cap the score.
    return True, min(0.7, 0.3 + 0.1 * len(agree) + 0.3 * sim)


def match(src: Listing, cand: Listing) -> MatchVerdict:
    reasons: list[str] = []

    # Gate 1: brand
    if not brands_match(src.brand, cand.brand):
        # Platforms sometimes omit the brand field - fall back to the title's first word.
        cand_brand_guess = cand.title.split()[0] if cand.title else None
        if not brands_match(src.brand, cand_brand_guess):
            return MatchVerdict(False, 0.0, [f"brand differs ({src.brand} vs {cand.brand or cand_brand_guess})"])
    reasons.append(f"brand {src.brand} matches")

    cat = src.category

    # Gate 2: model
    if cat == Category.SMARTPHONE:
        ok, sim = _model_check_strict(src, cand, reasons)
    elif cat == Category.TV:
        ok, sim = _model_check_tv(src, cand, reasons)
    elif cat == Category.SNEAKERS:
        ok, sim = _model_check_sneakers(src, cand, reasons)
    else:
        ok, sim = _model_check_apparel(src, cand, reasons)
    if not ok:
        return MatchVerdict(False, 0.0, reasons)

    # Gate 3: the category-specific attribute
    if cat == Category.SMARTPHONE:
        if src.storage_gb is None:
            reasons.append("storage unknown on Amazon page")
        elif cand.storage_gb is None:
            return MatchVerdict(False, 0.0, reasons + ["storage not shown on candidate"])
        elif src.storage_gb != cand.storage_gb:
            return MatchVerdict(False, 0.0, reasons + [f"storage differs ({src.storage_gb:g}GB vs {cand.storage_gb:g}GB)"])
        else:
            reasons.append(f"storage {src.storage_gb:g}GB matches")
        if src.ram_gb is not None and cand.ram_gb is not None:
            if src.ram_gb != cand.ram_gb:
                return MatchVerdict(False, 0.0, reasons + [f"RAM differs ({src.ram_gb:g}GB vs {cand.ram_gb:g}GB)"])
            reasons.append(f"RAM {src.ram_gb:g}GB matches")
        else:
            # iPhones etc. often don't state RAM; the model + storage already pins the variant.
            reasons.append("RAM not listed on one side (model + storage decide)")
            sim *= 0.95

    elif cat == Category.TV:
        if src.screen_in is None or cand.screen_in is None:
            return MatchVerdict(False, 0.0, reasons + ["screen size unknown"])
        if abs(src.screen_in - cand.screen_in) > 1:
            return MatchVerdict(False, 0.0, reasons + [f'screen size differs ({src.screen_in}" vs {cand.screen_in}")'])
        reasons.append(f'screen size {src.screen_in}" matches')

    else:  # sneakers / apparel
        if not genders_compatible(src.gender, cand.gender):
            return MatchVerdict(False, 0.0, reasons + [f"made for different wearer ({src.gender} vs {cand.gender})"])
        ok_c, why = colours_match(src.colour, cand.colour)
        if ok_c is False:
            return MatchVerdict(False, 0.0, reasons + [why])
        if ok_c is None:
            return MatchVerdict(False, 0.0, reasons + [why])
        reasons.append(why)
        if "family" not in why:
            sim += 0.1  # exact colour beats "same family" (olive vs green)

    score = min(1.0, 0.5 + 0.5 * sim)
    if cat == Category.APPAREL and not any("style code" in r for r in reasons):
        score = min(score, 0.85)  # garment-facts match is less certain than a model number
    return MatchVerdict(True, round(score, 3), reasons)
