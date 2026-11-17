import { describe, expect, it } from "vitest";
import { fractionToPercent, percentToFraction } from "./percent";

describe("percent ⇄ fraction", () => {
  it("converts percent text to a fraction string without floating point", () => {
    expect(percentToFraction("5")).toBe("0.05");
    expect(percentToFraction("7.5")).toBe("0.075");
    expect(percentToFraction("12.3456")).toBe("0.123456");
    expect(percentToFraction("0")).toBe("0.00");
  });
  it("refuses 100% and above, negatives, and too many decimals", () => {
    for (const bad of ["100", "-1", "5.12345", "abc", "", "5%"]) expect(percentToFraction(bad)).toBeNull();
  });
  it("shows a stored fraction as a percent", () => {
    expect(fractionToPercent("0.100000")).toBe("10");
    expect(fractionToPercent("0.075000")).toBe("7.5");
    expect(fractionToPercent("0.050000")).toBe("5");
    expect(fractionToPercent("0.123456")).toBe("12.3456");
  });
});
