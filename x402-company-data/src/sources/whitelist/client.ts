// MF "Wykaz podatników VAT" (Biała Lista) REST API — keyless, GET only, JSON.
// Quirks: quotas are per egress IP (search: 100 requests/day x <=30 NIPs, check:
// 5000/day) and WL-191 blocks the IP until midnight; errors are HTTP 400 with
// {code, message} (or nested under `exception`); an unknown NIP is HTTP 200 with
// `subject: null`; requestDateTime is Warsaw local time "dd-MM-yyyy HH:mm:ss".

import { normalizeNip } from "../../lib/ids";
import { normalizeNrb } from "../../lib/nrb";
import { UpstreamError } from "../errors";

export const WL_ENDPOINTS = {
  prod: "https://wl-api.mf.gov.pl",
  test: "https://wl-test.mf.gov.pl",
} as const;

export const WL_SEARCH_MAX_NIPS = 30;

/** The request was malformed (bad NIP, bank account or date) — not an upstream outage. */
export class WhitelistInputError extends Error {
  constructor(
    message: string,
    readonly code?: string,
  ) {
    super(message);
    this.name = "WhitelistInputError";
  }
}

export interface WhitelistClientOptions {
  env?: "prod" | "test";
  baseUrl?: string;
  fetch?: typeof fetch;
  timeoutMs?: number;
}

export interface WlMeta {
  requestId: string | null;
  requestDateTime: string | null;
}
export interface WlSearchOne extends WlMeta {
  /** Raw `subject`; null when the NIP is not in the register. */
  subject: Record<string, any> | null;
}
export interface WlSearchMany extends WlMeta {
  subjects: Record<string, any>[];
}
export interface WlCheck extends WlMeta {
  accountAssigned: boolean;
}

/** WL-1xx codes that mean "your request is wrong"; the rest are server/quota problems. */
const UPSTREAM_CODES = new Set(["WL-100", "WL-190", "WL-191"]);

const str = (v: unknown) => (typeof v === "string" && v.trim() ? v : null);

export class WhitelistClient {
  private readonly fetchFn: typeof fetch;
  private readonly base: string;

  constructor(private readonly opts: WhitelistClientOptions = {}) {
    this.fetchFn = opts.fetch ?? ((...a) => fetch(...a));
    this.base = (opts.baseUrl ?? WL_ENDPOINTS[opts.env ?? "prod"]).replace(/\/+$/, "");
  }

  private async get(path: string, date: string): Promise<Record<string, any>> {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) throw new WhitelistInputError(`invalid date: ${date}`);
    let res: Response;
    try {
      res = await this.fetchFn(`${this.base}${path}?date=${date}`, {
        headers: { Accept: "application/json" },
        signal: AbortSignal.timeout(this.opts.timeoutMs ?? 8000),
      });
    } catch (err) {
      throw new UpstreamError("MF_WL", `request failed: ${(err as Error).message}`);
    }
    if (res.status >= 500) throw new UpstreamError("MF_WL", `HTTP ${res.status}`, res.status);
    if (res.status === 429) throw new UpstreamError("MF_WL", "rate limited", 429);

    let body: any;
    try {
      body = await res.json();
    } catch {
      throw new UpstreamError("MF_WL", `invalid JSON (HTTP ${res.status})`, res.status);
    }
    const err = body?.exception ?? (body?.code ? body : null);
    if (err || !res.ok) {
      const code = str(err?.code) ?? "";
      const message = str(err?.message) ?? `HTTP ${res.status}`;
      if (code === "WL-191") throw new UpstreamError("MF_WL", `WL-191 daily request limit exhausted: ${message}`, 429);
      if (/^WL-1\d\d$/.test(code) && !UPSTREAM_CODES.has(code)) throw new WhitelistInputError(`${code} ${message}`, code);
      throw new UpstreamError("MF_WL", `${code || "HTTP " + res.status} ${message}`.trim(), res.status);
    }
    return body?.result && typeof body.result === "object" ? body.result : {};
  }

  private meta(r: Record<string, any>): WlMeta {
    return { requestId: str(r.requestId), requestDateTime: str(r.requestDateTime) };
  }

  /** `date` is the day the status should be valid for (YYYY-MM-DD, Warsaw). */
  async searchNip(nip: string, date: string): Promise<WlSearchOne> {
    const n = normalizeNip(nip);
    if (!n) throw new WhitelistInputError(`invalid NIP: ${nip}`);
    const r = await this.get(`/api/search/nip/${n}`, date);
    const subject = r.subject && typeof r.subject === "object" ? r.subject : null;
    return { subject, ...this.meta(r) };
  }

  /** One request for up to 30 NIPs — counts as a single search against the daily quota. */
  async searchNips(nips: string[], date: string): Promise<WlSearchMany> {
    if (nips.length === 0 || nips.length > WL_SEARCH_MAX_NIPS) throw new WhitelistInputError(`expected 1-${WL_SEARCH_MAX_NIPS} NIPs, got ${nips.length}`);
    const norm = nips.map((n) => normalizeNip(n) ?? "");
    const bad = norm.indexOf("");
    if (bad >= 0) throw new WhitelistInputError(`invalid NIP: ${nips[bad]}`);
    const r = await this.get(`/api/search/nips/${norm.join(",")}`, date);
    const subjects = Array.isArray(r.subjects) ? r.subjects.filter((s: unknown) => s && typeof s === "object") : [];
    return { subjects, ...this.meta(r) };
  }

  /** Is this bank account on the white list for this NIP on `date`? (`check` quota.) */
  async checkAccount(nip: string, nrb: string, date: string): Promise<WlCheck> {
    const n = normalizeNip(nip);
    if (!n) throw new WhitelistInputError(`invalid NIP: ${nip}`);
    const account = normalizeNrb(nrb);
    if (!account) throw new WhitelistInputError("invalid bank account number (NRB)");
    const r = await this.get(`/api/check/nip/${n}/bank-account/${account}`, date);
    if (r.accountAssigned !== "TAK" && r.accountAssigned !== "NIE") throw new UpstreamError("MF_WL", "unexpected check response");
    return { accountAssigned: r.accountAssigned === "TAK", ...this.meta(r) };
  }
}
