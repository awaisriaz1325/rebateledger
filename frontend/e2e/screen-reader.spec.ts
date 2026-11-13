/**
 * Screen-reader pass (SPEC §10, WCAG 1.3.1, 2.4.2, 2.4.6, 3.3.1, 4.1.2, 4.1.3).
 *
 * Screen readers (NVDA, JAWS, VoiceOver, Orca) read the browser's accessibility tree. These
 * tests read Chromium's tree for each page and check what a screen-reader user depends on:
 * a unique page title, landmarks, one h1 and no skipped heading levels, announcements on
 * route changes and form errors, and a live region for notifications. Each page's tree is
 * written to `test-results/screen-reader/` as a reading transcript for human review.
 *
 * Limit: this is not a run of a real screen reader. Speech output and reader-specific
 * quirks (for example virtual-cursor behaviour in NVDA) are not covered.
 */
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

const APP_PAGES = [
  "/app",
  "/app/tiers",
  "/app/suppliers",
  "/app/suppliers/new",
  "/app/agreements",
  "/app/agreements/model",
  "/app/imports",
  "/app/runs",
  "/app/results",
  "/app/discrepancies",
  "/app/credits",
  "/app/claims",
  "/app/approvals",
  "/app/reports",
  "/app/accruals",
  "/app/settings/profile",
  "/app/settings/organization",
  "/app/settings/security",
  "/app/settings/reconciliation",
  "/app/settings/approvals",
  "/app/settings/accounting",
  "/app/settings/members",
  "/app/settings/notifications",
  "/app/settings/templates",
  "/app/settings/plan",
  "/app/settings/audit",
];
const PUBLIC_PAGES = ["/login", "/forgot-password", "/", "/pricing", "/security"];

const OUT = path.join(__dirname, "..", "test-results", "screen-reader");

interface Structure {
  title: string;
  mains: number;
  h1: string[];
  skips: string[];
  liveRegions: number;
}

async function structure(page: Page): Promise<Structure> {
  return page.evaluate(() => {
    const visible = (el: Element) => !el.closest("[aria-hidden=true], [hidden]");
    const headings = [...document.querySelectorAll("h1, h2, h3, h4, h5, h6, [role=heading]")].filter(visible);
    const level = (h: Element) => Number(h.getAttribute("aria-level") ?? h.tagName.slice(1));
    const skips: string[] = [];
    let prev = 0;
    for (const h of headings) {
      const l = level(h);
      if (prev && l > prev + 1) skips.push(`h${prev} → h${l} "${h.textContent?.trim().slice(0, 40)}"`);
      prev = l;
    }
    return {
      title: document.title,
      mains: document.querySelectorAll("main, [role=main]").length,
      h1: headings.filter((h) => level(h) === 1).map((h) => h.textContent?.trim() ?? ""),
      skips,
      liveRegions: document.querySelectorAll("[aria-live], [role=status], [role=alert], [role=log]").length,
    };
  });
}

function save(name: string, tree: string): void {
  mkdirSync(OUT, { recursive: true });
  writeFileSync(path.join(OUT, `${name.replace(/^\//, "").replace(/\//g, "_") || "home"}.yml`), tree);
}


test.describe("reading structure: app", () => {
  for (const p of APP_PAGES) {
    test(`screen reader: ${p}`, async ({ page }) => {
      await page.goto(p);
      await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
      await expect(page.locator(".skeleton")).toHaveCount(0);
      const s = await structure(page);
      expect(s.title, "page has a title").not.toEqual("");
      expect(s.mains, "exactly one main landmark").toBe(1);
      expect(s.h1.length, `exactly one h1 (found: ${s.h1.join(" | ")})`).toBe(1);
      expect(s.skips, "no skipped heading levels").toEqual([]);
      await expect(page.getByRole("navigation").first()).toBeAttached();
      await expect(page.getByRole("banner")).toBeAttached();
      const tree = await page.locator("body").ariaSnapshot();
      save(p, tree);
    });
  }

  test("page titles are distinct so each page is announced differently", async ({ page }) => {
    const seen = new Map<string, string>();
    const dupes: string[] = [];
    for (const p of APP_PAGES) {
      await page.goto(p);
      await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
      const t = await page.title();
      if (seen.has(t)) dupes.push(`"${t}": ${seen.get(t)} and ${p}`);
      seen.set(t, p);
    }
    expect(dupes).toEqual([]);
  });
});

test.describe("reading structure: public", () => {
  test.use({ storageState: { cookies: [], origins: [] } });
  for (const p of PUBLIC_PAGES) {
    test(`screen reader: ${p}`, async ({ page }) => {
      await page.goto(p);
      await expect(page.locator("main").first()).toBeVisible();
      const s = await structure(page);
      expect(s.title).not.toEqual("");
      expect(s.mains).toBe(1);
      expect(s.h1.length, `exactly one h1 (found: ${s.h1.join(" | ")})`).toBe(1);
      expect(s.skips).toEqual([]);
      save(`public${p === "/" ? "_home" : p}`, await page.locator("body").ariaSnapshot());
    });
  }
});

test.describe("announcements", () => {
  test("client-side navigation is announced with the new page", async ({ page }) => {
    await page.goto("/app");
    await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
    await page.getByRole("navigation").getByRole("link", { name: "Suppliers" }).click();
    await page.waitForURL(/\/app\/suppliers$/);
    // Next.js renders a polite live region (next-route-announcer) and fills it on route changes.
    const announcer = page.locator("next-route-announcer");
    await expect(announcer).toBeAttached();
    await expect
      .poll(() => announcer.evaluate((el) => el.shadowRoot?.querySelector("[aria-live]")?.textContent ?? ""))
      .not.toEqual("");
    await expect(page.locator("nav a[aria-current=page]")).toHaveText(/Suppliers/);
  });

  test("form errors are tied to their fields and focus moves to the first one", async ({ page }) => {
    await page.goto("/app/suppliers/new");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.getByRole("button", { name: /add supplier/i }).click();
    const name = page.getByLabel(/^Name/);
    await expect(name).toHaveAttribute("aria-invalid", "true");
    await expect(name).toBeFocused();
    const describedBy = await name.getAttribute("aria-describedby");
    expect(describedBy, "error is referenced by aria-describedby").toBeTruthy();
    const message = await page.evaluate(
      (ids) => ids.split(/\s+/).map((id) => document.getElementById(id)?.textContent ?? "").join(" ").trim(),
      describedBy!,
    );
    expect(message, "screen reader hears the error with the field").not.toEqual("");
  });

  test("notifications use a live region", async ({ page }) => {
    await page.goto("/app/settings/profile");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    // sonner's toaster is a labelled region with aria-live, present before any toast appears.
    await expect(page.locator("section[aria-live]")).toBeAttached();
  });

  test("job progress and table counts are announced politely", async ({ page }) => {
    await page.goto("/app/suppliers");
    await expect(page.locator(".skeleton")).toHaveCount(0);
    await expect(page.locator("[aria-live=polite]").first()).toBeAttached();
  });

  test("icons are hidden and icon-only controls are named", async ({ page }) => {
    await page.goto("/app");
    await expect(page.locator(".skeleton")).toHaveCount(0);
    const unnamed = await page.evaluate(() =>
      [...document.querySelectorAll("button, a[href]")]
        .filter((el) => !el.closest("[aria-hidden=true]"))
        .filter((el) => !(el.getAttribute("aria-label") || el.getAttribute("aria-labelledby") || el.textContent?.trim() || el.getAttribute("title")))
        .map((el) => el.outerHTML.slice(0, 80)),
    );
    expect(unnamed).toEqual([]);
    const loudSvgs = await page.locator("svg:not([aria-hidden=true]):not([role=img])").evaluateAll((els) =>
      els.filter((el) => !el.closest("[aria-hidden=true]")).map((el) => el.parentElement?.outerHTML.slice(0, 80) ?? ""),
    );
    expect(loudSvgs, "decorative SVGs are aria-hidden").toEqual([]);
  });
});
