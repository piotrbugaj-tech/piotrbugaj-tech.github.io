# 03 - x402 ecosystem and discovery: what to build and where to register (as of 2026-10-10)

> **Status:** research for implementing a paid API (Polish company data) on Cloudflare Workers with Hono. Not financial or legal advice.
>
> **Evidence legend** (same convention as `01-licencje-i-limity.md`):
> - **[V-code]** read in the published npm package (`.d.ts` / `.mjs`) or in a cloned GitHub repo (x402-foundation/x402 @ `f8f8330`, 2026-10-10; cloudflare/templates, cloudflare/agents, cloudflare-docs, Merit-Systems/x402scan, ryanthegentry/402index, A2A, a2a-x402, tanod-labs/x402-price-index).
> - **[V-run]** executed by me: bundled with `wrangler 4.149.0`, ran in local `workerd` (the Workers runtime), called with a real `@x402/fetch` client against a mock facilitator.
> - **[S]** secondary: WebSearch summary of a web page I could not open directly (this sandbox cannot reach x402.org, coinbase.com, cloudflare docs, dev.to, huggingface; WebFetch has no DNS for them). Re-check before relying on it.
> - **[I]** my inference.

---

## 0. TL;DR (decisions)

1. **Use `@x402/hono` 2.28.0 inside our own Worker** (not the Cloudflare `x402-proxy-template`, not legacy `x402-hono`). It is v2 protocol, CAIP-2 networks, Bazaar extension support, dynamic pricing. **[V-code][V-run]**
2. **Mainnet facilitator: Coinbase CDP** (`https://api.cdp.coinbase.com/platform/v2/x402`) because the CDP Bazaar (and from it agentic.market, x402scan, 402index) only indexes services whose payments settle **through CDP** with `extensions.bazaar` + `resource` in the payload. Auth = CDP Secret API key -> JWT; **`@coinbase/x402` 2.1.0 `createFacilitatorConfig()` works in Workers (jose + WebCrypto)**, tested with an Ed25519 key. **[V-run]**
3. **Testnet facilitator: `https://x402.org/facilitator`** (Base Sepolia `eip155:84532`, no key, testnet only by documentation and by its source in the repo). I could not call it live from here. **[V-code][S]**
4. **Pricing:** single call `$0.01` (market median for company enrichment is `$0.027`, p25 `$0.01`, p75 `$0.10`; Tanod snapshot 2026-10-09). Batch endpoint with price = n x unit via `price: (ctx) => ...` - **tested**: 1 item -> `5000` atomic USDC, 3 items -> `15000`. **[V-run]**
5. **Discovery is not one thing.** Do all of: (a) CDP Bazaar (automatic after first settled CDP payment), (b) `/openapi.json` with `x-payment-info` (the format x402scan and the agentcash ecosystem now treat as canonical), (c) x402scan "Add Server", (d) 402index `POST /api/v1/register`, (e) x402-list.com submit, (f) llms.txt, (g) optional MCP Registry / A2A card. Checklist in section 10.
6. **Gotchas found by running the code** (details in section 1.5): per-request construction re-fetches `/supported` every request (cache per isolate); `resource.url` includes the query string unless you set `resource`; Ajv inside `@x402/extensions` cannot compile schemas in workerd and logs a harmless warning; server only accepts `PAYMENT-SIGNATURE` (v2), not legacy `X-PAYMENT`; CDP Bazaar `pathParams` handling is reported buggy, so prefer query-string or POST-body inputs over `/:param` routes.

---

## 1. SDK packages and versions

### 1.1 Versions on npm (queried 2026-10-10) **[V]**

| Package | Version | Last publish | Role / verdict |
|---|---|---|---|
| `@x402/core` | **2.28.0** | 2026-09-29 | Protocol types, `x402ResourceServer`, `HTTPFacilitatorClient`, `x402Client`. Subpaths `/server`, `/client`, `/http`, `/types`, `/facilitator`. Dep: `zod ^3.24.2` only |
| `@x402/hono` | **2.28.0** | 2026-09-29 | Hono middleware. Deps: `@x402/core ~2.28.0`, `@x402/extensions ~2.28.0`. Peer: `hono ^4`, optional `@x402/paywall` |
| `@x402/express` | 2.28.0 | 2026-09-29 | Express equivalent (not needed) |
| `@x402/evm` | **2.28.0** | 2026-09-29 | `ExactEvmScheme` (server `/exact/server`, client `/exact/client`), `UptoEvmScheme`, batch-settlement. Deps: `viem ^2.48.11`, `@x402/core ~2.28.0` |
| `@x402/fetch` | **2.28.0** | 2026-09-29 | Client: `wrapFetchWithPayment`, `wrapFetchWithPaymentFromConfig` |
| `@x402/extensions` | **2.28.0** | 2026-09-29 | Subpaths: `/bazaar`, `/sign-in-with-x`, `/offer-receipt`, `/payment-identifier`, `/builder-code`. Deps incl. `ajv`, `jose`, `viem`, `@noble/curves` |
| `@x402/svm`, `@x402/paywall`, `@x402/next`, `@x402/axios`, `@x402/mcp` | 2.28.0 | 2026-09-29 | Solana, browser paywall UI, Next, Axios, MCP wrapper |
| `@coinbase/x402` | **2.1.0** | 2025-12-23 | CDP facilitator config + JWT auth helper. Deps: `@coinbase/cdp-sdk ^1.29.0` (installed 1.58.0), `@x402/core ^2.0.0`, `viem`, `zod` |
| `x402` (legacy v1) | 1.2.0 | 2026-04-16 | v1 protocol, `X-PAYMENT` header, string networks (`base`). Legacy; not deprecated on npm, but no longer the main line |
| `x402-hono` (legacy v1) | 1.2.0 | 2026-04-16 | Legacy. **Still what Cloudflare's docs and `x402-proxy-template` use** |
| `agents` (Cloudflare) | 0.28.0 | - | `agents/x402` (`withX402`, `paidTool`, `withX402Client`) |

Release cadence of `@x402/*` is roughly weekly (2.22.0 on 2026-08-11 to 2.28.0 on 2026-09-29). `@x402/hono` pins `@x402/core` with `~` (same minor), so **pin all `@x402/*` to the same exact version** and upgrade together. Source repo moved: it is now **github.com/x402-foundation/x402** (formerly coinbase/x402; Technical Charter dated 2026-03-31; TSC = Coinbase, Cloudflare, Stripe). **[V-code]**

Other tools used for testing: hono 4.13.13, viem 2.57.4, jose 6.2.12, ajv 8.20.0, wrangler 4.149.0.

### 1.2 Does `@x402/hono` run on Cloudflare Workers? Yes. **[V-run]**

- Bundled `hono + @x402/hono + @x402/core + @x402/evm + @x402/extensions + @coinbase/x402` with `wrangler deploy --dry-run`: **734 KiB / 142 KiB gzip**, zero `node:` imports. The only bare built-in is `import { domainToASCII } from "url"` in `@x402/extensions` (used to validate `iconUrl`); wrangler/workerd resolved it and the Worker ran.
- Ran in local `workerd` **without** `nodejs_compat`, and served 402 and paid 200 responses end to end. I still recommend `"compatibility_flags": ["nodejs_compat"]`: Cloudflare's own x402 examples use it (`cloudflare/agents/examples/x402/wrangler.jsonc`, compat date `2026-06-11`) and `@coinbase/cdp-sdk/auth` calls `Buffer`. **[V-code]**
- Cloudflare's own example `cloudflare/agents/examples/x402/src/server.ts` uses exactly `@x402/hono ^2.17` + `HTTPFacilitatorClient` + `registerExactEvmScheme` inside a Worker. **[V-code]**
- No Node-only runtime dependency found in the dependency tree. The only runtime wart is Ajv (see 1.5).

### 1.3 Protocol version and headers **[V-code][V-run]**

v2 is the default and, on the server side, the only protocol accepted:

| Direction | Header | Content |
|---|---|---|
| Server 402 | `PAYMENT-REQUIRED` | base64 JSON `{x402Version:2, error, resource{url,description,mimeType,serviceName,tags,iconUrl}, accepts[], extensions{bazaar{info,schema,routeTemplate?}}}`; JSON body is just `{}` |
| Client retry | `PAYMENT-SIGNATURE` | base64 JSON payment payload (`@x402/core` `extractPayment` reads only this header; legacy `X-PAYMENT` is sent by the client only when `x402Version` is 1) |
| Server 200 | `PAYMENT-RESPONSE` | base64 JSON `{success, payer, transaction, network}` (decode with `decodePaymentResponseHeader` from `@x402/fetch`) |
| Facilitator -> server | `EXTENSION-RESPONSES` | base64 JSON, e.g. `{"bazaar":{"status":"success"}}`; internal, never forwarded to the buyer |

Consequence: v1-only clients (old `x402-fetch` 1.x) cannot pay our API. Current clients (`@x402/fetch`, agentcash, x402scan wallet) speak v2. **[I]**

Observed 402 for `GET /v1/company` on Base Sepolia: `amount:"10000"` (= $0.01, USDC has 6 decimals), `asset:0x036CbD53842c5426634e7929541eC2318f3dCF7e` (USDC Base Sepolia), `extra:{name:"USDC",version:"2"}`, `maxTimeoutSeconds` as configured. Base mainnet USDC is `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` (from `docs/extensions/bazaar.mdx`). **[V-run][V-code]**

### 1.4 Exact imports and signatures (verified against `.d.ts`)

```ts
import { paymentMiddleware, x402ResourceServer } from "@x402/hono";
// also exported by @x402/hono: paymentMiddlewareFromHTTPServer, paymentMiddlewareFromConfig,
//   setSettlementOverrides, x402HTTPResourceServer, HonoAdapter, RouteConfigurationError, ...
import { HTTPFacilitatorClient } from "@x402/core/server";
import type { HTTPRequestContext, RoutesConfig } from "@x402/core/server";
import type { Network } from "@x402/core/types";
import { registerExactEvmScheme } from "@x402/evm/exact/server";   // or: new ExactEvmScheme() from the same path
import { declareDiscoveryExtension } from "@x402/extensions/bazaar";
import { createFacilitatorConfig } from "@coinbase/x402";
```

```ts
// @x402/hono (index.d.mts)
declare function paymentMiddleware(
  routes: RoutesConfig, server: x402ResourceServer,
  paywallConfig?: PaywallConfig, paywall?: PaywallProvider,
  syncFacilitatorOnStart?: boolean,            // default true: calls facilitator /supported on first protected request
): MiddlewareHandler;

// @x402/core/server
class HTTPFacilitatorClient { constructor(config?: FacilitatorConfig) }   // default url "https://x402.org/facilitator"
interface FacilitatorConfig {
  url?: string;
  timeoutMs?: number;                           // default 90_000
  createAuthHeaders?: () => Promise<{ verify?: Record<string,string>; settle?: ...; supported?: ...; bazaar?: ... }>; // keyed by path, NOT flat
}

// @x402/evm/exact/server
function registerExactEvmScheme(server: x402ResourceServer, config?: { networks?: Network[] }): x402ResourceServer; // default wildcard eip155:*
// chaining alternative: new x402ResourceServer(fac).register("eip155:8453", new ExactEvmScheme())

// @x402/core/server - route config
type RoutesConfig = Record<string, RouteConfig> | RouteConfig;   // key = "GET /path" | "POST /path" (Hono path patterns, e.g. "/v1/x/:id", "/api/*")
interface RouteConfig {
  accepts: PaymentOption | PaymentOption[];
  resource?: string;            // override canonical resource URL (otherwise full request URL incl. query string!)
  description?: string;         // CDP rejects verify/settle if > 500 chars [S]
  mimeType?: string;
  serviceName?: string;         // bazaar: printable ASCII, <= 32 chars
  tags?: string[];              // bazaar: max 5, each printable ASCII <= 32 chars
  iconUrl?: string;             // bazaar: absolute http(s) URL, <= 2048, not an IP/localhost
  unpaidResponseBody?: (ctx) => { contentType: string; body: unknown } | Promise<...>;
  settlementFailedResponseBody?: ...;
  customPaywallHtml?: string;
  extensions?: Record<string, unknown>;   // put declareDiscoveryExtension(...) here (key "bazaar")
}
interface PaymentOption {
  scheme: string;               // "exact" (or "upto")
  network: Network;             // CAIP-2: "eip155:8453" (Base) | "eip155:84532" (Base Sepolia)
  payTo: string | ((ctx: HTTPRequestContext) => string | Promise<string>);
  price: Price | ((ctx: HTTPRequestContext) => Price | Promise<Price>);   // "$0.01" | 0.01 | {asset, amount, extra?}
  maxTimeoutSeconds?: number;
  extra?: Record<string, unknown>;
}

// @x402/extensions/bazaar
declare function declareDiscoveryExtension(config: DeclareDiscoveryExtensionInput): Record<string, DiscoveryExtension>; // returns { bazaar: {info, schema} }
//  GET/HEAD/DELETE: { input?, inputSchema?, pathParams?, pathParamsSchema?, output?: {example?, schema?} }
//  POST/PUT/PATCH : { bodyType: "json"|"form-data"|"text", input?, inputSchema?, pathParams?, pathParamsSchema?, output? }
//  MCP tool       : { toolName, description?, transport?, inputSchema, example?, output? }
//  NOTE: "method" is NOT passed; it is injected from the route key ("GET /x") by bazaarResourceServerExtension.
```

`@x402/hono` registers `bazaarResourceServerExtension` itself when any route has `extensions.bazaar`, and validates route extensions at startup (`validateBazaarRouteExtensions`, warns, never throws). **[V-code]**

### 1.5 Gotchas found while running it **[V-run]**

1. **Cache the middleware per isolate.** Workers only expose `env` at request time, so the natural code builds `HTTPFacilitatorClient`/`x402ResourceServer` per request. That made the SDK call facilitator `GET /supported` on every request (5 calls for 4 requests in my test). Build once lazily (`let cached`) as in section 9.
2. **`resource.url` defaults to the full request URL including the query string** (`.../v1/company?nip=5252248481`). For query-driven GET endpoints this would create one catalog URL per query. Fix: set `resource: "<PUBLIC_ORIGIN>/v1/company"` in the route config. Verified that the corrected value flows into the payload sent to the facilitator. Also guarantees `https://` (CDP validator rejects non-https `resource`, see section 6.1).
3. **Ajv cannot run in workerd.** On startup the SDK logs `x402: Route "GET /v1/company" has an invalid bazaar extension: Schema validation failed: Code generation from strings disallowed for this context` (plus an `Error compiling schema` line). It is a `console.warn`-level check only; the 402 response still contains the full `extensions.bazaar` object and the facilitator receives it (verified in the mock facilitator log: `ext: ['bazaar']`, `resource` present, `routeTemplate` present for path routes). Ignore or filter this log. Validation that matters (CDP) happens server-side at the facilitator.
4. **Client echoes what the server declares.** `@x402/fetch` sends `extensions.bazaar` and `resource` back inside `PaymentPayload`; the facilitator reads them. If a custom client drops them, nothing gets indexed (spec: "If the extension is omitted, discovery cataloging will not occur"). CDP maintainers confirmed the same: both `paymentPayload.extensions.bazaar` and `paymentPayload.resource` are required (cdp-sdk issue #824). **[V-code][S]**
5. **Unpaid probes must reach the 402.** The paywall middleware runs before our handlers, so a missing/invalid `nip` query still returns 402 (good - Bazaar and x402scan probe with empty/synthetic input). Keep input validation in the handler, behind the paywall. Do not return 200 "free trial" on protected paths: the CDP validator fails with `returns_402: expected 402, actual 200`. **[S]**

---

## 2. Dynamic pricing (price as a function of the request) **[V-code][V-run]**

`PaymentOption.price` accepts `Price | ((ctx: HTTPRequestContext) => Price | Promise<Price>)`. The context gives `ctx.adapter` with `getHeader`, `getMethod`, `getPath`, `getUrl`, `getQueryParams()`, `getQueryParam(name)`, `getBody()` (Hono adapter: `c.req.json()`, returns `undefined` on parse error; Hono caches the parsed body so the handler can call `c.req.json()` again). `payTo` can be dynamic too.

```ts
"POST /v1/batch": {
  accepts: {
    scheme: "exact", network, payTo: env.PAY_TO,
    price: async (ctx) => {
      const body = (await ctx.adapter.getBody?.()) as { nips?: unknown[] } | undefined;
      const n = Math.min(Math.max(body?.nips?.length ?? 1, 1), 100);
      return `$${(n * 0.005).toFixed(4)}`;          // 1 -> "5000", 3 -> "15000" atomic USDC (verified)
    },
  },
  ...
}
```

Notes:
- Requirements are rebuilt on every request from the body, so a client that signs for 3 items and then replays with 50 items fails amount matching (by construction; I did not test the tampered replay).
- **The handler must still enforce the cap** (e.g. reject `nips.length > 100` with 400 *before* doing work). The price function clamps; the handler must not process more than what was priced.
- A 402 probe with no/empty body prices as 1 item - that is what Bazaar/x402scan will see as the listed price. Document "$0.005 per item" in `description` and in OpenAPI (`x-payment-info.price.mode: "dynamic"` with `min`/`max`).
- **Alternative: `upto` scheme** (buyer authorizes a max, you settle the actual amount): `new UptoEvmScheme()` from `@x402/evm/upto/server`, route `scheme: "upto"`, and in the handler `setSettlementOverrides(c, { amount: "$0.03" })` (also accepts atomic units or `"50%"`), exported by `@x402/hono`. Fewer clients support `upto` than `exact`; CDP lists `exact`, `upto`, `batch-settlement` for Base. **[V-code][S]** Start with `exact`.

---

## 3. Facilitators

### 3.1 Coinbase CDP facilitator

- **URL:** `https://api.cdp.coinbase.com/platform/v2/x402` (endpoints `/verify`, `/settle`, `/supported`, `/discovery/resources`, `/discovery/search`, `/discovery/merchant?payTo=`, `/validate`). Appears in `x402-foundation/x402/docs/getting-started/quickstart-for-sellers.mdx` and in `@coinbase/x402` source. **[V-code]**
- **Auth:** CDP **Secret API key** (key id + secret from the CDP portal) -> per-request ES256/EdDSA JWT (`iss:"cdp"`, `sub:<keyId>`, `uris:["POST api.cdp.coinbase.com/platform/v2/x402/settle"]`, 120 s expiry, random nonce). `/verify` and `/settle` need it; `/supported` is signed too when keys are given; discovery `list` needs none. **[V-code][V-run]**
- **Helper:** `createFacilitatorConfig(apiKeyId?, apiKeySecret?)` returns `{ url, createAuthHeaders }` and plugs straight into `new HTTPFacilitatorClient(...)`. Exports: `createFacilitatorConfig`, `facilitator` (reads `process.env.CDP_API_KEY_ID/SECRET`), `createCdpAuthHeaders`, `createAuthHeader`, `createCorrelationHeader`. **[V-code]**
- **Runs in Workers: yes.** `generateJwt` (from `@coinbase/cdp-sdk/auth`) uses `jose` + `uncrypto` + `Buffer`; bundle is ~39 KiB; in workerd with an Ed25519 secret (64-byte base64, the CDP default format) it produced `alg:EdDSA`, `kid:<keyId>`, `uris:["POST api.cdp.coinbase.com/platform/v2/x402/settle"]`. Pass credentials **explicitly from `env`** (do not rely on `process.env`). The ECDSA (PEM, `importPKCS8`) path is in the same function; I did not execute it. **[V-run]**
- **Fees [S, conflicting]:** CDP docs (facilitator page, core-concepts page): first **1,000 onchain facilitator transactions per month free, then $0.001 per onchain transaction**; verification free; failed settle (4xx/5xx) not counted. An older FAQ table still says "fee-free on Base". Plan for the $0.001 model: at a $0.01 price that is 10% after the free tier. Confirm in the CDP portal pricing page before launch. Buyer pays no gas for `exact` (EIP-3009); the facilitator submits the tx.
- **Networks:** official docs list Base `eip155:8453` and Base Sepolia `eip155:84532` (exact, upto, batch-settlement); FAQ adds Polygon, Arbitrum, World, Solana mainnet (Solana exact only). Query `GET /supported` (with JWT) to confirm. **[S]**
- Compliance: CDP applies KYT/OFAC screening to every transaction (x402 docs facilitator table). **[V-code]**

### 3.2 `https://x402.org/facilitator` (public testnet)

Per the repo docs it supports only testnets: `eip155:84532`, Solana devnet, Stellar testnet, Aptos testnet, Hedera testnet, XRPL testnet; "recommended for testing and development... does not support Base mainnet". Its implementation lives in the repo (`typescript/site/app/facilitator/{verify,settle,supported}`). It is the SDK default URL. Cloudflare's docs say it is "operated by Coinbase". I could not reach it from this sandbox (proxy 403), so "still live" is documented, not probed. **[V-code]**

### 3.3 Cloudflare and other facilitators

- **There is no Cloudflare-operated general x402 facilitator** in the x402 docs facilitator list, in the Cloudflare x402 docs (they use `x402.org/facilitator`), or in x402scan's facilitator registry. What Cloudflare has: (a) TSC seat in the x402 Foundation (co-founded with Coinbase, announced 2025-09-23 **[S]**); (b) a `batch-settlement` scheme on network `cloudflare:402` using RFC 9421 HTTP message signatures for **Pay Per Crawl** (merchant-of-record, deferred billing; `specs/schemes/batch-settlement/scheme_batch_settlement_cloudflare.md`) - this is for web crawlers paying publishers, not for our API. **[V-code]**
- Other production facilitators listed in `docs/dev-tools/facilitators.md` (all **[V-code]** as listed; pricing claims **[S]**):
  - **PayAI** `https://facilitator.payai.network`: "no API keys"; multi-network incl. Base/Solana/Polygon/Arbitrum; cost-plus pricing effective 2026-09-21: network gas x1.30 in credits (Base 2.12 credits, credit = $0.001 -> about $0.0021/settlement), **1,000 free credits per receiving wallet (lifetime)**, testnets free. Has its own `/discovery/resources` (Tanod indexes 17,763 PayAI listings on 2026-10-09). x402scan reads it. Free tier is lifetime, CDP's is monthly.
  - **Dexter** (`dexter.cash/facilitator`): "free public facilitator, no fees, no account" (EVM + Solana). **Mogami** (`facilitator.mogami.tech`): "free, developer-focused facilitator for Base". **Corbits**, **Meridian**, **Solvador**, **Fireblocks**, **Polygon**, **Celo** etc. also listed. Bazaar indexing for these: not verified.
  - x402scan tracks settlement addresses of ~34 facilitators (coinbase, payai, dexter, corbits, daydreams, x402rs, thirdweb, openx402, ...), so volume through them appears in its dashboards. **[V-code]**
- **Trade-off:** CDP = the one catalog that matters most (agentic.market + Bazaar) and compliance screening; PayAI/Dexter = lower or zero fees but a smaller audience. You can use CDP for the mainnet `accepts` and still list a second `accepts` entry (e.g. Solana via another facilitator) later: `accepts` is an array and `x402ResourceServer` accepts multiple facilitator clients. **[I]**

---

## 4. Cloudflare-specific options

### 4.1 `cloudflare/templates` -> `x402-proxy-template` **[V-code]**

- Repo: `github.com/cloudflare/templates/tree/main/x402-proxy-template` (a directory in the monorepo, not a standalone repo; last commit in clone 2026-10-07).
- What it is: a Worker that sits in front of an origin. `PROTECTED_PATTERNS` routes return 402; after one payment it issues an **HMAC-SHA256 JWT cookie valid 1 hour** so the same browser/agent passes free for an hour (stateless; needs `JWT_SECRET` secret). Forwards to origin by DNS (route on your zone), `ORIGIN_URL`, or a service binding `ORIGIN_SERVICE`. Optional Bot Management filters (Enterprise only).
- Config (`wrangler.jsonc` `vars`): `PAY_TO`, `NETWORK` (`"base-sepolia"` / `"base"` - **v1 names**), `PROTECTED_PATTERNS: [{pattern:"/premium/*", price:"$0.01", description}]`, optional `ORIGIN_URL`, `FACILITATOR_URL` (default in template: `https://x402.org/facilitator`).
- **Built on legacy `x402-hono 1.0.0` + `x402 1.0.1` + `@coinbase/x402 2.0.0`** (v1 protocol, `X-PAYMENT`, no Bazaar extension, no per-request dynamic price, no `declareDiscoveryExtension`). Cloudflare's docs page "Charge for HTTP content" also still shows `x402-hono`. The Cloudflare *agents* examples, however, already use `@x402/hono ^2.17`.
- **Verdict: (b) `@x402/hono` in our own Worker.** The proxy's per-hour cookie model is wrong for per-call API revenue and it cannot emit Bazaar metadata, which is the main discovery channel. Use the template only as a reference for deploy shape and `wrangler.jsonc` vars.

### 4.2 Agents SDK / MCP paid tools **[V-code]**

- `agents/x402` (package `agents` 0.28.0): `withX402(new McpServer(...), { network: "eip155:84532" | "eip155:8453", recipient, facilitator: {url} })` then `server.paidTool(name, description, priceUsd, zodShape, annotations, handler)`; client side `withX402Client(mcpClient, {...})`. Examples: `cloudflare/agents/examples/x402-mcp` (McpAgent Durable Object, `nodejs_compat`). Network strings in the current example are CAIP-2; the docs page still says `base`/`base-sepolia`.
- Official alternative: `@x402/mcp` 2.28.0 `createPaymentWrapper(resourceServer, { accepts })` around `mcpServer.tool(...)` handlers + `createx402MCPClient` (README verified). Bazaar supports MCP tools via `declareDiscoveryExtension({ toolName, inputSchema, ... })`.
- Recommended order: REST API first; MCP later as a thin wrapper over the same functions. Do not build both paywalls at once.

### 4.3 Pay Per Crawl **[V-code][S]**

Cloudflare-native monetization for crawlers (`cloudflare:402` batch-settlement with signed HTTP messages; billing identity tied to the crawler's Signature-Agent). Irrelevant for a JSON API sold to agents; mention only so nobody confuses it with x402 on Base.

---

## 5. Client-side testing (Base Sepolia end to end)

Client verified against the local Worker + mock facilitator **[V-run]** (client signing needs no on-chain balance; against the real facilitator it needs USDC):

```ts
import { wrapFetchWithPayment, x402Client, decodePaymentResponseHeader } from "@x402/fetch";
import { ExactEvmScheme } from "@x402/evm/exact/client";
import { privateKeyToAccount } from "viem/accounts";

const account = privateKeyToAccount(process.env.EVM_PRIVATE_KEY as `0x${string}`);   // throwaway test key
const client = new x402Client().register("eip155:84532", new ExactEvmScheme(account)); // "eip155:*" also valid
const pay = wrapFetchWithPayment(fetch, client);

const r = await pay("https://api.example.com/v1/company?nip=5252248481");
console.log(r.status, await r.json());
console.log(decodePaymentResponseHeader(r.headers.get("PAYMENT-RESPONSE")!));  // {success, payer, transaction, network}

const r2 = await pay("https://api.example.com/v1/batch", {
  method: "POST", headers: { "content-type": "application/json" },
  body: JSON.stringify({ nips: ["5252248481", "1132191589"] }),
});
```

Shortcut: `wrapFetchWithPaymentFromConfig(fetch, { schemes: [{ network: "eip155:84532", client: new ExactEvmScheme(account) }] })`. Packages: `npm i @x402/fetch @x402/core @x402/evm viem`.

Test funds:
- **USDC (Base Sepolia):** Circle faucet `https://faucet.circle.com` -> network "Base Sepolia" -> USDC; public faucet is about 10 USDC per request, once per 24 h per testnet; the Circle developer console faucet gives 20 USDC but only to Circle-created wallets. **[S]**
- **ETH is not needed** by the buyer for `exact` (EIP-3009 `transferWithAuthorization`; facilitator pays gas). Only the owner's receiving wallet address is needed server-side. CDP also has a faucet API (`POST /platform/v2/evm/faucet`) if a CDP key exists. **[S]**
- Use a **fresh throwaway key** for tests; never the production `PAY_TO` wallet's key.
- Facilitator for the test: `https://x402.org/facilitator` with `NETWORK=eip155:84532` (no key). To test the CDP path end to end set `CDP_API_KEY_*` (CDP accepts Base Sepolia).
- Acceptance check: `r.status === 200`, `PAYMENT-RESPONSE.success === true`, tx visible on `https://sepolia.basescan.org/tx/<transaction>`.

---

## 6. Discovery and catalogs

### 6.1 Coinbase CDP x402 Bazaar (and agentic.market)

**Mechanism [V-code + S]:** there is no registration form. A resource is cataloged when a payment for it **settles through the CDP facilitator** and the `PaymentPayload` carries `extensions.bazaar` and `resource` (both are echoed by `@x402/fetch` from our 402). Spec: facilitator validates `info` against `schema`, extracts, catalogs; outcome is reported in the `EXTENSION-RESPONSES` header (`success|processing|rejected` + `rejectedReason`). First cataloging reportedly happens within seconds of the first settlement; updates to existing listings take about 75-86 minutes in batches; listings are evicted about 30 days after the last call. **[S: x402 issue #3045 community reports]**

**Steps** (CDP docs "get discovered", as summarized **[S]**):
1. Route key has explicit method and absolute path (`GET /v1/company`), `extensions.bazaar` via `declareDiscoveryExtension`, description <= 500 chars, public **https** URL.
2. Validate (free, no key): `POST https://api.cdp.coinbase.com/platform/v2/x402/validate` with `{ "url": "https://api.<domain>/v1/company", "method": "GET" }`. Success: `valid: true` and `simulation.outcome: "accepted"` (reporter in cdp-sdk #824 saw 25/25 preflight checks). Typical failures: non-https `resource` ("resource must start with 'https://' when protocol type is http"), endpoint returning 200/400/404/405 instead of 402 to the probe.
3. Make **one real paid call on mainnet through CDP** (e.g. $0.01 with `@x402/fetch`). Check: `GET https://api.cdp.coinbase.com/platform/v2/x402/discovery/merchant?payTo=<PAY_TO>` or page through `/discovery/resources?limit=1000&offset=N` (offset paging, no cursor token). Programmatic: `withBazaar(new HTTPFacilitatorClient(createFacilitatorConfig(...))).extensions.bazaar.listResources({ payTo })` / `.search({ query })` (`@x402/extensions/bazaar`, calls `<url>/discovery/resources|search`). **[V-code]**
4. Ranking uses recent calls, **unique payers**, and metadata completeness (description, input/output schema, service metadata). A hand-picked "curated/enriched" tier shown prominently on **agentic.market** exists: criteria cited are live mainnet payments, >= 99% availability over 30 days, passing validate/health probe, complete schema and pricing; a CDP maintainer stated meeting them does not guarantee inclusion ("at Coinbase's discretion", cdp-sdk #838, 2026-10-02). **[S]**
5. Known failure modes: validated + settled but not listed (cdp-sdk #764, #806, #824, x402 #3045). For #824 the maintainer's cause was a settlement lacking `paymentPayload.extensions.bazaar` / `paymentPayload.resource`. Use the standard SDK client for the first paid call.
6. **Path params are risky:** cdp-sdk #787 - Bazaar published `pathParams` as the URL-encoded route template (`%7Bsiren%7D`) instead of the concrete value, so buyers see a placeholder (open, no fix as of the thread). **Design choice: use query string (`?nip=`) or POST body, not `/v1/company/:nip`.**
7. Keep the 402 stable (no flapping, no 5xx on probes): consecutive failed probes lower ranking [S, Tanod guide].

**Tanod and the "34,062 offers on >2,000 hosts":** Tanod (`tanod.dev`, GitHub `tanod-labs`) is a seller + data publisher, not a catalog you register with. The figure is its daily snapshot of the **CDP Bazaar discovery list** (2026-10-09: 34,062 listings, 2,158 hosts, median listed price $0.01, 44.7% of listings from 19 templated bulk hosts, 94.4% of listings without a "use when" sentence, 16,236 listings with <= 1 payer in 30 days). The PayAI list is indexed separately (17,763 listings). **[V-code: `x402-bazaar-stats.json`; S for the DEV posts]** Practical takeaway: **being in the CDP Bazaar is the "Tanod" listing**; and put a "Use when ..." sentence in `description` (only 5.6% do) to stand out.

### 6.2 x402scan.com (Merit Systems) **[V-code: `Merit-Systems/x402scan` README + `docs/DISCOVERY.md` + API routes]**

- Explorer (volume by facilitator address, servers, resources, built-in wallet to invoke them).
- **Manual:** `https://www.x402scan.com/resources/register` -> "Add Server" (origin) or "Register This URL Only". Probes the URL, parses the 402 challenge, lists it automatically if valid.
- **Discovery precedence** when you click Add Server: (1) `GET /openapi.json` with `x-payment-info`; (2) `GET /.well-known/x402` (compat); fallback = endpoint-only registration. **Runtime 402 is authoritative.**
- Requirements for "payable" indexing: 402 with parseable challenge (`PAYMENT-REQUIRED` header v2 or legacy JSON body), non-empty `accepts`, Bazaar-style input schema (`extensions.bazaar.info`), runtime `accepts[].amount` in token atomic units (`0.01` USD = `"10000"`; common failure: decimal dollars). Unauthenticated probes must reach the 402 before body/query validation rejects them. Missing input schema -> `skipped`.
- Optional proof of ownership: `x-discovery.ownershipProofs` in OpenAPI (or `/.well-known/x402` `ownershipProofs`).
- API (needs SIWX wallet auth, so use the UI): `POST /api/x402/registry/register {url}` and `POST /api/x402/registry/register-origin {origin}`.
- Validator CLI: `npx -y @agentcash/discovery <domain> -v` (v1.7.5) and `npx @agentcash/discovery check <url>`.

### 6.3 Machine-readable discovery conventions

| Convention | State (2026-10) | What to publish |
|---|---|---|
| **OpenAPI `/openapi.json` + `x-payment-info`** | Canonical for x402scan and the agentcash ecosystem (`@agentcash/discovery` spec v1.0, public draft). `/.well-known/x402` and `/.well-known/mpp` are **no longer parsed** by that runtime (it only warns `LEGACY_WELL_KNOWN_FOUND`), but x402scan still accepts `/.well-known/x402` as compat. | `openapi: 3.1.0`, `info.title/version`, `info.contact.email` (ownership/dashboards), per operation `summary`, `security: []`, `x-payment-info: {price:{mode:"fixed",currency:"USD",amount:"0.01"}, protocols:[{x402:{}}]}`, `responses` incl. `"402"`. Dynamic: `mode:"dynamic", min, max`. Optional `x-agentcash-guidance.llmsTxtUrl`, `x-agentcash-provenance.ownershipProofs`. Full example in section 9.4. |
| `/.well-known/x402` | **No standalone spec in x402-foundation/x402** (grep of `specs/`, `docs/`: only x402scan defines it). x402scan format: `{"version":1,"resources":["https://api.example.com/v1/company", ...],"ownershipProofs":[...]}`. 402index is also reported to crawl it **[S]**. | Cheap to serve; publish as compat. |
| `llms.txt` | Referenced by agentcash spec (`x-agentcash-guidance.llmsTxtUrl`, freeform guidance fetched on demand), agentic.market publishes one. No x402 requirement. | Short: what the API does, endpoints, prices, example call, limits, contact. |
| **A2A AgentCard** `/.well-known/agent-card.json` | A2A spec v1.0.0 (latest release; repo head 2026-10-07). Required AgentCard fields: `name`, `description`, `supportedInterfaces[{url, protocolBinding, protocolVersion}]`, `version`, `capabilities`, `defaultInputModes`, `defaultOutputModes`, `skills[{id,name,description,tags[],examples?}]`; optional `provider`, `documentationUrl`, `securitySchemes`, `iconUrl`, `signatures`. **[V-code: a2a.proto]** | Only worthwhile if we expose a real A2A JSON-RPC endpoint. |
| **a2a-x402 extension** (`google-agentic-commerce/a2a-x402`) | v0.1 (URI `https://github.com/google-a2a/a2a-x402/v0.1`) and v0.2 (URI `https://github.com/google-agentic-commerce/a2a-x402/blob/main/spec/v0.2`). Declared in `AgentCard.capabilities.extensions[{uri, description, required:true}]`; clients activate with `X-A2A-Extensions` header; payment signalled via task state `input-required` + `x402.payment.*` metadata. x402 Foundation spec has an equivalent `specs/transports-v2/a2a.md`. **[V-code]** | Low priority for a plain REST API. |
| **MCP Registry** (official, `registry.modelcontextprotocol.io`) | Preview/API-frozen v0.1. Publish with `mcp-publisher` (`init`, `validate`, `login github|dns|http`, `publish`), `server.json` with `remotes` (streamable-http URL). Namespace `io.github.<user>/<name>` (GitHub auth) or reverse-DNS `com.<domain>/<name>` (DNS TXT / HTTP key proof). **[S]** | Only after we ship an MCP endpoint. |

### 6.4 Other catalogs (how to get in)

| Catalog | How listed | Source |
|---|---|---|
| **402index.io** (community registry L402 + x402 + MPP; hourly health checks) | (1) `curl -X POST https://402index.io/api/v1/register -H 'content-type: application/json' -d '{"url":"https://api.example.com/v1/company"}'` - probe validates the 402 and lists automatically. (2) PR with a YAML file under `listings/` (name, description, url, protocol `x402`, `price_usd`, `category`, `provider`). (3) Already in the x402 Bazaar/Satring/l402apps/MPP directory -> aggregated, no action. (4) Domain claim for editing: `POST /api/v1/claim` then host `/.well-known/402index-verify.txt`, verify at `/api/v1/claim/verify`, edit via `PATCH /api/v1/services/:id`. Contact hello@402index.io. | **[V-code]** `ryanthegentry/402index` README, CONTRIBUTING.md, `src/services/domain-verify.js` |
| **x402-list.com** | Web form or `POST /api/v1/submit`; automatic 402 probe, then **human review**; **free-host/tunnel domains (vercel.app, workers.dev, ngrok, trycloudflare) are rejected** - own domain required; 1 submission per email per 7 days; pending auto-rejected after 7 days. | **[S]** |
| **agentic.market** (Coinbase storefront over the CDP Bazaar) | Automatic via CDP Bazaar; curated tier is editorial (about 70 services at launch) | **[S]** Coinbase launch post, cdp-sdk #838 |
| **x402.org/ecosystem** | The site source is not in the x402 repo (`typescript/site` only hosts the facilitator), and I could not find submission instructions. Likely a form/PR managed by Coinbase; ask in the x402 Discord/Slack or open an issue in `x402-foundation/x402`. **Unverified.** | - |
| **x402dev.com, Proxy402, awesome-x402 lists, x402-wiki** | Found no authoritative submission process (x402dev and Proxy402 returned nothing in search). `x402-wiki` accepts service submissions via GitHub issues/PRs **[S]**. Low value vs. the ones above. | - |
| **Onyx Bazaar, Agent402, other leaderboards** | Derived from the CDP Bazaar/volume automatically; no action. | **[S]** |

---

## 7. Ecosystem pricing and demand signals

All price numbers are **listed** prices (first payment option in each 402 listing), not prices buyers paid. Source: Tanod, CC BY 4.0, `github.com/tanod-labs/x402-price-index` (cloned; `data/x402-category-prices.json` snapshot 2026-10-09 and `data/x402-prices.md` hand-checked 2026-10-09/10; Tanod is itself a seller, so first-party bias applies). **[V-code for the data files]**

| Category | Offers / hosts (auto snapshot) | min | p25 | **median** | p75 | max |
|---|---|---|---|---|---|---|
| **Company enrichment** | 71 / 40 | 0.001 | 0.01 | **0.03** (hand-checked: **0.027**) | 0.10 | 35.0 |
| PDF APIs | 238 / 121 | 0.001 | 0.005 | 0.010 | 0.02 | 1.24 |
| OCR | 47 / 31 | 0.001 | 0.005 | 0.010 | 0.02 | 0.261 |
| Speech to text (hand-checked) | 39 / 24 | - | - | 0.06 | - | - |
| Whole CDP Bazaar | 34,062 / 2,158 | 0.00001 | 0.005 | **0.01** | 0.01 | 1000 (p90 0.05) |

Note on the bottom row: in `x402-bazaar-stats.json`, `price.under_001 = 30.8` is the share of priced listings below $0.01 (matches the DEV post wording) and `under_01 = 94.8` the share below $0.1 (consistent with q1 0.005, median/q3 0.01, p90 0.05). **[V-code]** So $0.01 sits exactly at the Bazaar-wide median and at p25 for company enrichment.

Other signals:
- **GET endpoints attract more payers than POST:** 31.5% of GET endpoints (3,575 of 11,344) had >= 3 unique payers in 30 days vs 14.5% of POST (3,717 of 25,691), snapshot 2026-10-10 (correlation, not cause). **[V-code]** -> make the single-lookup endpoint a GET.
- Demand is concentrated: 16,236 of 34,062 listings have <= 1 payer in 30 days; the top 8 most-paid listings in Tanod's part-3 post were all on one host (`api.onesource.io`). **[S]**
- Company data is among the **highest-priced** categories: Turnkey's Bazaar analysis (Aug 13 - Sep 13 2026) reports enrichment calls as the priciest (PDL match $0.28, Whitepages $0.22) and a median payment on Base of $0.0061 across 440,608 distinct payers. **[S]**
- **A direct competitor exists for French company data**: a SIREN endpoint listed in the Bazaar with a path-param route (cdp-sdk #787). **[S]**
- Another report: median $0.02 across 19,338 priced routes, only 21% payable when probed (TOLL-402, July 2026). **[S]** -> reliability of the 402 handshake is itself a differentiator.
- No verified "top earners by revenue" dataset found; x402scan shows volume per server but I could not open it.

**Pricing implication [I]:** Polish registry data (KRS/CEIDG/GUS) is cheap for us to serve; keep the basic profile at `$0.01` (at/under market median, p25 = 0.01), richer endpoints (full KRS extract, board members, beneficial owners) `$0.05-0.10`, batch `$0.005`/item. With CDP's $0.001/tx after 1,000 free tx per month, a $0.01 call keeps 90%.

---

## 8. Remaining uncertainties

1. CDP pricing page vs FAQ (free tier wording) and exact `/supported` network list - verify in the CDP portal with a real key.
2. Whether Base **Sepolia** payments through CDP get listed in the public Bazaar. Evidence says yes (2,407 "Base Sepolia (testnet)" listings in the snapshot; a maintainer fixed an issue by sending a Sepolia tx), but featured/curated needs mainnet.
3. `x402.org/facilitator` liveness was not probed (network block).
4. Bazaar indexing for PayAI/Dexter/Mogami: PayAI has `/discovery/resources`; others unverified.
5. Ajv warning could in future become an error if the SDK changes to `throw`; pin versions and keep the Worker smoke test in CI.
6. x402scan's own requirement set may change; run `npx @agentcash/discovery` before each registration.

---

## 9. Recommended implementation for our Worker

### 9.1 Layout

```
src/index.ts          # Hono app (below)
wrangler.jsonc
public/ (optional)    # or serve /openapi.json, /llms.txt, /.well-known/x402 from the Worker
```

Install (exact, same version for all `@x402/*`):

```bash
npm i hono@^4.13 viem@^2.57 \
  @x402/core@2.28.0 @x402/hono@2.28.0 @x402/evm@2.28.0 @x402/extensions@2.28.0 @coinbase/x402@2.1.0
npm i -D wrangler@^4.149 typescript @cloudflare/workers-types
# client / tests
npm i -D @x402/fetch@2.28.0
```

### 9.2 `wrangler.jsonc`

```jsonc
{
  "name": "company-data-api",
  "main": "src/index.ts",
  "compatibility_date": "2026-09-01",
  "compatibility_flags": ["nodejs_compat"],
  "routes": [{ "pattern": "api.example.com", "custom_domain": true }],   // own domain (x402-list.com rejects workers.dev)
  "vars": {
    "PUBLIC_ORIGIN": "https://api.example.com",
    "PAY_TO": "0xYourReceivingWalletOnBase",
    "NETWORK": "eip155:84532",                       // switch to "eip155:8453" for production
    "FACILITATOR_URL": "https://x402.org/facilitator" // testnet; ignored when CDP keys are set
  }
}
// secrets (production):  wrangler secret put CDP_API_KEY_ID ; wrangler secret put CDP_API_KEY_SECRET
// local: .dev.vars with the same names
```

### 9.3 `src/index.ts` (typechecked with tsc, bundled with wrangler, executed in workerd against a mock facilitator and a real `@x402/fetch` client)

```ts
import { Hono } from "hono";
import type { MiddlewareHandler } from "hono";
import { paymentMiddleware, x402ResourceServer } from "@x402/hono";
import { HTTPFacilitatorClient } from "@x402/core/server";
import type { HTTPRequestContext, RoutesConfig } from "@x402/core/server";
import type { Network } from "@x402/core/types";
import { registerExactEvmScheme } from "@x402/evm/exact/server";
import { declareDiscoveryExtension } from "@x402/extensions/bazaar";
import { createFacilitatorConfig } from "@coinbase/x402";

type Env = {
  PAY_TO: string;
  PUBLIC_ORIGIN: string;          // https://api.example.com (no trailing slash)
  NETWORK: string;                // "eip155:84532" | "eip155:8453"
  FACILITATOR_URL?: string;       // testnet facilitator when no CDP keys
  CDP_API_KEY_ID?: string;
  CDP_API_KEY_SECRET?: string;
};

const UNIT_USD = 0.005;           // batch price per NIP
const MAX_BATCH = 100;
const app = new Hono<{ Bindings: Env }>();

// Build once per isolate (env exists only at request time on Workers).
let cached: MiddlewareHandler | undefined;
function getPaywall(env: Env): MiddlewareHandler {
  if (cached) return cached;
  const network = env.NETWORK as Network;
  const facilitator = new HTTPFacilitatorClient(
    env.CDP_API_KEY_ID && env.CDP_API_KEY_SECRET
      ? createFacilitatorConfig(env.CDP_API_KEY_ID, env.CDP_API_KEY_SECRET)   // https://api.cdp.coinbase.com/platform/v2/x402 + JWT
      : { url: env.FACILITATOR_URL ?? "https://x402.org/facilitator" },
  );
  const server = registerExactEvmScheme(new x402ResourceServer(facilitator), { networks: [network] });

  const routes: RoutesConfig = {
    "GET /v1/company": {
      accepts: { scheme: "exact", network, payTo: env.PAY_TO, price: "$0.01", maxTimeoutSeconds: 60 },
      resource: `${env.PUBLIC_ORIGIN}/v1/company`,        // canonical URL without query string
      description: "Company profile by Polish NIP. Use when you need legal name, status and address of a company.",
      mimeType: "application/json",
      serviceName: "PL Company Data",                     // <= 32 printable ASCII
      tags: ["company", "kyb", "poland"],                 // <= 5 tags
      iconUrl: `${env.PUBLIC_ORIGIN}/icon.png`,
      extensions: {
        ...declareDiscoveryExtension({
          input: { nip: "5252248481" },
          inputSchema: { properties: { nip: { type: "string", pattern: "^[0-9]{10}$" } }, required: ["nip"] },
          output: { example: { nip: "5252248481", name: "ACME sp. z o.o." } },
        }),
      },
    },
    "POST /v1/batch": {
      accepts: {
        scheme: "exact",
        network,
        payTo: env.PAY_TO,
        price: async (ctx: HTTPRequestContext) => {
          const body = (await ctx.adapter.getBody?.()) as { nips?: unknown[] } | undefined;
          const n = Math.min(Math.max(body?.nips?.length ?? 1, 1), MAX_BATCH);
          return `$${(n * UNIT_USD).toFixed(4)}`;         // n x unit price
        },
      },
      resource: `${env.PUBLIC_ORIGIN}/v1/batch`,
      description: "Batch company lookup, $0.005 per NIP (max 100). Use when you need many companies at once.",
      mimeType: "application/json",
      serviceName: "PL Company Data",
      tags: ["company", "batch", "poland"],
      extensions: {
        ...declareDiscoveryExtension({
          bodyType: "json",
          input: { nips: ["5252248481"] },
          inputSchema: { properties: { nips: { type: "array", items: { type: "string" }, maxItems: MAX_BATCH } }, required: ["nips"] },
          output: { example: { results: [] } },
        }),
      },
    },
  };
  cached = paymentMiddleware(routes, server);   // 3rd arg PaywallConfig only matters for browsers (HTML paywall)
  return cached;
}

app.use("*", (c, next) => getPaywall(c.env)(c, next));   // only matching "METHOD /path" keys are charged

// Free, un-paywalled discovery documents (registered before/after is irrelevant; they are not in `routes`)
app.get("/", (c) => c.text("ok"));
// app.get("/openapi.json", ...), app.get("/llms.txt", ...), app.get("/.well-known/x402", ...)  -> section 9.4

// Paid handlers run only after payment verified; settlement happens after the handler returns 2xx.
app.get("/v1/company", (c) => {
  const nip = c.req.query("nip");
  if (!nip || !/^[0-9]{10}$/.test(nip)) return c.json({ error: "nip must be 10 digits" }, 400);
  return c.json({ nip, name: "ACME sp. z o.o." });       // real lookup here
});
app.post("/v1/batch", async (c) => {
  const { nips } = await c.req.json<{ nips: string[] }>();
  if (!Array.isArray(nips) || nips.length < 1 || nips.length > MAX_BATCH) return c.json({ error: "1..100 nips" }, 400);
  return c.json({ results: nips.map((nip) => ({ nip })) });
});
export default app;
```

Behaviours confirmed in workerd: 402 with v2 header for unpaid calls, `PAYMENT-RESPONSE` on paid 200, batch of 1 -> `amount 5000`, batch of 3 -> `amount 15000`, payload to facilitator contains `extensions.bazaar` and `resource{url,description,mimeType,serviceName,tags,iconUrl}`, `x402Version 2`.

Behaviour of an error from the handler: the middleware settles only after the handler returns; if `c.res.status >= 400` (or the handler throws) it calls `cancellationDispatcher.cancel(...)` and **does not settle**, so a handler 400/404/5xx does not charge the buyer (read in `@x402/hono/dist/esm/index.mjs`; I did not run a 400 case). The paid path also calls `Buffer.from(...)`, another reason to keep `nodejs_compat` on. **[V-code]** Validate cheap inputs *before* costly lookups; unpaid callers hit the 402 first, so malformed input without payment returns 402, not 400 - intended.

### 9.4 Discovery documents served by the Worker (free routes)

`/openapi.json` (x402scan, agentcash):

```json
{
  "openapi": "3.1.0",
  "info": { "title": "PL Company Data", "version": "1.0.0", "contact": { "email": "you@example.com" },
            "x-guidance": "Polish company data (KRS/CEIDG/REGON). Pay per call in USDC on Base via x402." },
  "x-agentcash-guidance": { "llmsTxtUrl": "https://api.example.com/llms.txt" },
  "paths": {
    "/v1/company": { "get": {
      "summary": "Company profile by NIP",
      "security": [],
      "parameters": [{ "name": "nip", "in": "query", "required": true, "schema": { "type": "string", "pattern": "^[0-9]{10}$" } }],
      "x-payment-info": { "price": { "mode": "fixed", "currency": "USD", "amount": "0.01" }, "protocols": [{ "x402": {} }] },
      "responses": { "200": { "description": "OK" }, "402": { "description": "Payment Required" } } } },
    "/v1/batch": { "post": {
      "summary": "Batch company lookup, 0.005 USD per NIP, max 100",
      "security": [],
      "requestBody": { "required": true, "content": { "application/json": { "schema": { "type": "object", "required": ["nips"], "properties": { "nips": { "type": "array", "maxItems": 100, "items": { "type": "string" } } } } } } },
      "x-payment-info": { "price": { "mode": "dynamic", "currency": "USD", "min": "0.005", "max": "0.50" }, "protocols": [{ "x402": {} }] },
      "responses": { "200": { "description": "OK" }, "402": { "description": "Payment Required" } } } }
  }
}
```

`/.well-known/x402` (compat for x402scan/402index): `{"version":1,"resources":["https://api.example.com/v1/company","https://api.example.com/v1/batch"]}`

`/llms.txt`: 10-20 lines - purpose, the two endpoints with example requests and prices, network (Base, USDC), "v2 x402: use `@x402/fetch`", data sources and freshness, rate/limit note, contact. (Mention source attribution required by the registries - see `01-licencje-i-limity.md`.)

### 9.5 Production switch (testnet -> mainnet)

1. `NETWORK=eip155:8453`; `PAY_TO` = a mainnet address the owner controls (consider a fresh wallet; payments are irrevocable USDC transfers).
2. Create a CDP Secret API key (Ed25519 default) in the CDP portal; `wrangler secret put CDP_API_KEY_ID` / `CDP_API_KEY_SECRET`. Now `createFacilitatorConfig` path is active and `FACILITATOR_URL` ignored. The x402.org facilitator **must not** be used for mainnet.
3. Custom domain with https; `PUBLIC_ORIGIN` = that origin.
4. Smoke test: unpaid GET -> 402 + `PAYMENT-REQUIRED`; `POST /platform/v2/x402/validate` -> accepted.
5. One real $0.01 payment with `@x402/fetch` from a funded mainnet wallet (this also triggers Bazaar indexing).

---

## 10. Catalog registration checklist (after deployment)

Pre-flight (once, before any registration)
- [ ] Custom domain over https (not `*.workers.dev`); `PUBLIC_ORIGIN` set; `resource` URLs canonical.
- [ ] `curl -i https://api.example.com/v1/company` -> `402`, header `PAYMENT-REQUIRED` decodes to `x402Version:2`, `accepts[0].network = eip155:8453`, `amount = "10000"`, `extensions.bazaar` present, `resource.url` https without query.
- [ ] Same for `POST /v1/batch` (empty body -> price of 1 item).
- [ ] `/openapi.json`, `/llms.txt`, `/.well-known/x402`, `/icon.png` return 200 without payment.
- [ ] `npx -y @agentcash/discovery api.example.com -v` -> no errors; `npx @agentcash/discovery check https://api.example.com/v1/company`.
- [ ] CDP validate: `curl -X POST https://api.cdp.coinbase.com/platform/v2/x402/validate -H 'content-type: application/json' -d '{"url":"https://api.example.com/v1/company","method":"GET"}'` -> `valid:true`, `simulation.outcome:"accepted"`.

Day 0 (triggers CDP Bazaar -> agentic.market, 402index, x402scan aggregation)
- [ ] One real mainnet payment ($0.01) via `@x402/fetch` for each of `GET /v1/company` and `POST /v1/batch` (a batch of 1-2 items). Watch the `EXTENSION-RESPONSES` header (`bazaar.status`).
- [ ] Verify listing: `GET https://api.cdp.coinbase.com/platform/v2/x402/discovery/merchant?payTo=<PAY_TO>` (or `listResources({payTo})` / `search({query:"polish company data"})`). If absent after ~1 hour: re-run validate, confirm the settled payload had `extensions.bazaar` + `resource`, then open an issue in `coinbase/cdp-sdk` (label x402) citing #824.

Day 0-1 (explicit registrations)
- [ ] **x402scan:** https://www.x402scan.com/resources/register -> "Add Server" with `https://api.example.com`; confirm both routes registered, none `skipped/failed`. Optionally add `x-discovery.ownershipProofs`.
- [ ] **402index.io:** `curl -X POST https://402index.io/api/v1/register -H 'content-type: application/json' -d '{"url":"https://api.example.com/v1/company"}'` (repeat for `/v1/batch`); then domain claim (`POST /api/v1/claim` -> serve `/.well-known/402index-verify.txt` -> `POST /api/v1/claim/verify`) to be able to edit the listing.
- [ ] **x402-list.com:** submit via the web form or `POST /api/v1/submit` (own domain; human review; 1 submission/email/7 days).
- [ ] **agentic.market:** nothing to submit; after 30 days of mainnet traffic and >= 99% availability, check listing and consider asking Coinbase for curation (editorial, no guarantee).
- [ ] **x402.org/ecosystem / x402 Discord/Slack:** ask how to be added (process unverified).

Week 1-4 (quality signals that drive Bazaar ranking)
- [ ] Keep availability >= 99.5% and 402 handshake stable (no 5xx/200 on unpaid probes). Add an external uptime check on the 402.
- [ ] Keep `lastCalledAt` fresh: listings drop ~30 days after the last call - schedule a $0.01 self-test call weekly from a cron Worker (also a canary).
- [ ] Description includes a "Use when ..." sentence; input/output examples present; `serviceName`, `tags`, `iconUrl` set.
- [ ] Watch unique payers (Bazaar counts them) and x402scan volume.

Optional, later
- [ ] **MCP:** expose `/mcp` (via `@x402/mcp` or `agents/x402` `paidTool`) and publish to the official MCP Registry (`mcp-publisher publish`, namespace via GitHub or DNS), add `declareDiscoveryExtension({toolName,...})` for Bazaar MCP listing.
- [ ] **A2A:** only if we implement an A2A agent: `/.well-known/agent-card.json` + a2a-x402 extension declaration.
- [ ] Second facilitator / network (PayAI or Dexter for fee-free, Solana) via an additional `accepts` entry.

---

## 11. Sources

Verified in code/runtime
- npm registry metadata and package contents for the packages in 1.1 (installed in the scratchpad, `.d.ts` and `.mjs` read).
- https://github.com/x402-foundation/x402 (`specs/extensions/bazaar.md`, `specs/x402-specification-v2.md`, `docs/dev-tools/facilitators.md`, `docs/core-concepts/network-and-token-support.mdx`, `docs/getting-started/quickstart-for-sellers.mdx`, `docs/extensions/bazaar.mdx`, `docs/schemes/upto.mdx`, `TSC.md`, `specs/schemes/batch-settlement/scheme_batch_settlement_cloudflare.md`, `specs/transports-v2/a2a.md`)
- https://github.com/cloudflare/templates/tree/main/x402-proxy-template ; https://github.com/cloudflare/agents (`examples/x402`, `examples/x402-mcp`, `packages/agents/src/mcp/client/x402.ts`) ; cloudflare-docs `src/content/docs/agents/tools/payments/x402/*.mdx`
- https://github.com/Merit-Systems/x402scan (`README.md`, `docs/DISCOVERY.md`, `apps/scan/src/app/api/x402/registry/*`, `packages/external/facilitators`)
- https://www.npmjs.com/package/@agentcash/discovery (README + `docs/SPECIFICATION.md`)
- https://github.com/ryanthegentry/402index (README, CONTRIBUTING.md, `src/services/domain-verify.js`, `src/openapi.js`)
- https://github.com/tanod-labs/x402-price-index (data files, CC BY 4.0)
- https://github.com/a2aproject/A2A (`specification/a2a.proto`, `docs/specification.md`) ; https://github.com/google-agentic-commerce/a2a-x402 (`spec/v0.1`, `spec/v0.2`)
- GitHub issues read via WebFetch: https://github.com/coinbase/cdp-sdk/issues/824 , /787 , /838 ; https://github.com/x402-foundation/x402/issues/3045 ; https://github.com/PayAINetwork/docs/pull/78

Secondary (WebSearch summaries; pages not directly opened)
- CDP docs: https://docs.cdp.coinbase.com/x402/seller/facilitator , /x402/support/faq , /x402/seller/get-discovered , /x402/quickstart-for-sellers
- https://www.coinbase.com/developer-platform/discover/launches/agentic-market ; https://www.coinbase.com/blog/coinbase-and-cloudflare-will-launch-x402-foundation
- Tanod posts: https://dev.to/tanod/state-of-the-x402-bazaar-34062-listings-2158-hosts-and-94-missing-a-use-when-line-34co , https://dev.to/tanod/how-to-get-an-x402-endpoint-listed-and-featured-in-the-cdp-bazaar-43b9 , https://dev.to/tanod/what-ai-agents-pay-per-call-pdf-speech-to-text-solana-reads-and-company-data-on-x402-2o04 , https://dev.to/tanod/what-ai-agents-pay-per-call-part-3-which-x402-listings-actually-get-paid-d36
- https://www.turnkey.com/blog/agents-buying-coinbases-x402-bazaar-discovery-layer ; https://x402-list.com/api ; https://developers.circle.com/w3s/developer-console-faucet ; MCP Registry guides (roxyapi.com, speakeasy.com)
