// KRS Open API (Ministerstwo Sprawiedliwości) — keyless JSON API.
// We only use the public OdpisAktualny endpoint (personal data masked by the source).
// Never use the consent-only "Full API" or the CAPTCHA-protected eKRS search
// (art. 60a ustawy o KRS since 29.11.2025 — see docs/research/01-licencje-i-limity.md §1.4).

import { UpstreamError } from "../errors";

export const KRS_BASE = "https://api-krs.ms.gov.pl/api/krs";

export type KrsRegister = "P" | "S";

export interface KrsOdpis {
  register: KrsRegister;
  /** Raw OdpisAktualny JSON ("odpis" object). */
  odpis: Record<string, any>;
}

export interface KrsClientOptions {
  baseUrl?: string;
  fetch?: typeof fetch;
  timeoutMs?: number;
}

export class KrsClient {
  private readonly fetchFn: typeof fetch;
  private readonly base: string;

  constructor(private readonly opts: KrsClientOptions = {}) {
    this.fetchFn = opts.fetch ?? ((...a) => fetch(...a));
    this.base = (opts.baseUrl ?? KRS_BASE).replace(/\/+$/, "");
  }

  private async get(krs: string, register: KrsRegister): Promise<Record<string, any> | null> {
    let res: Response;
    try {
      res = await this.fetchFn(`${this.base}/OdpisAktualny/${krs}?rejestr=${register}&format=json`, {
        headers: { Accept: "application/json" },
        signal: AbortSignal.timeout(this.opts.timeoutMs ?? 8000),
      });
    } catch (err) {
      throw new UpstreamError("KRS", `request failed: ${(err as Error).message}`);
    }
    if (res.status === 404 || res.status === 204 || res.status === 400) return null;
    if (!res.ok) throw new UpstreamError("KRS", `HTTP ${res.status}`, res.status);
    let body: any;
    try {
      body = await res.json();
    } catch {
      throw new UpstreamError("KRS", "invalid JSON");
    }
    const odpis = body?.odpis;
    if (!odpis || typeof odpis !== "object") return null;
    // Guard against the API answering for a different number.
    const n = String(odpis.naglowekA?.numerKRS ?? "");
    if (n && n.padStart(10, "0") !== krs) return null;
    return odpis;
  }

  /**
   * Current extract for a KRS number. Entrepreneurs live in register P,
   * associations/foundations in S; a number exists in only one of them.
   */
  async odpisAktualny(krs: string, prefer: KrsRegister = "P"): Promise<KrsOdpis | null> {
    const order: KrsRegister[] = prefer === "P" ? ["P", "S"] : ["S", "P"];
    for (const register of order) {
      const odpis = await this.get(krs, register);
      if (odpis) return { register, odpis };
    }
    return null;
  }
}
