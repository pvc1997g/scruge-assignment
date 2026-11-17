"""Search Amazon.in and print organic (non-sponsored) product links, to build a test set."""

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bs4 import BeautifulSoup  # noqa: E402

from app import http  # noqa: E402

for q in sys.argv[1:]:
    r, _ = http.get("amazon", "https://www.amazon.in/s", params={"k": q})
    soup = BeautifulSoup(r.text, "lxml")
    print(f"\n# {q}")
    n = 0
    for div in soup.select('div[data-component-type="s-search-result"][data-asin]'):
        asin = div["data-asin"]
        if not asin or "AdHolder" in " ".join(div.get("class", [])) or div.select_one(".puis-sponsored-label-text"):
            continue
        h2 = div.select_one("h2")
        title = re.sub(r"\s+", " ", h2.get_text(" ", strip=True)) if h2 else ""
        print(f"https://www.amazon.in/dp/{asin}  {title[:110]}")
        n += 1
        if n >= 4:
            break
