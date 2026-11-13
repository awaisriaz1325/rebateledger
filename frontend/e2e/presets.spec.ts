/** ERP presets (v1.1 Phase 12): recognise an ERP export, apply its mapping, user confirms. */
import { expect, test } from "@playwright/test";
import { expectAccessible, seed } from "./fixtures/app";

test("a Prophet 21-shaped export is recognised, mapped and committed after the user confirms", async ({ page }) => {
  const s = seed();
  const stamp = Date.now();
  const csv = [
    "Supplier ID,Vendor Invoice No,Line No,Item ID,Qty Received,Unit Cost,Extended Cost,Invoice Date,Date Received,Location ID",
    `${s.supplier_code},P21-${stamp},1,WIRE-12,10,4.50,45.00,02/10/2026,02/09/2026,MAIN`,
    `${s.supplier_code},P21-${stamp},2,BOX-4,2,12.00,24.00,02/10/2026,02/09/2026,MAIN`,
  ].join("\n");

  await page.goto("/app/imports/new");
  await page.getByLabel("Purchase lines").check();
  await page.locator("#file").setInputFiles({ name: `p21-${stamp}.csv`, mimeType: "text/csv", buffer: Buffer.from(csv) });
  await page.getByRole("button", { name: "Upload and continue" }).click();
  await page.waitForURL(/\/app\/imports\/[0-9a-f-]{36}$/);

  await expect(page.getByText("This looks like an export from Epicor Prophet 21")).toBeVisible();
  await expectAccessible(page);
  await page.getByRole("button", { name: "Use Epicor Prophet 21 mapping" }).click();
  await expect(page.getByText("Mapping from the Epicor Prophet 21 preset")).toBeVisible();
  await expect(page.getByLabel(/^SKU/)).toHaveValue("Item ID");
  await expect(page.getByLabel(/^Extended amount/)).toHaveValue("Extended Cost");
  await expect(page.getByLabel("Date format")).toHaveValue("MM/DD/YYYY");

  await page.getByRole("button", { name: "Save mapping and preview" }).click();
  await expect(page.getByText("2 of 2 preview rows are valid")).toBeVisible();
  await page.getByRole("button", { name: "Validate the whole file" }).click();
  await expect(page.getByRole("heading", { name: "Full validation" })).toBeVisible({ timeout: 60_000 });
  await page.getByRole("button", { name: "Commit import" }).click();
  await expect(page.getByRole("heading", { name: "Result" })).toBeVisible({ timeout: 60_000 });
  await expect(page.locator("dt", { hasText: /^Committed$/ }).locator("..")).toContainText("2");
});

test("presets are listed in settings and can be copied to an editable template", async ({ page }) => {
  await page.goto("/app/settings/templates");
  const table = page.getByRole("table", { name: "ERP report presets" });
  await expect(table).toBeVisible();
  const row = table.getByRole("row").filter({ hasText: "NetSuite" }).filter({ hasText: "credits" });
  await expect(row.getByText("Unverified")).toBeVisible();
  await expectAccessible(page);
  await row.getByRole("button", { name: /Copy to my templates/ }).click();
  await expect(page.getByText(/Saved as template “NetSuite credits”/)).toBeVisible();
  await expect(page.getByRole("table", { name: "Import templates" })).toContainText("NetSuite credits");
});
