// CEIDG API v3 (Hurtownia Danych CEIDG) — JSON over HTTPS with a Bearer JWT.
// Quirks: limits are 50 req / 3 min and 1000 req / 60 min per token (429, sometimes
// 403, with Retry-After); maintenance windows answer with an HTML "Przerwa…" page;
// an unknown NIP gives 204/404 or an empty `firma` array. Every record describes a
// natural person — keep what we request and return to the minimum.

import { UpstreamError } from "../errors";

export const CEIDG_ENDPOINTS = {
  prod: "https://dane.biznes.gov.pl/api/ceidg/v3",
  test: "https://test-dane.biznes.gov.pl/api/ceidg/v3",
} as const;

/** Prod validates `limit` <= 25 even though the docs show 50. */
export const CEIDG_PAGE_MAX = 25;

export type CeidgRecord = Record<string, any>;

export interface CeidgClientOptions {
  token: string;
  env?: "prod" | "test";
  baseUrl?: string;
  fetch?: typeof fetch;
  timeoutMs?: number;
  /** Local guard in front of the upstream quota (Workers rate limiting binding). */
  limiter?: RateLimit;
}

export class CeidgClient {
  private readonly fetchFn: typeof fetch;
  private readonly base: string;

  constructor(private readonly opts: CeidgClientOptions) {
    this.fetchFn = opts.fetch ?? ((...a) => fetch(...a));
    this.base = (opts.baseUrl ?? CEIDG_ENDPOINTS[opts.env ?? "prod"]).replace(/\/+$/, "");
  }

  private async get(path: string, params: Record<string, string>): Promise<any | null> {
    if (this.opts.limiter) {
      const { success } = await this.opts.limiter.limit({ key: "ceidg" });
      if (!success) throw new UpstreamError("CEIDG", "local quota guard", 429);
    }
    const url = `${this.base}${path}?${new URLSearchParams(params)}`;
    let res: Response;
    try {
      res = await this.fetchFn(url, {
        headers: { Accept: "application/json", Authorization: `Bearer ${this.opts.token}` },
        signal: AbortSignal.timeout(this.opts.timeoutMs ?? 8000),
      });
    } catch (err) {
      throw new UpstreamError("CEIDG", `request failed: ${(err as Error).message}`);
    }
    if (res.status === 204 || res.status === 404) return null;
    const retryAfter = res.headers.get("retry-after");
    if (res.status === 429 || (res.status === 403 && retryAfter)) {
      throw new UpstreamError("CEIDG", `rate limited${retryAfter ? ` (retry after ${retryAfter}s)` : ""}`, 429);
    }
    if (res.status === 401 || res.status === 403) throw new UpstreamError("CEIDG", `authorization failed (HTTP ${res.status})`, res.status);

    const text = await res.text().catch(() => "");
    if (res.status === 400) {
      // A malformed identifier cannot exist in the register.
      if (/NIEPOPRAWNY_NUMER_(NIP|REGON)/.test(text)) return null;
      throw new UpstreamError("CEIDG", `HTTP 400 ${text.slice(0, 200)}`, 400);
    }
    if (!res.ok) throw new UpstreamError("CEIDG", `HTTP ${res.status}`, res.status);
    if (!text.trim()) return null;
    try {
      return JSON.parse(text);
    } catch {
      throw new UpstreamError("CEIDG", /przerwa/i.test(text) ? "maintenance page" : "invalid JSON", 503);
    }
  }

  private async firma(params: Record<string, string>): Promise<CeidgRecord | null> {
    const body = await this.get("/firma", params);
    const list = body?.firma;
    // `firma` is an array even for one hit; tolerate a lone object.
    const first = Array.isArray(list) ? list[0] : list;
    return first && typeof first === "object" ? first : null;
  }

  /** Full record by NIP, or null when CEIDG has no such business. */
  firmaByNip(nip: string): Promise<CeidgRecord | null> {
    return this.firma({ nip });
  }

  firmaByRegon(regon: string): Promise<CeidgRecord | null> {
    return this.firma({ regon });
  }

  /** Short records matching a business name (first page only). */
  async searchByName(name: string, opts: { city?: string; limit?: number } = {}): Promise<CeidgRecord[]> {
    const limit = Math.min(Math.max(Math.trunc(opts.limit ?? 10), 1), CEIDG_PAGE_MAX);
    const params: Record<string, string> = { nazwa: name, limit: String(limit), page: "0" };
    if (opts.city) params.miasto = opts.city;
    const list = (await this.get("/firmy", params))?.firmy;
    return Array.isArray(list) ? list.slice(0, limit) : [];
  }
}
