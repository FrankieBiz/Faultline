import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "FaultLine — Controlled Browser QA & Verified Source Repair",
  description: "Meta Global AI Developer Hackathon entry: reproduce a seeded checkout failure in a real browser, gate a proposed patch, and verify it in an isolated runtime.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-[#090d16] text-[#e6edf3] antialiased">
        {children}
      </body>
    </html>
  );
}
