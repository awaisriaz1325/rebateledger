import { describe, expect, it } from "vitest";
import { neutralize, toCsv } from "./csv";

describe("csv", () => {
  it("neutralises formula prefixes (SPEC §9 case 47)", () => {
    expect(neutralize('=HYPERLINK("x")')).toBe(`'=HYPERLINK("x")`);
    expect(neutralize("+cmd")).toBe("'+cmd");
    expect(neutralize("@SUM(1)")).toBe("'@SUM(1)");
    expect(neutralize("-10.00")).toBe("'-10.00");
    expect(neutralize("plain")).toBe("plain");
  });
  it("quotes cells", () => {
    expect(toCsv(["a", "b"], [['x,"y"', "=1"]])).toBe('a,b\r\n"x,""y""",\'=1\r\n');
  });
});
