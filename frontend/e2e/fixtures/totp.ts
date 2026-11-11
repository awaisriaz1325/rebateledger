/**
 * RFC 6238 TOTP (SHA-1, 30 s, 6 digits) with Node's crypto — no extra dependency.
 * The server rejects a code whose time step was already used, so `freshCode`
 * remembers the last step per secret (in the git-ignored state dir, shared by the
 * setup project and the test worker) and waits for the next step when needed.
 */
import { createHmac } from "node:crypto";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

const STEP = 30;
const USED = path.join(__dirname, "..", ".state", "totp-used.json");

function base32Decode(input: string): Buffer {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  const clean = input.replace(/=+$/, "").replace(/\s/g, "").toUpperCase();
  let bits = 0;
  let value = 0;
  const out: number[] = [];
  for (const ch of clean) {
    const idx = alphabet.indexOf(ch);
    if (idx < 0) throw new Error("invalid base32 secret");
    value = (value << 5) | idx;
    bits += 5;
    if (bits >= 8) {
      out.push((value >>> (bits - 8)) & 0xff);
      bits -= 8;
    }
  }
  return Buffer.from(out);
}

export function totp(secret: string, step: number): string {
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(step));
  const mac = createHmac("sha1", base32Decode(secret)).update(counter).digest();
  const offset = mac[mac.length - 1] & 0x0f;
  const code = (mac.readUInt32BE(offset) & 0x7fffffff) % 1_000_000;
  return code.toString().padStart(6, "0");
}

function readUsed(): Record<string, number> {
  try {
    return existsSync(USED) ? (JSON.parse(readFileSync(USED, "utf8")) as Record<string, number>) : {};
  } catch {
    return {};
  }
}

/** A code for a time step this secret has not used yet (waits up to one step). */
export async function freshCode(secret: string): Promise<string> {
  const used = readUsed();
  let step = Math.floor(Date.now() / 1000 / STEP);
  while (used[secret] !== undefined && step <= used[secret]) {
    const waitMs = (step + 1) * STEP * 1000 - Date.now() + 250;
    await new Promise((r) => setTimeout(r, Math.max(waitMs, 50)));
    step = Math.floor(Date.now() / 1000 / STEP);
  }
  used[secret] = step;
  writeFileSync(USED, JSON.stringify(used));
  return totp(secret, step);
}
