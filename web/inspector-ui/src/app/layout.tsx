import type { Metadata } from "next";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import "./globals.css";

export const metadata: Metadata = {
  title: "FaultLine — reproduce, repair, and verify live failures",
  description: "Check HTTP invariants from faultline.toml or any URL, reproduce failures in two fresh sessions, and repair registered scenarios in an isolated sandbox before delivering a verified fix.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`dark ${GeistSans.variable} ${GeistMono.variable}`}>
      <body className="min-h-[100dvh] antialiased">
        {children}
      </body>
    </html>
  );
}
