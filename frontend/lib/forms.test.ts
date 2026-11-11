import { describe, expect, it } from "vitest";
import { safeNext } from "./forms";

describe("safeNext", () => {
  it("allows only relative same-site paths", () => {
    expect(safeNext("/app/claims")).toBe("/app/claims");
    expect(safeNext("//evil.example")).toBe("/app");
    expect(safeNext("https://evil.example")).toBe("/app");
    expect(safeNext("/\\evil")).toBe("/app");
    expect(safeNext(null)).toBe("/app");
  });
});
