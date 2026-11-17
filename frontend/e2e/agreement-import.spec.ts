/** Bulk agreement import (v1.2 Phase 21): preview shows problems; a clean file creates drafts. */
import { expect, test } from "@playwright/test";
import { expectAccessible } from "./fixtures/app";

const HEADER = "agreement_ref,agreement_name,supplier,effective_from,period_type,fiscal_aligned,date_basis,measure,spend_basis,threshold_comparison,negative_result,rounding_mode,payment_terms_days,stacking,prorate_thresholds_on_partial_period,zero_baseline_policy,component_key,component_type,rate,tier_threshold,tier_rate";
const COMMON = "2026-01-01,quarterly,true,invoice_date,spend,net_of_returns,gte,floor_at_zero,half_up,30,stackable,false,needs_review";

test("preview a file with a problem, fix it, and create drafts", async ({ page }) => {
  const ref = `BULK-${Date.now()}`;
  await page.goto("/app/agreements");
  await page.getByRole("link", { name: "Import from CSV" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Import agreements" })).toBeVisible();
  await page.getByText("Column guide").click();
  await expect(page.getByRole("table", { name: "Columns of the agreement import file" })).toBeVisible();

  const bad = `${HEADER}\n${ref},Bulk flat,Acme Electrical Supply,${COMMON},base,flat_percent,2,,\n`;
  await page.getByLabel("CSV file").setInputFiles({ name: "agreements.csv", mimeType: "text/csv", buffer: Buffer.from(bad) });
  await page.getByRole("button", { name: "Preview" }).click();
  const problems = page.getByRole("table", { name: "Problems found in the file" });
  await expect(problems).toContainText("write 0.02 or 2%");
  await expect(page.getByText("Fix the file first")).toBeVisible();
  await expectAccessible(page);

  const good = `${HEADER}\n${ref},Bulk tiers,Acme Electrical Supply,${COMMON},tiers,tiered_all_units,,0,1%\n${ref},Bulk tiers,Acme Electrical Supply,${COMMON},tiers,tiered_all_units,,50000,2%\n`;
  await page.getByLabel("CSV file").setInputFiles({ name: "agreements.csv", mimeType: "text/csv", buffer: Buffer.from(good) });
  await page.getByRole("button", { name: "Preview" }).click();
  const items = page.getByRole("table", { name: "Agreements that the file would create or update" });
  await expect(items).toContainText(ref);
  await expect(items).toContainText("Create draft");
  await page.getByRole("button", { name: "Create 1 draft" }).click();
  await page.waitForURL(/\/app\/agreements$/);
  await expect(page.getByText("1 draft created")).toBeVisible();
});
