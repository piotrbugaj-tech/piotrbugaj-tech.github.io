import { describe, expect, it } from "vitest";
import { SearchIndex, type IndexEntry } from "../src/services/search-index";
import { sqliteD1, sqliteD1NoFts } from "./helpers/d1-sqlite";

const e = (name: string, regon: string, over: Partial<IndexEntry> = {}): IndexEntry => ({
  nip: null, regon, krs: null, name, legalForm: "limited_liability_company", status: "active", city: "WARSZAWA", source: "REGON", ...over,
});

async function seeded(mk = sqliteD1) {
  const db = mk();
  const idx = new SearchIndex(db);
  await idx.upsert(e("POLSKI KONCERN NAFTOWY ORLEN SPÓŁKA AKCYJNA", "610188201", { nip: "7740001454", krs: "0000028860", legalForm: "joint_stock_company", city: "PŁOCK", source: "KRS" }));
  await idx.upsert(e("ORLEN SERWIS S.A.", "611111111", { legalForm: "joint_stock_company", city: "PŁOCK" }));
  await idx.upsert(e("ŻÓŁW SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ", "622222222", { city: "ŁÓDŹ" }));
  await idx.upsert(e("ZIELONA ORLENKA SP. Z O.O.", "633333333", { city: "WARSZAWA" }));
  return { db, idx };
}

describe.each([
  ["FTS5", sqliteD1],
  ["LIKE fallback", sqliteD1NoFts],
])("SearchIndex (%s)", (_n, mk) => {
  it("upserts and finds by token, returning identifiers", async () => {
    const { idx } = await seeded(mk);
    const hits = await idx.search("orlen koncern");
    expect(hits).toHaveLength(1);
    expect(hits[0]).toMatchObject({
      name: "POLSKI KONCERN NAFTOWY ORLEN SPÓŁKA AKCYJNA",
      identifiers: { nip: "7740001454", regon: "610188201", krs: "0000028860" },
      legalForm: "joint_stock_company", status: "active", city: "PŁOCK", source: "KRS",
    });
    expect(await idx.count()).toBe(4);
  });

  it("prefix-matches the last token only", async () => {
    const { idx } = await seeded(mk);
    const names = (await idx.search("orl")).map((h) => h.name);
    expect(names).toContain("ORLEN SERWIS S.A.");
    expect(names).toContain("POLSKI KONCERN NAFTOWY ORLEN SPÓŁKA AKCYJNA");
    expect(await idx.search("rlen")).toEqual([]);
    expect(await idx.search("orl serwis")).toEqual([]); // non-last tokens are whole words
  });

  it("ignores legal-form noise words and diacritics", async () => {
    const { idx } = await seeded(mk);
    expect((await idx.search("zolw sp z o o"))[0]?.name).toMatch(/^ŻÓŁW/);
    expect((await idx.search("żółw"))[0]?.name).toMatch(/^ŻÓŁW/);
  });

  it("filters by city (folded, prefix)", async () => {
    const { idx } = await seeded(mk);
    expect((await idx.search("orlen", { city: "plock" })).map((h) => h.city)).toEqual(["PŁOCK", "PŁOCK"]);
    expect((await idx.search("orlen", { city: "Warsz" })).map((h) => h.name)).toEqual(["ZIELONA ORLENKA SP. Z O.O."]);
    expect(await idx.search("orlen", { city: "lodz" })).toEqual([]);
    expect((await idx.search("zolw", { city: "lodz" }))).toHaveLength(1);
  });

  it("ranks shorter names first among equal matches", async () => {
    const { idx } = await seeded(mk);
    const names = (await idx.search("orlen")).map((h) => h.name);
    expect(names.indexOf("ORLEN SERWIS S.A.")).toBeLessThan(names.indexOf("POLSKI KONCERN NAFTOWY ORLEN SPÓŁKA AKCYJNA"));
  });

  it("upsert is idempotent and updates in place", async () => {
    const { idx } = await seeded(mk);
    await idx.upsert(e("ORLEN SERWIS NOWA NAZWA", "611111111", { status: "in_liquidation", legalForm: "joint_stock_company" }));
    await idx.upsert(e("ORLEN SERWIS NOWA NAZWA", "611111111", { status: "in_liquidation", legalForm: "joint_stock_company" }));
    expect(await idx.count()).toBe(4);
    const hits = await idx.search("orlen serwis");
    expect(hits).toHaveLength(1);
    expect(hits[0]).toMatchObject({ name: "ORLEN SERWIS NOWA NAZWA", status: "in_liquidation" });
    expect(await idx.search("orlen serwis s")).toHaveLength(1); // old tokens gone, no stale FTS rows
  });

  it("merges an entity first seen by KRS only once REGON is known", async () => {
    const idx = new SearchIndex(mk());
    await idx.upsert(e("ALFA SA", null as unknown as string, { regon: null, krs: "0000111111", legalForm: "joint_stock_company" }));
    await idx.upsert(e("ALFA SA", "123456785", { krs: "0000111111", legalForm: "joint_stock_company" }));
    expect(await idx.count()).toBe(1);
    expect((await idx.search("alfa"))[0]?.identifiers.regon).toBe("123456785");
  });

  it("refuses natural persons and unidentifiable entries", async () => {
    const idx = new SearchIndex(mk());
    await idx.upsert(e("JAN KOWALSKI", "111111111", { legalForm: "sole_proprietorship" }));
    await idx.upsert(e("KOWALSKI I NOWAK S.C.", "222222222", { legalForm: "civil_partnership" }));
    await idx.upsert(e("ANNA NOWAK", "333333333", { legalForm: null }));
    await idx.upsert(e("BEZ IDENTYFIKATORA SA", null as unknown as string, { regon: null }));
    expect(await idx.count()).toBe(0);
    expect(await idx.search("kowalski")).toEqual([]);
    await idx.upsert(e("NIEZNANA FORMA SA", "444444444", { legalForm: null, krs: "0000222222" })); // KRS => legal entity
    expect(await idx.count()).toBe(1);
  });

  it("survives hostile queries", async () => {
    const { db, idx } = await seeded(mk);
    for (const q of ['"', "NEAR(", "a OR b", "*", "'; DROP TABLE entities; --", "orlen AND", "NOT orlen", "name_folded:orlen", "^orlen", "(orlen", "orlen)*", "{x}", "\\", "%_", "orlen -zolw"]) {
      await expect(idx.search(q)).resolves.toBeInstanceOf(Array);
      await expect(idx.search(q, { city: q })).resolves.toBeInstanceOf(Array);
    }
    expect(await idx.count()).toBe(4);
    expect(db.raw.prepare("SELECT name FROM sqlite_master WHERE name = 'entities'").all()).toHaveLength(1);
    expect(await idx.search("NOT orlen")).toEqual([]); // NOT is a required plain word, not an operator
  });

  it("returns [] for empty or 1-char queries", async () => {
    const { idx } = await seeded(mk);
    expect(await idx.search("")).toEqual([]);
    expect(await idx.search("   ")).toEqual([]);
    expect(await idx.search("o")).toEqual([]);
    expect(await idx.search("sp z o.o.")).toEqual([]); // only noise words
  });

  it("clamps limit to 1..20 (default 10)", async () => {
    const idx = new SearchIndex(mk());
    for (let i = 0; i < 30; i++) await idx.upsert(e(`BUDIMEX ${i} SA`, String(100000000 + i)));
    expect(await idx.search("budimex")).toHaveLength(10);
    expect(await idx.search("budimex", { limit: 500 })).toHaveLength(20);
    expect(await idx.search("budimex", { limit: 0 })).toHaveLength(10);
    expect(await idx.search("budimex", { limit: -5 })).toHaveLength(1);
    expect(await idx.search("budimex", { limit: 3 })).toHaveLength(3);
    expect(await idx.search("budimex", { limit: Number.NaN })).toHaveLength(10);
  });
});

describe("SearchIndex without a D1 binding", () => {
  it("is a no-op", async () => {
    const idx = new SearchIndex();
    await expect(idx.upsert(e("ORLEN SA", "610188201"))).resolves.toBeUndefined();
    expect(await idx.search("orlen")).toEqual([]);
    expect(await idx.count()).toBe(0);
  });
});
