# Accessibility and performance (Phase 10)

## Accessibility: WCAG 2.2 AA (SPEC §10)

### Automated (axe-core via `@axe-core/playwright`)

`frontend/e2e/fixtures/app.ts::expectAccessible` runs axe with the tags `wcag2a`,
`wcag2aa`, `wcag21a`, `wcag21aa` and `wcag22aa`. It waits for running animations to
finish, so contrast is measured on final colours. Any violation fails the test.

| Area | Pages | Where |
|---|---|---|
| App (signed in) | Dashboard, tiers, suppliers (list + new), agreements, imports, runs, results, discrepancies, credits, claims, approvals, reports, and all 10 settings pages | `e2e/a11y.spec.ts` |
| Signed out | Login, forgot password, reset password, verify email, accept invite, unsubscribe | `e2e/a11y.spec.ts` |
| Journeys | Import wizard steps, run detail, explain drawer, claim detail, evidence pack, MFA enrolment, sessions, ops console pages, open dialogs and drawers | `money.spec.ts` (17 checks), `account.spec.ts` (6), `ops.spec.ts` (5), `auth.spec.ts` (3) |
| Marketing | Every public page | `site.spec.ts` (4 checks) |

Result (2026-11-12, production build): **62 of 62 Playwright tests passed with 0 axe violations.**

Issues fixed by these checks in Phases 6–9 included:
- Chart SVG exposed as an unlabeled focusable layer.
- An icon-only user-menu button with no name.
- An empty table header cell.
- A link distinguished by colour alone.
- Toast contrast measured during fade-in.
- Duplicate "CSV" button names.

### Built-in patterns

- Semantic landmarks with one `h1` per page, and a skip link.
- Visible focus rings (`:focus-visible`) and full keyboard operation of menus, dialogs and
  drawers (Radix primitives).
- `aria-live="polite"` on job progress.
- Amounts use tabular numerals; negatives use a minus sign *and* colour.
- `prefers-reduced-motion` turns off transitions (`app/globals.css`).
- Component tests cover the import column mapping, the data table and the terms editor.

### Not automated

SPEC §10 asks for a **manual keyboard pass per phase**. Automated tools cannot do this, and
it was **not performed** (UNVERIFIED). It is listed in "How I can verify manually". Screen
reader testing (NVDA/VoiceOver) is also not done; recommended before launch.

## Performance budgets

| Budget | Source | Result | Status |
|---|---|---|---|
| Marketing Lighthouse ≥ 90 in all four categories | SPEC §4.16 [PROPOSED TARGET] | Home 100/100/100/100, Pricing 99/100/100/100, Security 100/100/100/100 (local production build, Phase 9; marketing pages unchanged since) | Met |
| List endpoints p95 < 500 ms at 100k rows | SPEC §11 [PROPOSED TARGET] | Every list endpoint ≤ 118 ms p95 | Met |
| Tier tracker / dashboard | (aggregate, no target) | p95 ≈ 0.7 s | Gap noted (`load-tests.md` §3) |
| 1M-row import within memory budget | SPEC §9 case 27, ADR 0012 | 258 MB, 3.2 min | Met |
| 50 agreements × 1M lines < 5 min on staging | SPEC §4.6 [PROPOSED TARGET] | 306.7 s on the shared dev VM (242.7 s in Phase 4) | Re-measure on staging (Phase 11) |
| Large tables | SPEC §10 | Row virtualization above 500 rows (`components/data-table.tsx`) | Met |

App pages are client-rendered behind auth, so Lighthouse was not run on them. Their cost
is dominated by the API timings above.
