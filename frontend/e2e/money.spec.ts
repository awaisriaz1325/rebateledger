/**
 * The core money journey on one fresh tenant, in order:
 * agreement → import (ambiguous dates) → preview → run → explain → credit split → claim → recovered.
 *
 * Hand-worked expectations (2% flat, quarterly, last calendar year Y, closed agreement):
 *   Q1: 10,000.00 + 5,000.00 = 15,000.00 × 0.02 = 300.00
 *   Q2: 20,000.00            × 0.02 = 400.00
 *   Q3, Q4: no purchases → 0.00 (not earned)                       total 700.00
 * A 350.00 credit split 300.00 → Q1 and 50.00 → Q2 leaves Q1 matched and
 * Q2 short-paid by 350.00, which a claim then recovers in full.
 */
import { expect, test, type Page } from "@playwright/test";
import { expectAccessible, seed } from "./fixtures/app";

test.describe.configure({ mode: "serial" });

const Y = new Date().getFullYear() - 1;
const AGREEMENT = "Acme 2% volume rebate";
const CSV = [
  "Vendor Code,Invoice No,SKU,Qty,Amount,Invoice Date",
  `ACME,INV-1001,WIRE-12,100,10000.00,01/02/${Y}`,
  `ACME,INV-1002,BRK-20,50,5000.00,03/04/${Y}`,
  `ACME,INV-1003,PANEL-200,20,20000.00,05/06/${Y}`,
].join("\n");

let agreementUrl = "";

async function toast(page: Page, text: string | RegExp) {
  await expect(page.locator("[data-sonner-toast]").filter({ hasText: text }).first()).toBeVisible();
}

test("create and activate an agreement", async ({ page }) => {
  await page.goto("/app/agreements/new");
  await expectAccessible(page);
  await page.locator("#a-supplier").selectOption({ label: "Acme Electrical Supply" });
  await page.locator("#a-name").fill(AGREEMENT);
  await page.getByLabel("Effective from").fill(`${Y}-01-01`);
  await page.getByLabel("Effective to").fill(`${Y}-12-31`);
  const save = page.getByRole("button", { name: "Save draft" });
  await expect(save).toBeEnabled();
  await save.click();
  await page.waitForURL(/\/app\/agreements\/[0-9a-f-]{36}$/);
  agreementUrl = new URL(page.url()).pathname;
  await page.getByRole("button", { name: "Activate" }).click();
  await toast(page, "Version activated");
  await expectAccessible(page);
});

test("import purchases: ambiguous dates must be chosen, then validate and commit", async ({ page }) => {
  await page.goto("/app/imports/new");
  await expectAccessible(page);
  await page.getByLabel("Purchase lines").check();
  await page.locator("#file").setInputFiles({ name: "purchases.csv", mimeType: "text/csv", buffer: Buffer.from(CSV) });
  await page.getByRole("button", { name: "Upload and continue" }).click();
  await page.waitForURL(/\/app\/imports\/[0-9a-f-]{36}$/);

  await expect(page.getByText("Dates are ambiguous")).toBeVisible();
  const save = page.getByRole("button", { name: "Save mapping and preview" });
  await expect(save).toBeDisabled(); // never guessed
  await expectAccessible(page);
  await page.getByLabel("Date format").selectOption("MM/DD/YYYY");
  await save.click();
  await expect(page.getByText("3 of 3 preview rows are valid")).toBeVisible();

  await page.getByRole("button", { name: "Validate the whole file" }).click();
  await expect(page.getByRole("heading", { name: "Full validation" })).toBeVisible({ timeout: 60_000 });
  await page.getByRole("button", { name: "Commit import" }).click();
  await expect(page.getByRole("heading", { name: "Result" })).toBeVisible({ timeout: 60_000 });
  await expect(page.locator("dt", { hasText: /^Committed$/ }).locator("..")).toContainText("3");
  await expectAccessible(page);
});

test("dry-run preview shows the hand-worked Q1 amount", async ({ page }) => {
  await page.goto(agreementUrl);
  await page.getByRole("tab", { name: "Preview" }).click();
  await page.getByLabel("Period containing").fill(`${Y}-02-15`);
  await page.getByRole("button", { name: "Preview", exact: true }).click();
  await expect(page.getByText("$300.00").first()).toBeVisible();
  await expectAccessible(page);
});

test("run, then explain an amount step by step", async ({ page }) => {
  await page.goto("/app/runs");
  await expectAccessible(page);
  await page.getByLabel("From").fill(`${Y}-01-01`);
  await page.getByLabel("To", { exact: true }).fill(`${Y}-12-31`);
  await page.getByRole("button", { name: "Start run" }).click();
  await page.waitForURL(/\/app\/runs\/[0-9a-f-]{36}$/);
  await expect(page.getByText("Total expected")).toBeVisible({ timeout: 90_000 });
  await expect(page.locator("dt", { hasText: /^Total expected$/ }).locator("..")).toContainText("$700.00");
  await expectAccessible(page);

  const q2 = page.getByRole("row").filter({ hasText: `${Y}-Q2` });
  await q2.getByRole("button", { name: "Explain" }).click();
  const drawer = page.getByRole("dialog", { name: "How this amount was calculated" });
  await expect(drawer).toBeVisible();
  await expect(drawer).toContainText("$400.00");
  await expect(drawer).toContainText("20,000.00");
  await expectAccessible(page);
});

test("results show both earned quarters as missing before any credit", async ({ page }) => {
  await page.goto("/app/results");
  await expectAccessible(page);
  for (const q of ["Q1", "Q2"]) {
    await expect(page.getByRole("row").filter({ hasText: `${Y}-${q}` })).toContainText("Missing");
  }
});

test("a manual credit is split across two periods", async ({ page }) => {
  await page.goto("/app/credits");
  await page.getByRole("button", { name: "Enter a credit" }).click();
  const enter = page.getByRole("dialog", { name: "Enter a credit" });
  await enter.getByLabel("Supplier").selectOption({ label: "Acme Electrical Supply" });
  await enter.getByLabel("Credit memo number").fill(`CM-${seed().tag}`);
  await enter.getByLabel("Date").fill(`${Y}-09-15`);
  await enter.getByLabel("Amount ($)").fill("350.00");
  await enter.getByRole("button", { name: "Save credit" }).click();
  await toast(page, "Credit recorded");

  const card = page.getByRole("listitem").filter({ hasText: `CM-${seed().tag}` });
  await expect(card).toContainText("$350.00");
  await expectAccessible(page);
  await card.getByRole("button", { name: "Allocate…" }).click();
  const dialog = page.getByRole("dialog", { name: `Allocate CM-${seed().tag}` });
  await dialog.getByLabel("Agreement").first().selectOption({ label: AGREEMENT });
  await dialog.getByLabel("Period start").first().fill(`${Y}-01-01`);
  await dialog.getByLabel("Period end").first().fill(`${Y}-03-31`);
  await dialog.getByLabel("Amount ($)").first().fill("300.00");
  await dialog.getByRole("button", { name: "Add another period" }).click();
  await dialog.getByLabel("Agreement").nth(1).selectOption({ label: AGREEMENT });
  await dialog.getByLabel("Period start").nth(1).fill(`${Y}-04-01`);
  await dialog.getByLabel("Period end").nth(1).fill(`${Y}-06-30`);
  await dialog.getByLabel("Amount ($)").nth(1).fill("50.00");
  await expectAccessible(page);
  await dialog.getByRole("button", { name: "Allocate", exact: true }).click();
  await toast(page, "Credit allocated");

  await page.goto("/app/results");
  await expect(page.getByRole("row").filter({ hasText: `${Y}-Q1` })).toContainText("Matched");
  const q2 = page.getByRole("row").filter({ hasText: `${Y}-Q2` });
  await expect(q2).toContainText("Short-paid");
  await expect(q2).toContainText("$350.00");
});

test("a claim goes from discrepancy to fully recovered", async ({ page }) => {
  await page.goto("/app/discrepancies");
  await expectAccessible(page);
  await page.getByRole("checkbox", { name: new RegExp(`${Y}-Q2`) }).check();
  await page.getByRole("button", { name: "Create claim" }).click();
  const create = page.getByRole("dialog", { name: "Create a claim" });
  await expect(create).toContainText("$350.00");
  await create.getByRole("button", { name: "Create claim" }).click();
  await page.waitForURL(/\/app\/claims\/[0-9a-f-]{36}$/);
  await expectAccessible(page);

  await page.getByRole("button", { name: "Mark submitted to supplier" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Confirm" }).click();
  await toast(page, /now submitted/i);

  await page.getByRole("button", { name: "Link a credit" }).click();
  const link = page.getByRole("dialog", { name: "Link a recovering credit" });
  await link.getByLabel("Enter a new credit").check();
  await link.getByLabel("Credit memo number").fill(`CM-R-${seed().tag}`);
  await link.getByLabel("Date").fill(`${Y + 1}-01-20`);
  await link.getByLabel("Amount ($)").fill("350.00");
  await expectAccessible(page);
  await link.getByRole("button", { name: "Link credit" }).click();
  await toast(page, "Recovery linked");

  await page.getByRole("button", { name: "Resolve: fully recovered" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Confirm" }).click();
  await toast(page, /now recovered/i);
  await expect(page.locator("dt", { hasText: /^Recovered$/ }).locator("..")).toContainText("$350.00");
});
