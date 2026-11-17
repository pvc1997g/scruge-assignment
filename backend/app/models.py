from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


class Category(str, Enum):
    SMARTPHONE = "smartphone"
    TV = "tv"
    SNEAKERS = "sneakers"
    APPAREL = "apparel"  # t-shirts, polos, jerseys


class Status(str, Enum):
    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    NOT_LISTED = "not_listed"
    ERROR = "error"  # we could not check (blocked / site down) - never confuse with NOT_LISTED


PLATFORMS_BY_CATEGORY = {
    Category.SMARTPHONE: ["flipkart", "croma"],
    Category.TV: ["flipkart", "croma"],
    Category.SNEAKERS: ["flipkart", "myntra"],
    Category.APPAREL: ["flipkart", "myntra"],
}


@dataclass
class Listing:
    """One product as seen on any platform (the Amazon source or a candidate)."""

    platform: str
    title: str
    url: str
    brand: Optional[str] = None
    category: Optional[Category] = None
    colour: Optional[str] = None
    ram_gb: Optional[float] = None
    storage_gb: Optional[float] = None
    screen_in: Optional[int] = None
    model_number: Optional[str] = None
    gender: Optional[str] = None
    available: Optional[bool] = None
    price: Optional[float] = None
    image: Optional[str] = None
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["category"] = self.category.value if self.category else None
        d.pop("extra", None)
        return d


@dataclass
class MatchVerdict:
    is_match: bool
    score: float
    reasons: list[str]  # human readable: why it matched / why it was rejected


@dataclass
class PlatformResult:
    platform: str
    status: Status
    url: Optional[str] = None
    title: Optional[str] = None
    price: Optional[float] = None
    image: Optional[str] = None
    confidence: Optional[float] = None
    reasons: list[str] = field(default_factory=list)
    query: Optional[str] = None
    candidates_checked: int = 0
    error: Optional[str] = None
    note: Optional[str] = None  # caveat shown on the card, e.g. "found in a different colour"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d
