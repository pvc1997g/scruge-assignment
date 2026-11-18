"""Score the app against the reviewer's hand-checked answers for their 20 links (scripts/review_links.txt).

usage: .venv/bin/python scripts/score_review.py
A product counts as fully right only if both stores are right. None = the right answer is Not listed.
A listing id list holds every listing the reviewer accepted (plus verified duplicates of the same item).
"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.service import compare

EXPECTED = {
 "B0FDB9ZCTD": ("Galaxy M36", ["itmf77ec4e8758a8"], None),
 "B0CWPC2W5V": ("Galaxy A55", ["itmf96a733c20399"], None),
 "B0GS5SM6JR": ("REDMI A7 Pro 5G", ["itm88c66032a6b5e"], None),
 "B0HJB3GZ2C": ("iPhone 18 Pro", ["itm5f321763cbf7a"], ["324743"]),
 "B0H3KZHC8L": ("vivo Y31", ["itm5337e173eced8"], None),
 "B0F7X5FC43": ("Sony 55 2M2", ["itm170167561d8cd"], ["316615"]),
 "B0F7WVPWG8": ("Sony 43 2M2", ["itmfcc0fa647a566", "itm3805e76c12d48"], ["316033"]),
 "B0GTZ9TSDJ": ("LG 43 NU87", ["itm3ff016445103c", "itm9589c6f597e61"], ["323496"]),
 "B0F3JM1YP5": ("Xiaomi 32 F", ["itm06c5e7af5cb97"], None),
 "B0GXB76VRW": ("Samsung 43 Crystal", None, None),
 "B0000ATCP4": ("Converse CT", ["itmf3xnhhf46aeej", "itmf3xnhjppgqkfg"], ["23059432"]),
 "B0GSRDSKYD": ("Nike CV Alta W", ["itm2c3c4b3deffdc"], ["45376546"]),
 "B0CJ55P4M8": ("Skechers Uno Lite", ["itm5cf439bc9082d", "itm5afb605967c23"], ["26282022"]),
 "B0DPHV2SVJ": ("Nike Revolution 8", ["itm6aea77089d15d"], ["43109452"]),
 "B0GFN1LBFG": ("adidas Breaknet 3.0", None, ["38793823"]),
 "B0D9JYRZGB": ("Man Utd 24/25", ["itm7c11def2232b6"], ["30777713"]),
 "B0B4CZWYTH": ("adidas TIRO 23", ["itmc1a604341ed7d"], ["39599644"]),
 "B09167TMLD": ("Puma teamLIGA", ["itm83e572b3d911d"], ["28683750"]),
 "B0DDTH33PL": ("Puma Essential polo", ["itm5ae94aaeef3a3"], ["30850258", "24171074"]),
 "B07XK9H5KF": ("Levi's 025 black", ["itm2602a736e70e8"], ["12027432"]),
}

def judge(res, want):
    found = res["status"] in ("in_stock", "out_of_stock")
    if want is None:
        return ("RIGHT" if not found else "WRONG-MATCH"), ""
    if not found:
        return "MISSED", ""
    ok = any(w in (res["url"] or "") for w in want)
    return ("RIGHT" if ok else "CHECK"), (res["title"] or "")[:70] + " " + (res["url"] or "")[-45:]

def run(asin):
    name, fk, other = EXPECTED[asin]
    try:
        r = compare(f"https://www.amazon.in/dp/{asin}", use_cache=False)
    except Exception as e:
        return asin, name, [("ERROR", str(e)[:80])], False
    rows, allright = [], True
    for res in r["results"]:
        want = fk if res["platform"] == "flipkart" else other
        verdict, detail = judge(res, want)
        allright &= verdict == "RIGHT"
        why = "" if verdict == "RIGHT" else " | " + (res["reasons"][-1][:110] if res["reasons"] else "")
        rows.append((f"{res['platform']:8} {verdict:11} {res['status']:12}", detail + why))
    return asin, name, rows, allright

with ThreadPoolExecutor(4) as ex:
    out = list(ex.map(run, EXPECTED))
score = 0
for asin, name, rows, ok in out:
    score += ok
    print(f"{'OK ' if ok else '-- '} {name} ({asin})")
    for a, b in rows:
        print(f"      {a} {b}")
print(f"\nFULLY RIGHT: {score}/20")
