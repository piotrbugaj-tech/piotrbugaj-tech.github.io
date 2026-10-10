import { Hono, type Context, type MiddlewareHandler } from "hono";
import { cors } from "hono/cors";
import type { FacilitatorClient } from "@x402/core/server";
import type { Env } from "./env";
import { normalizeNip, parseIdFromQuery, type ParsedId } from "./lib/ids";
import { parseBatch, type ParsedBatch } from "./lib/batch";
import { CDP_FACILITATOR, createPaymentMiddleware, DEFAULT_FACILITATOR, DEFAULT_NETWORK } from "./payments";
import { ICON_SVG, llmsTxt, openApiDocument, SERVICE_DESCRIPTION, wellKnownX402, type DiscoveryContext } from "./discovery/openapi";
import { landingHtml } from "./discovery/landing";
import { PRODUCTS, SERVICE_NAME } from "./products";
import { RegonClient, REGON_TEST_KEY } from "./sources/regon/client";
import { RegonService, type RegonCore } from "./services/regon";
import { SearchIndex } from "./services/search-index";
import { nameTokens } from "./lib/namematch";
import { KrsService } from "./services/krs";
import { KrsClient } from "./sources/krs/client";
import { buildProfile } from "./services/profile";
import { CeidgService } from "./services/ceidg";
import { CeidgClient } from "./sources/ceidg/client";
import { warsawDate, WhitelistService } from "./services/whitelist";
import { WhitelistClient, WhitelistInputError } from "./sources/whitelist/client";
import { ViesService } from "./services/vies";
import { ViesClient } from "./sources/vies/client";
import { normalizeNrb } from "./lib/nrb";
import { attribution } from "./sources/attribution";
import { SCHEMA_VERSION } from "./schema/company";
import { UpstreamError } from "./sources/errors";
import { regonStatus, toVerifyResult } from "./views/verify";
import { mapLimit } from "./lib/pool";
import { optOutKey, policyFrom } from "./policy";
import { legalHtml } from "./discovery/legal";

const SEARCH_COVERAGE =
  "Legal entities (companies, foundations, associations, cooperatives…) indexed from official REGON/KRS records; status is as of the last lookup — call /pl/company/verify for the current status. Sole traders are not searchable by name (GDPR).";

export interface Deps {
  /** Upstream fetch (tests inject a fake registry). */
  fetch?: typeof fetch;
  /** x402 facilitator (tests inject an in-memory one). */
  facilitator?: FacilitatorClient;
}

type Vars = { id: ParsedId; batch: ParsedBatch; account: string };
export type AppEnv = { Bindings: Env; Variables: Vars };

interface Services {
  regon: RegonService;
  krs: KrsService;
  index: SearchIndex;
  ceidg?: CeidgService;
  whitelist: WhitelistService;
  vies: ViesService;
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
      const krs = new KrsClient({ fetch: deps.fetch, baseUrl: env.KRS_URL || undefined });
      const ceidg = env.CEIDG_API_TOKEN
        ? new CeidgService(
            new CeidgClient({ token: env.CEIDG_API_TOKEN, env: env.CEIDG_ENV === "test" ? "test" : "prod", fetch: deps.fetch, limiter: env.UPSTREAM_LIMITER }),
            env.CACHE,
          )
        : undefined;
      services = {
        regon: new RegonService(regon, env.CACHE),
        krs: new KrsService(krs, env.CACHE),
        index: new SearchIndex(env.INDEX_DB),
        ceidg,
        whitelist: new WhitelistService(new WhitelistClient({ fetch: deps.fetch }), env.CACHE),
        vies: new ViesService(new ViesClient({ fetch: deps.fetch }), env.CACHE),
      };
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

  const isPaying = (c: Context<AppEnv>) => !!(c.req.header("payment-signature") || c.req.header("x-payment"));

  // Validation runs before payment: malformed input gets a free 400.
  // A bare unpaid request (no parameters) is a discovery probe from a catalog
  // (CDP Bazaar validate, x402scan, 402index): it must get the 402 challenge.
  const requireId: MiddlewareHandler<AppEnv> = async (c, next) => {
    const q = c.req.query();
    if (!isPaying(c) && !q.nip && !q.regon && !q.krs) return next();
    const r = parseIdFromQuery(q);
    if (!r.ok) return c.json({ error: "invalid_request", message: r.error }, 400);
    c.set("id", r.id);
    await next();
  };

  // Art. 21 GDPR objections: identifiers on the exclusion list are not disclosed (free 451).
  const optOut: MiddlewareHandler<AppEnv> = async (c, next) => {
    const id = c.get("id");
    if (id && c.env.CACHE && (await c.env.CACHE.get(optOutKey(id.kind, id.value)))) {
      return c.json({ error: "unavailable_for_legal_reasons", message: "Data for this identifier is withheld following a data-subject objection." }, 451);
    }
    await next();
  };

  const nameParam = (c: Context<AppEnv>) => {
    const n = c.req.query("name")?.trim();
    return n ? n.slice(0, 200) : undefined;
  };

  const requireBatch: MiddlewareHandler<AppEnv> = async (c, next) => {
    const text = await c.req.text();
    if (!isPaying(c) && text.trim() === "") return next(); // discovery probe -> 402
    let body: unknown;
    try {
      body = JSON.parse(text);
    } catch {
      return c.json({ error: "invalid_request", message: "Body must be JSON." }, 400);
    }
    const parsed = parseBatch(body);
    if (parsed.error) return c.json({ error: "invalid_request", message: parsed.error, invalid: parsed.invalid }, 400);
    c.set("batch", parsed);
    await next();
  };

  /** Runs work after the response (Workers waitUntil); awaited inline where no execution context exists (tests). */
  const background = async (c: Context<AppEnv>, work: Promise<unknown>) => {
    const guarded = work.catch((err) => console.warn("background task failed", err));
    try {
      c.executionCtx.waitUntil(guarded);
    } catch {
      await guarded;
    }
  };

  /** Every resolved legal entity feeds the name-search index (natural persons are refused by the index). */
  const indexCore = (c: Context<AppEnv>, core: RegonCore) => {
    if (!core.found || !core.basic) return;
    return background(
      c,
      svc(c.env).index.upsert({
        nip: core.basic.nip,
        regon: core.basic.regon,
        krs: core.details?.krs ?? null,
        name: core.details?.name ?? core.basic.name,
        legalForm: core.details?.legalForm ?? (core.basic.type === "F" ? "sole_proprietorship" : null),
        status: regonStatus(core),
        city: core.basic.address.city,
        source: "REGON",
      }),
    );
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

  // Operational readiness (no secrets, only whether things are configured).
  app.get("/health", async (c) => {
    const e = c.env;
    const network = e.NETWORK ?? DEFAULT_NETWORK;
    const facilitator = e.FACILITATOR_URL || (e.CDP_API_KEY_ID ? CDP_FACILITATOR : DEFAULT_FACILITATOR);
    const checks = {
      payTo: !!e.PAY_TO,
      publicBaseUrlHttps: !!e.PUBLIC_BASE_URL?.startsWith("https://"),
      // x402.org only serves testnets; mainnet needs CDP (or another mainnet facilitator).
      facilitatorMatchesNetwork: !(network === "eip155:8453" && facilitator.includes("x402.org")),
      regonProductionKey: e.REGON_ENV !== "test" && !!e.REGON_API_KEY,
      cache: !!e.CACHE,
      searchIndex: !!e.INDEX_DB,
    };
    return c.json({
      ok: checks.payTo,
      ready: Object.values(checks).every(Boolean),
      network,
      facilitator: new URL(facilitator).host,
      naturalPersons: policy(c).naturalPersons,
      indexedEntities: await svc(e).index.count().catch(() => null),
      checks,
    });
  });

  // ---- free discovery documents ----
  const discoveryCtx = (c: Context<AppEnv>): DiscoveryContext => ({
    baseUrl: (c.env.PUBLIC_BASE_URL || new URL(c.req.url).origin).replace(/\/+$/, ""),
    network: c.env.NETWORK ?? DEFAULT_NETWORK,
    payTo: c.env.PAY_TO ?? "",
    contactEmail: c.env.CONTACT_EMAIL,
  });
  app.get("/openapi.json", (c) => c.json(openApiDocument(discoveryCtx(c))));
  app.get("/.well-known/x402", (c) => c.json(wellKnownX402(discoveryCtx(c))));
  app.get("/.well-known/402index-verify.txt", (c) => (c.env.INDEX402_VERIFY_TOKEN ? c.text(c.env.INDEX402_VERIFY_TOKEN) : c.notFound()));
  app.get("/icon.svg", (c) => c.body(ICON_SVG, 200, { "Content-Type": "image/svg+xml", "Cache-Control": "public, max-age=86400" }));
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

  const policy = (c: Context<AppEnv>) => policyFrom(c.env, discoveryCtx(c).baseUrl);

  app.get("/legal", (c) => c.html(legalHtml({ ...discoveryCtx(c), operator: c.env.OPERATOR_NAME, privacyContact: c.env.PRIVACY_CONTACT })));

  app.get("/pl/company/verify", rateLimit, requireId, optOut, payment, async (c) => {
    const id = c.get("id");
    try {
      const r = await svc(c.env).regon.core(id);
      await indexCore(c, r.value);
      return c.json(toVerifyResult(id, r, policy(c), nameParam(c)));
    } catch (err) {
      return upstreamFailure(c, err);
    }
  });

  app.get("/pl/company", rateLimit, requireId, optOut, payment, async (c) => {
    const id = c.get("id");
    const include = new Set((c.req.query("include") ?? "").split(",").map((s) => s.trim()));
    try {
      const r = await buildProfile(svc(c.env), {
        id,
        includeRepresentation: include.has("representation"),
        includeVat: include.has("vat"),
        policy: policy(c),
      });
      if (!r.found) {
        // 404 cancels settlement: a profile miss is free (use /verify for paid existence checks).
        return c.json({ error: "not_found", message: `No entity with ${id.kind.toUpperCase()} ${id.value} in REGON/KRS. You were not charged.` }, 404);
      }
      const p = r.profile;
      await background(
        c,
        svc(c.env).index.upsert({
          ...p.identifiers,
          name: p.name ?? "",
          legalForm: p.legalForm.normalized,
          status: p.status.code,
          city: p.address?.city ?? null,
          source: p.registries.krs ? "KRS" : "REGON",
        }),
      );
      return c.json(p);
    } catch (err) {
      return upstreamFailure(c, err);
    }
  });

  // Validation before payment; a bare unpaid probe gets the 402.
  const requireSearch: MiddlewareHandler<AppEnv> = async (c, next) => {
    const name = c.req.query("name")?.trim() ?? "";
    if (!isPaying(c) && !name) return next();
    if (nameTokens(name).join("").length < 3) {
      return c.json({ error: "invalid_request", message: "Parameter 'name' needs at least 3 significant characters (legal-form words like 'sp. z o.o.' are ignored)." }, 400);
    }
    await next();
  };

  app.get("/pl/company/search", rateLimit, requireSearch, payment, async (c) => {
    const name = c.req.query("name")!.trim().slice(0, 200);
    const city = c.req.query("city")?.trim() || undefined;
    const limit = Number(c.req.query("limit") ?? 10);
    const results = await svc(c.env).index.search(name, { city, limit });
    if (results.length === 0) {
      // 404 cancels settlement: an empty search is free.
      return c.json({ error: "not_found", message: "No matching legal entity in the index. You were not charged.", coverage: SEARCH_COVERAGE }, 404);
    }
    return c.json({
      query: { name, city: city ?? null },
      count: results.length,
      results,
      coverage: SEARCH_COVERAGE,
      notice: policy(c).notice,
    });
  });

  // Validation before payment (NIP + NRB checksums); a bare unpaid probe gets the 402.
  const requireAccountCheck: MiddlewareHandler<AppEnv> = async (c, next) => {
    const nip = c.req.query("nip");
    const account = c.req.query("account");
    if (!isPaying(c) && !nip && !account) return next();
    const n = nip ? normalizeNip(nip) : null;
    const a = account ? normalizeNrb(account) : null;
    if (!n || !a) {
      return c.json({ error: "invalid_request", message: "Provide a valid nip (10 digits, checksum) and account (Polish NRB/IBAN, 26 digits, checksum)." }, 400);
    }
    c.set("id", { kind: "nip", value: n });
    c.set("account", a);
    await next();
  };

  app.get("/pl/vat/account-check", rateLimit, requireAccountCheck, optOut, payment, async (c) => {
    const nip = c.get("id").value;
    const account = c.get("account");
    try {
      const r = await svc(c.env).whitelist.checkAccount(nip, account);
      return c.json({
        schemaVersion: SCHEMA_VERSION,
        query: { nip, account: `PL${account.slice(0, 2)} **** ${account.slice(-4)}` },
        assigned: r.value.assigned,
        date: warsawDate(r.fetchedAt),
        whiteListRequestId: r.value.requestId,
        whiteListRequestDateTime: r.value.requestDateTime,
        sources: [attribution("MF_WL", r.fetchedAt, r.cached)],
        notice:
          policy(c).notice +
          " The white-list query was performed by this service, not by you; for the Polish tax safe harbour keep your own verification record.",
      });
    } catch (err) {
      if (err instanceof WhitelistInputError) return c.json({ error: "invalid_request", message: err.message }, 400);
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
        for (const [v, r] of res) {
          found.set(`${kind}:${v}`, r);
          await indexCore(c, r.value);
        }
      });
      const pol = policy(c);
      const withheld: ParsedId[] = [];
      const results = [];
      for (const id of ids) {
        if (c.env.CACHE && (await c.env.CACHE.get(optOutKey(id.kind, id.value)))) withheld.push(id);
        else results.push(toVerifyResult(id, found.get(`${id.kind}:${id.value}`)!, pol));
      }
      return c.json({ count: results.length, results, invalid, ...(withheld.length ? { withheld } : {}) });
    } catch (err) {
      return upstreamFailure(c, err);
    }
  });

  return app;
}
