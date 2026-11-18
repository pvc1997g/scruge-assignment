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
    core_style_code, is_distinguishing, model_codes, model_tokens, style_codes_identical, style_codes_match, tokens,
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
    # The series name must be there too: "POP X" vs "POVA X" share only the variant word "x".
    name_missing = [t for t in st if t not in sd and t not in ct]
    if name_missing:
        reasons.append(f"different model name (missing {name_missing}): {' '.join(st)} vs {' '.join(ct)}")
        return False, 0.0
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


FULL_TITLE_VARIANTS = {"slip", "ins", "waterproof", "wp", "gtx", "goretex", "easyon", "flyease"}


def _style_code_hit(src: Listing, cand: Listing) -> bool:
    code = core_style_code(src.model_number)
    if not code:
        return False
    if style_codes_match(src.model_number, cand.model_number):
        return True
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
    # Construction variants often sit after a dash ("GO WALK FLEX - Waterproof Slip-Ins"), outside
    # the model name we compare, so look for them across the whole title.
    sd |= set(tokens(src.title)) & FULL_TITLE_VARIANTS
    cd |= set(tokens(cand.title)) & FULL_TITLE_VARIANTS
    if sd != cd:
        reasons.append(f"different model version ({sorted(sd) or '-'} vs {sorted(cd) or '-'})")
        return False, 0.0
    # Every model word must match both ways: "Court Vision Low Suede" is not "Court Vision Low Next Nature",
    # and "Smash Comfort" is not "Smashic Comfort". Generic words (running shoes, for men) are already gone.
    missing, extra = set(st) - set(ct), set(ct) - set(st)
    if missing or extra:
        bits = ([f"missing {sorted(missing)}"] if missing else []) + ([f"extra {sorted(extra)}"] if extra else [])
        reasons.append(f"different model ({', '.join(bits)}): '{' '.join(st)}' vs '{' '.join(ct)}'")
        return False, 0.0
    reasons.append(f"model '{' '.join(st)}' matches")
    return True, 1.0


def garment_facts(listing: Listing) -> dict[str, str]:
    """Facts from the spec table, with the title winning where both state a fact. Spec fields are
    often left at defaults ("Fit: Regular" on a shirt titled "Oversized Fit"), while title words
    are chosen deliberately for that product."""
    return {**listing.extra.get("facts", {}), **apparel_facts(listing.title, listing.brand)}


STRONG_FACTS = ("pattern", "fit", "sleeve", "neck")
# What a plain garment of each type is by default: agreeing on these says little.
DEFAULT_FACTS = {
    "tshirt": {"pattern": "solid", "fit": "regular", "sleeve": "short", "neck": "round"},
    "polo": {"pattern": "solid", "fit": "regular", "sleeve": "short", "neck": "collar"},
}
_NAME_NOISE = {"printed", "print", "solid", "cotton", "polyester", "regular", "slim", "fit", "pure", "half", "full",
               "sleeve", "sleeves", "neck", "round", "crew", "collar", "brand", "logo", "casual", "short", "long"}
# Descriptive words that are not a product-line name.
_LINE_NOISE = _NAME_NOISE | set("""
    oversized relaxed fitted classic comfortable comfort stylish rich soft premium wear everyday daily regular
    side branding detail details detailed embroidered applique pocket pockets drop shoulder sports sport training gym
    athleisure performance dri fit polycotton blend blended organic knitted knit ultra antiviral new graphic typography
    tipped contrast placket band mandarin henley v crew tee tees top shirt shirts tshirt tshirts polo polos jersey
    jerseys mens womens boys girls kids adult adults for with and the of in a an quick dry lightweight breathable
    stretch durable trendy latest fashion basic basics stripe striped colourblock colorblock textured self design
""".split())


def _line_words(listing: Listing) -> set[str]:
    toks = model_tokens(listing.title, listing.brand, cut_at_paren=False)
    # Numbers count only as line ids like Levi's "025"; "100" (% cotton) and years don't.
    return {t for t in toks if t not in _LINE_NOISE and len(t) >= 3
            and not (t.isdigit() and (t == "100" or len(t) == 4))}


def _model_check_apparel(src: Listing, cand: Listing, reasons: list[str]) -> tuple[bool, float]:
    """Clothes rarely have model names. Evidence, strongest first:
      1. the manufacturer style code (Amazon 'style number' == store 'style code')
      2. garment facts from both spec tables: pattern, fit, sleeve, neck (+ material)
    Any known fact that differs rejects. Weak facts (it's a t-shirt, it's cotton, a polo has a
    collar) are true of half the catalogue, so they never count towards a match on their own."""
    if style_codes_match(src.model_number, cand.model_number) or _style_code_hit(src, cand):
        reasons.append(f"style code {src.model_number} matches")
        return True, 1.0

    sf, cf = garment_facts(src), garment_facts(cand)
    if "type" in sf and "type" in cf and sf["type"] != cf["type"]:
        reasons.append(f"different garment ({sf['type']} vs {cf['type']})")
        return False, 0.0

    strong: list[str] = []
    for k in STRONG_FACTS + ("material",):
        a, b = sf.get(k), cf.get(k)
        if not a or not b:
            continue
        if k == "material" and "blend" in (a, b):
            continue  # "cotton" vs "cotton blend" is too fuzzy across stores to decide anything
        if a != b:
            reasons.append(f"different {k} ({a} vs {b})")
            return False, 0.0
        implied = k == "neck" and a == "collar" and sf.get("type") == "polo"
        if k in STRONG_FACTS and not implied:
            strong.append(f"{k}={a}")

    st = model_tokens(src.title, src.brand, cut_at_paren=False)
    ct = model_tokens(cand.title, cand.brand, cut_at_paren=False)
    sim = _dice(st, ct)
    # Jerseys / licensed tees are identified by their name words (India T20, Real Madrid 25/26 Away).
    shared_name = sorted(set(st) & set(ct) - _NAME_NOISE)
    named = sim >= 0.45 and len(shared_name) >= 3

    if sf.get("type") == "jersey" and not named:
        reasons.append(f"different or unknown jersey ({' '.join(st[:6]) or '?'} vs {' '.join(ct[:6]) or '?'})")
        return False, 0.0

    # Named product lines must agree: Puma "Essential" polo is not Puma "Pique Tipping" polo.
    sl, cl = _line_words(src), _line_words(cand)
    if sl and cl and not (sl & cl):
        reasons.append(f"different product line ({' '.join(sorted(sl))} vs {' '.join(sorted(cl))})")
        return False, 0.0

    if len(strong) < 2 and not named:
        have = ", ".join(strong) or "no detail in common"
        reasons.append(f"not enough evidence it's the same garment ({have}; need 2 of pattern/fit/sleeve/neck)")
        return False, 0.0

    defaults = DEFAULT_FACTS.get(sf.get("type", ""), {})
    distinctive = [s for s in strong if defaults.get(s.split("=")[0]) != s.split("=")[1]]
    shared_line = sorted(sl & cl)

    detail = ", ".join(([sf["type"]] if sf.get("type") else []) + strong)
    if named:
        detail += ("; " if detail else "") + "name words: " + " ".join(shared_name[:6])
    elif shared_line:
        detail += ("; " if detail else "") + "same line: " + " ".join(shared_line)
    reasons.append(f"same garment: {detail}")

    if not distinctive and not named and not shared_line:
        # "Solid, short sleeve, round neck" describes nearly every plain tee of that brand and colour.
        # That is not enough to call it the same product, so it doesn't count as found.
        reasons.append("only basic details in common (true of most plain garments), so not confirmed as the same product")
        return False, 0.0
    # Without a style code, score grows with the evidence but stays below 0.8 (shown only in "Why?").
    return True, min(0.55, 0.12 * len(strong) + 0.1 * len(distinctive) + (0.25 if named or shared_line else 0) + 0.15 * sim)


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
            # A colour name we can't read ("Gibraltar Sea") is fine only when the full style code is identical:
            # long codes name one colour variant, so they already settle the colour.
            if not style_codes_identical(src.model_number, cand.model_number):
                return MatchVerdict(False, 0.0, reasons + [why])
            reasons.append(f"identical style code {src.model_number} fixes the colour ({src.colour or '?'} = {cand.colour or '?'})")
        else:
            reasons.append(why)
            if "family" not in why:
                sim += 0.1  # exact colour beats "same family" (olive vs green)

    score = min(1.0, 0.5 + 0.5 * sim)
    if cat == Category.APPAREL and not any("style code" in r for r in reasons):
        score = min(score, 0.8)  # garment-facts match is less certain than a style code
    return MatchVerdict(True, round(score, 3), reasons)
