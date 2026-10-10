import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { privateKeyToAccount, generatePrivateKey } from "viem/accounts";
import { x402Client, wrapFetchWithPayment } from "@x402/fetch";
import { registerExactEvmScheme } from "@x402/evm/exact/client";
import { createApp } from "../src/app";
import type { Env } from "../src/env";
import { FakeFacilitator, fakeJson, fakeKrs, fakeRegon, memoryKV, ORLEN, SUSPENDED_JDG, upstreams } from "./helpers/fakes";

const fx = (f: string) => JSON.parse(readFileSync(new URL(`./fixtures/${f}`, import.meta.url), "utf8"));
const BASE = "https://api.example.test";
const ACCOUNT = "PL61 1090 1014 0000 0712 1981 2874"; // published IBAN example, valid checksum

function setup(opts: { ceidgToken?: string; wlDown?: boolean } = {}) {
  const regon = fakeRegon({ entities: [ORLEN, SUSPENDED_JDG] });
  const krs = fakeKrs({ "0000028860": { register: "P", body: fx("krs/odpis-aktualny-P.json") } });
  const wl = fakeJson((url) => {
    if (opts.wlDown) return [500, { code: "WL-190", message: "Niepoprawne żądanie" }];
    if (url.pathname.includes("/api/check/")) return [200, { result: { accountAssigned: "TAK", requestId: "chk-1", requestDateTime: "10-10-2026 10:00:00" } }];
    return [200, fx("whitelist/search-nip.json")];
  });
  const vies = fakeJson(() => [200, fx("vies/check-valid.json")]);
  const ceidg = fakeJson(() => [200, fx("ceidg/firma-details.json")]);
  const facilitator = new FakeFacilitator();
  const env: Env = { PAY_TO: "0x1111111111111111111111111111111111111111", NETWORK: "eip155:84532", CACHE: memoryKV(), PUBLIC_BASE_URL: BASE, CEIDG_API_TOKEN: opts.ceidgToken };
  const app = createApp({ fetch: upstreams(regon, krs, { "wl-api.mf.gov.pl": wl.fetch, "ec.europa.eu": vies.fetch, "dane.biznes.gov.pl": ceidg.fetch }), facilitator });
  const appFetch = (async (input: RequestInfo | URL, init?: RequestInit) => app.request(input instanceof Request ? input : String(input), init, env)) as typeof fetch;
  const paidFetch = wrapFetchWithPayment(appFetch, registerExactEvmScheme(new x402Client(), { signer: privateKeyToAccount(generatePrivateKey()) }));
  return { wl, vies, ceidg, facilitator, appFetch, paidFetch };
}

describe("GET /pl/vat/account-check", () => {
  it("validates NIP and NRB checksums before payment, 402 for bare probes", async () => {
    const { appFetch, wl } = setup();
    expect((await appFetch(`${BASE}/pl/vat/account-check`)).status).toBe(402);
    expect((await appFetch(`${BASE}/pl/vat/account-check?nip=7740001454&account=PL61109010140000071219812875`)).status).toBe(400);
    expect((await appFetch(`${BASE}/pl/vat/account-check?nip=7740001455&account=${encodeURIComponent(ACCOUNT)}`)).status).toBe(400);
    expect(wl.calls).toHaveLength(0);
  });

  it("returns the white-list answer with the MF request id and a masked account", async () => {
    const { paidFetch, facilitator } = setup();
    const res = await paidFetch(`${BASE}/pl/vat/account-check?nip=7740001454&account=${encodeURIComponent(ACCOUNT)}`);
    expect(res.status).toBe(200);
    const body = (await res.json()) as any;
    expect(body).toMatchObject({ assigned: true, whiteListRequestId: "chk-1", query: { nip: "7740001454", account: "PL61 **** 2874" } });
    expect(JSON.stringify(body)).not.toContain("109010140000071219812874");
    expect(facilitator.settleCalls[0].requirements.amount).toBe("10000");
  });

  it("is free (503) when the white list is unavailable", async () => {
    const { paidFetch, facilitator } = setup({ wlDown: true });
    const res = await paidFetch(`${BASE}/pl/vat/account-check?nip=7740001454&account=${encodeURIComponent(ACCOUNT)}`);
    expect(res.status).toBe(503);
    expect(facilitator.settleCalls).toHaveLength(0);
  });
});

describe("GET /pl/company?include=vat", () => {
  it("adds Polish VAT status and EU VAT validity without exposing account numbers", async () => {
    const { paidFetch } = setup();
    const p = (await (await paidFetch(`${BASE}/pl/company?nip=7740001454&include=vat`)).json()) as any;
    expect(p.vat).toMatchObject({ status: "active", euVatValid: true, bankAccountsCount: 1, hasVirtualAccounts: false, whiteListRequestId: "d4k7p-m9x2q8z" });
    expect(p.sources.map((s: any) => s.source)).toEqual(["REGON", "KRS", "MF_WL", "VIES"]);
    expect(JSON.stringify(p)).not.toContain("49102010260000042270201390");
  });

  it("returns vat=null unless requested and does not call MF/VIES", async () => {
    const { paidFetch, wl, vies } = setup();
    const p = (await (await paidFetch(`${BASE}/pl/company?nip=7740001454`)).json()) as any;
    expect(p.vat).toBeNull();
    expect(wl.calls.length + vies.calls.length).toBe(0);
  });
});

describe("CEIDG enrichment for sole traders", () => {
  it("uses CEIDG as the register of record when a token is configured", async () => {
    const { paidFetch, ceidg } = setup({ ceidgToken: "jwt" });
    const p = (await (await paidFetch(`${BASE}/pl/company?nip=1234563218`)).json()) as any;
    expect(ceidg.calls.length).toBe(1);
    // REGON (stale) says suspended, CEIDG says AKTYWNY -> CEIDG wins for natural persons.
    expect(p.status.code).toBe("active");
    expect(p.registries.ceidg).toMatchObject({ status: "AKTYWNY" });
    expect(p).toMatchObject({ name: null, personalDataRedacted: true });
    expect(p.address.street).toBeNull();
  });

  it("skips CEIDG for legal entities and when no token is set", async () => {
    let s = setup({ ceidgToken: "jwt" });
    await s.paidFetch(`${BASE}/pl/company?nip=7740001454`);
    expect(s.ceidg.calls).toHaveLength(0);
    s = setup();
    await s.paidFetch(`${BASE}/pl/company?nip=1234563218`);
    expect(s.ceidg.calls).toHaveLength(0);
  });
});
