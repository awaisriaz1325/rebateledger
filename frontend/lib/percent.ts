/** Percent ⇄ fraction as strings, never through floating point (rates are not JS numbers). */

/** "5.5" (percent) → "0.055" without floating point; null when not a valid 0–99.9999 percent. */
export function percentToFraction(text: string): string | null {
  const m = /^(\d{1,2})(?:\.(\d{1,4}))?$/.exec(text.trim());
  return m ? `0.${m[1].padStart(2, "0")}${m[2] ?? ""}` : null;
}

/** "0.055000" → "5.5" for display. */
export function fractionToPercent(fraction: string): string {
  const [, frac = ""] = fraction.split(".");
  const digits = frac.padEnd(2, "0");
  const whole = String(Number.parseInt(digits.slice(0, 2), 10));
  const rest = digits.slice(2).replace(/0+$/, "");
  return rest ? `${whole}.${rest}` : whole;
}
