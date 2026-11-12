/** Operator console: billing setup → invoice → tenant sees it; support access with consent. */
import { expect, test, type Browser, type Page } from "@playwright/test";
import { expectAccessible, seed, signIn, stepUpIfAsked } from "./fixtures/app";

test.describe.configure({ mode: "serial" });

let opsPage: Page;

async function operator(browser: Browser): Promise<Page> {
  if (!opsPage) {
    opsPage = await (await browser.newContext({ storageState: { cookies: [], origins: [] } })).newPage();
    await signIn(opsPage, seed().users.ops, /\/ops(\/|$)/);
  }
  return opsPage;
}

function orgName(): RegExp {
  return new RegExp(`E2E Distribution ${seed().tag}`);
}

test("every ops page is accessible", async ({ browser }) => {
  const page = await operator(browser);
  for (const path of ["/ops", "/ops/invoices", "/ops/plans", "/ops/requests", "/ops/announcements", "/ops/jobs", "/ops/settings", "/ops/audit"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.locator(".skeleton")).toHaveCount(0);
    await expectAccessible(page);
  }
});

test("operator issues an invoice and the organization's owner sees it", async ({ browser, page }) => {
  const ops = await operator(browser);
  await ops.goto("/ops/settings");
  await ops.getByLabel("Seller legal name").fill("Example Seller LLC (test)");
  await ops.getByLabel("Billing email").fill("billing@seller.example");
  await ops.getByLabel("Address").fill("1 Test Street, Testville");
  await ops.getByLabel("Payment instructions").fill("Bank transfer — placeholder account for tests.");
  await ops.getByRole("button", { name: "Save settings" }).click();
  await expect(ops.getByText("Billing settings saved")).toBeVisible();

  await ops.goto("/ops");
  await ops.getByRole("link", { name: orgName() }).click();
  await ops.waitForURL(/\/ops\/tenants\//);
  await ops.getByLabel("Billing email").fill("ap@e2e.example");
  await ops.getByLabel("Status").selectOption("active");
  await ops.getByRole("button", { name: "Save subscription" }).click();
  await expect(ops.getByText("Subscription saved")).toBeVisible();
  await ops.getByLabel("Description").fill("Growth plan — November");
  await ops.getByLabel("Unit price ($)").fill("499.00");
  await ops.getByRole("button", { name: "Save draft" }).click();
  await expect(ops.getByText(/Draft saved/)).toBeVisible();
  await expectAccessible(ops);

  await ops.getByRole("link", { name: "Draft" }).first().click();
  await ops.getByRole("button", { name: "Issue invoice" }).click();
  await ops.getByRole("dialog", { name: "Issue this invoice?" }).getByRole("button", { name: "Issue" }).click();
  await expect(ops.getByText("Invoice issued and emailed")).toBeVisible();
  const number = (await ops.getByRole("dialog").locator(".font-mono").first().innerText()).trim();
  expect(number).toMatch(/^RL-\d{4}-\d{4}$/);

  await page.goto("/app/settings/plan");
  const row = page.getByRole("table", { name: "Invoices" }).getByRole("row").filter({ hasText: number });
  await expect(row).toContainText("$499.00");
  await expect(row).toContainText("Issued");
  await expectAccessible(page);
});

test("support access needs the organization's consent and can be exited", async ({ browser, page }) => {
  const ops = await operator(browser);
  await ops.goto("/ops");
  await ops.getByRole("link", { name: orgName() }).click();
  await expect(ops.getByRole("button", { name: "Enter support session" })).toBeDisabled();

  await page.goto("/app/settings/security");
  await page.getByLabel("Reason (optional)").fill("Help with the import wizard");
  await page.getByRole("button", { name: "Grant access" }).click();
  await stepUpIfAsked(page, seed().users.owner);
  await expect(page.getByText(/support team has read-only access/i)).toBeVisible();

  await ops.reload();
  await ops.getByRole("button", { name: "Enter support session" }).click();
  await ops.waitForURL(/\/app$/);
  await expect(ops.getByText(/Support access is active/)).toBeVisible();
  await ops.goto("/app/suppliers");
  await expect(ops.getByText("Acme Electrical Supply")).toBeVisible();
  await expect(ops.getByRole("link", { name: "New supplier" })).toHaveCount(0); // read-only
  await expectAccessible(ops);
  await ops.getByRole("button", { name: "Exit support access" }).click();
  await ops.waitForURL(/\/ops$/);
});
