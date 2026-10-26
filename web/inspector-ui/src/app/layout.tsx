import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "FaultLine — Controlled Browser QA & Verified Source Repair",
  description: "Meta AI Developer Hackathon entry: Autonomous browser defect reproduction, Meta model repair, and sandboxed AST verification.",
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
