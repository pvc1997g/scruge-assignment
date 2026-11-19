# Scruge

Paste an Amazon.in product link and see whether the **same product** is sold on the other platforms:

| Category | Searched on | Must also match |
|---|---|---|
| Smartphones | Flipkart, Croma | RAM + storage |
| Televisions | Flipkart, Croma | Screen size |
| Sneakers | Flipkart, Myntra | Colour |
| T-shirts, polos, jerseys | Flipkart, Myntra | Colour |

Each platform shows exactly one of three results, each shown differently: **In stock** (with link),
**Out of stock** (with link), or **Not listed**. If a site doesn't respond even after a retry, it is shown as
Not listed with a visible note saying the site couldn't be checked, so a blocked site is never passed off as a
store that doesn't sell the product.

## Documents

- **[How Scruge finds the same product](docs/Scruge-Explained-Like-Im-5.docx)**: how the matching works, explained for a five-year-old, with real examples from the tests (short Word document).
- [The Same-Toy Detective](docs/Scruge-Explained-Like-Im-5.pdf): the same explanation as an illustrated picture book (11 pages).
- [How a link becomes an answer](docs/Scruge-Technical-Walkthrough.pdf): the end-to-end technical walkthrough, with architecture, a real request traced step by step, the matching rules, design decisions and test results (12 pages).
- [`docs/HOW_MATCHING_WORKS.md`](docs/HOW_MATCHING_WORKS.md): the same explanation as text, also served in the app at `/how-it-works`.
- [`docs/REWRITE_PLAN.md`](docs/REWRITE_PLAN.md): how the matcher was rewritten and measured, milestone by milestone, with every result (including the ones that didn't go our way).

The PDFs are rendered from `docs/pdf/*.html` with headless Chrome.

## Run it (one command)

Requirement: [Docker](https://docs.docker.com/get-docker/) with Compose.

```bash
docker compose up --build
```

Then open **http://localhost:3005**. The first build takes a few minutes; later starts take seconds.

- Port 3005 taken? Run `PORT=8080 docker compose up --build` and open http://localhost:8080.
- Stop everything with `Ctrl+C`, or `docker compose down` if you started it with `-d`.

Two containers start: `backend` (FastAPI, reachable only inside the Docker network) and `frontend` (Next.js,
which proxies `/api/*` to the backend). The frontend waits until the backend's health check passes.

## Run without Docker (for development)

Requirements: Python 3.11+ and Node 20+.

```bash
# 1. Backend (FastAPI) on :8000
cd backend
python3.12 -m venv .venv            # or: uv venv -p 3.12 .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --port 8000

# 2. Frontend (Next.js) on :3005, in another terminal
cd frontend
npm install
npm run dev -- --port 3005
```

Open http://localhost:3005. The frontend proxies `/api/*` to the backend (set `BACKEND_URL` to point elsewhere).

Terminal-only check of one or more links:

```bash
# with Docker (stack running):
docker compose exec backend python scripts/try_link.py https://www.amazon.in/dp/B0GVYGLNH7

# without Docker:
cd backend
.venv/bin/python scripts/try_link.py https://www.amazon.in/dp/B0GVYGLNH7
.venv/bin/python scripts/try_link.py $(grep -v '^#' scripts/test_links.txt)   # whole test set
.venv/bin/python scripts/score_review.py                                      # the reviewer's 20 links, scored
SCRUGE_MATCHER=v1 .venv/bin/python scripts/try_link.py <link>                 # the old matcher, for comparison
```

## Measuring the matcher (offline, repeatable)

Store search results change from minute to minute, so the matcher is measured on saved snapshots of what the stores
returned (`backend/eval/pools/`, 190 Amazon links) against 12,396 hand-checked listing pairs (`backend/eval/labels.jsonl`).

```bash
cd backend
.venv/bin/python scripts/evaluate.py --set test2 --matcher v2 -v   # fresh test set; also: dev, review, v1
.venv/bin/python scripts/build_background.py && .venv/bin/python scripts/train_v2.py   # rebuild rarity table + weights (dev only)
.venv/bin/python scripts/snapshot.py <links file>                  # save pools for new links
.venv/bin/python scripts/label.py show <ASIN>                      # label them (test links are shown blind)
```

| | Fresh test set (64 store checks) | Pair precision there | Reviewer's 20 (40) | Tuning set (280) |
|---|---|---|---|---|
| Old matcher (v1) | 48 | 60% | 37 | 232 |
| New matcher (v2, default) | 52 | 77% | 37 | 260 |

## API

`POST /api/compare` with `{"url": "<amazon link>", "refresh": false}` returns:

```jsonc
{
  "source":  { "title": "...", "brand": "OnePlus", "category": "smartphone", "ram_gb": 8, "storage_gb": 128, ... },
  "results": [
    { "platform": "flipkart", "status": "in_stock", "url": "...", "title": "...", "price": 19999,
      "confidence": 1.0, "reasons": ["brand OnePlus matches", "model ce6 lite matches", ...],
      "query": "OnePlus nord ce6 lite 8GB RAM 128GB", "candidates_checked": 24 },
    ...
  ],
  "elapsed_ms": 4800, "cached": false
}
```

Errors: `422` for non-Amazon links or unsupported categories, `502` if Amazon couldn't be read.

## Code map

```
backend/app/
  main.py          FastAPI endpoints
  service.py       orchestration: build queries → search platforms in parallel → match → stock
  match2/          the matcher (v2, default)
    facts.py       what a listing states: name words, versions, codes, attributes (store conventions live here)
    schema.py      per category: which attributes must agree, and how
    engine.py      identifiers first → hard rules → rarity-weighted evidence → learned score
    rarity.py      how much a word says about *which* product (background.json, built from dev pools)
    weights.json   the learned scoring, per category (scripts/train_v2.py)
  matcher.py       the previous matcher (v1); SCRUGE_MATCHER=v1 switches back
  normalize.py     text → facts: RAM, storage, screen size, colour families, model tokens, TV codes, garment facts
  http.py          shared HTTP client (curl_cffi with a Chrome fingerprint, retries, per-site sessions)
  sources/
    amazon.py      product page → structured Listing
    flipkart.py    search results + product page (stock status, colour, model code)
    croma.py       Croma's public search API (JSON)
    myntra.py      Myntra search page + product page (specs, colourway links)
frontend/src/app/
  page.tsx         the UI
  how-it-works/    renders docs/HOW_MATCHING_WORKS.md
```

## Design decisions

- **No paid APIs, no LLM.** Every decision is explainable: each result's `reasons` (in the API and
  `scripts/try_link.py`) list which checks passed and why near-misses were rejected.
- **Facts, not word lists.** Hard rules only for facts (storage, screen size, wearer, colour, clashing model codes).
  Whether names agree is judged by how rare each word is across the category, not by hand-made lists, and a small
  model learned from labelled pairs turns the evidence into a score. Adding a category means adding a table.
- **Measured, not eyeballed.** Changes are judged on saved snapshots against labelled pairs, with a test set that
  is chosen and labelled before the changes it judges (see `docs/REWRITE_PLAN.md`).
- **Only definite matches count.** A listing is shown as found only when it passes every check; there are no
  "maybe" results. A garment that agrees only on details true of most plain tees (solid, short sleeve, round
  neck) is not counted.
- **Exactly three results.** A site that doesn't answer gets one full retry with a fresh session; if it still
  fails, the row says Not listed *and* says the site couldn't be checked.
- **Platforms in parallel, 15-minute in-memory cache** per Amazon product.
- **Product pages only when needed.** Flipkart hides colour (fashion) and model codes (TVs) on search cards, so
  product pages are opened only for plausible candidates (at most 8 per search).

## Known limitations

- Scrapers depend on page structure; a platform redesign means updating one file in `sources/`.
- Datacenter IPs (cloud hosting) are more likely to be blocked by these sites than a home connection.
- Apparel without a style code is the weakest area: two plain polos of one brand and colour look the same on
  paper. When nothing distinctive agrees, it's reported as Not listed rather than guessed.
- The app opens at most 8 product pages per search to read colours and codes. On Myntra it also follows a
  product's own colourway links to the right colour; on Flipkart, colourways only appear as separate search results.
- Recall is bounded by each store's own search. Some listings (mostly sold-out ones) never appear in search
  results however the query is phrased; on the reviewer's 20 links, five products miss a listing for this reason.
- Stock is checked without a pincode ("being sold"), not delivery to a specific address.
