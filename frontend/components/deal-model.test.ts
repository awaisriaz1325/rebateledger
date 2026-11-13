import { describe, expect, it } from "vitest";
import { factorLabel } from "./deal-model";

describe("factorLabel", () => {
  it("labels sensitivity factors from their decimal strings", () => {
    expect(factorLabel("0.8")).toBe("-20% spend");
    expect(factorLabel("0.9")).toBe("-10% spend");
    expect(factorLabel("1.1")).toBe("+10% spend");
    expect(factorLabel("1.2")).toBe("+20% spend");
    expect(factorLabel("1.25")).toBe("+25% spend");
  });
});
