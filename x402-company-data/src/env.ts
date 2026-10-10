export interface Env {
  /** KV namespace for registry responses. */
  CACHE?: KVNamespace;
  /** Workers Rate Limiting bindings (optional; see wrangler.jsonc). */
  IP_LIMITER?: RateLimit;
  UPSTREAM_LIMITER?: RateLimit;

  /** Public origin, e.g. "https://api.example.com" — used in discovery documents. */
  PUBLIC_BASE_URL?: string;

  // --- x402 ---
  /** EVM address that receives USDC. Required: without it paid routes return 503. */
  PAY_TO?: string;
  /** CAIP-2 network id. "eip155:8453" = Base mainnet, "eip155:84532" = Base Sepolia. */
  NETWORK?: string;
  /** Facilitator base URL. CDP: https://api.cdp.coinbase.com/platform/v2/x402 */
  FACILITATOR_URL?: string;
  /** CDP API key (secret) — required only for the CDP facilitator. */
  CDP_API_KEY_ID?: string;
  CDP_API_KEY_SECRET?: string;

  // --- upstream registries ---
  /** GUS BIR1.1 user key (secret). */
  REGON_API_KEY?: string;
  /** "prod" | "test" — selects the BIR1.1 endpoint. */
  REGON_ENV?: string;
  /** Optional endpoint override (local smoke tests). */
  REGON_URL?: string;
  /** CEIDG API v3 JWT (secret). Optional — without it CEIDG enrichment is skipped. */
  CEIDG_API_TOKEN?: string;
  /** "prod" | "test" */
  CEIDG_ENV?: string;
}
