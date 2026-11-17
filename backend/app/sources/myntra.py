"""Myntra: search page embeds its results as JSON (window.__myx)."""

from __future__ import annotations

import json
import re
import threading
from urllib.parse import quote

from .. import http
from ..models import Listing
from ..normalize import apparel_facts_from_specs, parse_gender

BASE = "https://www.myntra.com"
_warm = threading.Event()


def _warm_up():
    # Myntra sets session cookies on the homepage; its search responses depend on them.
    if not _warm.is_set():
        http.get("myntra", BASE + "/", retries=1)
        _warm.set()


def _parse_products(products: list[dict]) -> list[Listing]:
    out = []
    for p in products:
        inv = p.get("inventoryInfo") or []
        available = any(i.get("available") for i in inv) if inv else None
        name = p.get("productName") or p.get("product") or ""
        out.append(Listing(
            platform="myntra",
            title=name,
            url=f"{BASE}/{p.get('landingPageUrl', '').lstrip('/')}",
            brand=p.get("brand"),
            colour=p.get("primaryColour") or p.get("baseColour"),
            gender=parse_gender(p.get("gender")) or parse_gender(name),
            available=available,
            price=p.get("price"),
            image=(p.get("searchImage") or ""),
            extra={"id": p.get("productId"), "article_type": (p.get("articleType") or {}).get("typeName") if isinstance(p.get("articleType"), dict) else p.get("articleType")},
        ))
    return out


def search(query: str) -> list[Listing]:
    _warm_up()
    slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")
    r, _ = http.get("myntra", f"{BASE}/{slug}", params={"rawQuery": query}, retries=1)
    m = re.search(r"window\.__myx\s*=\s*(\{.*?\})\s*</script>", r.text, re.S)
    if m:
        try:
            data = json.loads(m.group(1))
            products = ((data.get("searchData") or {}).get("results") or {}).get("products") or []
            return _parse_products(products)
        except json.JSONDecodeError:
            pass
    # Fallback: the JSON search endpoint the site's own frontend calls.
    _, data = http.get("myntra", f"{BASE}/gateway/v2/search/{quote(query)}", params={"rows": 50, "o": 0}, retries=1, expect_json=True)
    return _parse_products((data or {}).get("products") or [])


def enrich(item: Listing) -> Listing:
    """Open the product page for its spec table (fit, neck, sleeve, pattern, fabric) and live sizes."""
    if item.extra.get("enriched"):
        return item
    _warm_up()
    r, _ = http.get("myntra", item.url, retries=1)
    m = re.search(r"window\.__myx\s*=\s*(\{.*?\})\s*</script>", r.text, re.S)
    if not m:
        return item
    try:
        pdp = (json.loads(m.group(1)).get("pdpData") or {})
    except json.JSONDecodeError:
        return item
    attrs = pdp.get("articleAttributes") or {}
    item.extra["specs"] = attrs
    item.extra["facts"] = apparel_facts_from_specs(attrs)
    item.colour = item.colour or pdp.get("baseColour")
    sizes = pdp.get("sizes") or []
    if sizes:
        item.available = any(s.get("available") for s in sizes)
    item.extra["enriched"] = True
    return item
