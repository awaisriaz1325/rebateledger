import { describe, expect, it } from "vitest";
import { formatDate, formatMoney, formatQuantity, formatRatePercent, isNegative } from "./format";

describe("formatMoney", () => {
  it("formats decimal strings without float rounding", () => {
    expect(formatMoney("1234.56")).toBe("$1,234.56");
    expect(formatMoney("246914000000.00")).toBe("$246,914,000,000.00");
    // 0.1 + 0.2 style artefacts are impossible: the string is formatted exactly.
    expect(formatMoney("999999999999999.995")).toBe("$1,000,000,000,000,000.00");
    expect(formatMoney("10.125")).toBe("$10.13");
  });
  it("uses a real minus sign for negatives", () => {
    expect(formatMoney("-4629.78")).toBe("−$4,629.78");
    expect(isNegative("-4629.78")).toBe(true);
    expect(isNegative("-0.00")).toBe(false);
    expect(isNegative("12")).toBe(false);
  });
  it("rejects non-decimal input", () => {
    expect(formatMoney(null)).toBe("—");
    expect(formatMoney("1e5")).toBe("—");
    expect(formatMoney("=HYPERLINK()")).toBe("—");
  });
});

describe("other formatters", () => {
  it("formats rates, quantities and dates", () => {
    expect(formatRatePercent("0.025")).toBe("2.50%");
    expect(formatQuantity("1500.5000")).toBe("1,500.5");
    expect(formatDate("2028-02-29")).toBe("Feb 29, 2028");
    expect(formatDate("not-a-date")).toBe("—");
  });
});
