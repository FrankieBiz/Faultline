import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";

/*
 * Self-hosted OFL faces, the same sha256-pinned files as docs/assets/fonts (see DESIGN.md).
 * Zalando Sans sets display, headings, text and labels; Martian Mono is only for code, ids,
 * timestamps and readouts. Both are variable in width, so the faces declare their width range.
 */
const zalandoSans = localFont({
  src: "./fonts/zalando-sans-latin-wdth-wght.woff2",
  weight: "200 900",
  variable: "--font-sans",
  display: "swap",
  adjustFontFallback: "Arial",
  declarations: [{ prop: "font-stretch", value: "75% 125%" }],
});
const martianMono = localFont({
  src: "./fonts/martian-mono-latin-wdth-wght.woff2",
  weight: "100 800",
  variable: "--font-mono",
  display: "swap",
  adjustFontFallback: false,
  fallback: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
  declarations: [{ prop: "font-stretch", value: "75% 112.5%" }],
});

export const metadata: Metadata = {
  title: "FaultLine Inspector: make every AI fix prove itself",
  description: "Crawl a local or preview URL with a real browser, reproduce the failure, and accept a sandboxed repair only when independent checks pass.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${zalandoSans.variable} ${martianMono.variable}`}>
      <body className="min-h-[100dvh] antialiased">
        {children}
      </body>
    </html>
  );
}
