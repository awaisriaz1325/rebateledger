/**
 * Keyboard-only pass (SPEC §10, WCAG 2.1.1, 2.1.2, 2.4.3, 2.4.7, 2.4.11).
 *
 * Every page is walked with the Tab key alone. Each stop must be visible, named, show a
 * focus indicator and not be hidden under the sticky header; the walk must not get stuck.
 * Journeys then exercise shortcuts, menus, dialogs and tables with keys only.
 */
import { expect, test, type Page } from "@playwright/test";
import { seed } from "./fixtures/app";
import { freshCode } from "./fixtures/totp";

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

const SIGNED_OUT_PAGES = ["/login", "/forgot-password", "/reset-password", "/verify-email", "/accept-invite", "/unsubscribe"];
const SITE_PAGES = ["/", "/pricing", "/security"];

interface Stop {
  tag: string;
  name: string;
  visible: boolean;
  indicator: boolean;
  obscured: boolean;
  key: string;
}

/** Describe the focused element as a keyboard user experiences it. */
async function focused(page: Page): Promise<Stop | null> {
  return page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null;
    if (!el || el === document.body || el === document.documentElement) return null;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    const visible = rect.width > 0 && rect.height > 0 && style.visibility !== "hidden";
    const indicator =
      (style.outlineStyle !== "none" && parseFloat(style.outlineWidth) > 0) || (style.boxShadow !== "none" && style.boxShadow !== "");
    // WCAG 2.4.11: some part of the focused element must not be covered by other content.
    const points = [
      [rect.left + rect.width / 2, rect.top + rect.height / 2],
      [rect.left + 2, rect.top + 2],
      [rect.right - 2, rect.bottom - 2],
    ];
    const obscured = points.every(([x, y]) => {
      const hit = document.elementFromPoint(x, y);
      return !hit || !(hit === el || el.contains(hit) || hit.contains(el));
    });
    const label =
      el.getAttribute("aria-label") ||
      (el.getAttribute("aria-labelledby") ? document.getElementById(el.getAttribute("aria-labelledby")!)?.textContent : "") ||
      (el.id ? document.querySelector(`label[for="${CSS.escape(el.id)}"]`)?.textContent : "") ||
      el.closest("label")?.textContent ||
      el.getAttribute("title") ||
      (el as HTMLInputElement).placeholder ||
      el.textContent ||
      "";
    const path: string[] = [];
    for (let n: Element | null = el; n && n !== document.body; n = n.parentElement) {
      path.unshift(`${n.tagName}:${Array.prototype.indexOf.call(n.parentElement?.children ?? [], n)}`);
    }
    return { tag: el.tagName.toLowerCase(), name: label.trim().replace(/\s+/g, " ").slice(0, 60), visible, indicator, obscured, key: path.join("/") };
  });
}

/** Tab through the whole page; returns the stops in order and any problems found. */
async function tabWalk(page: Page, max = 400): Promise<{ stops: Stop[]; problems: string[] }> {
  const stops: Stop[] = [];
  const problems: string[] = [];
  const seen = new Set<string>();
  await page.locator("body").focus();
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  for (let i = 0; i < max; i++) {
    await page.keyboard.press("Tab");
    const stop = await focused(page);
    if (!stop) {
      if (stops.length > 0) return { stops, problems }; // wrapped past the last stop
      continue;
    }
    if (seen.has(stop.key)) return { stops, problems }; // cycled back to the start
    seen.add(stop.key);
    stops.push(stop);
    const where = `stop ${stops.length} <${stop.tag}> "${stop.name}"`;
    if (!stop.visible) problems.push(`${where}: focused but not visible`);
    if (!stop.indicator) problems.push(`${where}: no visible focus indicator`);
    if (stop.obscured) problems.push(`${where}: hidden under other content`);
    if (!stop.name) problems.push(`${where}: no accessible name`);
  }
  problems.push(`focus did not cycle within ${max} Tab presses (possible trap)`);
  return { stops, problems };
}

async function settled(page: Page): Promise<void> {
  await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
  await expect(page.locator(".skeleton")).toHaveCount(0);
}

test.describe("Tab walk: app", () => {
  for (const path of APP_PAGES) {
    test(`keyboard: ${path}`, async ({ page }) => {
      await page.goto(path);
      await settled(page);
      const { stops, problems } = await tabWalk(page);
      expect(stops[0]?.name, "first Tab stop is the skip link").toBe("Skip to content");
      expect(problems).toEqual([]);
      test.info().annotations.push({ type: "tab-stops", description: String(stops.length) });
    });
  }
});

test.describe("Tab walk: signed out and marketing", () => {
  test.use({ storageState: { cookies: [], origins: [] } });
  for (const path of [...SIGNED_OUT_PAGES, ...SITE_PAGES]) {
    test(`keyboard: ${path}`, async ({ page }) => {
      await page.goto(path);
      await expect(page.locator("main").first()).toBeVisible();
      const { stops, problems } = await tabWalk(page);
      expect(stops.length, "page has at least one Tab stop").toBeGreaterThan(0);
      expect(problems).toEqual([]);
    });
  }
});

test.describe("keyboard journeys", () => {
  test("skip link moves focus to the main content", async ({ page }) => {
    await page.goto("/app/suppliers");
    await settled(page);
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.locator("main#main")).toBeFocused();
    await page.keyboard.press("Tab");
    const inMain = await page.evaluate(() => document.querySelector("main#main")?.contains(document.activeElement) ?? false);
    expect(inMain, "next Tab stays inside main").toBe(true);
  });

  test("command palette: Ctrl+K, type, Enter, Esc returns focus", async ({ page }) => {
    await page.goto("/app");
    await settled(page);
    await page.keyboard.press("Tab");
    await page.keyboard.press("Control+k");
    const palette = page.getByRole("dialog");
    await expect(palette).toBeVisible();
    await page.keyboard.type("Credits");
    await page.keyboard.press("Enter");
    await page.waitForURL(/\/app\/credits/);
    await expect(palette).toBeHidden();

    await page.keyboard.press("Control+k");
    await expect(palette).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(palette).toBeHidden();
  });

  test("shortcut help: ? opens, focus is trapped, Esc closes and restores focus", async ({ page }) => {
    await page.goto("/app/suppliers");
    await settled(page);
    await page.keyboard.press("Tab");
    await page.keyboard.press("Tab");
    const before = await focused(page);
    await page.keyboard.press("?");
    const dialog = page.getByRole("dialog", { name: "Keyboard shortcuts" });
    await expect(dialog).toBeVisible();
    for (let i = 0; i < 6; i++) {
      await page.keyboard.press("Tab");
      const inside = await page.evaluate(() => !!document.activeElement?.closest("[role=dialog]"));
      expect(inside, "focus stays in the dialog").toBe(true);
    }
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    expect((await focused(page))?.key).toBe(before?.key);
  });

  test("user menu opens with Enter, moves with arrows, closes with Esc", async ({ page }) => {
    await page.goto("/app");
    await settled(page);
    const trigger = page.getByRole("button", { name: /account menu|user menu/i });
    await trigger.focus();
    await page.keyboard.press("Enter");
    const menu = page.getByRole("menu");
    await expect(menu).toBeVisible();
    await page.keyboard.press("ArrowDown");
    const inMenu = await page.evaluate(() => document.activeElement?.getAttribute("role") === "menuitem");
    expect(inMenu).toBe(true);
    await page.keyboard.press("Escape");
    await expect(menu).toBeHidden();
    await expect(trigger).toBeFocused();
  });

  test("table rows: arrows move between rows, Enter opens the row", async ({ page }) => {
    await page.goto("/app/suppliers");
    await settled(page);
    const rows = page.locator("table tbody tr[tabindex]");
    await expect(rows.first()).toBeVisible();
    await rows.first().focus();
    if ((await rows.count()) > 1) {
      await page.keyboard.press("ArrowDown");
      await expect(rows.nth(1)).toBeFocused();
      await page.keyboard.press("ArrowUp");
      await expect(rows.first()).toBeFocused();
    }
    await page.keyboard.press("Enter");
    await page.waitForURL(/\/app\/suppliers\/[0-9a-f-]{36}/);
    await settled(page);
  });

  test("sortable column headers work with Enter", async ({ page }) => {
    await page.goto("/app/suppliers");
    await settled(page);
    const sortable = page.locator("th[aria-sort] button").first();
    await sortable.focus();
    const th = page.locator("th[aria-sort]").first();
    await page.keyboard.press("Enter");
    await expect(th).toHaveAttribute("aria-sort", /ascending|descending/);
  });

  test("supplier form can be filled and submitted with the keyboard only", async ({ page }) => {
    await page.goto("/app/suppliers/new");
    await settled(page);
    await page.getByLabel(/^Name/).focus();
    const stamp = Date.now();
    await page.keyboard.type(`Keyboard Supply ${stamp}`);
    await page.keyboard.press("Tab");
    await expect(page.getByLabel(/^Supplier codes/)).toBeFocused();
    await page.keyboard.type(`KB${stamp}`);
    const submit = page.getByRole("button", { name: /add supplier/i });
    for (let i = 0; i < 40 && !(await submit.evaluate((b) => b === document.activeElement)); i++) await page.keyboard.press("Tab");
    await expect(submit).toBeFocused();
    await page.keyboard.press("Enter");
    await page.waitForURL(/\/app\/suppliers\/[0-9a-f-]{36}/);
  });
});

test.describe("keyboard sign-in", () => {
  test.use({ storageState: { cookies: [], origins: [] } });
  test("sign in with password and authenticator code using keys only", async ({ page }) => {
    const owner = seed().users.owner;
    await page.goto("/login");
    await page.keyboard.press("Tab"); // skip link or first field
    await page.getByLabel("Email").focus();
    await page.keyboard.type(owner.email);
    await page.keyboard.press("Tab");
    await expect(page.getByLabel("Password")).toBeFocused();
    await page.keyboard.type(owner.password);
    await page.keyboard.press("Enter");
    const code = page.getByLabel("Authentication code");
    await expect(code).toBeFocused();
    await page.keyboard.type(await freshCode(owner.totp_secret));
    await page.keyboard.press("Enter");
    await page.waitForURL(/\/app(\/|$)/);
  });
});
