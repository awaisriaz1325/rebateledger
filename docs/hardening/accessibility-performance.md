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

### Keyboard pass (2026-11-13)

`frontend/e2e/keyboard.spec.ts`, 40 tests, run in Chromium with key presses only:

- **Tab walk on 32 pages** (23 app pages, 6 signed-out pages, 3 marketing pages). Every
  stop must be visible, have a name, show a focus indicator and not be hidden under other
  content (WCAG 2.4.11). The walk must cycle, so there are no keyboard traps (2.1.2). On
  app pages the first stop must be "Skip to content".
- **Journeys:** skip link moves focus into `main`; Ctrl+K palette (type, Enter, Esc);
  `?` help dialog traps focus and Esc returns it; account menu with Enter, arrows and Esc;
  table rows with ↑/↓ and Enter; sortable headers with Enter; adding a supplier with the
  keyboard only; signing in with password and authenticator code using keys only.

Problems found and fixed:

| Problem | WCAG | Fix |
|---|---|---|
| Closing a dialog opened by a shortcut or row action dropped focus to the page body, so keyboard users lost their place | 2.4.3 | `useReturnFocus` in `components/ui/overlay.tsx`, used by Dialog, Drawer and the command palette: focus goes back to the element that opened the overlay |
| Breadcrumb links scrolled into view under the sticky header when focused | 2.4.11 | `scroll-padding-top: 4.5rem` on `html` (`app/globals.css`) |

### Screen-reader pass (2026-11-13)

`frontend/e2e/screen-reader.spec.ts`, 34 tests. Screen readers (NVDA, JAWS, VoiceOver,
Orca) read the browser's accessibility tree; these tests read Chromium's tree and check:

- Every page has a title, one `main` landmark, a banner and navigation, exactly one `h1`
  and no skipped heading levels (1.3.1, 2.4.2, 2.4.6).
- Page titles are distinct across all app pages.
- Client-side navigation is announced (Next.js route announcer).
- Form errors set `aria-invalid`, are linked with `aria-describedby`, and focus moves to
  the first invalid field (3.3.1).
- Notifications and table counts use live regions (4.1.3).
- Icon-only controls are named; decorative SVGs are hidden.

Each page's tree is written to `frontend/test-results/screen-reader/*.yml` (28 files), a
transcript of what a screen reader reads, in order.

Problems found and fixed:

| Problem | WCAG | Fix |
|---|---|---|
| Every app page had the same title ("RebateLedger — supplier rebate reconciliation"), so users could not tell pages apart in tabs or history | 2.4.2 | A server `layout.tsx` with a `metadata.title` on each app route (29 files), e.g. "Suppliers · RebateLedger" |
| Navigation inside the app was not announced: the Next.js announcer reads the title, which never changed | 4.1.3 | Fixed by the distinct titles; the test confirms the announcement |

**Limit:** this is not a session with a real screen reader. Speech output and
reader-specific behaviour (NVDA browse mode, VoiceOver rotor) are not covered. A short
manual session with NVDA on Windows or VoiceOver on macOS is still recommended before the
first customer, and is listed in "How I can verify manually".

Result (2026-11-13, production build): **136 of 136 Playwright tests passed** (62 earlier
journeys and axe checks, plus 40 keyboard and 34 screen-reader tests).

## Performance budgets

| Budget | Source | Result | Status |
|---|---|---|---|
| Marketing Lighthouse ≥ 90 in all four categories | SPEC §4.16 [PROPOSED TARGET] | Home 100/100/100/100, Pricing 99/100/100/100, Security 100/100/100/100 (local production build, Phase 9; marketing pages unchanged since) | Met |
| List endpoints p95 < 500 ms at 100k rows | SPEC §11 [PROPOSED TARGET] | Every list endpoint ≤ 118 ms p95 | Met |
| Tier tracker / dashboard | (aggregate, no target) | p95 ≈ 0.7 s | Accepted (ADR 0016) |
| 1M-row import within memory budget | SPEC §9 case 27, ADR 0012 | 258 MB, 3.2 min | Met |
| 50 agreements × 1M lines < 5 min on staging | SPEC §4.6 [PROPOSED TARGET] | 306.7 s on the shared dev VM (242.7 s in Phase 4) | Re-measure on staging (Phase 11) |
| Large tables | SPEC §10 | Row virtualization above 500 rows (`components/data-table.tsx`) | Met |

App pages are client-rendered behind auth, so Lighthouse was not run on them. Their cost
is dominated by the API timings above.
