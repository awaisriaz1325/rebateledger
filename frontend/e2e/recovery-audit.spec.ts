/** Look-back recovery audit (v1.2 Phase 20): coverage, calculation, identified shortfalls. */
import { expect, test } from "@playwright/test";
import { expectAccessible } from "./fixtures/app";

const Y = new Date().getFullYear() - 1;

test("check coverage, run the calculation and see identified (not recovered) shortfalls", async ({ page }) => {
  await page.goto("/app/recovery-audit");
  await expect(page.getByRole("heading", { level: 1, name: "Recovery audit" })).toBeVisible();
  await page.getByLabel("From").fill(`${Y}-01-01`);
  await page.getByLabel(/^To/).fill(`${Y}-12-31`);
  await page.getByRole("button", { name: "Check coverage" }).click();
  await expect(page.getByRole("table", { name: "Agreement and purchase-history coverage per supplier" })).toContainText("Acme Electrical Supply");
  await expectAccessible(page);

  await page.getByRole("button", { name: "Run the calculation for this range" }).click();
  await expect(page.getByText("Calculation finished.")).toBeVisible({ timeout: 90_000 });
  await expect(page.getByText("Identified, not recovered", { exact: true })).toBeVisible();
  await expect(page.getByText(/^Identified shortfall:/)).toBeVisible();
  await expectAccessible(page);
});
