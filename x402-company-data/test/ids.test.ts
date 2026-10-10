import { describe, expect, it } from "vitest";
import { normalizeKrs, normalizeNip, normalizeRegon, parseIdFromQuery } from "../src/lib/ids";
import { fold, normalizeLegalForm, normalizePkd, statusFromName } from "../src/lib/normalize";

describe("NIP", () => {
  it("accepts valid NIPs with separators and PL prefix", () => {
    expect(normalizeNip("774-00-01-454")).toBe("7740001454"); // ORLEN
    expect(normalizeNip("PL5260250995")).toBe("5260250995");
    expect(normalizeNip("526 025 09 95")).toBe("5260250995");
  });
  it("rejects bad checksums and formats", () => {
    expect(normalizeNip("7740001455")).toBeNull();
    expect(normalizeNip("123")).toBeNull();
    expect(normalizeNip("abcdefghij")).toBeNull();
  });
});

describe("REGON", () => {
  it("validates 9 and 14 digit REGONs", () => {
    expect(normalizeRegon("610188201")).toBe("610188201"); // ORLEN
    expect(normalizeRegon("610188202")).toBeNull();
    expect(normalizeRegon("12345678512347")).toBe("12345678512347");
    expect(normalizeRegon("12345678512348")).toBeNull();
  });
});

describe("KRS", () => {
  it("pads to 10 digits", () => {
    expect(normalizeKrs("28860")).toBe("0000028860");
    expect(normalizeKrs("0000028860")).toBe("0000028860");
    expect(normalizeKrs("00000")).toBeNull();
    expect(normalizeKrs("12345678901")).toBeNull();
  });
});

describe("parseIdFromQuery", () => {
  it("requires exactly one id", () => {
    expect(parseIdFromQuery({}).ok).toBe(false);
    expect(parseIdFromQuery({ nip: "7740001454", krs: "28860" }).ok).toBe(false);
    expect(parseIdFromQuery({ nip: "7740001454" })).toEqual({ ok: true, id: { kind: "nip", value: "7740001454" } });
    expect(parseIdFromQuery({ nip: "1111111112" }).ok).toBe(false);
  });
});

describe("normalisers", () => {
  it("folds Polish diacritics", () => {
    expect(fold("Spółka z ograniczoną  odpowiedzialnością")).toBe("SPOLKA Z OGRANICZONA ODPOWIEDZIALNOSCIA");
  });
  it("maps legal forms from KRS and GUS labels", () => {
    expect(normalizeLegalForm("SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ")).toBe("limited_liability_company");
    expect(normalizeLegalForm("SPÓŁKI AKCYJNE")).toBe("joint_stock_company");
    expect(normalizeLegalForm("SPÓŁKA KOMANDYTOWO-AKCYJNA")).toBe("limited_joint_stock_partnership");
    expect(normalizeLegalForm("PROSTA SPÓŁKA AKCYJNA")).toBe("simple_joint_stock_company");
    expect(normalizeLegalForm("SPÓŁKI KOMANDYTOWE")).toBe("limited_partnership");
    expect(normalizeLegalForm("OSOBY FIZYCZNE PROWADZĄCE DZIAŁALNOŚĆ GOSPODARCZĄ")).toBe("sole_proprietorship");
    expect(normalizeLegalForm("SPÓŁKI CYWILNE PROWADZĄCE DZIAŁALNOŚĆ NA PODSTAWIE UMOWY ZAWARTEJ ZGODNIE Z KODEKSEM CYWILNYM")).toBe(
      "civil_partnership",
    );
    expect(normalizeLegalForm(null, "FUNDACJA")).toBe("foundation");
    expect(normalizeLegalForm("cokolwiek")).toBe("other");
  });
  it("detects liquidation / bankruptcy from the name", () => {
    expect(statusFromName("ABC SPÓŁKA Z O.O. W LIKWIDACJI")).toBe("in_liquidation");
    expect(statusFromName("XYZ S.A. W UPADŁOŚCI")).toBe("in_bankruptcy");
    expect(statusFromName("ORLEN SPÓŁKA AKCYJNA")).toBeNull();
  });
  it("normalises PKD codes", () => {
    expect(normalizePkd("6201Z")).toBe("62.01.Z");
    expect(normalizePkd("62.01.Z")).toBe("62.01.Z");
  });
});
