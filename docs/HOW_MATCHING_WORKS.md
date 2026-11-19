# How the matching works (explained like you're 5)

## The short story

Imagine you have a toy car, and you want to know if two other toy shops sell **the exact same car**.

1. **First, we look closely at your toy.** We read its box (the Amazon page) and write down the important things:
   *who made it* (the brand), *what it's called* (the model), and *one special thing* that makes it different from its
   brothers and sisters. For a phone the special thing is **how much it can remember** (RAM and storage). For a TV it's
   **how big the screen is**. For shoes and t-shirts it's **the colour**.

2. **Then we go to the other shops and ask "do you have this?"** We type the toy's name into each shop's search box,
   just like you would.

3. **The shop shows us lots of toys. Most are *not* the same one.** Some are made by someone else. Some have a
   similar name but are a bigger or newer version. Some are the right toy but in a different colour.

4. **We play a game of "Is it the same?" with every toy, checking our list one item at a time:**
   - Same maker? If not → *not the same.* ❌
   - Same name, **including the little words like "Pro", "Ultra", "Plus" or the number "15" vs "16"**? If not → *not the same.* ❌
   - Same special thing (memory / screen size / colour)? If not → *not the same.* ❌
   - Passed everything? → *It's the same toy!* ✅

   A toy has to pass **every** check. Being "almost the same" is not good enough. An iPhone 16 **Plus** is not an
   iPhone 16, and red shoes are not the same as blue shoes.

5. **Finally, we look at whether you can take it home today.**
   - The shop has it and you can buy it → **In stock** 🟢 (we give you the link)
   - The shop has it, but the shelf is empty right now → **Out of stock** 🟠 (we still give you the link)
   - None of the shop's toys passed the game → **Not listed** ⚪

   If a shop's door was locked (the website didn't answer, even when we knocked twice), we still say **Not listed**,
   but we add a little note: *"we couldn't get in, try again."* We never pretend we looked when we didn't.

That's it! **Read the box → search the shop → check every toy, one thing at a time → see if it's on the shelf.**

---

## For grown-ups: what actually happens

### 1. Read the Amazon page
We fetch the Amazon product page and pull out structured facts from its title and spec tables: brand, category
(from the breadcrumb trail), RAM, storage, screen size, colour, manufacturer model number, and who it's for
(men / women / kids). Units are normalised (139 cm → 55 inches, 1 TB → 1024 GB, "Titanium Gray" → *grey*).

### 2. Search each platform
| Category | Platforms | How we search |
|---|---|---|
| Smartphones | Flipkart, Croma | `brand + model + RAM + storage` |
| TVs | Flipkart, Croma | full model code (e.g. `UA55M2EHAULXL`), then series code (`M2EHA`), then name + size |
| Sneakers | Flipkart, Myntra | `brand + model + colour + gender` |
| T-shirts / polos / jerseys | Flipkart, Myntra | `brand + gender + colour + pattern + garment type` |

If the first search finds nothing that matches, we try a looser one. Each platform is searched at the same time,
so the whole check usually takes 5–15 seconds.

### 3. Is it the same product? (`backend/app/match2/`)
One comparison routine for every category; the category only picks a short table of what must agree
(`schema.py`). Four steps:

1. **Read what each listing states** (`facts.py`), never guessing: the model's own words, its version words, any
   manufacturer code, and the attributes. Store conventions are handled here: Flipkart's model-name field and
   Myntra's "Collection Name" (Myntra calls a *Court Vision Alta* "Nike Women Leather Sneakers" in the title), model
   names inside brackets ("Nothing Phone (3a Lite)"), "Pro+" meaning "Pro Plus", and Croma writing "5G" in the name
   of every 5G phone it sells.
2. **Identifiers first.** The same manufacturer code is the same product: a TV model code (`K-55S30B`) or a
   garment/shoe style code (`IU1397`, so a Flipkart "ADIDAS Men Graphic Print T-Shirt" can be the Manchester United
   24/25 home kit). Codes of the same kind that clash reject (`43NU870` ≠ `43NU885`, `K-55S25B` ≠ `K-55S25BM2`).
   A one-letter sales variant of a TV code (`K-55S25EM2`) counts as the same set.
3. **Hard rules** (a conflict rejects): storage, RAM and 5G/4G for phones; screen size (±1 inch) for TVs; wearer,
   pack size and colour for shoes and clothes. Colour is compared as precisely as both sides state it: Amazon
   "Grey" matches any grey listing, but when both name a shade they must share it (`WOLF GREY` ≠ `FOOTBALL GREY`,
   `MAUVE` = `MVE`). Version words must agree (`8` vs `8 EasyOn`, `S24` vs `S24 FE`, `Pro` vs `Pro Plus`).
4. **Everything else is evidence, weighted by how rare each word is** in that category (`rarity.py`). Missing a
   common word costs little (Flipkart's "Samsung M36" without "Galaxy"); an extra rare word costs a lot
   (`Chuck Taylor All Star` vs `... Malden Street`, `574` vs `574 Legacy`). A small learned model per category turns
   the evidence into a score (`weights.json`, trained by `scripts/train_v2.py`). Plain garments with nothing
   distinctive in common score low and come back Not listed rather than as a guess.

### 4. Pick the winner and check stock
**Wrong colour, right model?** A Myntra product page lists the product's other colourways. When a listing is the
right model in the wrong colour, we open the colourway whose colour fits Amazon's and judge it like any listing
(the off-white *Court Vision Alta* is found this way).

Phones are listed once per colour, so several listings can pass every check. For phones we pick, in order:
**the same colour name** as Amazon ("Vivid Mint"), then **the same base colour** ("Onyx Black" ≈ "Black"), and
only as a last resort another colour, shown with a visible "different colour" note. If the exact colour is sold
out, we say so and mention the colours that are in stock. For shoes and clothes the exact colour wins first (off-white beats white when Amazon says off-white), then the
highest score, and ties go to the one you can actually buy. Stock comes from the platform itself:
- **Flipkart:** the product page's own `availabilityStatus` (`IN_STOCK` / `OUT_OF_STOCK`).
- **Croma:** the list of stores holding stock, from Croma's search API (empty → out of stock).
- **Myntra:** whether any size is available.

### 5. Keep the reasoning
The website keeps it simple: one result per store. Behind it, every result records exactly which checks passed,
or why the near-misses were rejected (e.g. *"different model version (8 vs 8 easyon)"*). It's in
the API's `reasons` field and printed by `scripts/try_link.py`, which makes the system easy to trust and debug.

### 6. How we know it works
The matcher was rewritten after a review found it had been tuned link by link. The rewrite was measured on saved
snapshots of what the stores returned (so both versions see identical input), against 12,396 hand-checked
listing pairs, with a test set chosen and labelled before the final changes (`docs/REWRITE_PLAN.md`):

| | Fresh test set (64 store checks) | Pair precision there | Reviewer's 20 links (40) | Tuning set (280) |
|---|---|---|---|---|
| Old matcher | 48 | 60% | 37 | 232 |
| New matcher | 52 | 77% | 37 | 260 |

Run it yourself: `scripts/evaluate.py --set test2 --matcher v2` (and `--matcher v1` for the old one).

### Known limits
- No paid APIs or LLMs: everything is rules plus the platforms' own public pages and data.
- If a platform changes its page layout, its adapter needs updating. Each platform lives in its own small file
  (`backend/app/sources/*.py`).
- The app opens a limited number of product pages per search (to read colours and codes), so on Flipkart, with many
  colourways of one shoe, the right colour can go unread.
- Plain clothes are the weakest area, and more examples don't fix it: the listings themselves often carry nothing
  that tells two plain polos apart (no code, no distinctive name). Those come back Not listed rather than guessed.
- Plain garments without a style code can't be told apart reliably (two plain black polos from one brand look the
  same on paper). Rather than guess, those are reported as Not listed.
- We can only judge what a store's search shows us. Some listings, mostly sold-out ones, never appear in the
  store's search results however the query is phrased, so they can't be found.
- Stock is checked without a delivery pincode, so it means "the platform is selling it", not "it can reach your
  address".
