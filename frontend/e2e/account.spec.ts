import { expect, test } from "@playwright/test";
import { expectAccessible, firstLink, latestEmail, seed, signIn, stepUpIfAsked } from "./fixtures/app";
import { freshCode } from "./fixtures/totp";

test.describe.configure({ mode: "serial" });

test("an owner changes an organization setting (server confirms it)", async ({ page }) => {
  const { owner } = seed().users;
  await page.goto("/app/settings/organization");
  await expectAccessible(page);
  const name = page.getByLabel("Organization name");
  await name.fill(`E2E Distribution ${seed().tag} Ltd`);
  await page.getByRole("button", { name: "Save changes" }).click();
  await stepUpIfAsked(page, owner);
  await expect(page.getByText(/saved/i).first()).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Organization name")).toHaveValue(`E2E Distribution ${seed().tag} Ltd`);
});

test("an invited admin accepts, is made to set up two-factor, and lands in the app", async ({ page, browser }) => {
  const { owner } = seed().users;
  const email = `e2e-invitee-${seed().tag}@example.com`;
  await page.goto("/app/settings/members");
  await expectAccessible(page);
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Role", { exact: true }).selectOption("admin");
  await page.getByRole("button", { name: "Send invite" }).click();
  await stepUpIfAsked(page, owner);
  await expect(page.getByText(email).first()).toBeVisible();

  const mail = await latestEmail(email, /invit/i);
  const link = firstLink(mail.text, "/accept-invite");
  const invitee = await (await browser.newContext()).newPage();
  await invitee.goto(new URL(link).pathname + new URL(link).search);
  await expectAccessible(invitee);
  await invitee.getByLabel("Your name").fill("Ivy Invitee");
  await invitee.getByLabel("Choose a password").fill("A-very-long-e2e-passphrase-2026");
  await invitee.getByRole("button", { name: "Accept invitation" }).click();

  await invitee.waitForURL(/\/mfa\/setup/);
  await expectAccessible(invitee);
  await invitee.getByText("Can’t scan? Enter the key manually").click();
  const secret = (await invitee.locator("p.font-mono").first().innerText()).trim();
  await invitee.getByLabel("6-digit code").fill(await freshCode(secret));
  await invitee.getByRole("button", { name: "Turn on two-factor authentication" }).click();
  await expect(invitee.getByRole("list", { name: "Recovery codes" })).toBeVisible();
  await invitee.getByLabel("I have saved these codes").check();
  await invitee.getByRole("button", { name: "Continue" }).click();
  await invitee.waitForURL(/\/app(\/|$)/);
  await invitee.close();
});

test("signing out another session ends it immediately", async ({ browser }) => {
  const { admin } = seed().users;
  const first = await (await browser.newContext()).newPage();
  const second = await (await browser.newContext()).newPage();
  await signIn(first, admin);
  await signIn(second, admin);
  await first.goto("/app/settings/profile");
  await expectAccessible(first);
  const sessions = first.getByRole("list", { name: "Active sessions" });
  // Sign out every other session (earlier specs may have left some), one confirmed response at a time.
  const buttons = sessions.getByRole("button", { name: "Sign out" });
  await expect(buttons.first()).toBeVisible();
  while ((await buttons.count()) > 0) {
    const before = await buttons.count();
    await buttons.first().click();
    await expect(buttons).toHaveCount(before - 1);
  }
  await second.goto("/app/results");
  await expect(second).toHaveURL(/\/login/);
  await first.goto("/app");
  await expect(first).toHaveURL(/\/app$/);
});
