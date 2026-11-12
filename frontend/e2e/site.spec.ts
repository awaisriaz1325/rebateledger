/** Marketing site: accessibility, content integrity, SEO files, pilot request end to end. */
import { expect, test } from "@playwright/test";
import { expectAccessible, latestEmail, seed, signIn } from "./fixtures/app";

test.use({ storageState: { cookies: [], origins: [] } });

const PAGES = ["/", "/how-it-works", "/features", "/security", "/pricing", "/about", "/contact", "/request-a-pilot", "/privacy", "/terms", "/dpa", "/cookies"];

/** Phrases that would claim proof we do not have (SPEC §4.16 content integrity). */
const INVENTED_PROOF = [
  /trusted by/i,
  /\b\d[\d,]*\+?\s+(customers|distributors|companies|teams)\b/i,
  /\$\s?\d[\d,.]*\s*(k|m|million)?\s+(recovered|saved)/i,
  /\b\d{1,3}\s?%\s+(more|of|increase|faster|recovery)/i,
  /SOC\s?2\s+(type\s+(i|ii)\s+)?(certified|compliant|report)/i,
  /ISO\s?27001\s+(certified|compliant)/i,
  /★|rated \d/i,
];

for (const path of PAGES) {
  test(`marketing page ${path} is accessible and makes no invented claims`, async ({ page }) => {
    const res = await page.goto(path);
    expect(res?.status()).toBe(200);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expectAccessible(page);
    const text = await page.locator("body").innerText();
    for (const pattern of INVENTED_PROOF) expect(text, `${path} matches ${pattern}`).not.toMatch(pattern);
    if (["/privacy", "/terms", "/dpa", "/cookies"].includes(path)) await expect(page.getByText("[LEGAL REVIEW REQUIRED]")).toBeVisible();
  });
}

test("pricing shows plans from the catalog with a pilot CTA and no checkout", async ({ page }) => {
  await page.goto("/pricing");
  await expect(page.getByRole("heading", { level: 2, name: "Growth" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Request a pilot" }).first()).toBeVisible();
  // No way to buy online: no checkout, card or buy-now control (the copy itself says there is no card checkout).
  await expect(page.getByRole("link", { name: /checkout|credit card|buy now/i })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /checkout|credit card|buy now/i })).toHaveCount(0);
});

test("404, robots, sitemap and the social image", async ({ page, request }) => {
  const res = await page.goto("/no-such-page");
  expect(res?.status()).toBe(404);
  await expect(page.getByRole("heading", { name: /can.t find that page/ })).toBeVisible();
  await expectAccessible(page);
  const robots = await (await request.get("/robots.txt")).text();
  expect(robots).toContain("Disallow: /app");
  expect(robots).toContain("Sitemap:");
  const sitemap = await (await request.get("/sitemap.xml")).text();
  expect(sitemap).toContain("/pricing");
  expect(sitemap).not.toContain("/privacy"); // templates stay out until reviewed
  expect(sitemap).not.toContain("/blog"); // no posts yet
  await page.goto("/");
  const ogUrl = await page.locator('meta[property="og:image"]').first().getAttribute("content");
  expect(ogUrl).toBeTruthy();
  const og = await request.get(new URL(ogUrl ?? "").pathname);
  expect(og.status()).toBe(200);
  expect(og.headers()["content-type"]).toContain("image/png");
  const ld = await page.locator('script[type="application/ld+json"]').first().textContent();
  expect(JSON.parse(ld ?? "[]")[1]["@type"]).toBe("SoftwareApplication");
  expect(ld).not.toMatch(/aggregateRating|review/i);
});

test("a pilot request reaches the ops inbox and sends both emails", async ({ page, browser }) => {
  const email = `pilot-${seed().tag}@distributor.example`;
  await page.goto("/request-a-pilot?plan=growth");
  await page.getByRole("button", { name: "Send request" }).click();
  await expect(page.getByText("Enter your name.")).toBeVisible(); // client-side mirror of server rules
  await page.getByLabel("Your name").fill("Pat Pilot");
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Company").fill(`Pilot Supply ${seed().tag}`);
  await page.getByLabel("Your role").fill("Controller");
  await page.getByLabel("Distributor segment").selectOption("Electrical");
  await page.getByLabel("ERP / accounting system").fill("Epicor Eclipse");
  await page.getByLabel("Approximate number of supplier rebate agreements").selectOption("26-50");
  await page.getByLabel(/I agree to be contacted/).check();
  await page.getByRole("button", { name: "Send request" }).click();
  await expect(page.getByText("Thanks — your request is in")).toBeVisible();
  await expectAccessible(page);

  const confirmation = await latestEmail(email, /received your .* pilot request/i);
  expect(confirmation.text).toContain("Pat Pilot");
  const notice = await latestEmail("ops-inbox@rebateledger.invalid", new RegExp(`New pilot request: Pilot Supply ${seed().tag}`));
  expect(notice.text).toContain("/ops/requests");

  const ops = await (await browser.newContext({ storageState: { cookies: [], origins: [] } })).newPage();
  await signIn(ops, seed().users.ops, /\/ops(\/|$)/);
  await ops.goto("/ops/requests");
  await expect(ops.getByText(`Pilot Supply ${seed().tag} · Pat Pilot, Controller`)).toBeVisible();
});
