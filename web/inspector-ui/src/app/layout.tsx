import type { Metadata } from "next";
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
    <html lang="en" className="dark">
      <body className="min-h-screen antialiased">
        {children}
      </body>
    </html>
  );
}
