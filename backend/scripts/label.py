"""Label candidate pairs in saved pools: is this listing the same product as the Amazon one?

  show ASIN            print the Amazon product and every unlabelled same-brand listing, numbered
  auto [ASIN ...]      label plain factual clashes 'different' (storage, RAM, screen, wearer, pack, accessory)
  set ASIN PLATFORM same=1,4 unsure=7 [--rest-different]
                       label by the numbers 'show' printed; --rest-different labels the other shown ones different
  fix ASIN PLATFORM LABEL URL-PART [URL-PART ...]
                       change existing labels (matched by a unique part of the URL)

What "same product" means (the brief's definition): same brand and model, plus RAM and storage for phones,
screen size for TVs, and colour for shoes and clothes. Colour is compared as precisely as both sides state
it: Amazon "Grey" matches any grey listing; Amazon "BLACK/CITRON" doesn't match "BLACK/NEW LEAF".

Labels go to eval/labels.jsonl (one JSON object per line, later lines win). The auto rules use only stated
facts, never the matcher, so the labels don't inherit the matcher's mistakes.
"""

import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models import Category  # noqa: E402
from app.normalize import (  # noqa: E402
    apparel_facts, brands_match, colours_match, core_style_code, genders_compatible, is_multipack, model_tokens,
)
from eval import pools  # noqa: E402

# Test links are labelled blind: no matcher's answer is shown.
_SPLITS = os.path.join(os.path.dirname(__file__), "..", "eval", "splits.json")
BLIND = set(json.load(open(_SPLITS)).get("test2", [])) if os.path.exists(_SPLITS) else set()
LABELS = os.path.join(os.path.dirname(__file__), "..", "eval", "labels.jsonl")
ACCESSORY = re.compile(r"\b(back panel|back glass|case|cover|screen guard|tempered|protector|charger|cable|"
                       r"remote|wall mount|stand|lens ring|flex|spare|skin|sticker|insole|laces|socks)\b", re.I)


def load() -> dict:
    out = {}
    if os.path.exists(LABELS):
        for line in open(LABELS):
            if line.strip():
                d = json.loads(line)
                out[(d["asin"], d["platform"], d["url"])] = d
    return out


def append(rows: list[dict]) -> None:
    with open(LABELS, "a") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def same_brand(src, c) -> bool:
    return brands_match(src.brand, c.brand) or brands_match(src.brand, c.title.split()[0] if c.title else "")


def pack_of(c) -> bool:
    return is_multipack(c.title) or str(c.extra.get("pack_of") or "1").strip() not in ("", "1")


def code_shape(code: str) -> str:
    return re.sub(r"\d+", "9", re.sub(r"[a-z]+", "a", code))


def comparable_codes(a: str, b: str) -> bool:
    """Two style codes from the same numbering system: same letter/digit shape (HR4608 vs KG9454), or one is
    the other plus a colour suffix (607096 vs 60709601). UDOEN1POLO123 vs UDTSH3158 are different systems."""
    if not (a and b and len(a) >= 6 and len(b) >= 6):
        return False
    return code_shape(a) == code_shape(b) or a.startswith(b) or b.startswith(a)


def factual_clash(src, c):
    """A reason the listing is plainly a different product, from stated facts only; else None."""
    cat = src.category
    # An accessory has none of the product's core facts ("SAMSUNG 45W Charger"); a TV whose title mentions its
    # "Voice Control Remote" still has a screen size.
    core = {Category.SMARTPHONE: c.storage_gb, Category.TV: c.screen_in}.get(cat, True)
    if ACCESSORY.search(c.title) and not ACCESSORY.search(src.title) and not (core and cat in (Category.SMARTPHONE, Category.TV)):
        return "accessory, not the product"
    if cat == Category.SMARTPHONE:
        if src.storage_gb and c.storage_gb and src.storage_gb != c.storage_gb:
            return f"storage {src.storage_gb:g} vs {c.storage_gb:g}"
        if src.ram_gb and c.ram_gb and src.ram_gb != c.ram_gb:
            return f"RAM {src.ram_gb:g} vs {c.ram_gb:g}"
    elif cat == Category.TV:
        if not c.screen_in:
            return "not a TV (no screen size)"
        if src.screen_in and c.screen_in and abs(src.screen_in - c.screen_in) > 1:
            return f"screen {src.screen_in} vs {c.screen_in}"
    else:
        if not genders_compatible(src.gender, c.gender):
            return f"wearer {src.gender} vs {c.gender}"
        if pack_of(c) and not is_multipack(src.title):
            return "multi-pack"
        # A manufacturer style code names one article in one colour.
        a, b = core_style_code(src.model_number), core_style_code(c.model_number)
        if comparable_codes(a, b):
            if a == b:
                return None
            if not (a.startswith(b) or b.startswith(a)):
                return f"style code {a} vs {b}"
            # 607096 vs 60709601: same article, colour suffix; the colour check below decides.
        if colours_match(src.colour, c.colour)[0] is False:
            return colours_match(src.colour, c.colour)[1]
        if cat == Category.APPAREL:
            st, ct = apparel_facts(src.title).get("type"), apparel_facts(c.title).get("type")
            if st and ct and st != ct and {st, ct} != {"jersey", "tshirt"}:
                return f"garment {st} vs {ct}"
    if cat == Category.SMARTPHONE:
        nums = {t for t in model_tokens(src.extra.get("model_name") or src.title, src.brand) if any(ch.isdigit() for ch in t)}
        ctoks = set(model_tokens(c.title, c.brand))
        if nums and not nums & ctoks:
            return f"model number {sorted(nums)} not in listing"
    return None


def factual_same(src, c):
    """Identical manufacturer style code (shoes, clothes): the same article."""
    if src.category in (Category.SNEAKERS, Category.APPAREL):
        a, b = core_style_code(src.model_number), core_style_code(c.model_number)
        if comparable_codes(a, b):
            if a == b:
                return f"style code {a} = {b}"
            if (a.startswith(b) or b.startswith(a)) and colours_match(src.colour, c.colour)[0]:
                return f"style code {a} ~ {b} and colour {c.colour}"
    return None


def pending(asin: str, labels: dict):
    """Unlabelled same-brand listings per store, in a stable order."""
    pool = pools.load(asin)
    src = pools.from_dict(pool["source"])
    out = {}
    for platform, pp in pool["platforms"].items():
        cands = pools.all_candidates(pp)
        fashion = src.category in (Category.SNEAKERS, Category.APPAREL)
        # Shoes and clothes can't be judged from a search card; only opened product pages are labelled.
        out[platform] = [(u, c) for u, c in sorted(cands.items())
                         if same_brand(src, c) and (asin, platform, u) not in labels
                         and (not fashion or u in pp["pages"])]
    return pool, src, out


def describe(c, opened: bool) -> str:
    e = c.extra
    bits = [f"colour={c.colour}" if c.colour else "", f"brandcol={e.get('brand_colour')}" if e.get("brand_colour") else "",
            f"ram={c.ram_gb:g}" if c.ram_gb else "", f"sto={c.storage_gb:g}" if c.storage_gb else "",
            f"scr={c.screen_in}" if c.screen_in else "", f"g={c.gender}" if c.gender else "",
            f"code={c.model_number}" if c.model_number else "", f"model={e.get('model_name')}" if e.get("model_name") else "",
            f"coll={e.get('collection')}" if e.get("collection") else "",
            f"pack={e.get('pack_of')}" if e.get("pack_of") not in (None, "1", 1) else "",
            "" if opened else "(page not opened)"]
    return " ".join(b for b in bits if b)


def show(asin: str):
    labels = load()
    pool, src, todo = pending(asin, labels)
    print(f"=== {asin} {src.category.value} | {src.title[:150]}")
    print(f"    brand={src.brand} colour={src.colour} ram={src.ram_gb} sto={src.storage_gb} scr={src.screen_in} "
          f"code={src.model_number} g={src.gender} model={src.extra.get('model_name')}")
    for platform, items in todo.items():
        pages = pool["platforms"][platform]["pages"]
        live = pool["platforms"][platform]["live"]
        answer = "hidden (test2)" if asin in BLIND else f"{live['status']} {str(live['url'])[-30:]}"
        print(f"  -- {platform}: {len(items)} to label (live v1 answer: {answer})")
        for i, (u, c) in enumerate(items, 1):
            text = (c.extra.get("text") or "")[:120].replace("\n", " ")
            print(f"  {i:3}. {c.title[:110]}")
            print(f"       {describe(c, u in pages)}  ...{u[-28:]}")
            if text and platform != "flipkart":
                print(f"       text: {text}")


def auto(asins: list[str]):
    labels = load()
    rows = []
    for asin in asins:
        _, src, todo = pending(asin, labels)
        for platform, items in todo.items():
            for u, c in items:
                why = factual_clash(src, c)
                if why:
                    rows.append({"asin": asin, "platform": platform, "url": u, "label": "different", "why": why, "by": "auto"})
                elif factual_same(src, c):
                    rows.append({"asin": asin, "platform": platform, "url": u, "label": "same", "why": factual_same(src, c), "by": "auto"})
    append(rows)
    print(f"auto-labelled {len(rows)} pairs 'different'")


def set_labels(asin: str, platform: str, specs: list[str]):
    labels = load()
    _, _, todo = pending(asin, labels)
    items = todo[platform]
    chosen = {}
    rest = "--rest-different" in specs
    for spec in specs:
        if "=" not in spec:
            continue
        lab, nums = spec.split("=", 1)
        for n in nums.split(","):
            if n.strip():
                chosen[int(n)] = lab
    rows = []
    for i, (u, c) in enumerate(items, 1):
        lab = chosen.get(i) or ("different" if rest else None)
        if lab:
            rows.append({"asin": asin, "platform": platform, "url": u, "label": lab, "by": "hand", "title": c.title[:80]})
    append(rows)
    print(f"{asin} {platform}: labelled {len(rows)} ({sum(r['label'] == 'same' for r in rows)} same)")


def fix(asin: str, platform: str, lab: str, parts: list[str]):
    pool = pools.load(asin)
    cands = pools.all_candidates(pool["platforms"][platform])
    rows = []
    for part in parts:
        hits = [u for u in cands if part in u]
        if len(hits) != 1:
            print(f"  {part!r} matches {len(hits)} listings, skipped")
            continue
        rows.append({"asin": asin, "platform": platform, "url": hits[0], "label": lab, "by": "hand-fix",
                     "title": cands[hits[0]].title[:80]})
    append(rows)
    print(f"{asin} {platform}: {len(rows)} relabelled {lab}")


def main():
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "show":
        for a in args:
            show(a)
    elif cmd == "auto":
        asins = args or sorted(os.path.basename(p).split(".")[0] for p in glob.glob(os.path.join(pools.POOL_DIR, "*.json.gz")))
        auto(asins)
    elif cmd == "fix":
        fix(args[0], args[1], args[2], args[3:])
    elif cmd == "set":
        set_labels(args[0], args[1], args[2:])


if __name__ == "__main__":
    main()
