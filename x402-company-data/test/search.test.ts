import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { privateKeyToAccount, generatePrivateKey } from "viem/accounts";
import { x402Client, wrapFetchWithPayment } from "@x402/fetch";
import { registerExactEvmScheme } from "@x402/evm/exact/client";
import { createApp } from "../src/app";
import type { Env } from "../src/env";
import { FakeFacilitator, fakeKrs, fakeRegon, memoryKV, ORLEN, SUSPENDED_JDG, upstreams } from "./helpers/fakes";
import { sqliteD1 } from "./helpers/d1-sqlite";

const BASE = "https://api.example.test";
const KRS_P = JSON.parse(readFileSync(new URL("./fixtures/krs/odpis-aktualny-P.json", import.meta.url), "utf8"));

function setup() {
  const regon = fakeRegon({ entities: [ORLEN, SUSPENDED_JDG] });
  const krs = fakeKrs({ "0000028860": { register: "P", body: KRS_P } });
  const facilitator = new FakeFacilitator();
  const env: Env = { PAY_TO: "0x1111111111111111111111111111111111111111", NETWORK: "eip155:84532", CACHE: memoryKV(), INDEX_DB: sqliteD1(), PUBLIC_BASE_URL: BASE };
  const app = createApp({ fetch: upstreams(regon, krs), facilitator });
  const appFetch = (async (input: RequestInfo | URL, init?: RequestInit) => app.request(input instanceof Request ? input : String(input), init, env)) as typeof fetch;
  const paidFetch = wrapFetchWithPayment(appFetch, registerExactEvmScheme(new x402Client(), { signer: privateKeyToAccount(generatePrivateKey()) }));
  return { facilitator, appFetch, paidFetch };
}

describe("GET /pl/company/search", () => {
  it("has its own price and answers bare probes with 402", async () => {
    const { appFetch } = setup();
    const res = await appFetch(`${BASE}/pl/company/search`);
    expect(res.status).toBe(402);
    expect(JSON.parse(atob(res.headers.get("PAYMENT-REQUIRED")!)).accepts[0].amount).toBe("10000");
  });

  it("rejects too-short queries for free", async () => {
    const { appFetch } = setup();
    expect((await appFetch(`${BASE}/pl/company/search?name=sp.%20z%20o.o.`)).status).toBe(400);
  });

  it("is free (404) while nothing matches, then finds entities resolved earlier", async () => {
    const { paidFetch, facilitator } = setup();
    let res = await paidFetch(`${BASE}/pl/company/search?name=orlen`);
    expect(res.status).toBe(404);
    expect(facilitator.settleCalls).toHaveLength(0);

    await paidFetch(`${BASE}/pl/company?nip=7740001454`); // resolves + indexes ORLEN
    await paidFetch(`${BASE}/pl/company/verify?nip=1234563218`); // sole trader: must NOT be indexed

    res = await paidFetch(`${BASE}/pl/company/search?name=orl`);
    expect(res.status).toBe(200);
    const body = (await res.json()) as any;
    expect(body.results[0]).toMatchObject({ identifiers: { nip: "7740001454", krs: "0000028860" }, legalForm: "joint_stock_company", status: "active" });
    expect(facilitator.settleCalls.at(-1)!.requirements.amount).toBe("10000");

    res = await paidFetch(`${BASE}/pl/company/search?name=testowy`);
    expect(res.status).toBe(404);
  });
});
