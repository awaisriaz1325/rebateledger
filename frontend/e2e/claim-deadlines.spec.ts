/** Claim-deadline alerts (v1.3 Phase 25): the alert can be turned off per channel like the others.
 *  When it fires is covered by backend tests with fixed dates. */
import { expect, test } from "@playwright/test";

test("claim-deadline alerts appear in notification settings and can be switched off by email", async ({ page }) => {
  await page.goto("/app/settings/notifications");
  const table = page.getByRole("table", { name: "Notification preferences" });
  await expect(table.getByRole("cell", { name: "Claim deadline approaching", exact: true })).toBeVisible();
  const email = page.getByLabel("Claim deadline approaching by email");
  // The box reflects the server's saved state, so click and wait for it (no optimistic UI).
  if (await email.isChecked()) {
    await email.click();
    await expect(email).not.toBeChecked();
  }
  await page.reload();
  await expect(page.getByLabel("Claim deadline approaching by email")).not.toBeChecked();
  await page.getByLabel("Claim deadline approaching by email").click();
  await expect(page.getByLabel("Claim deadline approaching by email")).toBeChecked();
  await page.reload();
  await expect(page.getByLabel("Claim deadline approaching by email")).toBeChecked();
});
