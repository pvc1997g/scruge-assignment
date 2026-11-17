"""Flipkart: search results page (server-rendered HTML) + product page for stock/colour."""

from __future__ import annotations

import html as htmllib
import json
import re
from typing import Optional
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from .. import http
from ..models import Listing
from ..normalize import (
    apparel_facts_from_specs, clean, parse_gender, parse_ram, parse_screen_inches, parse_storage,
)

BASE = "https://www.flipkart.com"
UNAVAILABLE = re.compile(r"currently unavailable|sold out|coming soon|out of stock|temporarily unavailable", re.I)
NOISE = re.compile(r"^(add to compare|currently unavailable|sold out|coming soon|hot deal|bank offer|only \d+ left|only few left|sponsored|assured|trending|bestseller|new|\d+% off|₹.*|[\d.,]+|free delivery.*)$", re.I)


def _clean_url(href: str) -> str:
    href = htmllib.unescape(href)
    p = urlparse(href)
    pid = parse_qs(p.query).get("pid", [None])[0]
    return f"{BASE}{p.path}" + (f"?pid={pid}" if pid else "")


def _price(segments: list[str]) -> Optional[float]:
    for s in segments:
        m = re.match(r"^₹\s?([\d,]+)$", s)
        if m:
            return float(m.group(1).replace(",", ""))
    return None


def search(query: str) -> list[Listing]:
    r, _ = http.get("flipkart", f"{BASE}/search", params={"q": query, "otracker": "search", "marketplace": "FLIPKART"}, retries=1)
    soup = BeautifulSoup(r.text, "lxml")
    out: list[Listing] = []
    seen: set[str] = set()
    for a in soup.select('a[href*="/p/itm"]'):
        card = a.find_parent("div", attrs={"data-id": True})
        if card is None:
            continue
        pid = card["data-id"]
        if pid in seen:
            continue
        seen.add(pid)
        segments = [clean(s) for s in card.stripped_strings]
        segments = [s for s in segments if s]
        unavailable = any(UNAVAILABLE.search(s) for s in segments)

        # Grid layout (fashion): "BRAND | Product name | ₹price"; the product link carries a title attribute.
        titled = card.select_one('a[href*="/p/itm"][title]')
        brand = None
        if titled:
            name = clean(titled["title"])
            try:
                idx = segments.index(name)
                brand = segments[idx - 1] if idx > 0 and not NOISE.match(segments[idx - 1]) else None
            except ValueError:
                brand = segments[0] if segments and not NOISE.match(segments[0]) else None
            title = f"{brand} {name}" if brand and not name.lower().startswith(brand.lower()) else name
        else:
            # Row layout (electronics): first meaningful line is the full title.
            img = card.select_one("img[alt]")
            title = clean(img["alt"]) if img and len(img.get("alt", "")) > 10 else next(
                (s for s in segments if len(s) > 15 and not NOISE.match(s)), "")
        if not title:
            continue
        href = card.select_one('a[href*="/p/itm"]')["href"]
        spec = " | ".join(segments)
        out.append(Listing(
            platform="flipkart",
            title=title,
            url=_clean_url(href),
            brand=brand or title.split()[0],
            ram_gb=parse_ram(spec),
            storage_gb=parse_storage(spec),
            screen_in=parse_screen_inches(title) or parse_screen_inches(spec),
            gender=parse_gender(title),
            available=False if unavailable else None,  # None = confirm on the product page
            price=_price(segments),
            image=(card.select_one("img") or {}).get("src") if card.select_one("img") else None,
            extra={"pid": pid, "card_text": spec[:300]},
        ))
    return out


_SPEC_PAIR = re.compile(r'"label_1":\{"value":\{"text":\["([^"]+)"\]\}\},"label_0":\{"value":\{"text":"([^"]+)"\}\}')
_SPEC_PAIR_REV = re.compile(r'"label_0":\{"value":\{"text":"([^"]+)"\}\}[^{}]{0,20},"label_1":\{"value":\{"text":\["([^"]+)"\]\}\}')


def enrich(item: Listing) -> Listing:
    """Open the product page: definitive stock status + colour/brand/specs."""
    r, _ = http.get("flipkart", item.url, retries=1)
    t = r.text
    m = re.search(r'"availabilityStatus":"([A-Z_]+)"', t)
    if m:
        item.available = m.group(1) == "IN_STOCK"
        item.extra["availability_status"] = m.group(1)
    elif UNAVAILABLE.search(t[:200000]) and "Sold Out" in t:
        item.available = False

    specs: dict[str, str] = {}
    for val, key in _SPEC_PAIR.findall(t):
        specs.setdefault(key.lower(), val)
    for key, val in _SPEC_PAIR_REV.findall(t):
        specs.setdefault(key.lower(), val)
    item.extra["specs"] = {k: specs[k] for k in list(specs)[:40]}
    item.extra["facts"] = apparel_facts_from_specs(specs)

    colour = specs.get("color") or specs.get("colour") or specs.get("brand color")
    if colour:
        item.colour = colour
    if specs.get("brand"):
        item.brand = specs["brand"]
    model = specs.get("model name") or specs.get("model id") or specs.get("model number") or specs.get("style code")
    if model:
        item.model_number = model
    if item.ram_gb is None and specs.get("ram"):
        item.ram_gb = parse_ram(specs["ram"] + " RAM")
    if item.storage_gb is None and specs.get("internal storage"):
        item.storage_gb = parse_storage(specs["internal storage"] + " storage")

    soup = BeautifulSoup(t, "lxml")
    for sc in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(sc.get_text())
        except Exception:
            continue
        for obj in data if isinstance(data, list) else [data]:
            if isinstance(obj, dict) and obj.get("@type") == "Product":
                if obj.get("brand", {}).get("name"):
                    item.brand = item.brand or obj["brand"]["name"]
                desc = obj.get("description") or ""
                item.extra["description"] = desc[:300]
                if not item.colour:
                    mc = re.search(r"\(([A-Za-z /]+?)(?:,|\))", obj.get("name", ""))
                    if mc:
                        item.colour = mc.group(1)
    if item.gender is None:
        item.gender = parse_gender(item.title)
    return item
