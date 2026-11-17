/** Buying groups (v1.1 Phase 16): create a group, choose its members. */
import { expect, test } from "@playwright/test";
import { expectAccessible } from "./fixtures/app";

test("create a buying group and add a member supplier", async ({ page }) => {
  const name = `Buying group ${Date.now()}`;
  await page.goto("/app/suppliers/new");
  await page.getByLabel("Type").selectOption("buying_group");
  await expect(page.getByText(/never import purchases under the group's code/)).toBeVisible();
  await page.getByLabel(/^Name/).fill(name);
  await page.getByLabel(/^Supplier codes/).fill(`BG${Date.now()}`);
  await page.getByRole("button", { name: "Add supplier" }).click();
  await page.waitForURL(/\/app\/suppliers\/[0-9a-f-]{36}$/);

  await expect(page.getByText("Buying group", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Merge into…" })).toHaveCount(0);
  await page.getByRole("tab", { name: "Members" }).click();
  await page.getByLabel("Acme Electrical Supply").check();
  await page.getByRole("button", { name: "Save members" }).click();
  await expect(page.getByText(/Members saved/)).toBeVisible();
  await expectAccessible(page);

  // v1.2 Phase 23: the group's fee on passed-through rebates.
  await page.getByLabel("Fee (%)").fill("150");
  await expect(page.getByText("Enter a percentage from 0 to 99.9999.")).toBeVisible();
  await page.getByLabel("Fee (%)").fill("7.5");
  await page.getByRole("button", { name: "Save fee" }).click();
  await expect(page.getByText(/Group fee saved/)).toBeVisible();
  await page.reload();
  await page.getByRole("tab", { name: "Members" }).click();
  await expect(page.getByLabel("Fee (%)")).toHaveValue("7.5");
  await expectAccessible(page);

  await page.goto("/app/agreements/new");
  await expect(page.locator("#a-supplier").getByRole("option", { name: `${name} (buying group)` })).toBeAttached();
});
