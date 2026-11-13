/** Deal modelling (v1.1 Phase 13): compare options, then turn one into a draft. */
import { expect, test } from "@playwright/test";
import { expectAccessible } from "./fixtures/app";

test("compare two options side by side and create a draft from one", async ({ page }) => {
  await page.goto("/app/agreements/model");
  await expect(page.getByRole("heading", { level: 1, name: "Deal modelling" })).toBeVisible();
  await page.getByLabel(/^Supplier/).selectOption({ label: "Acme Electrical Supply" });
  await page.getByRole("button", { name: "Add option" }).click();
  await expect(page.getByRole("heading", { name: "Option B" })).toBeVisible();
  await page.getByLabel("Name of option B").fill("Richer tiers");
  await expectAccessible(page);

  await page.getByRole("button", { name: "Compare options" }).click();
  const comparison = page.getByRole("table", { name: "Option comparison" });
  await expect(comparison).toBeVisible({ timeout: 30_000 });
  await expect(comparison.getByRole("columnheader", { name: "Option A" })).toBeVisible();
  await expect(comparison.getByRole("columnheader", { name: "Richer tiers" })).toBeVisible();
  await expect(comparison.getByRole("rowheader", { name: "If +10% spend" })).toBeVisible();
  await expect(page.getByRole("table", { name: "Rebate by period" })).toBeVisible();
  await expectAccessible(page);

  await page.getByRole("button", { name: "Create agreement draft from “Richer tiers”" }).click();
  const dialog = page.getByRole("dialog", { name: "Create agreement draft" });
  await dialog.getByLabel(/^Agreement name/).fill(`Modelled deal ${Date.now()}`);
  await dialog.getByRole("button", { name: "Save draft" }).click();
  await page.waitForURL(/\/app\/agreements\/[0-9a-f-]{36}$/);
});
