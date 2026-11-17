"use client";

import { useState } from "react";
import type { CompareResponse, PlatformResult, SourceProduct, Status } from "@/lib/types";

const STORE: Record<string, string> = { flipkart: "Flipkart", croma: "Croma", myntra: "Myntra", amazon: "Amazon" };
const CATEGORY: Record<string, string> = {
  smartphone: "Smartphone",
  tv: "Television",
  sneakers: "Sneakers",
  apparel: "T-shirt, polo or jersey",
};
const MUST_MATCH: Record<string, string> = {
  smartphone: "brand, model, RAM and storage",
  tv: "brand, model and screen size",
  sneakers: "brand, model and colour",
  apparel: "brand, style and colour",
};
const STORES_FOR: Record<string, string[]> = {
  smartphone: ["flipkart", "croma"],
  tv: ["flipkart", "croma"],
  sneakers: ["flipkart", "myntra"],
  apparel: ["flipkart", "myntra"],
};

const rupees = (v: number | null | undefined) => (v == null ? null : "₹" + Math.round(v).toLocaleString("en-IN"));

export default function Home() {
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<CompareResponse | null>(null);

  async function run(refresh = false, target?: string) {
    const link = (target ?? url).trim();
    if (!link) return;
    setLoading(true);
    setError(null);
    if (!refresh) setData(null);
    try {
      const res = await fetch("/api/compare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: link, refresh }),
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(body?.detail || `The server answered with an error (${res.status}).`);
      setData(body as CompareResponse);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't reach the server.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto max-w-5xl px-5">
      <section className="pt-14 pb-10 sm:pt-20">
        <h1 className="max-w-3xl text-[2.6rem] leading-[1.02] font-extrabold tracking-[-0.035em] sm:text-[3.6rem]">
          Paste an Amazon link. See who else sells the exact same thing.
        </h1>
        <p className="mt-5 max-w-xl text-[1.05rem] leading-relaxed text-muted">
          We read the product, search the other stores, and only count a listing when the brand, the model and the
          detail that matters (memory, screen size or colour) all agree.
        </p>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            run();
          }}
          className="mt-9 flex flex-col gap-2 sm:flex-row sm:items-stretch"
        >
          <label htmlFor="amazon-url" className="sr-only">Amazon product link</label>
          <input
            id="amazon-url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://www.amazon.in/dp/…"
            inputMode="url"
            autoComplete="off"
            spellCheck={false}
            className="min-w-0 flex-1 rounded-lg border border-rule-strong bg-surface px-4 py-3.5 text-base outline-none transition-colors placeholder:text-muted/60 focus:border-ink"
          />
          <button
            type="submit"
            disabled={loading || !url.trim()}
            className="rounded-lg bg-marigold px-6 py-3.5 font-semibold text-ink transition-colors hover:bg-marigold-deep disabled:cursor-not-allowed disabled:opacity-45"
          >
            {loading ? "Checking stores…" : "Check stores"}
          </button>
        </form>
        <p className="mt-3 text-sm text-muted">Works for smartphones, TVs, sneakers, and t-shirts, polos and jerseys.</p>
      </section>

      {error && (
        <div role="alert" className="mb-10 rounded-lg border-l-4 border-brick bg-brick-soft px-4 py-3">
          <p className="font-semibold text-brick">That link couldn&apos;t be checked</p>
          <p className="mt-0.5 text-sm text-ink/80">{error}</p>
        </div>
      )}

      {loading && !data && <Loading />}
      {data && <Results data={data} onRecheck={() => run(true, data.source.url)} rechecking={loading} />}
    </main>
  );
}

/* ------------------------------------------------------------------ loading */

function Loading() {
  return (
    <section aria-busy aria-live="polite" className="border-t border-ink pt-6">
      <div className="scanbar h-[3px] w-full rounded-full" />
      <p className="mt-4 text-sm text-muted">
        Reading the Amazon page, then searching each store and comparing listings. This usually takes 5 to 15 seconds.
      </p>
      <div className="mt-6 space-y-3">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-14 rounded-md bg-rule/50" />
        ))}
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ results */

function Results({ data, onRecheck, rechecking }: { data: CompareResponse; onRecheck: () => void; rechecking: boolean }) {
  const src = data.source;
  const found = data.results.filter((r) => r.status === "in_stock" || r.status === "out_of_stock").length;
  const total = data.results.length;
  return (
    <section className="border-t border-ink pt-6">
      <div className="flex flex-col gap-5 sm:flex-row sm:items-start">
        {src.image && (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={src.image} alt="" className="h-28 w-28 shrink-0 rounded-md border border-rule bg-white object-contain p-1.5" />
        )}
        <div className="min-w-0 flex-1">
          <p className="text-sm text-muted">{CATEGORY[src.category]} on Amazon</p>
          <h2 className="mt-1 text-xl font-bold leading-snug tracking-tight line-clamp-2">{src.title}</h2>
          <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1.5 text-sm">
            <Fact k="Brand" v={src.brand} />
            <Fact k="RAM" v={src.ram_gb ? `${src.ram_gb} GB` : null} />
            <Fact k="Storage" v={src.storage_gb ? `${src.storage_gb} GB` : null} />
            <Fact k="Screen" v={src.screen_in ? `${src.screen_in} inch` : null} />
            <Fact k="Model no." v={src.category === "tv" ? src.model_number : null} />
            <Fact k="Colour" v={src.colour} />
            <Fact k="For" v={src.gender ? src.gender[0].toUpperCase() + src.gender.slice(1) : null} />
          </dl>
        </div>
      </div>

      <div className="mt-10 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-lg font-bold tracking-tight">
          {found === 0
            ? `Not found on ${STORES_FOR[src.category].map((s) => STORE[s]).join(" or ")}`
            : found === total
              ? `Found on ${found === 2 ? "both" : "all"} stores`
              : `Found on ${found} of ${total} stores`}
        </h3>
        <p className="text-sm text-muted">
          Matched on {MUST_MATCH[src.category]}.{" "}
          <button onClick={onRecheck} disabled={rechecking} className="underline underline-offset-4 hover:text-ink disabled:opacity-50">
            {rechecking ? "Checking again…" : "Check again"}
          </button>
        </p>
      </div>

      <div role="table" aria-label="Same product on other stores" className="mt-4 border-t border-rule-strong">
        <div role="row" className="hidden grid-cols-[8rem_1fr_9rem_10rem_9.5rem] gap-4 border-b border-rule py-2.5 text-[0.8rem] text-muted md:grid">
          <span role="columnheader">Store</span>
          <span role="columnheader">Listing</span>
          <span role="columnheader" className="text-right">Price</span>
          <span role="columnheader">Status</span>
          <span role="columnheader" className="sr-only">Link</span>
        </div>
        <ReferenceRow src={src} />
        {data.results.map((r, i) => (
          <StoreRow key={r.platform} r={r} amazonPrice={src.price} delay={i} />
        ))}
      </div>

      <p className="mt-4 text-xs text-muted tnum">
        Checked in {(data.elapsed_ms / 1000).toFixed(1)} s{data.cached ? ", from a recent check" : ""}.
      </p>
    </section>
  );
}

function Fact({ k, v }: { k: string; v: string | null | undefined }) {
  if (!v) return null;
  return (
    <div className="flex gap-1.5">
      <dt className="text-muted">{k}</dt>
      <dd className="font-medium">{v}</dd>
    </div>
  );
}

const ROW = "grid grid-cols-1 gap-x-4 gap-y-2 border-b border-rule py-4 md:grid-cols-[8rem_1fr_9rem_10rem_9.5rem] md:items-center";

function ReferenceRow({ src }: { src: SourceProduct }) {
  return (
    <div role="row" className={`${ROW} bg-[#e9ede9]/60 md:bg-transparent`}>
      <div role="cell" className="font-semibold">Amazon</div>
      <div role="cell" className="text-sm text-muted">The product you pasted</div>
      <div role="cell" className="tnum font-semibold md:text-right">{rupees(src.price) ?? <span className="text-muted">—</span>}</div>
      <div role="cell">
        {src.available === false ? <StatusMark status="out_of_stock" /> : src.available ? <StatusMark status="in_stock" /> : null}
      </div>
      <div role="cell" className="md:text-right">
        <a href={src.url} target="_blank" rel="noreferrer" className="text-sm underline underline-offset-4 hover:text-marigold-deep">
          Open on Amazon
        </a>
      </div>
    </div>
  );
}

function StoreRow({ r, amazonPrice, delay }: { r: PlatformResult; amazonPrice: number | null; delay: number }) {
  const [open, setOpen] = useState(false);
  const found = r.status === "in_stock" || r.status === "out_of_stock";
  const diff = found && r.price != null && amazonPrice != null ? Math.round(r.price - amazonPrice) : null;
  const panelId = `why-${r.platform}`;

  return (
    <div className={`reveal reveal-${Math.min(delay + 2, 4)} border-b border-rule`}>
      <div role="row" className={`${ROW} border-b-0`}>
        <div role="cell" className="font-semibold">{STORE[r.platform] ?? r.platform}</div>

        <div role="cell" className="min-w-0">
          {found && r.title ? (
            <div className="flex items-center gap-3">
              {r.image && (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={r.image} alt="" className="h-11 w-11 shrink-0 rounded border border-rule bg-white object-contain" />
              )}
              <div className="min-w-0">
                <p className="text-[0.95rem] leading-snug line-clamp-2">{r.title}</p>
                {r.confidence != null && r.confidence < 0.95 && (
                  <p className="mt-0.5 text-xs text-muted">Likely match, {Math.round(r.confidence * 100)}% confidence</p>
                )}
              </div>
            </div>
          ) : (
            <p className="text-sm text-muted">
              {r.status === "not_listed"
                ? `No listing passed every check (${r.candidates_checked} looked at).`
                : "The store didn't respond, so we can't say either way."}
            </p>
          )}
          {r.note && <p className="mt-2 text-sm text-sold">{r.note}</p>}
        </div>

        <div role="cell" className="tnum md:text-right">
          {found && r.price != null ? (
            <>
              <span className="font-semibold">{rupees(r.price)}</span>
              {diff != null && diff !== 0 && (
                <span className={`block text-xs ${diff < 0 ? "text-stock" : "text-muted"}`}>
                  {rupees(Math.abs(diff))} {diff < 0 ? "less" : "more"}
                </span>
              )}
              {diff === 0 && <span className="block text-xs text-muted">Same as Amazon</span>}
            </>
          ) : (
            <span className="hidden text-muted md:inline">—</span>
          )}
        </div>

        <div role="cell">
          <StatusMark status={r.status} />
        </div>

        <div role="cell" className="flex items-center gap-4 md:justify-end">
          <button
            onClick={() => setOpen((o) => !o)}
            aria-expanded={open}
            aria-controls={panelId}
            className="text-sm text-muted underline-offset-4 hover:text-ink hover:underline"
          >
            {open ? "Hide" : "Why"}
          </button>
          {found && r.url && (
            <a
              href={r.url}
              target="_blank"
              rel="noreferrer"
              className={
                r.status === "in_stock"
                  ? "rounded-md bg-ink px-3.5 py-2 text-sm font-semibold text-paper hover:bg-[#1f3d33]"
                  : "rounded-md border border-rule-strong px-3.5 py-2 text-sm font-semibold hover:border-ink"
              }
            >
              {r.status === "in_stock" ? "Buy" : "View"}
            </a>
          )}
        </div>
      </div>

      {open && (
        <div id={panelId} className="mb-4 grid gap-x-4 md:grid-cols-[8rem_1fr]">
          <div className="hidden md:block" />
          <div className="rounded-md bg-surface px-4 py-3 text-sm ring-1 ring-rule">
            {r.query && (
              <p className="text-muted">
                Searched {STORE[r.platform]} for <span className="text-ink">“{r.query}”</span>
              </p>
            )}
            <ul className="mt-2 space-y-1">
              {r.reasons.map((why, i) => (
                <li key={i} className="flex gap-2">
                  <span aria-hidden className={`mt-[0.55rem] h-1 w-1 shrink-0 rounded-full ${reasonTone(why)}`} />
                  <span>{why}</span>
                </li>
              ))}
            </ul>
            {r.error && <p className="mt-2 text-brick">{r.error}</p>}
          </div>
        </div>
      )}
    </div>
  );
}

function reasonTone(why: string) {
  if (/differ|different|missing|not found|too little|unknown|no listing|couldn/i.test(why)) return "bg-brick";
  return "bg-stock";
}

/* ------------------------------------------------------------------ status */

const STATUS: Record<Status, { label: string; className: string; mark: React.ReactNode }> = {
  in_stock: {
    label: "In stock",
    className: "text-stock",
    mark: <span className="h-2.5 w-2.5 rounded-full bg-stock" />,
  },
  out_of_stock: {
    label: "Out of stock",
    className: "text-sold",
    mark: <span className="h-2.5 w-2.5 rounded-full border-2 border-sold bg-[linear-gradient(90deg,var(--sold)_50%,transparent_50%)]" />,
  },
  not_listed: {
    label: "Not listed",
    className: "text-muted",
    mark: <span className="h-2.5 w-2.5 rounded-full border-2 border-rule-strong" />,
  },
  error: {
    label: "Couldn't check",
    className: "text-brick",
    mark: <span className="h-2.5 w-2.5 rotate-45 bg-brick" />,
  },
};

function StatusMark({ status }: { status: Status }) {
  const s = STATUS[status];
  return (
    <span className={`inline-flex items-center gap-2 text-sm font-semibold ${s.className}`}>
      {s.mark}
      {s.label}
    </span>
  );
}
