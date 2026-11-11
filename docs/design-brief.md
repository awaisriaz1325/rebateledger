# Design brief (Phase 5) — [FOUNDER APPROVAL PENDING]

PHASES §5 asks for founder approval before components are built. The build proceeded
on this brief because the founder asked for uninterrupted delivery; every choice
below lives in design tokens (`frontend/app/globals.css`) so it can change in one place.

## Positioning and tone
A precise instrument for finance teams, not a "growth" dashboard. It should feel like
a well-kept ledger: calm, exact, trustworthy, quietly confident. Copy is plain,
finance-literate English (SPEC §10) — no hype, no exclamation marks, numbers first.

## Visual identity
- **Concept:** "ledger paper". Warm off-white canvas, ink-dark text, one deep green
  brand colour taken from banknote/ledger traditions, hairline rules instead of heavy
  cards, generous but disciplined whitespace.
- **Palette (light):** canvas `#f7f8f6`, surface `#ffffff`, ink `#15201b`,
  muted ink `#56645d`, rule `#dde3df`, brand `#1d4f3c` (hover `#163d2f`),
  brand-soft `#e5efe9`.
  Status colours carry meaning but never alone (always with a label/icon/sign):
  negative/short `#a3291c`, warning/pending `#8a5a00`, positive/matched `#1f6b46`,
  info/review `#2f5a8a`, neutral `#56645d`.
- **Palette (dark):** canvas `#0f1512`, surface `#151d19`, ink `#e6ece8`, muted `#9aa8a0`,
  rule `#26322c`, brand `#5fb38d`; status colours lightened to keep ≥ 4.5:1.
- All text/background pairs meet WCAG 2.2 AA (4.5:1 body, 3:1 large text/UI).

## Typography
- **IBM Plex Sans** (UI) and **IBM Plex Mono** (codes, hashes, references) via
  `next/font` (self-hosted at build: no runtime third-party requests).
- Figures always use tabular numerals (`font-variant-numeric: tabular-nums`) and are
  right-aligned. Negative money renders `−$1,234.56` (true minus) plus colour.
- Scale: 12 / 13 / 14 (base, app) / 16 / 20 / 24 / 32 px; marketing up to 48 px.

## Density and layout
- App optimised for ≥ 1280 px, usable at 1024 px; read-only views usable on mobile.
- Tables: 36 px rows (compact), sticky header, zebra off, hairline separators,
  virtualised above 500 rows.
- Left sidebar (collapsible), breadcrumbs, top bar with org switcher, global search
  (⌘/Ctrl-K command palette), notification bell, user menu.

## Interaction principles
- No optimistic UI for money, approvals, claims, imports or runs (SPEC frontend rules).
- Every view has skeleton loading, empty state with a next action, inline error with
  retry, and a permission-denied explanation. Stale results show a banner.
- Destructive actions confirm; irreversible ones require typing the object name.
- Motion is minimal (≤ 150 ms fades) and disabled under `prefers-reduced-motion`.

## Explicitly avoided
Gradients-as-decoration, glassmorphism, stock illustrations of people, fake charts,
invented social proof, dark patterns, colour-only status.
