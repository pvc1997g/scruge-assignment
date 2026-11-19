"""Turn a Listing into Facts: what the listing states about itself, and nothing more.

Every value is either known or None (unknown). Nothing here compares two listings; that is engine.py's job.
Store-specific conventions that change what a listing *states* live here, documented where they apply.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from ..models import Category, Listing
from ..normalize import (
    BASE_COLOURS, COLOUR_SYNONYMS, TOKEN_ALIASES, VARIANT_WORDS, apparel_facts, colour_family, colour_name_key, colour_words, core_style_code, is_multipack,
    clean, model_codes, network_gen, norm_brand, tokens,
)

# Words that say what kind of product it is, who it is for or how it is sold, never which model. Much shorter
# than v1's list: descriptive words ("sport", "casual", "running") stay, because rarity already weighs them low,
# and some of them name models ("Converse Sport Casual"). Variant words (ultra, prime, plus) always stay.
NOT_NAME = set("""
    5g 4g lte ai dual sim nfc smartphone phone mobile mobiles with and the for of in a an by to new latest edition
    storage ram rom expandable camera battery display tv television led oled qled uhd hd 4k 8k cm cms inch inches
    model series men mens women womens woman man boys boy girls girl kids kid unisex adult adults
    shoe shoes sneaker sneakers footwear t shirt shirts tshirt tshirts tee tees polo polos jersey jerseys
    pack size sizes uk us eu india original genuine xs s m l xl xxl xxxl 2xl 3xl 4xl
""".split())
_UNIT = re.compile(r"^\d+(?:\.\d+)?(gb|tb|mah|mp|hz|w|cm|cms|inch|inches|mm|k|p|nits|x)$")


def name_tokens(text: str, brand: Optional[str], cut_at_paren: bool) -> list[str]:
    """The model's own words: brand, kind-of-product words, colours and units removed."""
    t = clean(text)
    if cut_at_paren:
        head = re.split(r"[(|:,]| - | – ", t, maxsplit=1)[0]
        if len(tokens(head)) >= 2:
            # Some names live inside the first brackets: "Nothing Phone (3a Lite) (Black, 128 GB)".
            if not name_tokens(head, brand, False):
                inner = re.search(r"\(([^()]*)\)", t)
                if inner and not re.search(r"\d+\s*(gb|tb)\b|,", inner.group(1), re.I):
                    head = f"{head} {inner.group(1)}"
            t = head
    t = re.sub(r"\b\d+(?:\.\d+)?\s*(gb|tb|mb|mp|mah|hz|w|watts?|cm|cms|inch|inches|mm|nits)\b", " ", t, flags=re.I)
    skip = set(tokens(brand or "")) | {norm_brand(brand)} | NOT_NAME | set(BASE_COLOURS) | set(COLOUR_SYNONYMS)
    out = []
    for tok in tokens(t):
        for w in TOKEN_ALIASES.get(tok, [tok]):
            if w not in skip and not _UNIT.match(w) and not re.match(r"^\d+x\d+$", w) and w not in out:
                out.append(w)
    return out


HEIGHTS = {"low", "mid", "high"}
# Construction variants that make a different shoe even though they sit after a dash in the title.
CONSTRUCTION = {"slip", "ins", "waterproof", "wp", "gtx", "goretex", "easyon", "flyease"}
# Words that look like versions but aren't: "100% cotton", pack/size counts.
NOT_VERSIONS = {"100", "1", "0"}
PLAIN_COLOURS = set(BASE_COLOURS) | set(COLOUR_SYNONYMS) | {"multicolor", "multicolour", "na", "default"}


@dataclass
class Facts:
    category: Category
    brand: str
    name: list[str]                 # the model's own words (brand, generic words, colours and units removed)
    versions: set[str]              # words that pick one model out of a family: 8, 3.0, pro, plus, mid, easyon
    words: set[str]                 # every word the listing says about itself (title, model name, collection, text)
    codes: list[str] = field(default_factory=list)   # manufacturer codes: TV model codes, garment/shoe style codes
    attrs: dict = field(default_factory=dict)        # ram, storage, screen, network, gender, pack, colour, garment...


SHADE_ALIASES = {"gray": "grey", "lt": "light", "dk": "dark", "wht": "white", "blk": "black", "mel": "melange"}
# Only true base colours are plain here: descriptive names ("slate", "wolf", "midnight") are the shade itself.
BASE_SHADES = set(BASE_COLOURS) | {"gray", "multicolor", "multicolour", "multi", "na", "default", "colour", "color"}
SHADE_MODIFIERS = {"light", "dark", "deep", "pale", "bright", "medium", "true", "core", "new", "and"}


def shade_words(colour: Optional[str]) -> frozenset:
    words = set()
    text = re.sub(r"off[\s-]*white", "offwhite", (colour or "").lower())   # "Off White" is one colour, not "off"
    for w in re.findall(r"[a-z]+", text):
        w = SHADE_ALIASES.get(w, w)
        if len(w) <= 2 or w in BASE_SHADES or w in SHADE_MODIFIERS:
            continue
        words.add(w)
    return frozenset(words)


def _versions(name: list[str], name_words: set[str], category: Category) -> set[str]:
    out = set()
    # Phone names never carry style codes, so every word with a digit names the model (reno16c, s24, 15r).
    max_len = 12 if category == Category.SMARTPHONE else 5
    for t in name:
        if t in VARIANT_WORDS or t in HEIGHTS:
            out.add(t)
        elif re.search(r"\d", t) and len(t) <= max_len and t not in NOT_VERSIONS:
            out.add(t)       # 8, 3.0, s24, 574, 025; long alphanumerics (177288, ml574evg) are codes, not versions
    if category == Category.SNEAKERS:
        out |= name_words & CONSTRUCTION   # from the name only: descriptions say "slip-on" about laces
        # Low top is the default: "Chuck Taylor All Star" and "Chuck Taylor All Star Low Top" are the same shoe.
        if out & HEIGHTS == {"low"}:
            out.discard("low")
    if category == Category.APPAREL:
        out = {v for v in out if re.search(r"\d", v)}  # line ids and seasons (025, 24/25); "pro"/"max" are just words
    return out


def _name_source(item: Listing, is_source: bool, category: Category) -> str:
    if is_source and category == Category.SMARTPHONE:
        # For phones Amazon's 'Model Name' is the clean name ('iPhone 16'); for shoes and clothes it is often a
        # stock code ('300LS025-RN-TEE-P1', 'A10547C-black-7'), so the title is used there.
        mn = item.extra.get("model_name") or ""
        # Amazon's structured 'Model Name' is the cleanest name when it carries real model words.
        if mn and any(re.search(r"\d", t) or t in VARIANT_WORDS for t in name_tokens(mn, item.brand, True)):
            return mn
        return item.title
    if is_source:
        return item.title
    return " ".join(filter(None, [item.title, item.extra.get("model_name"), item.extra.get("collection")]))


def _plus(text: Optional[str]) -> Optional[str]:
    """'Note 14 Pro+' -> 'Note 14 Pro plus': the plus sign names a different model."""
    return re.sub(r"(?<=[A-Za-z0-9])\+(?![A-Za-z0-9])", " plus", text) if text else text


def _unescape(text):
    """Flipkart leaves JSON escapes in some fields: 'BLACK\\u002fCITRON' -> 'BLACK/CITRON'."""
    if not isinstance(text, str) or "\\u" not in text:
        return text
    return re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), text)


def extract(item: Listing, category: Category, is_source: bool = False) -> Facts:
    extra = {k: _unescape(v) for k, v in item.extra.items()}
    item = Listing(**{**item.__dict__, "title": _plus(_unescape(item.title)), "colour": _unescape(item.colour),
                      "model_number": _unescape(item.model_number),
                      "extra": {**extra, "model_name": _plus(extra.get("model_name")),
                                "collection": _plus(extra.get("collection"))}})
    text = " ".join(filter(None, [item.title, item.extra.get("model_name"), item.extra.get("collection"),
                                  item.extra.get("text")]))
    all_tokens = {a for t in tokens(text) for a in TOKEN_ALIASES.get(t, [t])}
    cut = category in (Category.SMARTPHONE,) or is_source
    name = name_tokens(_name_source(item, is_source, category), item.brand, cut)
    if is_source and category != Category.SMARTPHONE and len(name) < 2:
        name = name_tokens(item.title, item.brand, False)
    f = Facts(category=category, brand=norm_brand(item.brand or (item.title.split()[0] if item.title else "")),
              name=name, versions=_versions(name, set(tokens(_name_source(item, is_source, category))), category), words=all_tokens | set(name))
    a = f.attrs

    if category == Category.SMARTPHONE:
        a["storage"], a["ram"] = item.storage_gb, item.ram_gb
        a["network"] = network_gen(" ".join(filter(None, [item.title, item.extra.get("text")])))
        # Croma puts "5G" in the name of every 5G phone it sells (iPhones aside), so a Croma phone without it is 4G.
        if a["network"] is None and item.platform == "croma" and f.brand != "apple":
            a["network"] = "4g"

    elif category == Category.TV:
        a["screen"] = item.screen_in
        f.codes = model_codes(" ".join(filter(None, [item.model_number or "", item.title])), item.screen_in)

    else:
        a["gender"] = item.gender
        a["pack"] = 2 if (is_multipack(item.title) or str(item.extra.get("pack_of") or "1").strip() not in ("", "1")) else 1
        colour = item.extra.get("brand_colour") or item.colour
        base = colour_words(item.colour) or colour_words(item.extra.get("brand_colour"))
        a["colour"] = base[0] if base else None
        a["colour_family"] = colour_family(base[0]) if base else None
        # The distinctive words of a brand's shade name ("WOLF GREY/WHITE" -> {wolf}, "BLACK/CITRON" -> {citron}).
        # Plain colour words, modifiers and short store codes ("NV", "VG") say nothing more.
        a["colour_name"] = shade_words(colour) or None
        code = core_style_code(item.model_number)
        if code:
            f.codes = [code]
        if category == Category.APPAREL:
            g = {**item.extra.get("facts", {}), **apparel_facts(item.title, item.brand)}
            a["garment"] = g.get("type")
            for k in ("sleeve", "neck", "fit", "pattern"):
                a[k] = g.get(k) or None
    return f
