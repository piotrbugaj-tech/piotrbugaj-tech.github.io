import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { WhitelistClient, WhitelistInputError } from "../src/sources/whitelist/client";
import { vatStatusInfo } from "../src/sources/whitelist/normalize";
import { secondsUntilWarsawMidnight, warsawDate, WhitelistService } from "../src/services/whitelist";
import { UpstreamError } from "../src/sources/errors";
import { sha256Hex } from "../src/lib/hash";
import { memoryKV } from "./helpers/fakes";

const fixture = (n: string) => JSON.parse(readFileSync(new URL(`./fixtures/whitelist/${n}.json`, import.meta.url), "utf8"));
const FOUND = fixture("search-nip");
const NOTFOUND = fixture("search-nip-notfound");
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const NIP = "7740001454";
const NRB = "61109010140000071219812874";
const NOW = new Date("2026-10-10T08:15:00Z"); // 10:15 in Warsaw (CEST)

function fakeWl(respond: (url: URL) => Response | Promise<Response>) {
  const calls: string[] = [];
  const fn = (async (input: string | URL | Request) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url);
    calls.push(url.pathname + url.search);
    return respond(url);
  }) as typeof fetch;
  return { fetch: fn, calls, client: new WhitelistClient({ fetch: fn }) };
}

const happy = (url: URL) => {
  if (url.pathname.startsWith("/api/check/")) return json({ result: { accountAssigned: "TAK", requestId: "chk-1", requestDateTime: "10-10-2026 10:15:09" } });
  return json(url.pathname.endsWith(NIP) ? FOUND : NOTFOUND);
};

describe("Warsaw time helpers", () => {
  it("computes the Warsaw calendar date around midnight and DST", () => {
    expect(warsawDate(new Date("2026-10-10T08:15:00Z"))).toBe("2026-10-10");
    expect(warsawDate(new Date("2026-10-10T21:59:59Z"))).toBe("2026-10-10"); // 23:59:59 CEST
    expect(warsawDate(new Date("2026-10-10T22:00:00Z"))).toBe("2026-10-11"); // 00:00 CEST
    expect(warsawDate(new Date("2026-01-10T23:30:00Z"))).toBe("2026-01-11"); // 00:30 CET
  });

  it("returns seconds to the next Warsaw midnight", () => {
    expect(secondsUntilWarsawMidnight(new Date("2026-10-10T08:15:00Z"))).toBe(13 * 3600 + 45 * 60); // 10:15 -> 24:00
    expect(secondsUntilWarsawMidnight(new Date("2026-01-10T11:00:00Z"))).toBe(12 * 3600); // 12:00 CET
    expect(secondsUntilWarsawMidnight(new Date("2026-10-10T21:59:50Z"))).toBe(60); // clamped to KV minimum
    // 2026-10-24 -> 25 (fall back on the 25th): the 25th is 25h long.
    expect(secondsUntilWarsawMidnight(new Date("2026-10-24T22:00:00Z"))).toBe(25 * 3600); // 00:00 CEST on the 25th
    // 2026-03-29 spring forward: 23h day, starts 2026-03-28T23:00Z
    expect(secondsUntilWarsawMidnight(new Date("2026-03-28T23:00:00Z"))).toBe(23 * 3600);
  });
});

describe("WhitelistClient", () => {
  it("searches one NIP and returns the raw subject with request metadata", async () => {
    const up = fakeWl(() => json(FOUND));
    const r = await up.client.searchNip(NIP, "2026-10-10");
    expect(up.calls).toEqual([`/api/search/nip/${NIP}?date=2026-10-10`]);
    expect(r).toMatchObject({ requestId: "d4k7p-m9x2q8z", requestDateTime: "10-10-2026 10:15:02" });
    expect(r.subject?.statusVat).toBe("Czynny");
  });

  it("returns subject null (with metadata) for an unknown NIP", async () => {
    const r = await fakeWl(() => json(NOTFOUND)).client.searchNip(NIP, "2026-10-10");
    expect(r).toEqual({ subject: null, requestId: "d4k7p-w3n8r5t", requestDateTime: "10-10-2026 10:15:44" });
  });

  it("searches several NIPs in one request and enforces the 30 limit", async () => {
    const up = fakeWl(() => json({ result: { subjects: [FOUND.result.subject], requestId: "r1", requestDateTime: "10-10-2026 10:00:00" } }));
    const r = await up.client.searchNips([NIP, "1234563218"], "2026-10-10");
    expect(up.calls).toEqual([`/api/search/nips/${NIP},1234563218?date=2026-10-10`]);
    expect(r.subjects).toHaveLength(1);
    const many = Array.from({ length: 31 }, () => NIP);
    await expect(up.client.searchNips(many, "2026-10-10")).rejects.toBeInstanceOf(WhitelistInputError);
    await expect(up.client.searchNips([], "2026-10-10")).rejects.toBeInstanceOf(WhitelistInputError);
    expect(up.calls).toHaveLength(1);
  });

  it("checks an account and validates inputs locally", async () => {
    const up = fakeWl(happy);
    const r = await up.client.checkAccount(NIP, `PL${NRB}`, "2026-10-10");
    expect(up.calls).toEqual([`/api/check/nip/${NIP}/bank-account/${NRB}?date=2026-10-10`]);
    expect(r).toEqual({ accountAssigned: true, requestId: "chk-1", requestDateTime: "10-10-2026 10:15:09" });
    await expect(up.client.checkAccount(NIP, "61109010140000071219812875", "2026-10-10")).rejects.toBeInstanceOf(WhitelistInputError);
    await expect(up.client.checkAccount("1234567890", NRB, "2026-10-10")).rejects.toBeInstanceOf(WhitelistInputError);
    await expect(up.client.searchNip(NIP, "10-10-2026")).rejects.toBeInstanceOf(WhitelistInputError);
    expect(up.calls).toHaveLength(1);
  });

  it("maps accountAssigned NIE to false", async () => {
    const r = await fakeWl(() => json({ result: { accountAssigned: "NIE", requestId: "x", requestDateTime: "y" } })).client.checkAccount(NIP, NRB, "2026-10-10");
    expect(r.accountAssigned).toBe(false);
  });

  it("maps WL-1xx validation errors to WhitelistInputError (both envelope shapes)", async () => {
    const a = await fakeWl(() => json({ code: "WL-115", message: "Nieprawidlowy NIP" }, 400)).client.searchNip(NIP, "2026-10-10").catch((e) => e);
    expect(a).toBeInstanceOf(WhitelistInputError);
    expect(a).not.toBeInstanceOf(UpstreamError);
    expect(a.code).toBe("WL-115");
    const b = await fakeWl(() => json({ exception: { code: "WL-111", message: "bad account" } }, 400)).client.searchNip(NIP, "2026-10-10").catch((e) => e);
    expect(b).toBeInstanceOf(WhitelistInputError);
  });

  it("maps WL-100/190/191, 5xx, bad bodies and timeouts to UpstreamError", async () => {
    const fail = async (res: () => Response) => {
      const e = await fakeWl(res).client.searchNip(NIP, "2026-10-10").catch((x) => x);
      expect(e).toBeInstanceOf(UpstreamError);
      return e as UpstreamError;
    };
    expect(await fail(() => json({ code: "WL-191", message: "Limit żądań dla tego adresu IP został na dziś wyczerpany" }, 400))).toMatchObject({ source: "MF_WL", status: 429 });
    expect((await fail(() => json({ code: "WL-191", message: "x" }, 400))).message).toContain("WL-191");
    expect(await fail(() => json({ code: "WL-190", message: "x" }, 400))).toMatchObject({ source: "MF_WL" });
    await fail(() => json({ code: "WL-100", message: "x" }, 400));
    expect(await fail(() => new Response("oops", { status: 503 }))).toMatchObject({ status: 503 });
    await fail(() => new Response("<html>", { status: 200 }));
    await fail(() => json({ message: "???" }, 400));
    const hang = ((_u: unknown, init?: RequestInit) => new Promise((_, rej) => init?.signal?.addEventListener("abort", () => rej(init.signal!.reason)))) as typeof fetch;
    await expect(new WhitelistClient({ fetch: hang, timeoutMs: 20 }).searchNip(NIP, "2026-10-10")).rejects.toBeInstanceOf(UpstreamError);
  });

  it("uses the test environment base URL", async () => {
    const urls: string[] = [];
    const f = (async (u: string) => (urls.push(u), json(FOUND))) as unknown as typeof fetch;
    await new WhitelistClient({ env: "test", fetch: f }).searchNip(NIP, "2026-10-10");
    expect(urls[0]).toMatch(/^https:\/\/wl-test\.mf\.gov\.pl\/api\/search\/nip\//);
  });
});

describe("vatStatusInfo", () => {
  it("minimises the subject to status data", () => {
    const meta = { requestId: "d4k7p-m9x2q8z", requestDateTime: "10-10-2026 10:15:02" };
    const info = vatStatusInfo({ ...FOUND.result.subject, representatives: [{ firstName: "Jan", lastName: "Kowalski", pesel: "44051401359" }], partners: [{ companyName: "X" }] }, meta);
    expect(info).toEqual({
      vatStatus: "active",
      nip: NIP,
      regon: "610188201",
      krs: "0000028860",
      registrationLegalDate: "1999-01-01",
      removalDate: null,
      restorationDate: null,
      hasVirtualAccounts: false,
      accountsCount: 1,
      ...meta,
    });
    const s = JSON.stringify(info);
    for (const leak of ["49102010260000042270201390", "CHEMIKÓW", "Kowalski", "44051401359", "ORLEN"]) expect(s).not.toContain(leak);
  });

  it("maps statuses and the not-found case", () => {
    const m = { requestId: null, requestDateTime: null };
    expect(vatStatusInfo({ statusVat: "Zwolniony" }, m).vatStatus).toBe("exempt");
    expect(vatStatusInfo({ statusVat: "Niezarejestrowany" }, m).vatStatus).toBe("not_registered");
    expect(vatStatusInfo({ statusVat: "Cos innego" }, m).vatStatus).toBeNull();
    expect(vatStatusInfo(null, m, NIP)).toMatchObject({ vatStatus: null, nip: NIP, accountsCount: 0, hasVirtualAccounts: null });
  });
});

describe("WhitelistService", () => {
  const svc = (up: ReturnType<typeof fakeWl>, kv?: KVNamespace, budget?: number) => new WhitelistService(up.client, kv, { now: () => NOW, dailySearchBudget: budget });

  it("caches VAT status until Warsaw midnight under a dated key", async () => {
    const kv = memoryKV();
    const up = fakeWl(happy);
    const s = svc(up, kv);
    const a = await s.vatStatus(NIP);
    const b = await s.vatStatus(NIP);
    expect([a.cached, b.cached, up.calls.length]).toEqual([false, true, 1]);
    expect(a.value).toMatchObject({ vatStatus: "active", requestId: "d4k7p-m9x2q8z" });
    expect(up.calls[0]).toBe(`/api/search/nip/${NIP}?date=2026-10-10`);
    const entry = kv.store.get(`wl:status:v1:2026-10-10:${NIP}`);
    expect(entry).toBeDefined();
    const ttl = (entry!.expiresAt! - Date.now()) / 1000;
    expect(ttl).toBeGreaterThan(13 * 3600 + 44 * 60 - 5);
    expect(ttl).toBeLessThanOrEqual(13 * 3600 + 45 * 60);
  });

  it("enforces the soft daily search budget without calling upstream", async () => {
    const kv = memoryKV();
    const up = fakeWl(happy);
    const s = svc(up, kv, 2);
    await s.vatStatus(NIP);
    await s.vatStatus("1234563218");
    expect(kv.store.get("wl:budget:2026-10-10")?.value).toBe("2");
    const err = await s.vatStatus("5260250274").catch((e) => e);
    expect(err).toBeInstanceOf(UpstreamError);
    expect(err).toMatchObject({ source: "MF_WL", status: 429, message: expect.stringContaining("daily search budget exhausted") });
    expect(up.calls).toHaveLength(2);
    // cache hits are free, and the next day starts fresh
    expect((await s.vatStatus(NIP)).cached).toBe(true);
    const tomorrow = new WhitelistService(up.client, kv, { now: () => new Date("2026-10-11T08:00:00Z"), dailySearchBudget: 2 });
    expect((await tomorrow.vatStatus("5260250274")).cached).toBe(false);
  });

  it("applies the budget without KV too, and uses 90/day by default", async () => {
    const up = fakeWl(happy);
    const s = svc(up, undefined, 1);
    await s.vatStatus(NIP);
    await expect(s.vatStatus("1234563218")).rejects.toMatchObject({ status: 429 });
    const kv = memoryKV();
    await kv.put("wl:budget:2026-10-10", "89");
    const d = new WhitelistService(up.client, kv, { now: () => NOW });
    await d.vatStatus(NIP);
    await expect(d.vatStatus("1234563218")).rejects.toMatchObject({ status: 429 });
  });

  it("stops calling MF for the rest of the day after WL-191", async () => {
    const kv = memoryKV();
    const up = fakeWl(() => json({ code: "WL-191", message: "limit" }, 400));
    const s = svc(up, kv);
    await expect(s.vatStatus(NIP)).rejects.toMatchObject({ status: 429 });
    await expect(s.vatStatus("1234563218")).rejects.toMatchObject({ status: 429 });
    await expect(s.checkAccount(NIP, NRB)).rejects.toMatchObject({ status: 429 });
    expect(up.calls).toHaveLength(1);
  });

  it("does not cache failures", async () => {
    const kv = memoryKV();
    const s = svc(fakeWl(() => new Response("x", { status: 500 })), kv);
    await expect(s.vatStatus(NIP)).rejects.toBeInstanceOf(UpstreamError);
    expect([...kv.store.keys()].some((k) => k.startsWith("wl:status"))).toBe(false);
  });

  it("caches account checks under a hashed key and does not spend the search budget", async () => {
    const kv = memoryKV();
    const up = fakeWl(happy);
    const s = svc(up, kv, 1);
    const a = await s.checkAccount(NIP, `PL ${NRB}`);
    const b = await s.checkAccount(NIP, NRB);
    expect([a.cached, b.cached, up.calls.length]).toEqual([false, true, 1]);
    expect(a.value).toEqual({ assigned: true, requestId: "chk-1", requestDateTime: "10-10-2026 10:15:09" });
    const hash = await sha256Hex(`${NIP}:${NRB}`);
    expect([...kv.store.keys()]).toContain(`wl:check:v1:2026-10-10:${hash}`);
    expect(JSON.stringify([...kv.store.keys()])).not.toContain(NRB);
    expect(JSON.stringify([...kv.store.values()])).not.toContain(NRB);
    expect(kv.store.has("wl:budget:2026-10-10")).toBe(false);
  });

  it("rejects a malformed account before touching cache or upstream", async () => {
    const up = fakeWl(happy);
    await expect(svc(up, memoryKV()).checkAccount(NIP, "123")).rejects.toBeInstanceOf(WhitelistInputError);
    expect(up.calls).toHaveLength(0);
  });
});
