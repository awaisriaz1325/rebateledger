/** Supplier scorecard (v1.3 Phase 26): the tab on a supplier page and the report entry.
 *  The numbers are covered by a hand-worked backend test. */
import { expect, test } from "@playwright/test";
import { expectAccessible } from "./fixtures/app";

test("a supplier page has a scorecard tab and the report is listed", async ({ page }) => {
  await page.goto("/app/suppliers");
  await page.getByRole("link", { name: "Acme Electrical Supply", exact: true }).first().click();
  await page.waitForURL(/\/app\/suppliers\/[0-9a-f-]{36}$/);
  await page.getByRole("tab", { name: "Scorecard" }).click();
  await expect(page.getByText(/Scorecard, last 12 months|Nothing owed and due yet/)).toBeVisible();
  await expectAccessible(page);

  await page.goto("/app/reports");
  await page.getByRole("button", { name: /Supplier scorecard/ }).click();
  await expect(page.getByRole("heading", { name: "Supplier scorecard" })).toBeVisible();
  await expectAccessible(page);
});
