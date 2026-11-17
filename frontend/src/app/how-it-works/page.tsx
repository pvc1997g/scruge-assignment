import { readFile } from "node:fs/promises";
import path from "node:path";
import Link from "next/link";
import { marked } from "marked";

export const metadata = { title: "How Matching Works" };

async function loadDoc(): Promise<string> {
  // Single source of truth: the submission document in /docs.
  const candidates = [
    path.join(process.cwd(), "..", "docs", "HOW_MATCHING_WORKS.md"),
    path.join(process.cwd(), "docs", "HOW_MATCHING_WORKS.md"),
  ];
  for (const p of candidates) {
    try {
      return await readFile(p, "utf8");
    } catch {}
  }
  return "# How matching works\n\nThe document wasn't found.";
}

export default async function HowItWorks() {
  const html = await marked.parse(await loadDoc());
  return (
    <main className="mx-auto max-w-5xl px-5 pt-12">
      <Link href="/" className="text-sm text-muted underline-offset-4 hover:text-ink hover:underline">
        Back to the checker
      </Link>
      <article className="doc mt-8" dangerouslySetInnerHTML={{ __html: html }} />
    </main>
  );
}
