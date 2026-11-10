---
paths:
  - "frontend/**/*.ts"
  - "frontend/**/*.tsx"
  - "frontend/**/*.css"
---

# Frontend rules (Next.js)

- The browser talks to one origin only. All API calls go to same-origin
  `/api/v1/...` paths; never call the FastAPI service URL directly from the browser.
- Use the generated OpenAPI client and types. Do not hand-write API types.
- Money arrives as decimal strings. Format with `Intl.NumberFormat` for display
  only. Never parse money into JS numbers for arithmetic; the backend computes.
- Amounts are right-aligned with tabular numerals. Negatives use a minus sign
  and colour, never colour alone.
- Every data view has explicit loading (skeleton), empty, error and
  permission-denied states. No blank screens.
- No optimistic UI for money, approvals, claims, imports or runs: wait for the
  server's confirmed state.
- Destructive actions require a confirmation dialog; irreversible ones require
  typing the object name.
- Forms: react-hook-form + zod schemas that mirror (not replace) backend rules;
  always render server-side validation errors returned by the API.
- Accessibility is required: semantic HTML, labelled controls, visible focus,
  full keyboard operation, WCAG 2.2 AA contrast, `prefers-reduced-motion` respected.
- Never put tokens, tenant data or PII in URLs, `localStorage`, or analytics events.
- Never render user-supplied HTML. No `dangerouslySetInnerHTML` without a
  reviewed sanitizer and an ADR.
- Server components that call the API forward the incoming session cookie and
  `X-Request-ID`; they never cache tenant data in shared caches.
