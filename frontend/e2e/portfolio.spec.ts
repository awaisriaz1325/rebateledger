/** Advisor portfolio (v1.3 Phase 29). Isolation and the two-factor lock are covered by backend
 *  tests; this checks the page renders the user's organization, marked current, accessibly. */
import { expect, test } from "@playwright/test";
import { expectAccessible } from "./fixtures/app";

test("the portfolio lists the current organization", async ({ page }) => {
  await page.goto("/app/portfolio");
  await expect(page.getByRole("heading", { level: 1, name: "All organizations" })).toBeVisible();
  const table = page.getByRole("table", { name: "Your organizations" });
  await expect(table.getByText("(current)")).toBeVisible();
  await expect(table.getByRole("columnheader", { name: "Identified open variance" })).toBeVisible();
  await expectAccessible(page);
});
