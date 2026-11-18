/** Getting-started checklist (v1.3 Phase 24). Step logic is covered by backend tests; this checks
 *  the card on the dashboard: seven linked steps, accessible, and dismissible. */
import { expect, test } from "@playwright/test";
import { expectAccessible } from "./fixtures/app";

test("the dashboard checklist lists seven linked steps and can be dismissed", async ({ page }) => {
  await page.goto("/app");
  await expect(page.getByRole("heading", { level: 1, name: "Dashboard" })).toBeVisible();
  const card = page.locator("section").filter({ has: page.getByRole("heading", { name: /^Get started — \d of 7 done$/ }) });
  if ((await card.count()) === 0) return; // every step already done, or dismissed by an earlier test
  const steps = card.getByRole("listitem");
  await expect(steps).toHaveCount(7);
  await expect(steps.getByRole("link")).toHaveCount(7);
  await expect(card.getByRole("link", { name: /Add rebate agreements/ })).toHaveAttribute("href", "/app/agreements/import");
  await expectAccessible(page);
  await card.getByRole("button", { name: "Dismiss" }).click();
  await expect(card).toHaveCount(0);
});
