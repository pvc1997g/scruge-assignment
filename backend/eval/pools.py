"""Candidate pools: everything the stores returned for one Amazon product, saved so matchers can be
compared offline on identical input (store search results change from minute to minute).

A pool file (eval/pools/<ASIN>.json.gz) holds:
  source      the Amazon product as parsed
  platforms   per store:
                searches  {query: [listing as the search card showed it, ...]}
                pages     {url: listing after its product page was opened}
                live      what v1 answered during the recording run (status, url)
"""

from __future__ import annotations

import copy
import gzip
import json
import os
import threading
from dataclasses import asdict, fields

from app import http
from app.models import Category, Listing

POOL_DIR = os.path.join(os.path.dirname(__file__), "pools")
_FIELDS = {f.name for f in fields(Listing)}


def to_dict(item: Listing) -> dict:
    d = asdict(item)
    d["category"] = item.category.value if item.category else None
    return d


def from_dict(d: dict) -> Listing:
    d = {k: v for k, v in d.items() if k in _FIELDS}
    if d.get("category"):
        d["category"] = Category(d["category"])
    return Listing(**copy.deepcopy(d))


def pool_path(asin: str) -> str:
    return os.path.join(POOL_DIR, f"{asin}.json.gz")


def load(asin: str) -> dict:
    with gzip.open(pool_path(asin), "rt") as f:
        return json.load(f)


def save(asin: str, pool: dict) -> None:
    os.makedirs(POOL_DIR, exist_ok=True)
    with gzip.open(pool_path(asin), "wt") as f:
        json.dump(pool, f, ensure_ascii=False, separators=(",", ":"))


class RecordingAdapter:
    """Calls the real store adapter and keeps a copy of every search and every opened product page."""

    def __init__(self, real):
        self.real = real
        self.searches: dict[str, list[dict]] = {}
        self.pages: dict[str, dict] = {}
        self._lock = threading.Lock()

    def search(self, query: str) -> list[Listing]:
        found = self.real.search(query)
        with self._lock:
            self.searches[query] = [to_dict(c) for c in found]
        return found

    def enrich(self, item: Listing) -> Listing:
        self.real.enrich(item)
        with self._lock:
            self.pages[item.url] = to_dict(item)
        return item


class ReplayAdapter:
    """Serves a saved pool as if it were the store. A search or page that wasn't recorded behaves like a
    store that didn't answer (FetchError), and is counted so the gap is visible."""

    def __init__(self, platform_pool: dict):
        self.searches = platform_pool["searches"]
        self.pages = platform_pool["pages"]
        self.missing_searches: list[str] = []
        self.missing_pages: list[str] = []

    def search(self, query: str) -> list[Listing]:
        if query not in self.searches:
            self.missing_searches.append(query)
            raise http.FetchError(f"not recorded: search {query!r}")
        return [from_dict(d) for d in self.searches[query]]

    def enrich(self, item: Listing) -> Listing:
        page = self.pages.get(item.url)
        if page is None:
            self.missing_pages.append(item.url)
            raise http.FetchError(f"not recorded: page {item.url}")
        for k, v in from_dict(page).__dict__.items():
            setattr(item, k, v)
        return item


def all_candidates(platform_pool: dict) -> dict[str, Listing]:
    """Every distinct listing in a store's pool, using the opened product page where there is one."""
    out: dict[str, Listing] = {}
    for results in platform_pool["searches"].values():
        for d in results:
            url = d["url"]
            if url not in out:
                out[url] = from_dict(platform_pool["pages"].get(url, d))
    return out
