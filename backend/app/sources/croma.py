"""Croma: public search API used by croma.com itself (JSON)."""

from __future__ import annotations

import re

from .. import http
from ..models import Listing
from ..normalize import parse_ram, parse_screen_inches, parse_storage

API = "https://api.croma.com/searchservices/v1/search"
BASE = "https://www.croma.com"


def search(query: str) -> list[Listing]:
    _, data = http.get("croma", API, params={
        "currentPage": 0, "query": f"{query}:relevance", "fields": "FULL",
        "channel": "WEB", "channelCode": "400049", "spellOpt": "DEFAULT",
    }, retries=1, expect_json=True)
    out = []
    for p in (data or {}).get("products", []) or []:
        name = p.get("name") or ""
        text = f"{name} | {p.get('summary') or ''} | {p.get('quickViewDesc') or ''}"
        stock = p.get("stockFlag") or []
        price = (p.get("price") or {}).get("value")
        out.append(Listing(
            platform="croma",
            title=name,
            url=BASE + p.get("url", ""),
            brand=p.get("manufacturer") or name.split()[0],
            ram_gb=parse_ram(name) or parse_ram(text),
            storage_gb=parse_storage(name) or parse_storage(text),
            screen_in=parse_screen_inches(name),
            # Croma's short summary carries the manufacturer code ("E-SONY LED Bravia2 II K-55S25BM2 4K UHD").
            model_number=p.get("summary") or None,
            # Croma lists the stores/warehouses holding stock; an empty list means nothing can be bought.
            available=bool(stock),
            price=price,
            image=p.get("plpImage"),
            extra={"text": re.sub(r"<[^>]+>", " ", text), "code": p.get("code"), "stock_locations": len(stock), "plm_status": p.get("plmStatus")},
        ))
    return out


def enrich(item: Listing) -> Listing:
    return item
