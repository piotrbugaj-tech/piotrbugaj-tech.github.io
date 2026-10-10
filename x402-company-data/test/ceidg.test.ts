import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { CeidgClient } from "../src/sources/ceidg/client";
import { ceidgDetails, ceidgSearchHit, ceidgStatus } from "../src/sources/ceidg/normalize";
import { CeidgService } from "../src/services/ceidg";
import { UpstreamError } from "../src/sources/errors";
import { memoryKV } from "./helpers/fakes";

const fixture = (n: string) => JSON.parse(readFileSync(new URL(`./fixtures/ceidg/${n}.json`, import.meta.url), "utf8"));
const FIRMA = fixture("firma-details");
const FIRMY = fixture("firmy-by-nip");

interface Call {
  url: URL;
  headers: Headers;
}

/** Fake CEIDG: answers every request with `respond`, recording calls. */
function fakeCeidg(respond: (url: URL) => Response | Promise<Response>) {
  const calls: Call[] = [];
  const fn = (async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url);
    calls.push({ url, headers: new Headers(init?.headers) });
    return respond(url);
  }) as typeof fetch;
  return { fetch: fn, calls };
}

const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } });

const client = (f: typeof fetch, extra: Partial<ConstructorParameters<typeof CeidgClient>[0]> = {}) => new CeidgClient({ token: "tok-123", fetch: f, ...extra });

describe("CEIDG normaliser", () => {
  it("maps the detail fixture", () => {
    const d = ceidgDetails(FIRMA.firma[0]);
    expect(d).toMatchObject({
      id: "0e8b8c1a-4a6f-4d0a-9d52-5b3f6a9c1e77",
      statusRaw: "AKTYWNY",
      status: "active",
      name: "JAN TESTOWY USŁUGI TRANSPORTOWE",
      nip: "1234563218",
      regon: "123456785",
      startedAt: "2015-03-12",
      suspendedAt: "2019-01-07",
      resumedAt: "2019-07-01",
      endedAt: null,
      removedAt: null,
    });
    expect(d.address).toMatchObject({ street: "Test-Wilcza", buildingNumber: "12", unitNumber: "3", postalCode: "23-200", city: "Kraśnik", country: "PL" });
    expect(d.pkd).toEqual([
      { code: "49.41.Z", description: "TRANSPORT DROGOWY TOWARÓW", primary: true },
      { code: "52.29.C", description: "POZOSTAŁA DZIAŁALNOŚĆ WSPOMAGAJĄCA TRANSPORT LĄDOWY", primary: false },
    ]);
  });

  it("never carries personal contact data", () => {
    const json = JSON.stringify(ceidgDetails(FIRMA.firma[0]));
    for (const secret of ["kontakt@example.test", "600 000 000", "TESTOWY\"", "POLSKA", "obywatel", "adresKorespondencyjny"]) {
      expect(json).not.toContain(secret);
    }
    expect(Object.keys(ceidgDetails(FIRMA.firma[0])).sort()).toEqual(
      ["address", "endedAt", "id", "name", "nip", "pkd", "regon", "removedAt", "resumedAt", "startedAt", "status", "statusRaw", "suspendedAt"],
    );
  });

  it("maps every status, including the source typo", () => {
    expect(ceidgStatus("AKTYWNY")).toBe("active");
    expect(ceidgStatus("ZAWIESZONY")).toBe("suspended");
    expect(ceidgStatus("WYKRESLONY")).toBe("removed");
    expect(ceidgStatus("OCZEKUJE_NA_ROZPOCZECIE_DZIALANOSCI")).toBe("not_started");
    expect(ceidgStatus("OCZEKUJE_NA_ROZPOCZECIE_DZIALALNOSCI")).toBe("not_started");
    expect(ceidgStatus("WYLACZNIE_W_FORMIE_SPOLKI")).toBe("active");
    expect(ceidgStatus("COS_NOWEGO")).toBe("unknown");
    expect(ceidgStatus(undefined)).toBe("unknown");
    const d = ceidgDetails({ status: "WYLACZNIE_W_FORMIE_SPOLKI" });
    expect([d.status, d.statusRaw]).toEqual(["active", "WYLACZNIE_W_FORMIE_SPOLKI"]);
  });

  it("reads v2-style string PKD and removal dates", () => {
    const d = ceidgDetails({ status: "WYKRESLONY", pkdGlowny: "6201Z", pkd: ["6201Z", "6202Z"], dataZakonczenia: "2023-01-31", dataWykreslenia: "2023-02-10" });
    expect(d.pkd.map((p) => [p.code, p.primary])).toEqual([["62.01.Z", true], ["62.02.Z", false]]);
    expect([d.endedAt, d.removedAt, d.address]).toEqual(["2023-01-31", "2023-02-10", null]);
  });

  it("maps a short search record", () => {
    expect(ceidgSearchHit(FIRMY.firmy[0])).toEqual({
      name: "JAN TESTOWY USŁUGI TRANSPORTOWE",
      nip: "1234563218",
      regon: "123456785",
      status: "active",
      city: "Kraśnik",
    });
  });
});

describe("CeidgClient", () => {
  it("looks up by NIP with Bearer auth and unwraps the firma array", async () => {
    const up = fakeCeidg(() => json(FIRMA));
    const raw = await client(up.fetch).firmaByNip("1234563218");
    expect(raw?.nazwa).toBe("JAN TESTOWY USŁUGI TRANSPORTOWE");
    expect(up.calls).toHaveLength(1);
    expect(up.calls[0].url.href).toBe("https://dane.biznes.gov.pl/api/ceidg/v3/firma?nip=1234563218");
    expect(up.calls[0].headers.get("authorization")).toBe("Bearer tok-123");
  });

  it("looks up by REGON, uses the test env and custom base URL", async () => {
    const up = fakeCeidg(() => json({ firma: FIRMA.firma[0] })); // lone object tolerated
    expect(await client(up.fetch, { env: "test" }).firmaByRegon("123456785")).not.toBeNull();
    expect(up.calls[0].url.href).toBe("https://test-dane.biznes.gov.pl/api/ceidg/v3/firma?regon=123456785");
    await client(up.fetch, { baseUrl: "https://x.test/v3/" }).firmaByNip("1234563218");
    expect(up.calls[1].url.origin + up.calls[1].url.pathname).toBe("https://x.test/v3/firma");
  });

  it("treats 204, 404, empty bodies and empty arrays as not found", async () => {
    for (const res of [() => new Response(null, { status: 204 }), () => new Response("", { status: 404 }), () => new Response("", { status: 200 }), () => json({ firma: [] }), () => json({})]) {
      expect(await client(fakeCeidg(res).fetch).firmaByNip("1234563218")).toBeNull();
    }
  });

  it("treats NIEPOPRAWNY_NUMER_NIP as not found but other 400s as errors", async () => {
    expect(await client(fakeCeidg(() => json({ code: "NIEPOPRAWNY_NUMER_NIP", message: "x" }, 400)).fetch).firmaByNip("1")).toBeNull();
    await expect(client(fakeCeidg(() => json({ code: "BRAK_PARAMETROW_ZAPYTANIA" }, 400)).fetch).firmaByNip("1")).rejects.toBeInstanceOf(UpstreamError);
  });

  it("maps auth, quota, server and maintenance failures to UpstreamError", async () => {
    const fail = async (res: () => Response) => {
      const err = await client(fakeCeidg(res).fetch).firmaByNip("1234563218").then(() => null, (e) => e);
      expect(err).toBeInstanceOf(UpstreamError);
      return err as UpstreamError;
    };
    expect(await fail(() => new Response("no", { status: 401 }))).toMatchObject({ source: "CEIDG", status: 401 });
    expect(await fail(() => new Response("no", { status: 403 }))).toMatchObject({ status: 403 });
    const limited = await fail(() => new Response("slow down", { status: 429, headers: { "Retry-After": "120" } }));
    expect(limited).toMatchObject({ status: 429 });
    expect(limited.message).toContain("120");
    expect(await fail(() => new Response("slow down", { status: 403, headers: { "Retry-After": "60" } }))).toMatchObject({ status: 429 });
    expect(await fail(() => new Response("boom", { status: 502 }))).toMatchObject({ status: 502 });
    const maint = await fail(() => new Response("<html><body>Przerwa w działaniu serwisu</body></html>", { status: 200, headers: { "content-type": "text/html" } }));
    expect(maint.message).toContain("maintenance");
    await fail(() => new Response("<html>Przerwa</html>", { status: 503 }));
  });

  it("maps network errors and timeouts to UpstreamError", async () => {
    const boom = (async () => {
      throw new TypeError("fetch failed");
    }) as typeof fetch;
    await expect(client(boom).firmaByNip("1234563218")).rejects.toBeInstanceOf(UpstreamError);
    const hang = ((_u: unknown, init?: RequestInit) =>
      new Promise((_, reject) => init?.signal?.addEventListener("abort", () => reject(init.signal!.reason)))) as typeof fetch;
    await expect(client(hang, { timeoutMs: 20 }).firmaByNip("1234563218")).rejects.toBeInstanceOf(UpstreamError);
  });

  it("searches by name with city, clamping the page size", async () => {
    const up = fakeCeidg(() => json(FIRMY));
    const hits = await client(up.fetch).searchByName("Jan Testowy", { city: "Kraśnik", limit: 100 });
    expect(hits).toHaveLength(1);
    const q = up.calls[0].url;
    expect(q.pathname).toBe("/api/ceidg/v3/firmy");
    expect(Object.fromEntries(q.searchParams)).toEqual({ nazwa: "Jan Testowy", miasto: "Kraśnik", limit: "25", page: "0" });
    expect(await client(fakeCeidg(() => new Response(null, { status: 204 })).fetch).searchByName("x")).toEqual([]);
  });

  it("stops locally when the limiter says no, without calling upstream", async () => {
    const up = fakeCeidg(() => json(FIRMA));
    const keys: string[] = [];
    let allow = true;
    const limiter = { limit: async ({ key }: { key: string }) => (keys.push(key), { success: allow }) } as RateLimit;
    const c = client(up.fetch, { limiter });
    await c.firmaByNip("1234563218");
    expect(keys).toEqual(["ceidg"]);
    allow = false;
    await expect(c.firmaByNip("1234563218")).rejects.toMatchObject({ source: "CEIDG", status: 429, message: expect.stringContaining("local quota guard") });
    expect(up.calls).toHaveLength(1);
  });
});

describe("CeidgService", () => {
  it("caches lookups for 24h and not-found for 1h", async () => {
    const kv = memoryKV();
    let found = true;
    const up = fakeCeidg(() => (found ? json(FIRMA) : new Response("", { status: 404 })));
    const svc = new CeidgService(client(up.fetch), kv);

    const a = await svc.byNip("1234563218");
    const b = await svc.byNip("1234563218");
    expect([a.cached, b.cached, up.calls.length]).toEqual([false, true, 1]);
    expect(b.value?.status).toBe("active");
    const ttl = (key: string) => Math.round(((kv.store.get(key)!.expiresAt ?? 0) - Date.now()) / 1000);
    expect(ttl("ceidg:v1:nip:1234563218")).toBeGreaterThan(86000);

    found = false;
    const miss = await svc.byRegon("123456785");
    expect(miss.value).toBeNull();
    expect(ttl("ceidg:v1:regon:123456785")).toBeLessThanOrEqual(3600);
    expect((await svc.byRegon("123456785")).cached).toBe(true);
  });

  it("caches name search by folded query for 6h", async () => {
    const kv = memoryKV();
    const up = fakeCeidg(() => json(FIRMY));
    const svc = new CeidgService(client(up.fetch), kv);
    const a = await svc.searchByName("Kraśnik  usługi", { limit: 5 });
    const b = await svc.searchByName("KRASNIK USLUGI", { limit: 5 });
    expect(a.value[0]).toMatchObject({ nip: "1234563218", status: "active" });
    expect([a.cached, b.cached, up.calls.length]).toEqual([false, true, 1]);
    const [key, entry] = [...kv.store.entries()][0];
    expect(key).toMatch(/^ceidg:v1:search:[0-9a-f]{64}$/);
    expect((entry.expiresAt! - Date.now()) / 1000).toBeLessThanOrEqual(6 * 3600);
    await svc.searchByName("kraśnik usługi", { limit: 10 });
    expect(up.calls.length).toBe(2);
  });

  it("does not cache upstream failures", async () => {
    const kv = memoryKV();
    const svc = new CeidgService(client(fakeCeidg(() => new Response("x", { status: 503 })).fetch), kv);
    await expect(svc.byNip("1234563218")).rejects.toBeInstanceOf(UpstreamError);
    expect(kv.store.size).toBe(0);
  });
});
