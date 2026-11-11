import { describe, expect, it } from "vitest";
import { totp } from "./totp";

describe("totp", () => {
  // RFC 6238 Appendix B, SHA-1 secret "12345678901234567890" (base32 below), 8 digits truncated to 6.
  it("matches the RFC 6238 test vectors", () => {
    const secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ";
    expect(totp(secret, Math.floor(59 / 30))).toBe("287082");
    expect(totp(secret, Math.floor(1111111109 / 30))).toBe("081804");
    expect(totp(secret, Math.floor(1234567890 / 30))).toBe("005924");
  });
});
