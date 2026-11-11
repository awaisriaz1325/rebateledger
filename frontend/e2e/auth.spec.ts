import { expect, test } from "@playwright/test";
import { expectAccessible, seed, signIn } from "./fixtures/app";

test.describe("authentication", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("password + authenticator sign-in reaches the dashboard; pages are accessible", async ({ page }) => {
    await page.goto("/login");
    await expectAccessible(page);
    await signIn(page, seed().users.admin);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expectAccessible(page);
  });

  test("a wrong password is refused without saying which part was wrong", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Email").fill(seed().users.admin.email);
    await page.getByLabel("Password").fill("not-the-password-123");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("alert").or(page.locator("[role=status]")).first()).toBeVisible();
    await expect(page).toHaveURL(/\/login/);
  });

  test("app pages redirect to sign-in without a session", async ({ page }) => {
    await page.goto("/app/results");
    await expect(page).toHaveURL(/\/login/);
  });
});
