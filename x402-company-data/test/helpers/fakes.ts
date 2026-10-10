import type { FacilitatorClient } from "@x402/core/server";
import type { PaymentPayload, PaymentRequirements, SettleResponse, SupportedResponse, VerifyResponse } from "@x402/core/types";

// ---------- KV ----------
export function memoryKV() {
  const store = new Map<string, { value: string; expiresAt?: number }>();
  const kv = {
    store,
    async get(key: string, type?: string) {
      const e = store.get(key);
      if (!e || (e.expiresAt && e.expiresAt < Date.now())) return null;
      return type === "json" ? JSON.parse(e.value) : e.value;
    },
    async put(key: string, value: string, opts?: { expirationTtl?: number }) {
      store.set(key, { value, expiresAt: opts?.expirationTtl ? Date.now() + opts.expirationTtl * 1000 : undefined });
    },
    async delete(key: string) {
      store.delete(key);
    },
  };
  return kv as unknown as KVNamespace & { store: typeof store };
}

// ---------- facilitator ----------
export class FakeFacilitator implements FacilitatorClient {
  verifyCalls: Array<{ payload: PaymentPayload; requirements: PaymentRequirements }> = [];
  settleCalls: Array<{ payload: PaymentPayload; requirements: PaymentRequirements }> = [];
  constructor(readonly network = "eip155:84532") {}
  async getSupported(): Promise<SupportedResponse> {
    return { kinds: [{ x402Version: 2, scheme: "exact", network: this.network as `${string}:${string}` }], extensions: ["bazaar"], signers: {} };
  }
  async verify(payload: PaymentPayload, requirements: PaymentRequirements): Promise<VerifyResponse> {
    this.verifyCalls.push({ payload, requirements });
    const auth = (payload.payload as { authorization?: { from?: string; value?: string } }).authorization;
    const ok = auth?.value === requirements.amount;
    return { isValid: ok, invalidReason: ok ? undefined : "amount_mismatch", payer: auth?.from };
  }
  async settle(payload: PaymentPayload, requirements: PaymentRequirements): Promise<SettleResponse> {
    this.settleCalls.push({ payload, requirements });
    return { success: true, transaction: "0x" + "ab".repeat(32), network: requirements.network, payer: (payload.payload as any).authorization?.from };
  }
}

// ---------- REGON BIR1.1 ----------
export const xmlEscape = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

/** Wraps a SOAP result the way BIR1.1 does: MTOM multipart + escaped inner XML. */
export function mtom(op: string, result: string): string {
  const boundary = "uuid:3a1b2c3d-0000-4000-8000-000000000001+id=1";
  return (
    `--${boundary}\r\nContent-ID: <http://tempuri.org/0>\r\nContent-Transfer-Encoding: 8bit\r\n` +
    `Content-Type: application/xop+xml;charset=utf-8;type="application/soap+xml"\r\n\r\n` +
    `<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:a="http://www.w3.org/2005/08/addressing"><s:Header>` +
    `<a:Action s:mustUnderstand="1">http://CIS/BIR/PUBL/2014/07/IUslugaBIRzewnPubl/${op}Response</a:Action></s:Header>` +
    `<s:Body><${op}Response xmlns="http://CIS/BIR/PUBL/2014/07"><${op}Result>${result}</${op}Result></${op}Response></s:Body></s:Envelope>\r\n--${boundary}--\r\n`
  );
}

export const dane = (rows: Array<Record<string, string>>) =>
  xmlEscape(`<root>${rows.map((r) => `<dane>${Object.entries(r).map(([k, v]) => `<${k}>${xmlEscape(v)}</${k}>`).join("")}</dane>`).join("")}</root>`);

export interface FakeRegonEntity {
  search: Record<string, string>;
  report: Record<string, string>;
  pkd?: Array<Record<string, string>>;
}

export const ORLEN: FakeRegonEntity = {
  search: {
    Regon: "610188201", Nip: "7740001454", StatusNip: "", Nazwa: "ORLEN SPÓŁKA AKCYJNA", Wojewodztwo: "MAZOWIECKIE", Powiat: "Płock",
    Gmina: "M. Płock", Miejscowosc: "Płock", KodPocztowy: "09-411", Ulica: "ul. Test-Chemików", NrNieruchomosci: "7", NrLokalu: "",
    Typ: "P", SilosID: "6", DataZakonczeniaDzialalnosci: "", MiejscowoscPoczty: "Płock",
  },
  report: {
    praw_regon9: "610188201", praw_nip: "7740001454", praw_nazwa: "ORLEN SPÓŁKA AKCYJNA", praw_nazwaSkrocona: "ORLEN S.A.",
    praw_numerWRejestrzeEwidencji: "0000028860", praw_dataWpisuDoRejestruEwidencji: "2001-06-26", praw_dataPowstania: "1993-12-07",
    praw_dataRozpoczeciaDzialalnosci: "1993-12-07", praw_dataWpisuDoRegon: "", praw_dataZawieszeniaDzialalnosci: "",
    praw_dataWznowieniaDzialalnosci: "", praw_dataZakonczeniaDzialalnosci: "", praw_dataSkresleniaZRegon: "",
    praw_dataOrzeczeniaOUpadlosci: "", praw_adSiedzKraj_Symbol: "PL", praw_adSiedzKodPocztowy: "09411",
    praw_adSiedzNumerNieruchomosci: "7", praw_adSiedzNumerLokalu: "", praw_adresEmail: "", praw_adresStronyinternetowej: "www.orlen.pl",
    praw_adSiedzWojewodztwo_Nazwa: "MAZOWIECKIE", praw_adSiedzPowiat_Nazwa: "Płock", praw_adSiedzGmina_Nazwa: "M. Płock",
    praw_adSiedzMiejscowosc_Nazwa: "Płock", praw_adSiedzMiejscowoscPoczty_Nazwa: "Płock", praw_adSiedzUlica_Nazwa: "ul. Test-Chemików",
    praw_podstawowaFormaPrawna_Nazwa: "OSOBA PRAWNA", praw_szczegolnaFormaPrawna_Nazwa: "SPÓŁKI AKCYJNE",
    praw_rodzajRejestruEwidencji_Nazwa: "REJESTR PRZEDSIĘBIORCÓW",
  },
  pkd: [
    { praw_pkdKod: "1920Z", praw_pkdNazwa: "WYTWARZANIE PRODUKTÓW RAFINACJI ROPY NAFTOWEJ", praw_pkdPrzewazajace: "1" },
    { praw_pkdKod: "4671Z", praw_pkdNazwa: "SPRZEDAŻ HURTOWA PALIW", praw_pkdPrzewazajace: "0" },
  ],
};

export const SUSPENDED_JDG: FakeRegonEntity = {
  search: {
    Regon: "123456785", Nip: "1234563218", StatusNip: "", Nazwa: "JAN TESTOWY USŁUGI", Wojewodztwo: "MAZOWIECKIE", Powiat: "Warszawa",
    Gmina: "Warszawa", Miejscowosc: "Warszawa", KodPocztowy: "00-001", Ulica: "ul. Testowa", NrNieruchomosci: "1", NrLokalu: "2",
    Typ: "F", SilosID: "1", DataZakonczeniaDzialalnosci: "", MiejscowoscPoczty: "Warszawa",
  },
  report: {
    fiz_regon9: "123456785", fiz_nazwa: "JAN TESTOWY USŁUGI", fiz_dataRozpoczeciaDzialalnosci: "2015-03-01",
    fiz_dataZawieszeniaDzialalnosci: "2024-01-15", fiz_dataWznowieniaDzialalnosci: "", fiz_dataZakonczeniaDzialalnosci: "",
    fiz_adSiedzKodPocztowy: "00001", fiz_adSiedzMiejscowosc_Nazwa: "Warszawa", fiz_adresEmail: "jan@example.com",
  },
};

export interface FakeRegonOptions {
  entities: FakeRegonEntity[];
  /** Force HTTP errors. */
  failWith?: number;
}

/** Fake fetch implementing the parts of BIR1.1 we use. Counts calls per operation. */
export function fakeRegon(opts: FakeRegonOptions) {
  const calls: string[] = [];
  const byKey = (k: string, v: string) => opts.entities.filter((e) => e.search[k] === v || (k === "Krs" && e.report.praw_numerWRejestrzeEwidencji === v));
  const fn = (async (_url: string | URL | Request, init?: RequestInit) => {
    const body = String(init?.body ?? "");
    const op = /IUslugaBIR(?:zewnPubl)?\/(\w+)<\/wsa:Action>/.exec(body)?.[1] ?? "?";
    calls.push(op);
    if (opts.failWith) return new Response("Service Unavailable", { status: opts.failWith });
    const text = (re: RegExp) => re.exec(body)?.[1] ?? "";
    let result = "";
    if (op === "Zaloguj") result = "fake-sid-0001";
    else if (op === "GetValue") result = text(/<ns:pNazwaParametru>(\w+)</) === "KomunikatKod" ? "4" : "";
    else if (op === "DaneSzukajPodmioty") {
      const m = /<dat:(\w+)>([^<]*)<\/dat:\1>/.exec(body)!;
      const key = { Nip: "Nip", Nipy: "Nip", Regon: "Regon", Regony9zn: "Regon", Krs: "Krs", Krsy: "Krs" }[m[1]]!;
      const rows = m[2].split(",").flatMap((v) => byKey(key, v).map((e) => e.search));
      result = rows.length ? dane(rows) : dane([{ ErrorCode: "4", ErrorMessagePl: "Nie znaleziono podmiotu dla podanych kryteriów wyszukiwania.", ErrorMessageEn: "No data found for the specified search criteria." }]);
    } else if (op === "DanePobierzPelnyRaport") {
      const regon = text(/<ns:pRegon>(\d+)</);
      const report = text(/<ns:pNazwaRaportu>(\w+)</);
      const e = opts.entities.find((x) => x.search.Regon === regon);
      const rows = !e ? [] : /Pkd$/.test(report) ? (e.pkd ?? []) : [e.report];
      result = rows.length ? dane(rows) : dane([{ ErrorCode: "4", ErrorMessagePl: "Nie znaleziono" }]);
    }
    return new Response(mtom(op, result), {
      status: 200,
      headers: { "Content-Type": 'multipart/related; type="application/xop+xml"; start="<http://tempuri.org/0>"; boundary="uuid:3a1b2c3d-0000-4000-8000-000000000001+id=1"; start-info="application/soap+xml"' },
    });
  }) as typeof fetch;
  return { fetch: fn, calls };
}

// ---------- KRS Open API ----------
export function fakeKrs(odpisy: Record<string, { register: "P" | "S"; body: unknown }>, opts: { failWith?: number } = {}) {
  const calls: string[] = [];
  const fn = (async (input: string | URL | Request) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url);
    calls.push(url.pathname + url.search);
    if (opts.failWith) return new Response("err", { status: opts.failWith });
    const krs = url.pathname.split("/").pop()!;
    const entry = odpisy[krs];
    if (!entry || entry.register !== url.searchParams.get("rejestr")) return new Response("", { status: 404 });
    return new Response(JSON.stringify(entry.body), { status: 200, headers: { "content-type": "application/json" } });
  }) as typeof fetch;
  return { fetch: fn, calls };
}

/** Routes upstream calls to the right fake by host. */
export function upstreams(regon: { fetch: typeof fetch }, krs: { fetch: typeof fetch }) {
  return (async (input: string | URL | Request, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (url.includes("api-krs.ms.gov.pl")) return krs.fetch(input, init);
    return regon.fetch(input, init);
  }) as typeof fetch;
}
