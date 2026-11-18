"""Read an Amazon.in product page and turn it into a structured Listing."""

from __future__ import annotations

import re
import time
from typing import Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .. import http
from ..models import Category, Listing
from ..normalize import (
    apparel_facts_from_specs, clean, parse_gender, parse_ram, parse_screen_inches, parse_storage,
)


class UnsupportedProduct(Exception):
    pass


ASIN_RE = re.compile(r"(?:/dp/|/gp/product/|/gp/aw/d/|/product/|/d/)([A-Z0-9]{10})(?:[/?#]|$)", re.I)


def extract_asin(url: str) -> Optional[str]:
    m = ASIN_RE.search(url)
    return m.group(1).upper() if m else None


def resolve_asin(url: str) -> str:
    url = url.strip()
    if not re.match(r"^https?://", url):
        url = "https://" + url
    host = urlparse(url).netloc.lower()
    if not any(h in host for h in ("amazon.", "amzn.")):
        raise UnsupportedProduct("That doesn't look like an Amazon link.")
    asin = extract_asin(url)
    if asin:
        return asin
    # Short links (amzn.in/d/xxxx, amzn.to/xxxx) redirect to the full product URL.
    r, _ = http.get("amazon", url)
    asin = extract_asin(str(r.url)) or extract_asin(r.text[:5000])
    if not asin:
        raise UnsupportedProduct("Couldn't find a product ID (ASIN) in that Amazon link.")
    return asin


def _details(soup: BeautifulSoup) -> dict[str, str]:
    """Collect every 'key: value' spec row Amazon shows, from its several table layouts."""
    d: dict[str, str] = {}

    def put(k: str, v: str):
        k = clean(k).strip(" :‎‏").lower()
        v = clean(v).strip(" :‎‏")
        if k and v and k not in d and len(k) < 60:
            d[k] = v

    for tr in soup.select("#productOverview_feature_div tr, #poExpander tr"):
        tds = tr.find_all("td")
        if len(tds) >= 2:
            put(tds[0].get_text(" "), tds[1].get_text(" "))
    for tr in soup.select("table.prodDetTable tr, #productDetails_techSpec_section_1 tr, #productDetails_detailBullets_sections1 tr"):
        th, td = tr.find("th"), tr.find("td")
        if th and td:
            put(th.get_text(" "), td.get_text(" "))
    for li in soup.select("#detailBullets_feature_div li, #detailBulletsWrapper_feature_div li"):
        txt = clean(li.get_text(" "))
        if ":" in txt:
            k, v = txt.split(":", 1)
            put(k, v)
    # Fashion "Product details" facts block
    for row in soup.select(".product-facts-detail"):
        left = row.select_one(".a-col-left")
        right = row.select_one(".a-col-right")
        if left and right:
            put(left.get_text(" "), right.get_text(" "))
    return d


def _brand(soup: BeautifulSoup, details: dict[str, str]) -> Optional[str]:
    for k in ("brand", "brand name", "manufacturer"):
        if details.get(k):
            return details[k].split(",")[0].strip()
    byline = soup.select_one("#bylineInfo")
    if byline:
        t = clean(byline.get_text(" "))
        m = re.match(r"(?:Visit the|Brand:)\s*(.+?)(?:\s+Store)?$", t, re.I)
        if m:
            return m.group(1).strip()
    return None


def _looks_like_phone(details: dict[str, str]) -> bool:
    """Spec-table evidence, for pages with no breadcrumbs and a title without the word 'smartphone'."""
    generic = (details.get("generic name", "") + " " + details.get("form factor", "")).lower()
    if re.search(r"smartphone|mobile phone|cell ?phone", generic):
        return True
    os_ = details.get("operating system", "").lower()
    model = (details.get("model name", "") + " " + generic).lower()
    if re.search(r"ipad|tablet|watch|tv|laptop|macbook", model):
        return False
    phone_os = re.search(r"\b(ios|android|hyperos|oxygenos|one ?ui|funtouch|coloros|miui)\b", os_)
    phone_specs = any(k in details for k in ("sim card slot count", "cellular technology", "sim card size",
                                             "wireless carrier", "talk time"))
    has_storage = any(k in details for k in ("memory storage capacity", "internal storage"))
    return bool(phone_os and (phone_specs or has_storage))


def _category(crumbs: str, title: str, details: Optional[dict[str, str]] = None) -> Optional[Category]:
    c, t = crumbs.lower(), title.lower()
    # Strongest to weakest evidence. Phone titles often mention accessories in the box
    # ("6500mAh + 45W Fast Charger"), so the accessory filter only guards the title-only check.
    leaf = c.split("›")[-1].strip() if c else ""
    crumb_phone = "smartphone" in leaf or (
        "smartphone" in c and not re.search(r"case|cover|protector|charger|cable|accessor|holder|stand", leaf)
    )
    accessory = re.search(r"\b(case|cover|screen guard|tempered|protector|charger|cable|compatible with|back panel|replacement)\b", t)
    if (
        crumb_phone
        or (details is not None and _looks_like_phone(details))
        or (not accessory and re.search(r"\b(smartphone|mobile phone|iphone)\b", t))
    ):
        return Category.SMARTPHONE
    if "television" in c or "smart tvs" in c or re.search(r"\b(tv|television)\b", t) and re.search(r"(inch|cm)", t):
        return Category.TV
    if re.search(r"t-?shirts?|polos?|jerseys?", c) or re.search(r"\b(t-?shirts?|tees?|polos?|jerseys?)\b", t):
        return Category.APPAREL
    if re.search(r"shoes|sneakers|footwear", c) or re.search(r"\b(sneakers?|shoes?)\b", t):
        return Category.SNEAKERS
    return None


def _colour(soup: BeautifulSoup, details: dict[str, str]) -> Optional[str]:
    for sel in ("#inline-twister-expanded-dimension-text-color_name", "#variation_color_name .selection"):
        el = soup.select_one(sel)
        if el and clean(el.get_text()):
            return clean(el.get_text())
    for k in ("colour", "color", "colour name", "color name"):
        if details.get(k):
            return details[k]
    return None


# The buy-box price, most specific first. A page also carries many other prices (carousels,
# M.R.P., per-unit), so take the first selector that yields a number, never "first price on the page".
_PRICE_SELECTORS = [
    "#corePriceDisplay_desktop_feature_div .priceToPay .a-offscreen",
    "#corePriceDisplay_desktop_feature_div .priceToPay .a-price-whole",
    "#corePriceDisplay_desktop_feature_div .a-price-whole",
    "#corePrice_feature_div .a-price .a-offscreen",
    "#corePrice_desktop .a-price .a-offscreen",
    "#tp_price_block_total_price_ww .a-offscreen",
    "#apex_desktop .priceToPay .a-offscreen",
    "#apex_desktop .a-price:not(.a-text-price) .a-offscreen",
    "#priceblock_ourprice", "#priceblock_dealprice",
]


def _to_amount(text: str) -> Optional[float]:
    m = re.search(r"\d[\d,]*(?:\.\d+)?", text or "")
    if not m:
        return None
    v = float(m.group(0).replace(",", ""))
    return v if v > 0 else None



def _availability(text: str) -> Optional[bool]:
    """Amazon's availability line, e.g. "In stock", "Only 3 left in stock", "Available to ship in 1-2 days",
    "Currently unavailable.", "Temporarily out of stock." None when it says nothing we recognise."""
    t = (text or "").lower()
    if not t:
        return None
    if re.search(r"currently unavailable|out of stock|not available|unavailable|no longer available", t):
        return False
    if re.search(r"in stock|left in stock|available to ship|usually (dispatched|ships)|ships within|dispatched within|available", t):
        return True
    return None

def _price(soup: BeautifulSoup, html: str = "") -> Optional[float]:
    for sel in _PRICE_SELECTORS:
        for el in soup.select(sel):
            v = _to_amount(el.get_text())
            if v:
                return v
    # Fallback: the price Amazon embeds for its own variant picker.
    m = re.search(r'"priceAmount"\s*:\s*([\d.]+)', html)
    return _to_amount(m.group(1)) if m else None


def fetch_product(url: str) -> Listing:
    asin = resolve_asin(url)
    canonical = f"https://www.amazon.in/dp/{asin}"
    # Amazon sometimes answers with a tiny interstitial ("continue shopping" / captcha) instead of
    # the product. A fresh session usually gets the real page on the next try.
    for attempt in range(3):
        r, _ = http.get("amazon", canonical, retries=2)
        blocked = ("validateCaptcha" in r.text or "api-services-support@amazon.com" in r.text
                   or (r.status_code == 200 and 'id="productTitle"' not in r.text))  # holding pages come in all sizes
        if not blocked:
            break
        http.reset_session("amazon")
        time.sleep(0.8 * (attempt + 1))
    else:
        raise http.FetchError("Amazon is showing a bot check right now; please try again in a minute.")
    if r.status_code == 404:
        raise UnsupportedProduct("Amazon says this product page doesn't exist.")

    soup = BeautifulSoup(r.text, "lxml")
    title_el = soup.select_one("#productTitle")
    if not title_el:
        raise http.FetchError("Couldn't read the Amazon product page (no title found).")
    title = clean(title_el.get_text())
    details = _details(soup)
    crumbs = clean(soup.select_one("#wayfinding-breadcrumbs_feature_div").get_text(" ")) if soup.select_one("#wayfinding-breadcrumbs_feature_div") else ""
    category = _category(crumbs, title, details)
    if category is None:
        raise UnsupportedProduct(
            "This product isn't a smartphone, TV, sneaker or t-shirt/polo/jersey, which are the categories this tool supports."
        )

    ram = None
    for k in ("ram memory installed size", "ram", "ram memory installed", "ram size", "memory"):
        if details.get(k):
            m = re.search(r"(\d+(?:\.\d+)?)\s*(GB|TB|MB)", details[k], re.I)
            if m and m.group(2).upper() != "MB":
                ram = float(m.group(1)) * (1024 if m.group(2).upper() == "TB" else 1)
                break
    ram = ram or parse_ram(title)
    storage = None
    for k in ("memory storage capacity", "internal storage", "storage", "rom"):
        if details.get(k):
            m = re.search(r"(\d+(?:\.\d+)?)\s*(GB|TB)", details[k], re.I)
            if m:
                storage = float(m.group(1)) * (1024 if m.group(2).upper() == "TB" else 1)
                break
    storage = storage or parse_storage(title)
    # Amazon sometimes puts the storage figure in the RAM field (common on iPhones) - phones don't have >32GB RAM.
    if ram is not None and (ram > 32 or (storage is not None and ram == storage)):
        ram = None

    screen = parse_screen_inches(title)
    if screen is None:
        for k in ("screen size", "display size", "standing screen display size"):
            if details.get(k):
                screen = parse_screen_inches(details[k])
                if screen:
                    break

    model_number = (details.get("style number") or details.get("item model number")
                    or details.get("model number") or details.get("model"))
    gender = parse_gender(details.get("department")) or parse_gender(title)
    avail_el = soup.select_one("#availability")
    avail_txt = clean(avail_el.get_text(" ")).lower() if avail_el else ""
    img = soup.select_one("#landingImage, #imgBlkFront")

    brand = _brand(soup, details)
    if not brand:
        # Some listings have no brand field; the title almost always starts with it.
        brand = "U.S. Polo Assn." if re.match(r"u\.?s\.? polo", title, re.I) else title.split()[0]

    return Listing(
        platform="amazon",
        title=title,
        url=canonical,
        brand=brand,
        category=category,
        colour=_colour(soup, details),
        ram_gb=ram if category == Category.SMARTPHONE else None,
        storage_gb=storage if category == Category.SMARTPHONE else None,
        screen_in=screen if category == Category.TV else None,
        model_number=model_number,
        gender=gender if category in (Category.SNEAKERS, Category.APPAREL) else None,
        available=_availability(avail_txt),
        price=_price(soup, r.text),
        image=(img.get("data-old-hires") or img.get("src")) if img else None,
        extra={
            "asin": asin, "breadcrumbs": crumbs, "model_name": details.get("model name"),
            "facts": apparel_facts_from_specs(details) if category == Category.APPAREL else {},
        },
    )
