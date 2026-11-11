import { test as setup } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { seed, signIn, STATE_DIR } from "./fixtures/app";

/** Fresh tenant + MFA-enrolled users for this run, then a signed-in owner session. */
setup("seed tenant and sign in the owner", async ({ page }) => {
  mkdirSync(STATE_DIR, { recursive: true });
  writeFileSync(path.join(STATE_DIR, "totp-used.json"), "{}");
  execFileSync("make", ["-C", path.join(__dirname, "..", ".."), "e2e-seed"], { stdio: "inherit" });
  await signIn(page, seed().users.owner);
  await page.context().storageState({ path: path.join(STATE_DIR, "owner.json") });
});
