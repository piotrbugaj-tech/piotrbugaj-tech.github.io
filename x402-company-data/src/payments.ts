import type { MiddlewareHandler } from "hono";
import { paymentMiddleware, x402ResourceServer } from "@x402/hono";
import { HTTPFacilitatorClient, type FacilitatorClient } from "@x402/core/server";
import type { HTTPRequestContext, RoutesConfig, RouteConfig } from "@x402/core/server";
import type { Network } from "@x402/core/types";
import { ExactEvmScheme } from "@x402/evm/exact/server";
import { declareDiscoveryExtension } from "@x402/extensions/bazaar";
import type { Env } from "./env";
import { PRODUCTS, SERVICE_NAME, SERVICE_TAGS, type Product } from "./products";
import { batchSize } from "./lib/batch";
import { cdpAuthHeaders } from "./lib/cdp-auth";

export const DEFAULT_NETWORK = "eip155:8453"; // Base mainnet
export const DEFAULT_FACILITATOR = "https://x402.org/facilitator"; // testnet only

function discovery(p: Product) {
  if (p.method === "GET") {
    const properties = Object.fromEntries(
      Object.entries(p.queryParams ?? {}).map(([k, v]) => [k, { type: v.type, description: v.description, ...(v.enum ? { enum: v.enum } : {}) }]),
    );
    const required = Object.entries(p.queryParams ?? {})
      .filter(([, v]) => v.required)
      .map(([k]) => k);
    const example = Object.fromEntries(
      Object.entries(p.queryParams ?? {})
        .filter(([, v]) => v.example)
        .map(([k, v]) => [k, v.example]),
    );
    return declareDiscoveryExtension({
      input: example,
      inputSchema: { type: "object", properties, ...(required.length ? { required } : {}) },
      output: { example: p.outputExample },
    });
  }
  return declareDiscoveryExtension({
    bodyType: "json",
    input: p.bodyExample ?? {},
    inputSchema: p.bodySchema ?? { type: "object" },
    output: { example: p.outputExample },
  });
}

export function buildRoutes(env: Env): RoutesConfig {
  const network = (env.NETWORK ?? DEFAULT_NETWORK) as Network;
  const payTo = env.PAY_TO!;
  const routes: Record<string, RouteConfig> = {};
  for (const p of PRODUCTS) {
    const price =
      p.unitPrice !== undefined
        ? async (ctx: HTTPRequestContext) => {
            const n = batchSize(await ctx.adapter.getBody?.());
            const usd = Math.max(p.minPrice ?? 0, n * p.unitPrice!);
            return `$${usd.toFixed(4)}`;
          }
        : p.price;
    routes[`${p.method} ${p.path}`] = {
      accepts: { scheme: "exact", price, network, payTo, maxTimeoutSeconds: 120 },
      description: p.description,
      mimeType: "application/json",
      serviceName: SERVICE_NAME,
      tags: SERVICE_TAGS,
      ...(env.PUBLIC_BASE_URL ? { resource: env.PUBLIC_BASE_URL + p.path } : {}),
      extensions: { ...discovery(p) },
      unpaidResponseBody: async () => ({
        contentType: "application/json",
        body: {
          error: "payment_required",
          message: `This endpoint costs ${p.price} in USDC on ${network === DEFAULT_NETWORK ? "Base" : network}, paid per call via x402. No account or API key needed.`,
          docs: (env.PUBLIC_BASE_URL ?? "") + "/openapi.json",
        },
      }),
    };
  }
  return routes;
}

export function buildFacilitator(env: Env): FacilitatorClient {
  const url = env.FACILITATOR_URL ?? DEFAULT_FACILITATOR;
  const useCdp = !!(env.CDP_API_KEY_ID && env.CDP_API_KEY_SECRET);
  return new HTTPFacilitatorClient({
    url,
    ...(useCdp ? { createAuthHeaders: () => cdpAuthHeaders(url, env.CDP_API_KEY_ID!, env.CDP_API_KEY_SECRET!) } : {}),
  });
}

/**
 * Builds the x402 middleware once per isolate (env is constant for an isolate).
 * `facilitator` can be injected (tests use an in-memory one).
 */
export function createPaymentMiddleware(env: Env, facilitator?: FacilitatorClient): MiddlewareHandler {
  const network = (env.NETWORK ?? DEFAULT_NETWORK) as Network;
  const server = new x402ResourceServer(facilitator ?? buildFacilitator(env)).register(network, new ExactEvmScheme());
  return paymentMiddleware(buildRoutes(env), server);
}
