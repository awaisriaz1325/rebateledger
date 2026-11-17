/** Supplier statement compare (v1.2 Phase 22): import a statement, see it, choose its agreement. */
import { expect, test } from "@playwright/test";
import { expectAccessible, seed } from "./fixtures/app";

const Y = new Date().getFullYear() - 1;

test("an imported statement line without a known program asks for its agreement", async ({ page }) => {
  const s = seed();
  const stamp = Date.now();
  const csv = ["Vendor,Program,Period from,Period to,Rebate,Statement", `${s.supplier_code},NOPE-${stamp},${Y}-01-01,${Y}-03-31,1234.56,ST-${stamp}`].join("\n");
  await page.goto("/app/imports/new");
  await page.getByLabel("Supplier statement").check();
  await page.locator("#file").setInputFiles({ name: `statement-${stamp}.csv`, mimeType: "text/csv", buffer: Buffer.from(csv) });
  await page.getByRole("button", { name: "Upload and continue" }).click();
  await page.waitForURL(/\/app\/imports\/[0-9a-f-]{36}$/);
  await page.getByLabel("Date format").selectOption("YYYY-MM-DD");
  await page.getByRole("button", { name: "Save mapping and preview" }).click();
  await expect(page.getByText("1 of 1 preview rows are valid")).toBeVisible();
  await page.getByRole("button", { name: "Validate the whole file" }).click();
  await expect(page.getByRole("heading", { name: "Full validation" })).toBeVisible({ timeout: 60_000 });
  await page.getByRole("button", { name: "Commit import" }).click();
  await expect(page.getByRole("heading", { name: "Result" })).toBeVisible({ timeout: 60_000 });

  await page.goto("/app/statements");
  await expect(page.getByRole("heading", { level: 1, name: "Supplier statements" })).toBeVisible();
  await page.getByLabel("Show").selectOption("unmatched");
  const table = page.getByRole("table", { name: "Supplier statement lines" });
  const row = table.getByRole("row").filter({ hasText: `ST-${stamp}` });
  await expect(row).toContainText("$1,234.56");
  await expect(row).toContainText("No agreement");
  await expectAccessible(page);
  await row.getByRole("button", { name: "Choose agreement" }).click();
  const dialog = page.getByRole("dialog", { name: "Agreement for this statement line" });
  await expect(dialog.getByLabel("Agreement")).toBeVisible();
  await expectAccessible(page);
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toHaveCount(0);
});
