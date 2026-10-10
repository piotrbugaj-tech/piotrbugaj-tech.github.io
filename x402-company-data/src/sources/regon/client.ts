// GUS REGON — BIR1.1 ("Baza Internetowa REGON") SOAP client, fetch-only so it
// runs on Cloudflare Workers. The service speaks SOAP 1.2 + WS-Addressing and
// answers with an MTOM/XOP multipart body; the useful payload is an
// XML-escaped <root><dane>…</dane></root> string inside <…Result>.

import { XMLParser } from "fast-xml-parser";
import { UpstreamError } from "../errors";

export const REGON_ENDPOINTS = {
  prod: "https://wyszukiwarkaregon.stat.gov.pl/wsBIR/UslugaBIRzewnPubl.svc",
  test: "https://wyszukiwarkaregontest.stat.gov.pl/wsBIR/UslugaBIRzewnPubl.svc",
} as const;

/** Public key for the GUS test environment (published in the BIR1.1 docs). */
export const REGON_TEST_KEY = "abcde12345abcde12345";

const NS = "http://CIS/BIR/PUBL/2014/07";
const NS_DATA = "http://CIS/BIR/PUBL/2014/07/DataContract";
const ACTION_PUBL = "http://CIS/BIR/PUBL/2014/07/IUslugaBIRzewnPubl/";
const ACTION_GETVALUE = "http://CIS/BIR/2014/07/IUslugaBIR/GetValue";

/** Session id lifetime is 60 min on the GUS side; renew a bit earlier. */
const SESSION_TTL_MS = 50 * 60 * 1000;
/** BIR1.1 accepts at most 20 identifiers per DaneSzukajPodmioty call. */
export const REGON_BATCH_MAX = 20;

export type RegonRecord = Record<string, string>;
export type SearchParam = "Nip" | "Regon" | "Krs" | "Nipy" | "Regony9zn" | "Regony14zn" | "Krsy";

export type RegonReport =
  | "BIR11OsPrawna"
  | "BIR11OsPrawnaPkd"
  | "BIR11OsFizycznaDaneOgolne"
  | "BIR11OsFizycznaDzialalnoscCeidg"
  | "BIR11OsFizycznaDzialalnoscRolnicza"
  | "BIR11OsFizycznaDzialalnoscPozostala"
  | "BIR11OsFizycznaDzialalnoscSkreslonaDo20141108"
  | "BIR11OsFizycznaPkd";

const xml = new XMLParser({
  ignoreAttributes: true,
  parseTagValue: false, // keep identifiers as strings (leading zeros!)
  trimValues: true,
  isArray: (name) => name === "dane",
});

const ENTITIES: Record<string, string> = { lt: "<", gt: ">", amp: "&", quot: '"', apos: "'" };

export function decodeXmlEntities(s: string): string {
  return s.replace(/&(#x[0-9a-fA-F]+|#\d+|[a-z]+);/g, (m, e: string) => {
    if (e[0] === "#") {
      const code = e[1] === "x" ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10);
      return Number.isFinite(code) ? String.fromCodePoint(code) : m;
    }
    return ENTITIES[e] ?? m;
  });
}

/** Pulls the text of <OperationResult> out of a (possibly multipart) SOAP response. */
export function extractResult(body: string, operation: string): string | null {
  const re = new RegExp(`<(?:[\\w-]+:)?${operation}Result(?:\\s[^>]*)?(?:/>|>([\\s\\S]*?)</(?:[\\w-]+:)?${operation}Result>)`);
  const m = re.exec(body);
  if (!m) return null;
  return decodeXmlEntities(m[1] ?? "").trim();
}

/** Parses the inner <root><dane>…</dane></root> document into flat records. */
export function parseDane(inner: string): RegonRecord[] {
  if (!inner) return [];
  const doc = xml.parse(inner) as { root?: { dane?: Array<Record<string, unknown>> } };
  const rows = doc.root?.dane ?? [];
  return rows.map((row) => {
    const out: RegonRecord = {};
    for (const [k, v] of Object.entries(row)) out[k] = v === undefined || v === null ? "" : String(v);
    return out;
  });
}

function envelope(action: string, to: string, body: string): string {
  return (
    `<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" xmlns:ns="${NS}" xmlns:dat="${NS_DATA}">` +
    `<soap:Header xmlns:wsa="http://www.w3.org/2005/08/addressing">` +
    `<wsa:To>${to}</wsa:To><wsa:Action>${action}</wsa:Action>` +
    `</soap:Header><soap:Body>${body}</soap:Body></soap:Envelope>`
  );
}

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

export interface RegonClientOptions {
  apiKey: string;
  env?: "prod" | "test";
  /** Overrides the endpoint (local smoke tests, proxies). */
  url?: string;
  fetch?: typeof fetch;
  timeoutMs?: number;
}

/** "not found" is a normal answer, not an error. */
export class RegonNotFound extends Error {}

export class RegonClient {
  private readonly url: string;
  private readonly fetchFn: typeof fetch;
  private sid: string | null = null;
  private sidAt = 0;

  constructor(private readonly opts: RegonClientOptions) {
    this.url = opts.url ?? REGON_ENDPOINTS[opts.env ?? "prod"];
    this.fetchFn = opts.fetch ?? ((...a) => fetch(...a));
  }

  private async call(action: string, body: string, sid?: string): Promise<string> {
    const headers: Record<string, string> = { "Content-Type": "application/soap+xml; charset=utf-8" };
    if (sid) headers.sid = sid;
    let res: Response;
    try {
      res = await this.fetchFn(this.url, {
        method: "POST",
        headers,
        body: envelope(action, this.url, body),
        signal: AbortSignal.timeout(this.opts.timeoutMs ?? 8000),
      });
    } catch (err) {
      throw new UpstreamError("REGON", `request failed: ${(err as Error).message}`);
    }
    const text = await res.text();
    if (!res.ok) throw new UpstreamError("REGON", `HTTP ${res.status}`, res.status);
    return text;
  }

  private async login(): Promise<string> {
    const text = await this.call(
      ACTION_PUBL + "Zaloguj",
      `<ns:Zaloguj><ns:pKluczUzytkownika>${esc(this.opts.apiKey)}</ns:pKluczUzytkownika></ns:Zaloguj>`,
    );
    const sid = extractResult(text, "Zaloguj");
    if (!sid) throw new UpstreamError("REGON", "login rejected (invalid API key?)");
    this.sid = sid;
    this.sidAt = Date.now();
    return sid;
  }

  private async session(): Promise<string> {
    if (this.sid && Date.now() - this.sidAt < SESSION_TTL_MS) return this.sid;
    return this.login();
  }

  async getValue(param: "KomunikatKod" | "KomunikatTresc" | "StatusSesji" | "StatusUslugi" | "StanDanych"): Promise<string | null> {
    const sid = await this.session();
    const text = await this.call(
      ACTION_GETVALUE,
      `<ns:GetValue xmlns:ns="http://CIS/BIR/2014/07"><ns:pNazwaParametru>${param}</ns:pNazwaParametru></ns:GetValue>`,
      sid,
    );
    return extractResult(text, "GetValue");
  }

  /**
   * Runs an operation that returns <root><dane>. Retries once with a fresh
   * session when GUS reports an expired session (KomunikatKod 7).
   */
  private async dataCall(op: string, body: string): Promise<RegonRecord[]> {
    for (let attempt = 0; attempt < 2; attempt++) {
      const sid = await this.session();
      const text = await this.call(ACTION_PUBL + op, body, sid);
      const inner = extractResult(text, op);
      if (inner) {
        const rows = parseDane(inner);
        const err = rows[0]?.ErrorCode;
        if (err === undefined || err === "") return rows;
        if (err === "4") throw new RegonNotFound(rows[0].ErrorMessagePl || "not found");
        if (err === "7" && attempt === 0) {
          this.sid = null;
          continue;
        }
        throw new UpstreamError("REGON", `ErrorCode ${err}: ${rows[0].ErrorMessagePl ?? rows[0].ErrorMessageEn ?? ""}`);
      }
      // Empty result: ask the service why.
      const code = await this.getValue("KomunikatKod");
      if (code === "4") throw new RegonNotFound("not found");
      if (code === "7" && attempt === 0) {
        this.sid = null;
        continue;
      }
      const msg = await this.getValue("KomunikatTresc").catch(() => null);
      throw new UpstreamError("REGON", `empty result, KomunikatKod=${code ?? "?"} ${msg ?? ""}`.trim());
    }
    throw new UpstreamError("REGON", "session could not be established");
  }

  /** DaneSzukajPodmioty — basic data for one id, or up to 20 ids (Nipy/Regony9zn/Krsy). */
  async search(param: SearchParam, value: string | string[]): Promise<RegonRecord[]> {
    const v = Array.isArray(value) ? value.join(",") : value;
    return this.dataCall(
      "DaneSzukajPodmioty",
      `<ns:DaneSzukajPodmioty><ns:pParametryWyszukiwania><dat:${param}>${esc(v)}</dat:${param}></ns:pParametryWyszukiwania></ns:DaneSzukajPodmioty>`,
    );
  }

  /** DanePobierzPelnyRaport — full report for a REGON. */
  async report(regon: string, report: RegonReport): Promise<RegonRecord[]> {
    return this.dataCall(
      "DanePobierzPelnyRaport",
      `<ns:DanePobierzPelnyRaport><ns:pRegon>${esc(regon)}</ns:pRegon><ns:pNazwaRaportu>${report}</ns:pNazwaRaportu></ns:DanePobierzPelnyRaport>`,
    );
  }
}
