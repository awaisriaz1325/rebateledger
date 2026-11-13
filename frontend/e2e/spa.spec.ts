/** SPA claims (v1.1 Phase 17): add a SPA, import sales, claim, record payment. */
import { expect, test } from "@playwright/test";
import { expectAccessible, seed } from "./fixtures/app";

const Y = new Date().getFullYear() - 1;

test("SPA sales become a claim that is submitted and paid", async ({ page }) => {
  const s = seed();
  const stamp = Date.now();
  await page.goto("/app/spa");
  await expect(page.getByRole("heading", { level: 1, name: "SPA claims" })).toBeVisible();
  await page.getByRole("tab", { name: "SPAs" }).click();
  await page.getByRole("button", { name: "Add SPA" }).click();
  const dialog = page.getByRole("dialog", { name: "Add SPA" });
  await dialog.getByLabel(/^Supplier/).selectOption({ label: "Acme Electrical Supply" });
  await dialog.getByLabel(/^SPA number/).fill(`SPA-${stamp}`);
  await dialog.getByLabel(/^Customer/).fill("Hospital Build");
  await dialog.getByLabel(/^Valid from/).fill(`${Y}-01-01`);
  await dialog.getByLabel(/^Valid to/).fill(`${Y}-12-31`);
  await dialog.getByLabel(/^Items/).fill(`WIRE-${stamp}, 10.00, 7.50\nBOX-${stamp}, 40.00, 31.25, 100`);
  await expectAccessible(page);
  await dialog.getByRole("button", { name: "Save SPA" }).click();
  await expect(page.getByRole("table", { name: "SPAs" })).toContainText(`SPA-${stamp}`);

  const csv = [
    "Vendor,Invoice,Date,Customer,Item,Qty,Cost",
    `${s.supplier_code},S-${stamp}-1,${Y}-02-10,Hospital Build,WIRE-${stamp},10,10.00`,
    `${s.supplier_code},S-${stamp}-2,${Y}-02-11,Hospital Build,BOX-${stamp},4,40.00`,
  ].join("\n");
  await page.goto("/app/imports/new");
  await page.getByLabel("Sales lines (SPA claims)").check();
  await page.locator("#file").setInputFiles({ name: `sales-${stamp}.csv`, mimeType: "text/csv", buffer: Buffer.from(csv) });
  await page.getByRole("button", { name: "Upload and continue" }).click();
  await page.waitForURL(/\/app\/imports\/[0-9a-f-]{36}$/);
  await page.getByLabel("Date format").selectOption("YYYY-MM-DD");
  await page.getByRole("button", { name: "Save mapping and preview" }).click();
  await expect(page.getByText("2 of 2 preview rows are valid")).toBeVisible();
  await page.getByRole("button", { name: "Validate the whole file" }).click();
  await expect(page.getByRole("heading", { name: "Full validation" })).toBeVisible({ timeout: 60_000 });
  await page.getByRole("button", { name: "Commit import" }).click();
  await expect(page.getByRole("heading", { name: "Result" })).toBeVisible({ timeout: 60_000 });

  // WIRE: (10.00 − 7.50) × 10 = 25.00 ; BOX: (40.00 − 31.25) × 4 = 35.00 → 60.00 claimable
  await page.goto("/app/spa");
  await expect(page.getByRole("table", { name: "SPA summary by supplier" })).toContainText("$60.00");
  await expectAccessible(page);
  await page.getByRole("tab", { name: "Claims" }).click();
  await page.getByRole("button", { name: "New claim" }).click();
  const make = page.getByRole("dialog", { name: "New SPA claim" });
  await make.getByLabel(/^Supplier/).selectOption({ label: "Acme Electrical Supply" });
  await make.getByLabel(/^Sales up to/).fill(`${Y}-12-31`);
  await make.getByRole("button", { name: "Create claim" }).click();
  const claims = page.getByRole("table", { name: "SPA claims" });
  await expect(claims).toContainText("$60.00");
  await claims.getByRole("button", { name: /SPA-CL-/ }).first().click();
  const drawer = page.getByRole("dialog");
  await expect(drawer.getByRole("table", { name: "Lines in this claim" })).toContainText(`WIRE-${stamp}`);
  await drawer.getByRole("button", { name: "Mark submitted" }).click();
  await expect(page.getByText("Claim is now submitted")).toBeVisible();
  await drawer.getByLabel("Amount paid ($)").fill("60.00");
  await drawer.getByLabel("Credit memo reference").fill(`CM-${stamp}`);
  await drawer.getByRole("button", { name: "Record payment" }).click();
  await expect(page.getByText("Claim is now paid")).toBeVisible();
  await expectAccessible(page);
});
