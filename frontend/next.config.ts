import type { NextConfig } from "next";

/**
 * Same-origin rule (SPEC §7): the browser only talks to this origin. `/api/*` is
 * proxied to FastAPI, so the session cookie stays first-party with `__Host-`.
 * RL_API_ORIGIN is server-side only (never exposed to the browser).
 *
 * cacheComponents is off for v1 (ADR 0011): every page is rendered per request so
 * the CSP nonce applies everywhere and tenant data is never in a shared cache.
 */
const apiOrigin = process.env.RL_API_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  cacheComponents: false,
  partialPrefetching: false,
  poweredByHeader: false,
  reactStrictMode: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiOrigin}/api/:path*` }];
  },
};

export default nextConfig;
