import { describe, expect, it } from "vitest";
import { buildUrl, errorText, ApiError } from "../../src/services/api";
import { fmtBytes, fmtNum, fmtTime } from "../../src/components/ui";

describe("buildUrl", () => {
  it("skips empty values and repeats arrays", () => {
    expect(buildUrl("/api/x", { a: 1, b: "", c: null, d: undefined, t: ["entity", "document"] })).toBe("/api/x?a=1&t=entity&t=document");
    expect(buildUrl("/api/x")).toBe("/api/x");
  });
  it("encodes user input safely", () => {
    expect(buildUrl("/api/search", { q: 'a&b="c"' })).toBe("/api/search?q=a%26b%3D%22c%22");
  });
});

describe("errorText", () => {
  it("includes validation details", () => {
    const e = new ApiError(422, "validation_failed", "Workflow is invalid", { errors: ["n1: missing required parameter x"] });
    expect(errorText(e)).toBe("Workflow is invalid: n1: missing required parameter x");
  });
});

describe("formatters", () => {
  it("never fabricate values for missing data", () => {
    expect(fmtNum(undefined)).toBe("—");
    expect(fmtNum(null)).toBe("—");
    expect(fmtTime(null)).toBe("—");
  });
  it("format bytes and UTC times", () => {
    expect(fmtBytes(0)).toBe("0 B");
    expect(fmtBytes(1536)).toBe("1.5 KB");
    expect(fmtTime("2025-03-01T10:15:00")).toBe("2025-03-01 10:15:00 UTC");
    expect(fmtTime("2025-03-01T10:15:00+01:00")).toBe("2025-03-01 09:15:00 UTC");
  });
});
