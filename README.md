# Same Product Finder

Paste an Amazon.in product link and see whether the **same product** is sold on the other platforms:

| Category | Searched on | Must also match |
|---|---|---|
| Smartphones | Flipkart, Croma | RAM + storage |
| Televisions | Flipkart, Croma | Screen size |
| Sneakers | Flipkart, Myntra | Colour |
| T-shirts, polos, jerseys | Flipkart, Myntra | Colour |

Each platform shows one of: **In stock** (with link), **Out of stock** (with link), **Not listed**, or
**Couldn't check** (the site didn't respond, which is never reported as "not listed").

## Documents

- **[The Same-Toy Detective](docs/Scruge-Explained-Like-Im-5.pdf)**: how matching works, explained for a five-year-old (11-page picture book).
- **[How a link becomes an answer](docs/Scruge-Technical-Walkthrough.pdf)**: the end-to-end technical walkthrough, with architecture, a real request traced step by step, the matching rules, design decisions and test results (12 pages).
- [`docs/HOW_MATCHING_WORKS.md`](docs/HOW_MATCHING_WORKS.md): the same explanation as text, also served in the app at `/how-it-works`.

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
```

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
  matcher.py       the matching rules (brand / model / category attribute gates + scoring)
  normalize.py     text → facts: RAM, storage, screen size, colour families, model tokens, TV codes, garment facts
  http.py          shared HTTP client (curl_cffi with a Chrome fingerprint, retries, per-site sessions)
  sources/
    amazon.py      product page → structured Listing
    flipkart.py    search results + product page (stock status, colour, model code)
    croma.py       Croma's public search API (JSON)
    myntra.py      Myntra search page (embedded JSON)
frontend/src/app/
  page.tsx         the UI
  how-it-works/    renders docs/HOW_MATCHING_WORKS.md
```

## Design decisions

- **No paid APIs, no LLM.** Matching is deterministic rules, so every decision is explainable: the UI's
  "Why?" button shows which checks passed and why near-misses were rejected.
- **Hard gates, then score.** A candidate must pass *every* check (brand, model, category attribute). The score
  only ranks candidates that already passed. "Almost the same" never counts as a match.
- **"Not listed" vs "Couldn't check" are different.** A network failure or block is reported as an error,
  never as "the platform doesn't sell it".
- **Platforms in parallel, 15-minute in-memory cache** per Amazon product.
- **Product pages only when needed.** Flipkart hides colour (fashion) and model codes (TVs) on search cards, so
  product pages are opened only for plausible candidates (at most 8 per search).

## Known limitations

- Scrapers depend on page structure; a platform redesign means updating one file in `sources/`.
- Datacenter IPs (cloud hosting) are more likely to be blocked by these sites than a home connection.
- Apparel without a style code is matched on garment facts (type, pattern, fit, sleeve, neck, material) plus
  colour and gender, so confidence is capped at 85%.
- Stock is checked without a pincode ("being sold"), not delivery to a specific address.
