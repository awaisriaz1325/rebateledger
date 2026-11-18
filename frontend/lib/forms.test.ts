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
  it("blocks paths that browsers turn into another site (audit 2026-11-18)", () => {
    // URL parsing strips tabs and newlines, so "/\t/evil" becomes "//evil".
    for (const evil of ["/\t/evil.example", "/\n/evil.example", "/\r\n/evil.example", "/ /evil.example", "/\\/evil.example"]) {
      expect(safeNext(evil)).toBe("/app");
    }
    expect(safeNext("/app/claims?status=open#top")).toBe("/app/claims?status=open#top");
  });
});
