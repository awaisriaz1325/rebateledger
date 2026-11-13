/** Automated WCAG 2.2 AA checks on every app page not already covered by a journey. */
import { expect, test } from "@playwright/test";
import { expectAccessible } from "./fixtures/app";

const PAGES = [
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
  "/app/settings/profile",
  "/app/settings/organization",
  "/app/settings/security",
  "/app/settings/reconciliation",
  "/app/settings/approvals",
  "/app/settings/members",
  "/app/settings/notifications",
  "/app/settings/templates",
  "/app/settings/plan",
  "/app/settings/audit",
];

for (const path of PAGES) {
  test(`accessible: ${path}`, async ({ page }) => {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.locator(".skeleton")).toHaveCount(0);
    await expectAccessible(page);
  });
}

test.describe("signed out", () => {
  test.use({ storageState: { cookies: [], origins: [] } });
  for (const path of ["/login", "/forgot-password", "/reset-password", "/verify-email", "/accept-invite", "/unsubscribe"]) {
    test(`accessible: ${path}`, async ({ page }) => {
      await page.goto(path);
      await expect(page.locator("main, body").first()).toBeVisible();
      await expectAccessible(page);
    });
  }
});
