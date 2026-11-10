# ADR 0011 — Next.js Cache Components disabled for v1

Status: accepted

`create-next-app@16.4.6` enables `cacheComponents` + `partialPrefetching`, which
prerender static shells. SPEC §8.3 requires a strict **nonce-based** CSP on all
responses, and Next.js applies nonces only to dynamically rendered pages
(`node_modules/next/dist/docs/01-app/02-guides/content-security-policy.md`).
The app must also never cache tenant data in shared caches.

Decision: `cacheComponents: false`, `partialPrefetching: false`. Every page is
rendered per request; the `proxy.ts` sets a fresh nonce and CSP. Marketing pages
are still fast (small server components, no client data fetching).

Revisit at the next Next.js major (the docs say both flags become default) —
at that point evaluate nonce support for prerendered shells.
