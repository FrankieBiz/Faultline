import type { NextConfig } from "next";

/**
 * Origin of the BuggyShop FastAPI backend that browser `/api/*` requests are
 * proxied to. In the FaultLine job network this is the fixed internal service
 * name; locally it defaults to the backend's development port.
 *
 * Next.js serializes rewrites into the build output, so this value is read
 * when `next build` runs. Rebuild after changing `BUGGYSHOP_BACKEND_URL`.
 */
const DEFAULT_BACKEND_URL = "http://127.0.0.1:8000";

/**
 * Resolves and validates the backend origin, failing the build early on a
 * malformed value instead of producing a frontend that proxies nowhere.
 */
function resolveBackendOrigin(): string {
  const raw = process.env.BUGGYSHOP_BACKEND_URL?.trim() || DEFAULT_BACKEND_URL;
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new Error(`BUGGYSHOP_BACKEND_URL must be an absolute http(s) URL; received "${raw}".`);
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error(`BUGGYSHOP_BACKEND_URL must use http or https; received "${raw}".`);
  }
  return url.origin;
}

const backendOrigin = resolveBackendOrigin();

const nextConfig: NextConfig = {
  poweredByHeader: false,
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendOrigin}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
