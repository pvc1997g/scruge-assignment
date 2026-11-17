import type { Metadata } from "next";
import Link from "next/link";
import { Schibsted_Grotesk } from "next/font/google";
import "./globals.css";

const schibsted = Schibsted_Grotesk({ variable: "--font-schibsted", subsets: ["latin"], weight: ["400", "500", "600", "700", "800"] });

export const metadata: Metadata = {
  title: "Scruge",
  description: "Paste an Amazon link and see whether Flipkart, Croma or Myntra sell the exact same product.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className={`${schibsted.variable} antialiased`}>
        <header className="border-b border-rule">
          <div className="mx-auto flex max-w-5xl items-center justify-between px-5 py-4">
            <Link href="/" className="flex items-center gap-2 font-extrabold tracking-tight text-lg">
              <span aria-hidden className="grid h-6 w-6 place-items-center rounded-[5px] bg-ink">
                <span className="h-2.5 w-2.5 rounded-full bg-marigold" />
              </span>
              Scruge
            </Link>
            <Link href="/how-it-works" className="text-sm text-muted hover:text-ink underline-offset-4 hover:underline">
              How matching works
            </Link>
          </div>
        </header>
        {children}
        <div className="h-20" />
      </body>
    </html>
  );
}
