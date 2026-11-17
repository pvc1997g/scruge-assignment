"""Turn messy product text into comparable facts.

Every platform writes the same product differently:
  Amazon:   "Samsung Galaxy S24 5G AI Smartphone (Onyx Black, 8GB, 256GB Storage)"
  Flipkart: "Samsung Galaxy S24 5G Snapdragon (Onyx Black, 256 GB)" + "8 GB RAM | 256 GB ROM"
  Croma:    "SAMSUNG Galaxy S24 5G (8GB RAM, 256GB, Onyx Black)"
These helpers pull out brand / RAM / storage / screen size / colour / model tokens
so the matcher can compare facts instead of raw strings.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

# ----------------------------------------------------------------------------- text


def clean(text: Optional[str]) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("‎", " ").replace("‏", " ")
    return re.sub(r"\s+", " ", text).strip()


def tokens(text: str) -> list[str]:
    """Lowercase alphanumeric tokens. Joins hyphenated model codes: 'KD-55X74L' -> 'kd55x74l'."""
    text = clean(text).lower()
    text = re.sub(r"(\b[a-z]{1,3})-(\d)", r"\1\2", text)  # 'KD-55X74L' -> 'kd55x74l', 'GT-7' -> 'gt7'
    text = text.replace("'", "")  # "'07" -> "07", "men's" -> "mens"
    return re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", text)


# ----------------------------------------------------------------------------- brand

BRAND_ALIASES = {
    # same company / sub-brand sold under either name across platforms
    "redmi": "xiaomi",
    "mi": "xiaomi",
    "poco": "xiaomi",
    "uspoloassn": "uspolo",
    "uspoloassociation": "uspolo",
    "uspoloassndenimco": "uspolo",
    "levis": "levis",
    "puma": "puma",
    "adidasoriginals": "adidas",
    "nikesportswear": "nike",
    "pumaselect": "puma",
    "tommyhilfigerjeans": "tommyhilfiger",
    "hm": "hm",
    "lgelectronics": "lg",
    "samsungelectronics": "samsung",
    "applecomputer": "apple",
    "oneplusindia": "oneplus",
}


def norm_brand(brand: Optional[str]) -> str:
    if not brand:
        return ""
    b = clean(brand).lower()
    b = re.sub(r"^(visit the|brand:)\s*", "", b)
    b = re.sub(r"\s*store$", "", b)
    b = re.sub(r"[^a-z0-9]", "", b)
    return BRAND_ALIASES.get(b, b)


def brands_match(a: Optional[str], b: Optional[str]) -> bool:
    na, nb = norm_brand(a), norm_brand(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    # "samsung" vs "samsungindia", "puma" vs "pumaselect"
    short, long_ = sorted([na, nb], key=len)
    return len(short) >= 3 and long_.startswith(short)


# ----------------------------------------------------------------------------- memory

_SIZE = r"(\d+(?:\.\d+)?)\s*(GB|TB)"


def _to_gb(num: str, unit: str) -> float:
    v = float(num)
    return v * 1024 if unit.upper() == "TB" else v


def parse_ram(text: str) -> Optional[float]:
    t = clean(text)
    m = re.search(_SIZE + r"\s*(?:of\s*)?RAM", t, re.I) or re.search(r"RAM\s*[:\-]?\s*" + _SIZE, t, re.I)
    val = None
    if m:
        val = _to_gb(m.group(1), m.group(2))
    else:
        m = re.search(r"\b(\d{1,2})\s*\+\s*(\d{2,4})\s*GB\b", t, re.I)  # "12+256GB"
        if m:
            val = float(m.group(1))
    # No phone has more than 32GB RAM; a bigger figure is the storage, mis-labelled.
    return val if val is not None and val <= 32 else None


def parse_storage(text: str) -> Optional[float]:
    t = clean(text)
    m = re.search(r"\b(\d{1,2})\s*\+\s*(\d{2,4})\s*GB\b", t, re.I)
    if m:
        return float(m.group(2))
    m = re.search(_SIZE + r"\s*(?:ROM|Storage|Internal)", t, re.I)
    if m:
        return _to_gb(m.group(1), m.group(2))
    # Otherwise: biggest GB/TB value that is not the RAM figure (phones: storage >= 32GB)
    ram = parse_ram(t)
    vals = []
    for mm in re.finditer(_SIZE, t, re.I):
        after = t[mm.end(): mm.end() + 6].lower()
        if "ram" in after:
            continue
        vals.append(_to_gb(mm.group(1), mm.group(2)))
    vals = [v for v in vals if v >= 16 and v != ram]
    return max(vals) if vals else None


# ----------------------------------------------------------------------------- screen size


def parse_screen_inches(text: str) -> Optional[int]:
    t = clean(text)
    m = re.search(r"(\d{2,3}(?:\.\d+)?)\s*(?:inches|inch|in\b|\"|”|-inch)", t, re.I)
    if m:
        return round(float(m.group(1)))
    m = re.search(r"(\d{2,3}(?:\.\d+)?)\s*cms?\b", t, re.I)
    if m:
        return round(float(m.group(1)) / 2.54)
    return None


# ----------------------------------------------------------------------------- colour

BASE_COLOURS = [
    "black", "white", "grey", "silver", "blue", "green", "red", "pink", "purple", "yellow",
    "orange", "brown", "beige", "gold", "maroon", "navy", "olive", "teal", "multi",
]

COLOUR_SYNONYMS = {
    "gray": "grey", "graphite": "grey", "charcoal": "grey", "ash": "grey", "slate": "grey", "titanium": "grey",
    "onyx": "black", "jet": "black", "obsidian": "black", "midnight": "black", "phantom": "black", "noir": "black",
    "ivory": "white", "offwhite": "white", "cream": "beige", "chalk": "white", "pearl": "white", "snow": "white",
    "cobalt": "blue", "sky": "blue", "aqua": "blue", "turquoise": "teal", "indigo": "blue", "azure": "blue", "denim": "blue",
    "mint": "green", "lime": "green", "sage": "green", "emerald": "green", "khaki": "beige", "tan": "brown",
    "camel": "brown", "coffee": "brown", "chocolate": "brown", "rust": "orange", "coral": "orange", "peach": "orange",
    "burgundy": "maroon", "wine": "maroon", "crimson": "red", "scarlet": "red", "magenta": "pink", "rose": "pink",
    "violet": "purple", "lavender": "purple", "lilac": "purple", "mauve": "purple", "mustard": "yellow", "lemon": "yellow",
    "amber": "yellow", "bronze": "brown", "champagne": "gold", "multicolor": "multi", "multicolour": "multi",
    # adidas / Puma colour codes ("CBLACK/FTWWHT", "BROYAL")
    "cblack": "black", "ftwwht": "white", "cwhite": "white", "owhite": "white", "broyal": "blue", "conavy": "navy",
    "dkblue": "blue", "royblu": "blue", "grefiv": "grey", "grefou": "grey", "grethr": "grey", "gretwo": "grey",
    "gresix": "grey", "silvmt": "silver", "goldmt": "gold", "scarle": "red", "betsca": "red", "carbon": "grey",
}

# Colours that are commonly treated as interchangeable shades of each other.
COLOUR_FAMILIES = {
    "navy": "blue",
    "maroon": "red",
    "olive": "green",
    "teal": "green",
    "silver": "grey",
    "beige": "brown",
}


def colour_words(text: Optional[str]) -> list[str]:
    """Ordered base colours in a colour string. 'Titanium Gray' -> ['grey'], 'White/Black' -> ['white','black']."""
    if not text:
        return []
    t = clean(text).lower().replace("off-white", "offwhite").replace("off white", "offwhite").replace("multi-colour", "multi")
    out = []
    for tok in re.findall(r"[a-z]+", t):
        base = tok if tok in BASE_COLOURS else COLOUR_SYNONYMS.get(tok)
        if base and base not in out:
            out.append(base)
    return out


def colour_family(c: str) -> str:
    return COLOUR_FAMILIES.get(c, c)


def colours_match(a: Optional[str], b: Optional[str]) -> tuple[Optional[bool], str]:
    """Returns (match?, explanation). None when we can't tell."""
    ca, cb = colour_words(a), colour_words(b)
    if not ca or not cb:
        return None, f"colour unknown ({a or '?'} vs {b or '?'})"
    if ca[0] == cb[0]:
        return True, f"colour {ca[0]} = {cb[0]}"
    if colour_family(ca[0]) == colour_family(cb[0]):
        return True, f"colour {ca[0]} ≈ {cb[0]} (same family)"
    return False, f"colour differs ({a} → {ca[0]} vs {b} → {cb[0]})"


# ----------------------------------------------------------------------------- gender

def parse_gender(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    t = " " + clean(text).lower().replace("'", "") + " "
    if re.search(r"\bunisex\b", t):
        return "unisex"
    if re.search(r"\b(boys?|girls?|kids?|infants?|toddlers?|older kids|little kids|baby)\b", t):
        return "kids"
    if re.search(r"\b(women|womens|woman|ladies|female)\b", t):
        return "women"
    if re.search(r"\b(men|mens|man|male|gents)\b", t):
        return "men"
    return None


def genders_compatible(a: Optional[str], b: Optional[str]) -> bool:
    if not a or not b or a == b:
        return True
    if "unisex" in (a, b) and "kids" not in (a, b):
        return True
    return False


# ----------------------------------------------------------------------------- model tokens

# Words that describe the *kind* of product, not *which* product.
GENERIC_WORDS = set(
    """
    5g 4g lte ai smartphone smart phone mobile mobiles cell cellular dual sim with and the for of in a an by to new
    latest edition storage ram rom gb tb expandable upto up camera battery display fast charging charger included
    tv television led oled qled uhd hd full ultra 4k 8k ready android google webos tizen os cm cms inch inches
    model series smarttv frameless bezel less hdr dolby atmos audio sound speakers voice remote assistant
    alexa built works netflix prime video youtube hotstar star energy rating 2023 2024 2025 2026 year
    men mens women womens woman man boys boy girls girl kids kid unisex adult adults
    shoe shoes sneaker sneakers footwear running sports sport casual walking training trainers trainer gym lace laceup
    ups lace-ups slip on outdoor lifestyle comfortable lightweight trendy stylish
    t shirt shirts tshirt tshirts tee tees polo polos jersey jerseys top tops wear clothing apparel
    pack size sizes uk us eu india original genuine
    """.split()
)

# Words that, when they appear, change WHICH model it is (S24 vs S24 Ultra vs S24 FE).
VARIANT_WORDS = set(
    """
    pro plus max ultra mini lite fe neo edge prime note fold flip go power turbo play x xl s se e r
    """.split()
)

# Same word, different spelling across platforms.
TOKEN_ALIASES = {
    "lo": ["low"], "hi": ["high"], "nn": ["next", "nature"], "colour": ["color"],
    "tshirt": ["t", "shirt"], "07": ["07"], "1s": ["1"],
}

_UNIT_TOKEN = re.compile(r"^\d+(?:\.\d+)?(gb|tb|mah|mp|hz|w|cm|cms|inch|inches|mm|k|p|nits|x)$")
_DIMENSION = re.compile(r"^\d+x\d+$")


def model_tokens(title: str, brand: Optional[str] = None, cut_at_paren: bool = True) -> list[str]:
    """Tokens that identify the model. Drops brand, colours, specs and generic product words."""
    t = clean(title)
    if cut_at_paren:
        # Amazon/Flipkart/Croma put specs after the first '(' / '|' / ':' / ',' / ' - ': the model name is before it.
        head = re.split(r"[(|:,]| - | – ", t, maxsplit=1)[0]
        if len(tokens(head)) >= 2:
            t = head
    # Drop spec figures like "128 GB", "50 MP", "5000 mAh" before tokenising.
    t = re.sub(r"\b\d+(?:\.\d+)?\s*(gb|tb|mb|mp|mah|hz|w|watts?|cm|cms|inch|inches|mm|nits)\b", " ", t, flags=re.I)
    brand_toks = set(tokens(brand or ""))
    nb = norm_brand(brand)
    out = []
    expanded: list[str] = []
    for tok in tokens(t):
        expanded.extend(TOKEN_ALIASES.get(tok, [tok]))
    for tok in expanded:
        if tok in brand_toks or tok == nb or tok in GENERIC_WORDS:
            continue
        if tok in BASE_COLOURS or tok in COLOUR_SYNONYMS:
            continue
        if _UNIT_TOKEN.match(tok) or _DIMENSION.match(tok):
            continue
        if tok not in out:
            out.append(tok)
    return out


def is_distinguishing(tok: str) -> bool:
    """A token that pins the exact model: has a digit (s24, 15, 990v6, 07) or is a variant word (pro, ultra)."""
    return bool(re.search(r"\d", tok)) or tok in VARIANT_WORDS


# ----------------------------------------------------------------------------- model codes (TVs)

_CODE_NOISE = re.compile(
    r"^(\d+(hz|p|k|w|cm|cms|inch|inches|gb|mah|mp|nits|watts?)|\d+x\d+|hdr\d*\w*|hdmi\d*|usb\d*|wifi\d*|dts\w*|"
    r"dolby\w*|mpeg\d*|h26\d|ddr\d|av1|ipv\d|ac\d+|a\d{2}\w?|bt\d+|ce\d+)$"
)
_YEARISH = re.compile(r"^(19|20)\d{2}$")


def model_codes(text: str, screen_in: Optional[int] = None) -> list[str]:
    """Alphanumeric codes like UA55U8500HULXL, 55QNED65BLA, K55S25B, U8500H, QNED65.

    When a code embeds the screen size (UA55UE85AHULXL, 55QNED65BLA, K-55S25B) we also emit
    the size-free series part (UE85AHULXL, QNED65BLA, S25B), because retailers like Croma
    name TVs by series ("SAMSUNG UE85AH 140 cm (55 inch)").
    """
    out: list[str] = []
    raw = clean(text)
    raw = re.sub(r"([A-Za-z0-9])-([A-Za-z0-9])", r"\1\2", raw)  # KD-55X74L -> KD55X74L

    def add(c: str):
        if c and c not in out:
            out.append(c)

    for tok in re.findall(r"[A-Za-z0-9]+", raw):
        low = tok.lower()
        if len(low) < 5 or not (re.search(r"[a-z]", low) and re.search(r"\d", low)):
            continue
        if _CODE_NOISE.match(low):
            continue
        add(low)
        m = re.match(r"^([a-z]{0,3})(\d{2,3})([a-z][a-z0-9]{2,})$", low)
        if m and (screen_in is None or abs(int(m.group(2)) - screen_in) <= 1):
            series = m.group(3)
            if re.search(r"\d", series):
                add(series)
                # Samsung India codes end with a region suffix: UE85AH + ULXL / KLXL / UXXL
                core = re.sub(r"([uka]?lxl|[uka]?xxl)$", "", series)
                if core != series and len(core) >= 4:
                    add(core)
    return out


def codes_overlap(src_codes: list[str], cand_codes: list[str]) -> Optional[str]:
    """Return the shared code if one code contains the other (series 'ue85ah' inside 'ue85ahulxl')."""
    for s in src_codes:
        for c in cand_codes:
            if s == c:
                return c
            short, long_ = sorted([s, c], key=len)
            if len(short) >= 4 and long_.startswith(short) or (len(short) >= 6 and short in long_):
                return short
    return None


# ----------------------------------------------------------------------------- apparel facts

def _strip_brand(text: str, brand: Optional[str]) -> str:
    t = clean(text).lower()
    if brand:
        b = re.escape(clean(brand).lower())
        t = re.sub(b, " ", t)
    # brand names that contain garment words
    t = re.sub(r"u\.?\s?s\.?\s?polo\s+ass(n|ociation)\.?", " ", t)
    t = re.sub(r"\bpolo\s+ralph\s+lauren\b", " ", t)
    return t


def apparel_facts(text: str, brand: Optional[str] = None) -> dict[str, str]:
    """Garment type, pattern, fit, sleeve and neck - the things that make two tees 'the same tee'."""
    t = " " + _strip_brand(text, brand).replace("-", " ") + " "
    f: dict[str, str] = {}
    if re.search(r"\bjerseys?\b", t):
        f["type"] = "jersey"
    elif re.search(r"\bpolos?\b|polo collar", t):
        f["type"] = "polo"
    elif re.search(r"\bt ?shirts?\b|\btees?\b|tshirts?", t):
        f["type"] = "tshirt"
    if re.search(r"\bstrip(e|ed|es)\b", t):
        f["pattern"] = "striped"
    elif re.search(r"colou?r ?block", t):
        f["pattern"] = "colourblock"
    elif re.search(r"\b(printed|print|graphic|typography|logo)\b", t):
        f["pattern"] = "printed"
    elif re.search(r"\b(solid|plain|basic)\b", t):
        f["pattern"] = "solid"
    if re.search(r"\bslim\b", t):
        f["fit"] = "slim"
    elif re.search(r"\b(oversized|relaxed|boxy|loose)\b", t):
        f["fit"] = "oversized"
    elif re.search(r"\bmuscle\b", t):
        f["fit"] = "muscle"
    elif re.search(r"\b(regular|classic|standard)\b", t):
        f["fit"] = "regular"
    if re.search(r"\b(polyester|poly|dri.?fit|aeroready|dry.?cell|nylon)\b", t):
        f["material"] = "synthetic"
    elif re.search(r"\b(cotton blend|blended)\b", t):
        f["material"] = "blend"
    elif re.search(r"\bcotton\b", t):
        f["material"] = "cotton"
    if re.search(r"\bsleeveless\b", t):
        f["sleeve"] = "sleeveless"
    elif re.search(r"\b(full|long)\s*sleeves?\b", t):
        f["sleeve"] = "long"
    elif re.search(r"\b(half|short)\s*sleeves?\b", t):
        f["sleeve"] = "short"
    if re.search(r"\bv\s?neck\b", t):
        f["neck"] = "v"
    elif re.search(r"\b(round|crew)\s?neck\b", t):
        f["neck"] = "round"
    elif re.search(r"\bhenley\b", t):
        f["neck"] = "henley"
    elif re.search(r"\b(polo|spread|button.?down)?\s?collar\b", t) or f.get("type") == "polo":
        f["neck"] = "collar"
    return f
