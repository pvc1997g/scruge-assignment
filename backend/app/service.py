"""Glue: Amazon link -> source product -> search each platform -> match -> status."""

from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from . import http
from .matcher import match, source_model_tokens
from .models import PLATFORMS_BY_CATEGORY, Category, Listing, PlatformResult, Status
from .normalize import (
    apparel_facts, brands_match, codes_overlap, colour_words, colours_match, genders_compatible,
    is_multipack, model_codes, model_tokens, network_gen,
)
from .sources import amazon, croma, flipkart, myntra

log = logging.getLogger("scruge")

ADAPTERS = {"flipkart": flipkart, "croma": croma, "myntra": myntra}
MAX_ENRICH = 8  # product pages opened per query (Flipkart hides colour / TV model codes on search cards)

_cache: dict[str, tuple[float, dict]] = {}
_cache_lock = threading.Lock()
CACHE_TTL = 15 * 60


# ----------------------------------------------------------------------------- queries

def build_queries(src: Listing, platform: str) -> list[str]:
    brand = src.brand or ""
    model = " ".join(source_model_tokens(src) if src.category == Category.SMARTPHONE else model_tokens(src.title, src.brand))
    qs: list[str] = []
    if src.category == Category.SMARTPHONE:
        ram = f" {src.ram_gb:g}GB RAM" if src.ram_gb else ""
        sto = f" {src.storage_gb:g}GB" if src.storage_gb else ""
        colour = f" {src.colour}" if src.colour else ""
        qs += [f"{brand} {model}{ram}{sto}", f"{brand} {model}{colour}{sto}", f"{brand} {model}"]
    elif src.category == Category.TV:
        codes = model_codes(" ".join(filter(None, [src.model_number or "", src.title])), src.screen_in)
        size = f" {src.screen_in} inch" if src.screen_in else ""
        if src.model_number and re.fullmatch(r"[A-Za-z0-9-]{5,20}", src.model_number.strip()):
            qs.append(src.model_number.strip())    # as written: L32MB-FIN, K-55S25BM2
        if codes:
            qs.append(codes[0].upper())            # full code: UA55UE85AHULXL
            if len(codes) > 1:
                series_code = min(codes[1:], key=len)  # shortest series form: UE85AH
                qs.append(f"{brand} {series_code.upper()}{size}")
        series = " ".join(model_tokens(src.title, src.brand, cut_at_paren=False)[:4])
        qs.append(f"{brand} {series}{size} tv")
    elif src.category == Category.SNEAKERS:
        colour = (colour_words(src.colour) or [""])[0].replace("offwhite", "off white")
        gender = {"men": " men", "women": " women"}.get(src.gender or "", "")
        # Myntra's search leans on the product type: "nike revolution 8" misfires, "... running shoes" works.
        kind = next((k for k in ("running shoes", "walking shoes", "casual shoes", "basketball shoes", "sneakers")
                     if k in src.title.lower() or (k == "sneakers" and "sneaker" in src.title.lower())), "shoes")
        qs += [f"{brand} {model} {colour}{gender}".strip(), f"{brand} {model} {kind}".strip(), f"{brand} {model}".strip()]
    else:
        f = apparel_facts(src.title, src.brand)
        colour = (colour_words(src.colour) or [""])[0].replace("offwhite", "off white")
        gender = {"men": "men", "women": "women", "kids": "kids"}.get(src.gender or "", "")
        garment = {"polo": "polo t-shirt", "jersey": "jersey", "tshirt": "t-shirt"}.get(f.get("type", ""), "t-shirt")
        pattern = f.get("pattern", "")
        if f.get("type") == "jersey":
            # Jerseys are named by team/event: "India Official T20 International Cricket Fan"
            words = [t for t in model_tokens(src.title, src.brand, cut_at_paren=False)
                     if len(t) > 1 and t not in _JERSEY_QUERY_NOISE]
            qs.append(f"{brand} {' '.join(words[:5])} jersey")
            # Stores often sell kits as plain T-shirts; the line name + colour finds those ("adidas tiro jersey men blue").
            line = [w for w in words if not w.isdigit()][:2]
            if line:
                qs.append(f"{brand} {' '.join(line)} jersey {gender} {colour}")
        qs += [f"{brand} {gender} {colour} {pattern} {garment}", f"{brand} {gender} {garment}"]
    # de-dupe, keep order
    seen, out = set(), []
    for q in qs:
        q = " ".join(q.split())
        if q and q.lower() not in seen:
            seen.add(q.lower())
            out.append(q)
    return out


# ----------------------------------------------------------------------------- per platform

def _apparel_prefilter(src: Listing, cand: Listing) -> bool:
    """Worth opening this product page? Same brand, same kind of garment, compatible colour and wearer."""
    if not (brands_match(src.brand, cand.brand) or brands_match(src.brand, cand.title.split()[0] if cand.title else "")):
        return False
    st, ct = apparel_facts(src.title, src.brand).get("type"), apparel_facts(cand.title, cand.brand).get("type")
    if st and ct and st != ct and {st, ct} != {"jersey", "tshirt"}:
        return False
    if is_multipack(cand.title):
        return False
    if colours_match(src.colour, cand.colour or cand.title)[0] is False:
        return False
    return genders_compatible(src.gender, cand.gender)


_JERSEY_QUERY_NOISE = {"official", "fan", "polyester", "regular", "slim", "fit", "round", "neck", "crew", "football",
                       "soccer", "cricket", "breathable", "jsy", "printed", "graphic", "replica", "kit", "half", "sleeve",
                       "sleeves", "short", "dry", "quick"}
_SHOE_MATERIALS = {"leather", "ltr", "suede", "canvas", "mesh", "synthetic", "knit", "textile"}


def _shoe_shortlist(src: Listing, items: list[Listing]) -> list[Listing]:
    """Shoe listings worth opening: those whose title already passes on brand + model (colour unknown yet),
    then same-brand listings whose title names no model at all ("Nike Women Leather Sneakers"), because
    Myntra keeps the model in a collection field on the product page."""
    named, unnamed = [], []
    for c in items:
        if not (brands_match(src.brand, c.brand) or brands_match(src.brand, c.title.split()[0] if c.title else "")):
            continue
        if not genders_compatible(src.gender, c.gender) or colours_match(src.colour, c.colour or c.title)[0] is False:
            continue
        if _quick_prefilter(src, c):
            named.append(c)
        elif not [t for t in model_tokens(c.title, c.brand, cut_at_paren=False) if t not in _SHOE_MATERIALS]:
            unnamed.append(c)
    return named + unnamed


def _quick_prefilter(src: Listing, cand: Listing) -> bool:
    """Cheap check before opening a product page: does brand+model already pass (ignoring colour)?"""
    probe = Listing(**{**cand.__dict__, "colour": src.colour})  # pretend colour matches
    return match(src, probe).is_match


PLATFORM_NAMES = {"flipkart": "Flipkart", "croma": "Croma", "myntra": "Myntra"}


def unreachable(platform: str, error: str, query: Optional[str] = None) -> PlatformResult:
    """The brief allows three results, so a site we couldn't reach is 'Not listed', with a note saying why."""
    name = PLATFORM_NAMES[platform]
    return PlatformResult(
        platform=platform, status=Status.NOT_LISTED, query=query, error=error,
        note=f"{name} didn't respond, so we couldn't check it. Try again in a minute.",
        reasons=[f"Couldn't reach {name} ({error}), so this is not a confirmed 'not listed'."],
    )


def check_platform(src: Listing, platform: str) -> PlatformResult:
    adapter = ADAPTERS[platform]
    queries = build_queries(src, platform)
    errors: list[str] = []
    candidates: dict[str, Listing] = {}
    used_query = None
    matches: list[tuple[float, Listing, list[str]]] = []
    rejections: list[str] = []

    for q in queries:
        try:
            found = adapter.search(q)
        except http.FetchError as e:
            errors.append(str(e))
            continue
        used_query = used_query or q
        new = [c for c in found if c.url not in candidates]
        for c in new:
            candidates[c.url] = c

        # Flipkart search cards don't show colour (fashion) or model codes (TVs): open the
        # product pages of plausible candidates to read those facts before matching.
        if src.category == Category.APPAREL:
            # Garment facts live on product pages (both stores): open the plausible ones first. With a style
            # code to look for, open more of them: a code match settles it even when the title says nothing.
            shortlist = [c for c in new if _apparel_prefilter(src, c)]
            cap = MAX_ENRICH * 2 if src.model_number else MAX_ENRICH
            if src.model_number and apparel_facts(src.title, src.brand).get("type") == "jersey":
                cap = MAX_ENRICH * 3  # kits hide behind generic "Men Striped Crew Neck T-Shirt" titles
            with ThreadPoolExecutor(max_workers=6) as ex:
                list(ex.map(_safe_enrich(adapter), shortlist[:cap]))
        elif src.category == Category.SNEAKERS:
            with ThreadPoolExecutor(max_workers=6) as ex:
                list(ex.map(_safe_enrich(adapter), _shoe_shortlist(src, new)[:MAX_ENRICH]))
        elif platform == "flipkart" and src.category == Category.TV:
            # Flipkart cards hide TV model codes: open same brand + size listings with no *different* code in the title.
            src_codes = model_codes(" ".join(filter(None, [src.model_number or "", src.title])), src.screen_in)
            shortlist = [c for c in new if brands_match(src.brand, c.brand)
                         and c.screen_in is not None and src.screen_in is not None
                         and abs(c.screen_in - src.screen_in) <= 1
                         and (not model_codes(c.title, c.screen_in) or codes_overlap(src_codes, model_codes(c.title, c.screen_in)))]
            with ThreadPoolExecutor(max_workers=4) as ex:
                list(ex.map(_safe_enrich(adapter), shortlist[:MAX_ENRICH]))

        found_here = False
        for c in new:
            v = match(src, c)
            if v.is_match and src.category == Category.APPAREL and not c.extra.get("specs"):
                # Never accept a garment on its title alone: read its spec table, then judge again.
                _safe_enrich(adapter)(c)
                v = match(src, c)
            if not v.is_match:
                rejections.append(f"{c.title[:70]} → {v.reasons[-1]}")
                continue
            matches.append((v.score, c, v.reasons))
            found_here = True
        if found_here:
            used_query = q
        if matches:
            # Phones are sold once per colour: keep searching (colour-specific query next) until we find the
            # Amazon colour. Clothes matched on details alone (no style code) also keep searching, because a
            # closer listing may only show up in a later, broader search.
            if src.category == Category.SMARTPHONE:
                done = best_tier(src, matches) == 2
            elif src.category == Category.APPAREL:
                done = any(score >= 0.99 for score, _, _ in matches)
            else:
                done = True
            if done:
                break

    best = pick_best(src, matches) if matches else None

    if best is None:
        if errors and not candidates:
            return unreachable(platform, "; ".join(errors[:2]), query=queries[0] if queries else None)
        reasons = ["No listing passed all the checks."] + rejections[:4]
        note = None
        if errors:
            note = (f"{PLATFORM_NAMES[platform]} didn't answer every search, so this may be incomplete. "
                    "Try again in a minute.")
        return PlatformResult(platform=platform, status=Status.NOT_LISTED, query=used_query,
                              candidates_checked=len(candidates), reasons=reasons, note=note,
                              error="; ".join(errors[:2]) or None)

    score, item, reasons = best
    note = None
    if src.category == Category.SMARTPHONE and src.colour:
        tier = colour_tier(src, item)
        if tier == 2:
            reasons = reasons + [f"same colour ({src.colour})"]
        elif tier == 1:
            reasons = reasons + [f"similar colour ({src.colour} ≈ {_variant_colour(item)})"]
        else:
            note = (f"Same model, RAM and storage, but in {_variant_colour(item) or 'a different colour'}: "
                    f"the {src.colour} version isn't listed here.")
            reasons = reasons + [f"{src.colour} not found; showing the closest variant"]
            score *= 0.9
    # Confirm stock on the product page when the search card couldn't tell us. A platform can list
    # the same variant more than once (different sellers / chip variants): if the first is sold
    # out, check up to two more equally good listings before calling it out of stock.
    if item.available is None or platform == "flipkart":
        same_rank = [m for m in sorted(matches, key=_rank_key(src), reverse=True)
                     if _rank_key(src)(m)[:3] == _rank_key(src)(best)[:3]][:3]
        for i, (s, cand, why) in enumerate(same_rank):
            try:
                adapter.enrich(cand)
            except http.FetchError as e:
                if i == 0:
                    reasons = reasons + [f"couldn't open product page to confirm stock ({e})"]
                continue
            if i == 0 or cand.available:
                score, item = s, cand
                if i > 0:
                    reasons = why + [r for r in reasons if r not in why and "colour" in r]
            if cand.available:
                break
    if item.available is None:
        reasons = reasons + ["stock not stated; listing is live so treating as buyable"]
    status = Status.OUT_OF_STOCK if item.available is False else Status.IN_STOCK
    if status == Status.OUT_OF_STOCK and src.category == Category.SMARTPHONE and note is None:
        sold_out = _variant_colour(item).lower()
        others = sorted({_variant_colour(c) for _, c, _ in matches
                         if c.available is not False and _variant_colour(c)
                         and _variant_colour(c).lower() != sold_out})
        if others:
            note = f"This colour is sold out, but the same model is available in {', '.join(others[:3])}."
    return PlatformResult(
        platform=platform, status=status, url=item.url, title=item.title, price=item.price, image=item.image,
        confidence=round(min(score, 1.0), 2), reasons=reasons, query=used_query, candidates_checked=len(candidates),
        note=note,
    )


# ----------------------------------------------------------------------------- colour variants (phones)

def _variant_colour(c: Listing) -> str:
    """Colour of a phone listing: explicit field, else the colour inside the title's brackets."""
    if c.colour:
        return c.colour
    m = re.search(r"\(([^)]*)\)", c.title)
    if not m:
        return ""
    parts = [p.strip() for p in m.group(1).split(",")]
    named = [p for p in parts if not re.search(r"\d", p)]
    return named[0] if named else ""


def colour_tier(src: Listing, c: Listing) -> int:
    """2 = exact colour name, 1 = same base colour, 0 = different / unknown."""
    if not src.colour:
        return 0
    norm = lambda s: "".join(ch for ch in s.lower() if ch.isalnum())
    cand_colour = _variant_colour(c)
    if norm(src.colour) and (norm(src.colour) == norm(cand_colour) or norm(src.colour) in norm(c.title)):
        return 2
    if cand_colour and colours_match(src.colour, cand_colour)[0]:
        return 1
    return 0


def best_tier(src: Listing, matches: list) -> int:
    if src.category != Category.SMARTPHONE:
        return 2
    return max(colour_tier(src, c) for _, c, _ in matches)


def _rank_key(src: Listing):
    def key(m):
        score, c, _ = m
        phone = src.category == Category.SMARTPHONE
        tier = colour_tier(src, c) if phone else 0
        # A listing that states the same network (REDMI A7 Pro 5G) beats one that doesn't say (REDMI A7 Pro).
        net = int(phone and network_gen(src.title) is not None and network_gen(c.title) == network_gen(src.title))
        return (net, tier, round(score, 2), c.available is not False, c.available is True)
    return key


def pick_best(src: Listing, matches: list):
    """Phones: same colour first, then match score, then buyable. Others: score, then buyable."""
    return max(matches, key=_rank_key(src))


def _safe_enrich(adapter):
    def run(item: Listing):
        try:
            adapter.enrich(item)
        except http.FetchError:
            pass
        return item
    return run


# ----------------------------------------------------------------------------- entry point

def compare(url: str, use_cache: bool = True) -> dict:
    t0 = time.time()
    asin = amazon.resolve_asin(url)
    with _cache_lock:
        hit = _cache.get(asin)
    if use_cache and hit and time.time() - hit[0] < CACHE_TTL:
        return {**hit[1], "cached": True}

    src = amazon.fetch_product(url)
    platforms = PLATFORMS_BY_CATEGORY[src.category]
    with ThreadPoolExecutor(max_workers=len(platforms)) as ex:
        results = list(ex.map(lambda p: _guarded(src, p), platforms))

    payload = {
        "source": src.to_dict(),
        "results": [r.to_dict() for r in results],
        "elapsed_ms": int((time.time() - t0) * 1000),
        "cached": False,
    }
    with _cache_lock:
        _cache[asin] = (time.time(), payload)
    return payload


def _guarded(src: Listing, platform: str) -> PlatformResult:
    # A site that didn't answer at all gets one more full attempt with a fresh session
    # before we fall back to "Not listed, couldn't check".
    result = None
    for attempt in range(2):
        try:
            result = check_platform(src, platform)
        except Exception as e:  # never let one platform break the whole response
            log.exception("platform %s failed", platform)
            result = unreachable(platform, f"{type(e).__name__}: {e}")
        if not (result.error and result.candidates_checked == 0):
            return result
        http.reset_session(platform)
        time.sleep(1.5)
    return result
