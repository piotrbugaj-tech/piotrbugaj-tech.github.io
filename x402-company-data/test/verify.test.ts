import { describe, expect, it } from "vitest";
import { privateKeyToAccount, generatePrivateKey } from "viem/accounts";
import { x402Client, wrapFetchWithPayment, decodePaymentResponseHeader } from "@x402/fetch";
import { registerExactEvmScheme } from "@x402/evm/exact/client";
import { createApp } from "../src/app";
import type { Env } from "../src/env";
import { FakeFacilitator, fakeRegon, memoryKV, ORLEN, SUSPENDED_JDG } from "./helpers/fakes";

const PAY_TO = "0x1111111111111111111111111111111111111111";

function setup(opts: { failWith?: number } = {}) {
  const regon = fakeRegon({ entities: [ORLEN, SUSPENDED_JDG], ...opts });
  const facilitator = new FakeFacilitator();
  const kv = memoryKV();
  const env: Env = { PAY_TO, NETWORK: "eip155:84532", REGON_API_KEY: "test-key", CACHE: kv, PUBLIC_BASE_URL: "https://api.example.test" };
  const app = createApp({ fetch: regon.fetch, facilitator });
  const appFetch = (async (input: RequestInfo | URL, init?: RequestInit) => app.request(input instanceof Request ? input : String(input), init, env)) as typeof fetch;
  const client = registerExactEvmScheme(new x402Client(), { signer: privateKeyToAccount(generatePrivateKey()) });
  const paidFetch = wrapFetchWithPayment(appFetch, client);
  return { app, env, regon, facilitator, kv, appFetch, paidFetch };
}

const URL_BASE = "https://api.example.test";

describe("GET /pl/company/verify", () => {
  it("answers bare discovery probes with 402 but rejects invalid identifiers for free", async () => {
    const { appFetch, regon } = setup();
    let res = await appFetch(`${URL_BASE}/pl/company/verify`);
    expect(res.status).toBe(402); // catalogs (CDP validate, x402scan) probe without parameters
    res = await appFetch(`${URL_BASE}/pl/company/verify?nip=7740001455`);
    expect(res.status).toBe(400);
    expect(await res.json()).toMatchObject({ error: "invalid_request" });
    expect(regon.calls).toHaveLength(0);
  });

  it("answers 402 with x402 payment requirements when unpaid", async () => {
    const { appFetch, regon } = setup();
    const res = await appFetch(`${URL_BASE}/pl/company/verify?nip=7740001454`);
    expect(res.status).toBe(402);
    const header = res.headers.get("PAYMENT-REQUIRED");
    expect(header).toBeTruthy();
    const req = JSON.parse(atob(header!));
    expect(req.x402Version).toBe(2);
    expect(req.accepts[0]).toMatchObject({ scheme: "exact", network: "eip155:84532", payTo: PAY_TO, amount: "5000" });
    expect(req.extensions?.bazaar).toBeTruthy();
    expect(await res.json()).toMatchObject({ error: "payment_required" });
    expect(regon.calls).toHaveLength(0); // no upstream work for unpaid requests
  });

  it("serves verified data after payment and settles exactly once", async () => {
    const { paidFetch, facilitator } = setup();
    const res = await paidFetch(`${URL_BASE}/pl/company/verify?nip=774-000-14-54`);
    expect(res.status).toBe(200);
    const body = (await res.json()) as any;
    expect(body).toMatchObject({
      found: true,
      active: true,
      status: "active",
      name: "ORLEN SPÓŁKA AKCYJNA",
      identifiers: { nip: "7740001454", regon: "610188201", krs: "0000028860" },
      legalForm: "joint_stock_company",
      isNaturalPerson: false,
    });
    expect(body.sources[0]).toMatchObject({ source: "REGON", cached: false });
    expect(facilitator.settleCalls).toHaveLength(1);
    const receipt = decodePaymentResponseHeader(res.headers.get("PAYMENT-RESPONSE")!);
    expect(receipt.success).toBe(true);
  });

  it("reports suspended sole traders as not active", async () => {
    const { paidFetch } = setup();
    const body = (await (await paidFetch(`${URL_BASE}/pl/company/verify?nip=1234563218`)).json()) as any;
    expect(body).toMatchObject({ found: true, active: false, status: "suspended", isNaturalPerson: true, legalForm: "sole_proprietorship" });
  });

  it("returns found=false for a valid but unregistered NIP (paid answer)", async () => {
    const { paidFetch, facilitator } = setup();
    const res = await paidFetch(`${URL_BASE}/pl/company/verify?nip=5250007738`);
    expect(res.status).toBe(200);
    expect(await res.json()).toMatchObject({ found: false, active: false, status: "not_found" });
    expect(facilitator.settleCalls).toHaveLength(1);
  });

  it("does not charge when the registry is down", async () => {
    const { paidFetch, facilitator } = setup({ failWith: 503 });
    const res = await paidFetch(`${URL_BASE}/pl/company/verify?nip=7740001454`);
    expect(res.status).toBe(503);
    expect(await res.json()).toMatchObject({ error: "upstream_unavailable", source: "REGON" });
    expect(facilitator.verifyCalls).toHaveLength(1);
    expect(facilitator.settleCalls).toHaveLength(0);
  });

  it("serves repeat lookups from KV without calling the registry", async () => {
    const { paidFetch, regon } = setup();
    await paidFetch(`${URL_BASE}/pl/company/verify?nip=7740001454`);
    const callsAfterFirst = regon.calls.length;
    const body = (await (await paidFetch(`${URL_BASE}/pl/company/verify?nip=7740001454`)).json()) as any;
    expect(regon.calls.length).toBe(callsAfterFirst);
    expect(body.sources[0].cached).toBe(true);
  });

  it("fails closed when PAY_TO is not configured", async () => {
    const regon = fakeRegon({ entities: [ORLEN] });
    const app = createApp({ fetch: regon.fetch, facilitator: new FakeFacilitator() });
    const res = await app.request(`${URL_BASE}/pl/company/verify?nip=7740001454`, {}, { NETWORK: "eip155:84532" } as Env);
    expect(res.status).toBe(503);
  });
});

describe("POST /pl/company/verify/batch", () => {
  it("prices per identifier with a minimum and skips invalid ones", async () => {
    const { appFetch } = setup();
    const post = (body: unknown) =>
      appFetch(`${URL_BASE}/pl/company/verify/batch`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });

    let res = await post({ nip: ["7740001454"] });
    expect(res.status).toBe(402);
    expect(JSON.parse(atob(res.headers.get("PAYMENT-REQUIRED")!)).accepts[0].amount).toBe("10000"); // min $0.01

    res = await post({ nip: ["7740001454", "1234563218", "5250007738", "7740001455"], regon: ["610188201"] });
    expect(JSON.parse(atob(res.headers.get("PAYMENT-REQUIRED")!)).accepts[0].amount).toBe("12000"); // 4 valid × $0.003

    res = await appFetch(`${URL_BASE}/pl/company/verify/batch`, { method: "POST" });
    expect(res.status).toBe(402); // empty-body probe gets the minimum price
    expect(JSON.parse(atob(res.headers.get("PAYMENT-REQUIRED")!)).accepts[0].amount).toBe("10000");

    res = await post({ nip: ["bad"] });
    expect(res.status).toBe(400);
    res = await post({ nip: Array.from({ length: 51 }, () => "7740001454") });
    expect(res.status).toBe(400);
  });

  it("returns per-identifier results after payment", async () => {
    const { paidFetch, facilitator } = setup();
    const res = await paidFetch(`${URL_BASE}/pl/company/verify/batch`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ nip: ["7740001454", "1234563218", "5250007738", "123"], regon: ["610188201"] }),
    });
    expect(res.status).toBe(200);
    const body = (await res.json()) as any;
    expect(body.count).toBe(4);
    expect(body.results.map((r: any) => [r.query.value, r.status])).toEqual([
      ["7740001454", "active"],
      ["1234563218", "suspended"],
      ["5250007738", "not_found"],
      ["610188201", "active"],
    ]);
    expect(body.invalid).toEqual([{ kind: "nip", input: "123", error: "invalid format or checksum" }]);
    expect(facilitator.settleCalls).toHaveLength(1);
    expect(facilitator.settleCalls[0].requirements.amount).toBe("12000");
  });
});

describe("data-protection policy", () => {
  it("withholds the name of sole traders by default but supports ?name= matching", async () => {
    const { paidFetch } = setup();
    const body = (await (await paidFetch(`${URL_BASE}/pl/company/verify?nip=1234563218&name=Jan%20Testowy`)).json()) as any;
    expect(body).toMatchObject({ found: true, name: null, personalDataRedacted: true, nameMatch: { result: "partial" } });
    expect(body.notice).toContain("/legal");
  });

  it("shows company names and matches them ignoring legal-form words", async () => {
    const { paidFetch } = setup();
    const body = (await (await paidFetch(`${URL_BASE}/pl/company/verify?nip=7740001454&name=Orlen%20S.A.`)).json()) as any;
    expect(body).toMatchObject({ name: "ORLEN SPÓŁKA AKCYJNA", personalDataRedacted: false, nameMatch: { result: "match", score: 1 } });
  });

  it("returns the name of sole traders when NATURAL_PERSONS=full", async () => {
    const { appFetch, env } = setup();
    env.NATURAL_PERSONS = "full";
    const client = registerExactEvmScheme(new x402Client(), { signer: privateKeyToAccount(generatePrivateKey()) });
    const body = (await (await wrapFetchWithPayment(appFetch, client)(`${URL_BASE}/pl/company/verify?nip=1234563218`)).json()) as any;
    expect(body).toMatchObject({ name: "JAN TESTOWY USŁUGI", personalDataRedacted: false });
  });

  it("answers 451 for free when the data subject objected", async () => {
    const { appFetch, kv, facilitator, regon } = setup();
    await kv.put("optout:nip:1234563218", "2026-10-10 objection #1");
    const res = await appFetch(`${URL_BASE}/pl/company/verify?nip=1234563218`);
    expect(res.status).toBe(451);
    expect(facilitator.verifyCalls).toHaveLength(0);
    expect(regon.calls).toHaveLength(0);
  });

  it("serves the legal page", async () => {
    const { appFetch } = setup();
    const res = await appFetch(`${URL_BASE}/legal`);
    expect(res.status).toBe(200);
    expect(await res.text()).toContain("Art. 14 GDPR");
  });
});
