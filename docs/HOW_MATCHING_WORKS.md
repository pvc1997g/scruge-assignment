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

   And if a shop's door was locked (the website didn't answer), we say **"Couldn't check"**. We never pretend that
   means "they don't sell it".

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

### 3. The checks (every one must pass)
1. **Brand.** Normalised, so `SAMSUNG` = `Samsung`, and `Redmi` = `Xiaomi`.
2. **Model.** This is the hard part, and it works differently per category:
   - **Phones:** we remove marketing words ("5G", "AI Smartphone") and compare the words that *identify* the model:
     anything with a digit (`S24`, `15`, `CE6`) or a variant word (`Pro`, `Ultra`, `Plus`, `Lite`, `FE`). These must be
     **identical**, and every series word must be present too. That's how `Galaxy S24` correctly fails against
     `Galaxy S24 Ultra` and `Galaxy S26`, and `POP X` fails against `POVA X`.
   - **TVs:** we compare the **manufacturer model code**. Flipkart hides it on search results, so we open the
     product page to read it. Croma names TVs by series (`LG NU870B`) while Amazon shows the full code
     (`43NU870BPLA`), so a series match is accepted with slightly lower confidence and the UI says so.
   - **Sneakers:** a matching style code (e.g. `DD8959-100`) is an instant match. Otherwise the model words must
     match exactly, both ways, once generic words ("running shoes", "for men") are removed, and version words
     (`Mid`, `Low`, `Comfort`, `Waterproof`, `Slip-Ins`, `'07`) are checked across the whole title. So
     `Smashic` ≠ `Smashic Comfort` and `Court Vision Low Suede` ≠ `Court Vision Low Next Nature`.
   - **T-shirts / polos / jerseys:** clothes rarely have model names, so we use the best evidence available:
     1. **Style code.** If Amazon's style number equals the store's style code, it's the same garment (100%).
     2. **Garment facts from all three spec tables:** **pattern** (solid / printed / striped), **fit**
        (slim / regular / oversized), **sleeve** and **neck**, plus **material**. Any fact that differs rejects;
        named product lines must agree (Puma *Essential* ≠ *Pique Tipping*); at least two strong facts must agree.
        "It's a cotton t-shirt" counts for nothing. These are shown as **likely** matches (up to 80%).
     3. If only the default facts agree (solid, short sleeve, round neck: true of most plain tees), the result is
        labelled a **possible** match (about 70%) with "check the details before buying".
3. **The category's extra rule.**
   - Phones: storage must be equal. RAM must be equal whenever both sites state it (Apple doesn't publish RAM,
     so model + storage decide there).
   - TVs: screen size must be equal (±1 inch, to absorb 138 cm vs 139.7 cm rounding).
   - Sneakers / apparel: base colour must match (`Onyx` → black, `Navy` ≈ blue). An exact colour scores higher
     than a "same family" colour. Who it's for must also be compatible: men's ≠ women's, but unisex fits both.

### 4. Pick the winner and check stock
Phones are listed once per colour, so several listings can pass every check. For phones we pick, in order:
**the same colour name** as Amazon ("Vivid Mint"), then **the same base colour** ("Onyx Black" ≈ "Black"), and
only as a last resort another colour, shown with a visible "different colour" note. If the exact colour is sold
out, we say so and mention the colours that are in stock. For everything else, the highest score wins, and ties go
to the one you can actually buy. Stock comes from the platform itself:
- **Flipkart:** the product page's own `availabilityStatus` (`IN_STOCK` / `OUT_OF_STOCK`).
- **Croma:** the list of stores holding stock, from Croma's search API (empty → out of stock).
- **Myntra:** whether any size is available.

### 5. Show the reasoning
Every result has a **"Why?"** button listing exactly which checks passed, or why the near-misses were rejected
(e.g. *"Redmi Note 17 Pro → different model (missing 14, extra 17)"*). This makes the system easy to trust and
easy to debug.

### Known limits
- No paid APIs or LLMs: everything is rules plus the platforms' own public pages and data.
- If a platform changes its page layout, its adapter needs updating. Each platform lives in its own small file
  (`backend/app/sources/*.py`).
- Plain garments without a style code can't be told apart reliably (two plain black polos from one brand look the
  same on paper). Those matches are labelled "possible", never confirmed, and the "Why?" panel shows the evidence.
- Stock is checked without a delivery pincode, so it means "the platform is selling it", not "it can reach your
  address".
