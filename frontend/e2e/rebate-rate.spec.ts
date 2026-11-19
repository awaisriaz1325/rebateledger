/** Effective rebate rate (v1.3 Phase 28): the dashboard tile opens the report. Numbers are
 *  covered by a hand-worked backend test. */
import { expect, test } from "@playwright/test";
import { expectAccessible } from "./fixtures/app";

test("the dashboard rate tile opens the effective rebate rate report", async ({ page }) => {
  await page.goto("/app");
  const tile = page.getByRole("link", { name: /Rebate earned, % of purchases/ });
  await expect(tile).toBeVisible();
  await tile.click();
  await page.waitForURL(/\/app\/reports\?report=rebate_rate$/);
  await expect(page.getByRole("heading", { name: "Effective rebate rate" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Effective rebate rate/ })).toHaveAttribute("aria-current", "page");
  await expectAccessible(page);
});
