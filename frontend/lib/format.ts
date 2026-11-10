/**
 * Display formatting only (SPEC §10). Money arrives from the API as decimal strings
 * and is never converted to a JS number: Intl.NumberFormat formats numeric strings
 * exactly (ECMA-402 "StringNumericLiteral" input), so no precision is lost.
 */

const DECIMAL = /^-?\d+(\.\d+)?$/;
const MINUS = "−";

const money = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
  roundingMode: "halfExpand",
});

export function isDecimalString(value: unknown): value is `${number}` {
  return typeof value === "string" && DECIMAL.test(value);
}

/** "-1234.5" → "−$1,234.50". Returns "—" for null/undefined/invalid input. */
export function formatMoney(value: string | null | undefined): string {
  if (!isDecimalString(value)) return "—";
  return money.format(value).replace("-", MINUS);
}

/** True when the decimal string is negative (for colour + sign, never colour alone). */
export function isNegative(value: string | null | undefined): boolean {
  return isDecimalString(value) && value.startsWith("-") && /[1-9]/.test(value);
}

/** "0.025" → "2.50%" with fixed decimals per context. */
export function formatRatePercent(value: string | null | undefined, fractionDigits = 2): string {
  if (!isDecimalString(value)) return "—";
  const nf = new Intl.NumberFormat("en-US", {
    style: "percent",
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  });
  return nf.format(value).replace("-", MINUS);
}

export function formatQuantity(value: string | null | undefined): string {
  if (!isDecimalString(value)) return "—";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 }).format(value).replace("-", MINUS);
}

const DATE = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });

/** ISO date "2026-03-04" → "Mar 4, 2026" (business dates have no timezone). */
export function formatDate(value: string | null | undefined): string {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return "—";
  return DATE.format(new Date(`${value}T00:00:00Z`));
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" }).format(d);
}
