import { Hono, type Context, type MiddlewareHandler } from "hono";
import { cors } from "hono/cors";
import type { FacilitatorClient } from "@x402/core/server";
import type { Env } from "./env";
import { parseIdFromQuery, type ParsedId } from "./lib/ids";
import { parseBatch, type ParsedBatch } from "./lib/batch";
import { createPaymentMiddleware, DEFAULT_NETWORK } from "./payments";
import { llmsTxt, openApiDocument, SERVICE_DESCRIPTION, type DiscoveryContext } from "./discovery/openapi";
import { landingHtml } from "./discovery/landing";
import { PRODUCTS, SERVICE_NAME } from "./products";
import { RegonClient, REGON_TEST_KEY } from "./sources/regon/client";
import { RegonService } from "./services/regon";
import { UpstreamError } from "./sources/errors";
import { toVerifyResult } from "./views/verify";
import { mapLimit } from "./lib/pool";

export interface Deps {
  /** Upstream fetch (tests inject a fake registry). */
  fetch?: typeof fetch;
  /** x402 facilitator (tests inject an in-memory one). */
  facilitator?: FacilitatorClient;
}

type Vars = { id: ParsedId; batch: ParsedBatch };
export type AppEnv = { Bindings: Env; Variables: Vars };

interface Services {
  regon: RegonService;
}

export function createApp(deps: Deps = {}) {
  const app = new Hono<AppEnv>();

  // Per-isolate singletons: env is fixed for the lifetime of an isolate.
  let services: Services | null = null;
  let pay: MiddlewareHandler | null = null;

  const svc = (env: Env): Services => {
    if (!services) {
      const regonEnv = env.REGON_ENV === "test" ? "test" : "prod";
      const regon = new RegonClient({
        apiKey: env.REGON_API_KEY ?? (regonEnv === "test" ? REGON_TEST_KEY : ""),
        env: regonEnv,
        url: env.REGON_URL || undefined,
        fetch: deps.fetch,
      });
      services = { regon: new RegonService(regon, env.CACHE) };
    }
    return services;
  };

  const payment: MiddlewareHandler<AppEnv> = async (c, next) => {
    // Fail closed: never serve paid data for free because of missing config.
    if (!c.env.PAY_TO) return c.json({ error: "service_misconfigured", message: "PAY_TO is not set" }, 503);
    pay ??= createPaymentMiddleware(c.env, deps.facilitator);
    return pay(c, next);
  };

  const rateLimit: MiddlewareHandler<AppEnv> = async (c, next) => {
    const limiter = c.env.IP_LIMITER;
    if (limiter) {
      const ip = c.req.header("cf-connecting-ip") ?? "unknown";
      const { success } = await limiter.limit({ key: ip });
      if (!success) {
        c.header("Retry-After", "60");
        return c.json({ error: "rate_limited", message: "Too many requests from this IP, retry in a minute." }, 429);
      }
    }
    await next();
  };

  // Validation runs before payment: malformed input gets a free 400.
  const requireId: MiddlewareHandler<AppEnv> = async (c, next) => {
    const r = parseIdFromQuery(c.req.query());
    if (!r.ok) return c.json({ error: "invalid_request", message: r.error }, 400);
    c.set("id", r.id);
    await next();
  };

  const requireBatch: MiddlewareHandler<AppEnv> = async (c, next) => {
    let body: unknown;
    try {
      body = await c.req.json();
    } catch {
      return c.json({ error: "invalid_request", message: "Body must be JSON." }, 400);
    }
    const parsed = parseBatch(body);
    if (parsed.error) return c.json({ error: "invalid_request", message: parsed.error, invalid: parsed.invalid }, 400);
    c.set("batch", parsed);
    await next();
  };

  const upstreamFailure = (c: Context<AppEnv>, err: unknown) => {
    // Any status >= 400 cancels x402 settlement: the agent is not charged.
    if (err instanceof UpstreamError) {
      console.error(err.message);
      c.header("Retry-After", "30");
      return c.json({ error: "upstream_unavailable", source: err.source, message: "Official register temporarily unavailable; you were not charged. Retry later." }, 503);
    }
    console.error(err);
    return c.json({ error: "internal_error", message: "You were not charged." }, 500);
  };

  app.use("*", cors({ origin: "*", exposeHeaders: ["PAYMENT-REQUIRED", "PAYMENT-RESPONSE", "X-PAYMENT-RESPONSE"] }));

  app.get("/health", (c) => c.json({ ok: true }));

  // ---- free discovery documents ----
  const discoveryCtx = (c: Context<AppEnv>): DiscoveryContext => ({
    baseUrl: (c.env.PUBLIC_BASE_URL || new URL(c.req.url).origin).replace(/\/+$/, ""),
    network: c.env.NETWORK ?? DEFAULT_NETWORK,
    payTo: c.env.PAY_TO ?? "",
  });
  app.get("/openapi.json", (c) => c.json(openApiDocument(discoveryCtx(c))));
  app.get("/llms.txt", (c) => c.text(llmsTxt(discoveryCtx(c))));
  app.get("/", (c) => {
    const ctx = discoveryCtx(c);
    if ((c.req.header("accept") ?? "").includes("text/html")) return c.html(landingHtml(ctx));
    return c.json({
      name: SERVICE_NAME,
      description: SERVICE_DESCRIPTION,
      payment: { protocol: "x402", network: ctx.network, asset: "USDC" },
      endpoints: PRODUCTS.map((p) => ({ method: p.method, path: p.path, price: p.price, summary: p.summary })),
      docs: { openapi: `${ctx.baseUrl}/openapi.json`, llms: `${ctx.baseUrl}/llms.txt`, legal: `${ctx.baseUrl}/legal` },
    });
  });

  app.get("/pl/company/verify", rateLimit, requireId, payment, async (c) => {
    const id = c.get("id");
    try {
      const r = await svc(c.env).regon.core(id);
      return c.json(toVerifyResult(id, r));
    } catch (err) {
      return upstreamFailure(c, err);
    }
  });

  app.post("/pl/company/verify/batch", rateLimit, requireBatch, payment, async (c) => {
    const { ids, invalid } = c.get("batch");
    const regon = svc(c.env).regon;
    try {
      const byKind = new Map<ParsedId["kind"], string[]>();
      for (const id of ids) byKind.set(id.kind, [...(byKind.get(id.kind) ?? []), id.value]);
      const found = new Map<string, Awaited<ReturnType<RegonService["core"]>>>();
      await mapLimit([...byKind.entries()], 3, async ([kind, values]) => {
        const res = await regon.coreMany(kind, values);
        for (const [v, r] of res) found.set(`${kind}:${v}`, r);
      });
      const results = ids.map((id) => toVerifyResult(id, found.get(`${id.kind}:${id.value}`)!));
      return c.json({ count: results.length, results, invalid });
    } catch (err) {
      return upstreamFailure(c, err);
    }
  });

  return app;
}
