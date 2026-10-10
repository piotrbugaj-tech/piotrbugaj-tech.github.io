import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { privateKeyToAccount, generatePrivateKey } from "viem/accounts";
import { x402Client, wrapFetchWithPayment } from "@x402/fetch";
import { registerExactEvmScheme } from "@x402/evm/exact/client";
import { createApp } from "../src/app";
import type { Env } from "../src/env";
import { krsDetails, parsePlMoney } from "../src/sources/krs/normalize";
import { FakeFacilitator, fakeKrs, fakeRegon, memoryKV, ORLEN, SUSPENDED_JDG, upstreams } from "./helpers/fakes";

const KRS_P = JSON.parse(readFileSync(new URL("./fixtures/krs/odpis-aktualny-P.json", import.meta.url), "utf8"));
const KRS_REMOVED = JSON.parse(readFileSync(new URL("./fixtures/krs/odpis-aktualny-wykreslony.json", import.meta.url), "utf8"));
const BASE = "https://api.example.test";

function setup(opts: { krsFail?: number; regonFail?: number } = {}) {
  const regon = fakeRegon({ entities: [ORLEN, SUSPENDED_JDG], failWith: opts.regonFail });
  const krs = fakeKrs({ "0000028860": { register: "P", body: KRS_P }, "0000999999": { register: "P", body: KRS_REMOVED } }, { failWith: opts.krsFail });
  const facilitator = new FakeFacilitator();
  const env: Env = { PAY_TO: "0x1111111111111111111111111111111111111111", NETWORK: "eip155:84532", CACHE: memoryKV(), PUBLIC_BASE_URL: BASE };
  const app = createApp({ fetch: upstreams(regon, krs), facilitator });
  const appFetch = (async (input: RequestInfo | URL, init?: RequestInit) => app.request(input instanceof Request ? input : String(input), init, env)) as typeof fetch;
  const paidFetch = wrapFetchWithPayment(appFetch, registerExactEvmScheme(new x402Client(), { signer: privateKeyToAccount(generatePrivateKey()) }));
  return { regon, krs, facilitator, appFetch, paidFetch };
}

describe("KRS normaliser", () => {
  it("maps the OdpisAktualny fixture", () => {
    const d = krsDetails("0000028860", { register: "P", odpis: KRS_P.odpis });
    expect(d).toMatchObject({
      nip: "7740001454",
      regon: "610188201",
      legalForm: "joint_stock_company",
      registeredAt: "2001-11-29",
      status: "active",
      capital: { amount: 1565420000, currency: "PLN" },
    });
    expect(d.pkd[0]).toEqual({ code: "19.20.Z", description: "PRODUKCJA WYROBÓW RAFINACJI ROPY NAFTOWEJ", primary: true });
    expect(d.representation?.members[0]).toEqual({ name: "D**** O*****", role: "PREZES ZARZĄDU" });
    expect(d.address?.postalCode).toBe("09-411");
  });

  it("detects struck-off entities", () => {
    const d = krsDetails("0000999999", { register: "P", odpis: KRS_REMOVED.odpis });
    expect(d.status).toBe("removed");
    expect(d.removedAt).toBe("2019-06-21");
  });

  it("parses Polish money", () => {
    expect(parsePlMoney("1 565 420 000,50")).toBe(1565420000.5);
    expect(parsePlMoney("")).toBeNull();
  });
});

describe("GET /pl/company", () => {
  it("merges REGON and KRS into one profile", async () => {
    const { paidFetch, facilitator } = setup();
    const res = await paidFetch(`${BASE}/pl/company?nip=7740001454&include=representation`);
    expect(res.status).toBe(200);
    const p = (await res.json()) as any;
    expect(p).toMatchObject({
      identifiers: { nip: "7740001454", regon: "610188201", krs: "0000028860" },
      name: "POLSKI KONCERN NAFTOWY ORLEN SPÓŁKA AKCYJNA",
      legalForm: { normalized: "joint_stock_company", label: "SPÓŁKA AKCYJNA" },
      status: { code: "active", active: true },
      capital: { amount: 1565420000, currency: "PLN" },
      registries: { krs: { register: "P", registeredAt: "2001-11-29" }, regon: { type: "P", silo: "6" } },
      warnings: [],
    });
    expect(p.address.city).toBe("Płock"); // REGON's mixed-case address preferred
    expect(p.pkd.primary.code).toBe("19.20.Z");
    expect(p.representation.body).toBe("ZARZĄD");
    expect(p.sources.map((s: any) => s.source)).toEqual(["REGON", "KRS"]);
    expect(facilitator.settleCalls[0].requirements.amount).toBe("20000");
  });

  it("omits representation unless requested", async () => {
    const { paidFetch } = setup();
    const p = (await (await paidFetch(`${BASE}/pl/company?krs=28860`)).json()) as any;
    expect(p.representation).toBeNull();
    expect(p.identifiers.krs).toBe("0000028860");
  });

  it("degrades gracefully when KRS is down", async () => {
    const { paidFetch } = setup({ krsFail: 503 });
    const res = await paidFetch(`${BASE}/pl/company?nip=7740001454`);
    expect(res.status).toBe(200);
    const p = (await res.json()) as any;
    expect(p.name).toBe("ORLEN SPÓŁKA AKCYJNA");
    expect(p.warnings[0]).toMatch(/KRS temporarily unavailable/);
  });

  it("is free (404) when nothing is found", async () => {
    const { paidFetch, facilitator } = setup();
    const res = await paidFetch(`${BASE}/pl/company?nip=5250007738`);
    expect(res.status).toBe(404);
    expect(facilitator.settleCalls).toHaveLength(0);
  });

  it("is free (503) when every register is down", async () => {
    const { paidFetch, facilitator } = setup({ krsFail: 503, regonFail: 503 });
    const res = await paidFetch(`${BASE}/pl/company?krs=28860`);
    expect(res.status).toBe(503);
    expect(facilitator.settleCalls).toHaveLength(0);
  });

  it("returns a city-level, nameless profile for sole traders by default", async () => {
    const { paidFetch } = setup();
    const p = (await (await paidFetch(`${BASE}/pl/company?nip=1234563218`)).json()) as any;
    expect(p).toMatchObject({ name: null, isNaturalPerson: true, personalDataRedacted: true, status: { code: "suspended", suspendedSince: "2024-01-15" } });
    expect(p.address).toMatchObject({ street: null, postalCode: null, city: "Warszawa" });
    expect(p.contact).toEqual({ website: null, email: null });
  });
});
