import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { extractResult, parseDane } from "../src/sources/regon/client";
import { basicFromSearch, detailsFromReport, pkdFromReport, statusFromDetails } from "../src/sources/regon/normalize";

const fx = (name: string) => readFileSync(new URL(`./fixtures/regon/${name}`, import.meta.url), "utf8");
const rows = (file: string, op: string) => parseDane(extractResult(fx(file), op) ?? "");

describe("REGON BIR1.1 fixtures (docs/research/02-api-zrodel.md)", () => {
  it("extracts the session id from a real Zaloguj response", () => {
    expect(extractResult(fx("zaloguj-response.xml"), "Zaloguj")).toBe("c47xb5n78ppgc9hks85f");
  });

  it("parses DaneSzukajPodmioty for a legal entity", () => {
    const [r] = rows("szukaj-osprawna-response.xml", "DaneSzukajPodmioty");
    const b = basicFromSearch(r);
    expect(b).toMatchObject({ regon: "000331501", nip: "5261040828", type: "P", silo: "6" });
    expect(b.name).toContain("STATYSTYCZNY");
    expect(b.address.city).toBe("Warszawa");
  });

  it("parses DaneSzukajPodmioty for a natural person", () => {
    const [r] = rows("szukaj-osfizyczna-response.xml", "DaneSzukajPodmioty");
    expect(basicFromSearch(r).type).toBe("F");
  });

  it("recognises the not-found answer", () => {
    const body = fx("szukaj-notfound-response.xml");
    const inner = extractResult(body, "DaneSzukajPodmioty");
    const parsed = inner ? parseDane(inner) : [];
    // Either an empty result (then GetValue KomunikatKod=4) or an ErrorCode=4 row.
    expect(parsed.length === 0 || parsed[0].ErrorCode === "4").toBe(true);
  });

  it("normalises the BIR11OsPrawna report", () => {
    const [r] = rows("raport-BIR11OsPrawna-response.xml", "DanePobierzPelnyRaport");
    const d = detailsFromReport(r);
    expect(d.isNaturalPerson).toBe(false);
    expect(d.name).toBeTruthy();
    expect(d.address?.postalCode).toMatch(/^\d{2}-\d{3}$/);
    expect(statusFromDetails(d)).toBeTypeOf("string");
  });

  it("normalises the BIR11OsFizycznaDzialalnoscCeidg report without exposing contact data", () => {
    const [r] = rows("raport-BIR11OsFizycznaDzialalnoscCeidg-response.xml", "DanePobierzPelnyRaport");
    const d = detailsFromReport(r);
    expect(d.isNaturalPerson).toBe(true);
    expect(d.legalForm).toBe("sole_proprietorship");
    expect(d.email).toBeNull();
    expect(d.website).toBeNull();
  });

  it("parses PKD codes and puts the primary one first", () => {
    const pkd = pkdFromReport(rows("raport-BIR11OsPrawnaPkd-response.xml", "DanePobierzPelnyRaport"));
    expect(pkd.length).toBeGreaterThan(0);
    expect(pkd[0].code).toMatch(/^\d{2}\.\d{2}\.[A-Z]$/);
    expect(pkd.filter((p) => p.primary).length).toBeLessThanOrEqual(1);
  });
});

describe("REGON parser edge cases", () => {
  it("accepts CDATA-wrapped payloads", () => {
    const body = `<s:Envelope><s:Body><DaneSzukajPodmiotyResponse><DaneSzukajPodmiotyResult><![CDATA[<root><dane><Regon>610188201</Regon><Nip>7740001454</Nip></dane></root>]]></DaneSzukajPodmiotyResult></DaneSzukajPodmiotyResponse></s:Body></s:Envelope>`;
    expect(parseDane(extractResult(body, "DaneSzukajPodmioty")!)).toEqual([{ Regon: "610188201", Nip: "7740001454" }]);
  });
  it("reads report fields case-insensitively", () => {
    const d = detailsFromReport({ fiz_nazwa: "X", fiz_dataSkresleniaDzialalnosciZRegon: "2020-01-02" });
    expect(d.removedAt).toBe("2020-01-02");
    const d2 = detailsFromReport({ praw_nazwa: "Y", praw_dataSkresleniazRegon: "2021-03-04" });
    expect(d2.removedAt).toBe("2021-03-04");
  });
});
