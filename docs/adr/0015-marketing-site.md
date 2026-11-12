# ADR 0015 — Marketing website

Status: accepted

## Decisions
1. **Same Next.js app**, public route group `app/(site)`: Home, How it works, Features,
   Security, Pricing, About, Contact, Request a pilot, Blog (404 and hidden from nav and
   sitemap until a post exists; an MDX renderer is added with the first post rather than
   shipping an unused dependency), Privacy, Terms, DPA, Cookie notice, 404 and 500 pages.
2. **Content integrity.** No customers, logos, testimonials, statistics, recoveries or
   certifications. Proof slots are visible `[PLACEHOLDER]` blocks. An E2E copy audit fails
   the build on phrases such as "trusted by", "N customers", "$X recovered", percentage
   claims, "SOC 2 certified", ratings. Security-page claims about TLS and encryption at
   rest are worded as production properties (Phase 11).
3. **Legal pages are templates** with a visible `[LEGAL REVIEW REQUIRED]` notice,
   `noindex`, and excluded from the sitemap. They MUST NOT ship to production unreviewed.
4. **Pricing** reads public plans from the catalog (`GET /api/v1/public/plans`); the CTA is
   "Request a pilot"; no checkout. Prices remain [PROPOSED DEFAULT].
5. **JSON-LD** (Organization, SoftwareApplication; no ratings, reviews or offers) is
   rendered with `dangerouslySetInnerHTML`. This is the only use in the codebase and is
   safe because the content is `JSON.stringify` of constants with `<` escaped to `<`,
   so it cannot terminate the script element or inject markup. The tag carries the CSP
   nonce. No user input ever reaches it.
6. **Pilot form**: react-hook-form + zod mirroring the server; server-side validation,
   required consent, honeypot, rate limits (5/hour/IP, 3/day/email), identical response
   for stored and discarded submissions; confirmation email to the requester (no content
   reflected back) and a notice to `RL_OPS_NOTIFY_EMAIL`. A bot challenge is not added:
   it would need a third-party service ([OPEN], needs approval).
7. **Analytics**: off by default. If `NEXT_PUBLIC_ANALYTICS_SRC` is set, a cookieless
   script loads on marketing pages only, with the nonce, and `proxy.ts` adds that origin to
   `script-src`/`connect-src` only on marketing routes. Provider remains [OPEN].
8. **sonner patch** (`patches/sonner@2.0.8.patch`): its runtime `<style>` injection is
   disabled because the CSP blocks it anyway and the same CSS ships as a stylesheet. This
   removed the console CSP error (Lighthouse Best Practices 92 → 100). Re-check the patch
   when upgrading sonner.

## Measured (production build, Lighthouse 13.6.0, headless Chromium, desktop defaults, local)
| Page | Performance | Accessibility | Best Practices | SEO | LCP | CLS |
|---|---|---|---|---|---|---|
| Home | 100 | 100 | 100 | 100 | 0.8 s | 0 |
| Pricing | 99 | 100 | 100 | 100 | 0.6 s | 0 |
| Security | 100 | 100 | 100 | 100 | 0.8 s | 0 |

Local measurements without network latency or a CDN; re-measure on staging.
