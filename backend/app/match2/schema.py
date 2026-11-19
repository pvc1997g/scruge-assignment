"""What has to agree, per category. Plain data: adding a category means adding a table here.

Each attribute names a comparison and two flags:
  hard   a conflict rejects the listing outright (a different storage size is a different phone)
  need   the listing must state it; unknown rejects (unless an identifier already settles it)
Soft attributes (hard=False) feed the score instead: stores label garment details inconsistently, so a
"slim" vs "regular" disagreement is evidence against, not proof.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from ..models import Category
from ..normalize import genders_compatible

# A comparison returns True (agree), False (conflict) or None (can't tell).
Compare = Callable[[object, object], Optional[bool]]


def equal(a, b) -> Optional[bool]:
    return None if a is None or b is None else a == b


def within(tolerance: float) -> Compare:
    def cmp(a, b):
        return None if a is None or b is None else abs(a - b) <= tolerance
    return cmp


def wearer(a, b) -> Optional[bool]:
    return None if not a or not b else genders_compatible(a, b)


def shades(a, b) -> Optional[bool]:
    """Two brand shade names agree when they share a distinctive word (prefixes count: mel ~ melange)."""
    if not a or not b:
        return None
    return any(x == y or (min(len(x), len(y)) >= 3 and (x.startswith(y) or y.startswith(x)))
               or _abbreviates(x, y) or _abbreviates(y, x) for x in a for y in b)


def _abbreviates(short: str, long_: str) -> bool:
    """Stores shorten shade names to codes: MVE = MAUVE, NVY = NAVY, CHRC = CHARCOAL. Same first letter, the
    short form's letters appear in order in the long one."""
    if not 3 <= len(short) <= 4 or len(long_) <= len(short) or short[0] != long_[0]:
        return False
    it = iter(long_)
    return all(ch in it for ch in short)


def garment(a, b) -> Optional[bool]:
    # Stores sell football jerseys as plain T-shirts ("ADIDAS Men Graphic Print Crew Neck Red T-Shirt").
    if a is None or b is None:
        return None
    return a == b or {a, b} == {"jersey", "tshirt"}


@dataclass(frozen=True)
class Attr:
    compare: Compare
    hard: bool = True
    need: bool = False


@dataclass(frozen=True)
class Spec:
    attrs: dict
    identifier: Optional[str] = None   # "model_code" (TVs) or "style_code" (shoes, clothes)
    versions: bool = True              # TV names are marketing; their model code decides instead
    versions_required: bool = False    # phones: a listing naming no model number at all is another phone


SCHEMA: dict[Category, dict[str, Attr]] = {
    Category.SMARTPHONE: {
        "storage": Attr(equal, need=True),
        "ram": Attr(equal),          # iPhones never state RAM: model + storage decide
        "network": Attr(equal),      # 5G and 4G versions share names but are different phones
    },
    Category.TV: {
        "screen": Attr(within(1), need=True),   # stores round centimetres differently
    },
    Category.SNEAKERS: {
        "gender": Attr(wearer),
        "pack": Attr(equal),
        "colour_family": Attr(equal, need=True),
        "colour_name": Attr(shades),  # both name a specific shade: WOLF GREY/WHITE is not FOOTBALL GREY/...
    },
    Category.APPAREL: {
        "gender": Attr(wearer),
        "pack": Attr(equal),
        "colour_family": Attr(equal, need=True),
        "colour_name": Attr(shades),
        "garment": Attr(garment),
        "sleeve": Attr(equal, hard=False),
        "neck": Attr(equal, hard=False),
        "fit": Attr(equal, hard=False),
        "pattern": Attr(equal, hard=False),
    },
}


SPECS: dict[Category, Spec] = {
    Category.SMARTPHONE: Spec(SCHEMA[Category.SMARTPHONE], versions_required=True),
    Category.TV: Spec(SCHEMA[Category.TV], identifier="model_code", versions=False),
    Category.SNEAKERS: Spec(SCHEMA[Category.SNEAKERS], identifier="style_code"),
    Category.APPAREL: Spec(SCHEMA[Category.APPAREL], identifier="style_code"),
}
