// EU VIES REST API — keyless. Quirks: transient failures (MS_UNAVAILABLE, TIMEOUT,
// *_MAX_CONCURRENT_REQ, ...) arrive as HTTP 200 + isValid:false, so only
// userError "INVALID" is a real negative; Poland and Germany return "---" instead
// of name/address; the number is passed without its country prefix, Greece is "EL".

import { UpstreamError } from "../errors";

export const VIES_BASE = "https://ec.europa.eu/taxation_customs/vies/rest-api";

export interface ViesResult {
  /** null: VIES could not answer (see `error`) — neither valid nor invalid. */
  valid: boolean | null;
  countryCode: string;
  vatNumber: string;
  name: string | null;
  address: string | null;
  requestDate: string | null;
  /** VIES error code when `valid` is null (e.g. "MS_UNAVAILABLE"); null for a definitive answer. */
  error: string | null;
}

export interface ViesClientOptions {
  baseUrl?: string;
  fetch?: typeof fetch;
  timeoutMs?: number;
}

/** Upper-cases, drops separators and a repeated country prefix; "GR" is VIES' "EL". */
export function normalizeVatInput(countryCode: string, vatNumber: string): { countryCode: string; vatNumber: string } {
  let cc = countryCode.trim().toUpperCase();
  if (cc === "GR") cc = "EL";
  let num = vatNumber.replace(/[\s.\-/]/g, "").toUpperCase();
  if (num.startsWith(cc) && num.length > cc.length + 4) num = num.slice(cc.length);
  return { countryCode: cc, vatNumber: num };
}

const text = (v: unknown): string | null => {
  if (typeof v !== "string") return null;
  const s = v.replace(/\s*\n\s*/g, ", ").trim();
  return s === "" || /^-+$/.test(s) ? null : s;
};

export class ViesClient {
  private readonly fetchFn: typeof fetch;
  private readonly base: string;

  constructor(private readonly opts: ViesClientOptions = {}) {
    this.fetchFn = opts.fetch ?? ((...a) => fetch(...a));
    this.base = (opts.baseUrl ?? VIES_BASE).replace(/\/+$/, "");
  }

  async check(countryCode: string, vatNumber: string): Promise<ViesResult> {
    const input = normalizeVatInput(countryCode, vatNumber);
    if (!/^[A-Z]{2}$/.test(input.countryCode) || !/^[A-Z0-9]{2,14}$/.test(input.vatNumber)) {
      return { valid: null, ...input, name: null, address: null, requestDate: null, error: "INVALID_INPUT" };
    }
    let res: Response;
    try {
      res = await this.fetchFn(`${this.base}/ms/${input.countryCode}/vat/${input.vatNumber}`, {
        headers: { Accept: "application/json" },
        signal: AbortSignal.timeout(this.opts.timeoutMs ?? 8000),
      });
    } catch (err) {
      throw new UpstreamError("VIES", `request failed: ${(err as Error).message}`);
    }
    if (res.status === 429 || res.status >= 500) throw new UpstreamError("VIES", `HTTP ${res.status}`, res.status);

    let body: any;
    try {
      body = await res.json();
    } catch {
      throw new UpstreamError("VIES", `invalid JSON (HTTP ${res.status})`, res.status);
    }
    const base = { ...input, name: null, address: null, requestDate: text(body?.requestDate) };

    // Error envelope: {actionSucceed:false, errorWrappers:[{error, message}]}
    const wrapped = body?.errorWrappers?.[0]?.error;
    if (wrapped || (!res.ok && body?.isValid === undefined && body?.valid === undefined)) {
      if (res.status === 404 || res.status === 400) return { ...base, valid: null, error: String(wrapped ?? "INVALID_INPUT") };
      throw new UpstreamError("VIES", `HTTP ${res.status} ${wrapped ?? ""}`.trim(), res.status);
    }

    const flag = body?.isValid ?? body?.valid;
    const userError = typeof body?.userError === "string" ? body.userError : null;
    if (flag === true) {
      return {
        ...base,
        valid: true,
        vatNumber: text(body.vatNumber) ?? input.vatNumber,
        name: text(body.name),
        address: text(body.address),
        error: null,
      };
    }
    if (flag === false && (userError === "INVALID" || (userError === null && body?.valid === false))) return { ...base, valid: false, error: null };
    return { ...base, valid: null, error: userError ?? "UNKNOWN" };
  }
}
