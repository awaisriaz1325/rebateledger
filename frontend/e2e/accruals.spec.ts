/** Month-end accruals (v1.1 Phase 15): GL settings, preview, sign-off gate. */
import { expect, test } from "@playwright/test";
import { expectAccessible } from "./fixtures/app";

test("set GL accounts, then preview a month end and see the sign-off gate", async ({ page }) => {
  await page.goto("/app/settings/accounting");
  await page.getByLabel("Rebate receivable account").fill("1250 Rebates receivable");
  await page.getByLabel(/^Offset account/).fill("5010 COGS - vendor rebates");
  await page.getByRole("button", { name: /Save/ }).click();
  await expect(page.getByText("Settings saved")).toBeVisible();
  await expectAccessible(page);

  await page.goto("/app/accruals");
  await expect(page.getByRole("heading", { level: 1, name: "Month-end accruals" })).toBeVisible();
  await expect(page.getByText("How to book this journal")).toBeVisible();
  await expect(page.getByText("GL accounts not set")).toHaveCount(0);
  const download = page.getByRole("button", { name: "Download journal" });
  await expect(download).toBeDisabled(); // needs the review checkbox (and lines)
  await page.getByLabel("Closing date (last day of a month)").fill("2025-05-30");
  await expect(page.getByText("The closing date must be the last day of a month.")).toBeVisible();
  await page.getByLabel("Closing date (last day of a month)").fill("2025-05-31");
  await expect(page.getByRole("heading", { name: /Outstanding at/ })).toBeVisible();
  await expectAccessible(page);
});
