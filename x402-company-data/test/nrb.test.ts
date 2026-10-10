import { describe, expect, it } from "vitest";
import { normalizeNrb } from "../src/lib/nrb";

const VALID = "61109010140000071219812874"; // PL61 1090 1014 0000 0712 1981 2874 (published IBAN example)

describe("normalizeNrb", () => {
  it("accepts plain, spaced, dashed and PL-prefixed forms", () => {
    expect(normalizeNrb(VALID)).toBe(VALID);
    expect(normalizeNrb("61 1090 1014 0000 0712 1981 2874")).toBe(VALID);
    expect(normalizeNrb("PL61 1090 1014 0000 0712 1981 2874")).toBe(VALID);
    expect(normalizeNrb("pl61-1090-1014-0000-0712-1981-2874")).toBe(VALID);
  });

  it("rejects a wrong checksum", () => {
    expect(normalizeNrb("62109010140000071219812874")).toBeNull();
    expect(normalizeNrb("61109010140000071219812875")).toBeNull();
  });

  it("rejects wrong length, letters and foreign prefixes", () => {
    expect(normalizeNrb("")).toBeNull();
    expect(normalizeNrb("6110901014000007121981287")).toBeNull();
    expect(normalizeNrb("611090101400000712198128744")).toBeNull();
    expect(normalizeNrb("6110901014000007121981287X")).toBeNull();
    expect(normalizeNrb("DE61109010140000071219812874")).toBeNull();
  });
});
