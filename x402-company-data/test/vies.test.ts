import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { ViesClient } from "../src/sources/vies/client";
import { ViesService } from "../src/services/vies";
import { UpstreamError } from "../src/sources/errors";
import { memoryKV } from "./helpers/fakes";

const fixture = (n: string) => JSON.parse(readFileSync(new URL(`./fixtures/vies/${n}.json`, import.meta.url), "utf8"));
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

function fakeVies(respond: (url: URL) => Response | Promise<Response>) {
  const calls: string[] = [];
  const fn = (async (input: string | URL | Request) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url);
    calls.push(url.href);
    return respond(url);
  }) as typeof fetch;
  return { fetch: fn, calls, client: new ViesClient({ fetch: fn }) };
}

describe("ViesClient", () => {
  it("calls GET /ms/{CC}/vat/{number} and reads a valid answer, treating --- as null", async () => {
    const up = fakeVies(() => json(fixture("check-valid")));
    const r = await up.client.check("pl", "PL 774-000-14-54");
    expect(up.calls).toEqual(["https://ec.europa.eu/taxation_customs/vies/rest-api/ms/PL/vat/7740001454"]);
    expect(r).toEqual({ valid: true, countryCode: "PL", vatNumber: "7740001454", name: null, address: null, requestDate: "2026-10-10T08:15:03.412Z", error: null });
  });

  it("returns name and address when the member state discloses them", async () => {
    const up = fakeVies(() => json({ isValid: true, userError: "VALID", name: "ACME GMBH", address: "MUSTERSTR 1\n10115 BERLIN", vatNumber: "123456789", requestDate: "2026-10-10T08:00:00.000Z" }));
    expect(await up.client.check("DE", "123456789")).toMatchObject({ valid: true, name: "ACME GMBH", address: "MUSTERSTR 1, 10115 BERLIN" });
  });

  it("reports INVALID as a definitive negative", async () => {
    const r = await fakeVies(() => json(fixture("check-invalid"))).client.check("PL", "1234567890");
    expect(r).toMatchObject({ valid: false, error: null, name: null });
  });

  it("maps transient HTTP-200 failures to valid:null with the error code", async () => {
    const r = await fakeVies(() => json(fixture("check-ms-unavailable"))).client.check("PL", "7740001454");
    expect(r).toMatchObject({ valid: null, error: "MS_UNAVAILABLE" });
    for (const code of ["TIMEOUT", "SERVICE_UNAVAILABLE", "MS_MAX_CONCURRENT_REQ", "GLOBAL_MAX_CONCURRENT_REQ"]) {
      expect(await fakeVies(() => json({ isValid: false, userError: code })).client.check("PL", "7740001454")).toMatchObject({ valid: null, error: code });
    }
    expect(await fakeVies(() => json({ isValid: false })).client.check("PL", "7740001454")).toMatchObject({ valid: null, error: "UNKNOWN" });
  });

  it("reads the POST-style `valid` flag and error envelope", async () => {
    expect(await fakeVies(() => json(fixture("check-post-valid"))).client.check("PL", "7740001454")).toMatchObject({ valid: true });
    const env = { actionSucceed: false, errorWrappers: [{ error: "INVALID_INPUT", message: "bad" }] };
    expect(await fakeVies(() => json(env, 400)).client.check("PL", "7740001454")).toMatchObject({ valid: null, error: "INVALID_INPUT" });
  });

  it("normalises Greece and a repeated prefix; rejects garbage input without calling out", async () => {
    const up = fakeVies(() => json({ isValid: true, userError: "VALID" }));
    await up.client.check("GR", "EL123456789");
    expect(up.calls[0]).toContain("/ms/EL/vat/123456789");
    expect(await up.client.check("P", "12")).toMatchObject({ valid: null, error: "INVALID_INPUT" });
    expect(up.calls).toHaveLength(1);
  });

  it("throws UpstreamError on 5xx, 429, non-JSON and network failure", async () => {
    for (const res of [() => new Response("x", { status: 503 }), () => new Response("x", { status: 429 }), () => new Response("<html>", { status: 200 })]) {
      await expect(fakeVies(res).client.check("PL", "7740001454")).rejects.toMatchObject({ source: "VIES" });
    }
    const boom = new ViesClient({ fetch: (async () => { throw new TypeError("down"); }) as typeof fetch });
    await expect(boom.check("PL", "7740001454")).rejects.toBeInstanceOf(UpstreamError);
  });
});

describe("ViesService", () => {
  it("caches valid and invalid answers", async () => {
    const kv = memoryKV();
    const up = fakeVies((url) => json(fixture(url.pathname.endsWith("7740001454") ? "check-valid" : "check-invalid")));
    const svc = new ViesService(up.client, kv);
    expect((await svc.check("PL", "7740001454")).cached).toBe(false);
    expect((await svc.check("pl", "PL7740001454")).cached).toBe(true);
    expect((await svc.check("PL", "1234567890")).value.valid).toBe(false);
    expect((await svc.check("PL", "1234567890")).cached).toBe(true);
    expect(up.calls).toHaveLength(2);
    expect(kv.store.has("vies:v1:PL:7740001454")).toBe(true);
    const ttl = (kv.store.get("vies:v1:PL:7740001454")!.expiresAt! - Date.now()) / 1000;
    expect(ttl).toBeGreaterThan(86000);
  });

  it("never caches an unknown (valid: null) answer", async () => {
    const kv = memoryKV();
    let down = true;
    const up = fakeVies(() => json(fixture(down ? "check-ms-unavailable" : "check-valid")));
    const svc = new ViesService(up.client, kv);
    const a = await svc.check("PL", "7740001454");
    expect(a).toMatchObject({ cached: false, value: { valid: null, error: "MS_UNAVAILABLE" } });
    expect(kv.store.size).toBe(0);
    down = false;
    expect((await svc.check("PL", "7740001454")).value.valid).toBe(true);
    expect(up.calls).toHaveLength(2);
  });

  it("propagates upstream failures", async () => {
    const svc = new ViesService(fakeVies(() => new Response("x", { status: 500 })).client, memoryKV());
    await expect(svc.check("PL", "7740001454")).rejects.toBeInstanceOf(UpstreamError);
  });
});
