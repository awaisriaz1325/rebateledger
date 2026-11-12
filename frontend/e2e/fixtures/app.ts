/** Shared E2E helpers: seeded users, sign-in, Mailpit and accessibility checks. */
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";
import { freshCode } from "./totp";

export interface SeedUser { email: string; password: string; totp_secret: string }
export interface Seed { tag: string; tenant_id: string; supplier_code: string; users: { owner: SeedUser; admin: SeedUser; ops: SeedUser } }

export const STATE_DIR = path.join(__dirname, "..", ".state");
export const MAILPIT = process.env.RL_E2E_MAILPIT ?? "http://localhost:8026";

export function seed(): Seed {
  return JSON.parse(readFileSync(path.join(STATE_DIR, "seed.json"), "utf8")) as Seed;
}

/** Password + authenticator sign-in through the real UI. */
export async function signIn(page: Page, user: SeedUser, landing: RegExp = /\/app(\/|$)/): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(user.email);
  await page.getByLabel("Password").fill(user.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByLabel("Authentication code").fill(await freshCode(user.totp_secret));
  await page.getByRole("button", { name: "Verify" }).click();
  await page.waitForURL(landing);
}

/** Complete the step-up dialog (password + authenticator code) if the API asks for it. */
export async function stepUpIfAsked(page: Page, user: SeedUser): Promise<void> {
  const dialog = page.getByRole("dialog").filter({ has: page.getByLabel("Password") });
  try {
    await dialog.waitFor({ state: "visible", timeout: 3_000 });
  } catch {
    return; // recent sign-in already counts as step-up
  }
  await dialog.getByLabel("Password").fill(user.password);
  const code = dialog.getByLabel("Authenticator code");
  if (await code.count()) await code.fill(await freshCode(user.totp_secret));
  await dialog.getByRole("button", { name: "Confirm" }).click();
}

/** WCAG 2.2 AA automated checks on the current page (no exclusions). */
export async function expectAccessible(page: Page): Promise<void> {
  // Let enter/exit transitions (toasts, drawers) settle so contrast is measured on the final colours.
  await page.waitForFunction(() => document.getAnimations().every((a) => a.playState !== "running" || a.effect?.getComputedTiming().iterations === Infinity));
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
  const summary = results.violations.map((v) => `${v.id} (${v.impact}): ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(", ")}`);
  expect(summary, "axe violations").toEqual([]);
}

interface MailSummary { ID: string; Subject: string }

/** Latest email to an address (polls Mailpit's API). */
export async function latestEmail(to: string, subject: RegExp): Promise<{ subject: string; text: string }> {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    const res = await fetch(`${MAILPIT}/api/v1/search?query=${encodeURIComponent(`to:${to}`)}&limit=10`);
    const body = (await res.json()) as { messages: MailSummary[] };
    const hit = body.messages.find((m) => subject.test(m.Subject));
    if (hit) {
      const msg = (await (await fetch(`${MAILPIT}/api/v1/message/${hit.ID}`)).json()) as { Subject: string; Text: string };
      return { subject: msg.Subject, text: msg.Text };
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`no email to ${to} matching ${subject}`);
}

export function firstLink(text: string, pathPrefix: string): string {
  const match = text.match(new RegExp(`https?://[^\\s)]+${pathPrefix.replace(/\//g, "\\/")}[^\\s)]*`));
  if (!match) throw new Error(`no ${pathPrefix} link in email`);
  return match[0];
}
