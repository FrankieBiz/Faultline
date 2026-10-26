import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import "@fontsource-variable/overpass";
import "./globals.css";
import { SiteHeader } from "@/components/site-header";

export const metadata: Metadata = {
  title: {
    default: "BuggyShop",
    template: "%s | BuggyShop",
  },
  description: "A two-item field outfitter used as the FaultLine checkout fixture.",
};

export const viewport: Viewport = {
  themeColor: "#183326",
};

/** Root layout: shared header, page content, and the demo-store disclosure. */
export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      <body className="flex min-h-dvh flex-col antialiased">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-50 focus:rounded-md focus:bg-white focus:px-4 focus:py-2 focus:font-semibold"
        >
          Skip to content
        </a>
        <SiteHeader />
        <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-5 pt-10 pb-20 sm:px-8">
          {children}
        </main>
        <footer className="border-t border-stone">
          <p className="mx-auto max-w-6xl px-5 py-6 text-sm text-moss sm:px-8">
            BuggyShop is a demonstration store for FaultLine. Orders are synthetic and no payment is taken.
          </p>
        </footer>
      </body>
    </html>
  );
}
