import { PRODUCTS, SERVICE_NAME, type Product } from "../products";
import { BATCH_MAX } from "../lib/batch";

export interface DiscoveryContext {
  baseUrl: string;
  network: string;
  payTo: string;
  contactEmail?: string;
}

export const SERVICE_DESCRIPTION =
  "Official Polish company registry data (GUS REGON, KRS court register, CEIDG) for AI agents. " +
  "Verify a counterparty, get a normalised company profile, search by name or verify in bulk. " +
  "Pay per call in USDC via x402 — no signup, no API key.";

export const networkLabel = (n: string) =>
  n === "eip155:8453" ? "Base" : n === "eip155:84532" ? "Base Sepolia (testnet)" : n;

function operation(p: Product, ctx: DiscoveryContext) {
  const op: Record<string, unknown> = {
    operationId: p.id.replace(/-(\w)/g, (_, c: string) => c.toUpperCase()),
    summary: p.summary,
    description: `${p.description}\n\nPrice: ${p.price} (USDC on ${networkLabel(ctx.network)}, x402).`,
    security: [],
    // agentcash / x402scan discovery format.
    "x-payment-info": {
      price:
        p.unitPrice !== undefined
          ? { mode: "dynamic", currency: "USD", min: String(p.minPrice ?? p.unitPrice), max: String(Math.max(p.minPrice ?? 0, p.unitPrice * BATCH_MAX)) }
          : { mode: "fixed", currency: "USD", amount: p.price.replace("$", "") },
      protocols: [{ x402: {} }],
    },
    responses: {
      "200": { description: "Success", content: { "application/json": { example: p.outputExample } } },
      "400": { description: "Invalid input (free — validated before payment)." },
      "402": { description: "Payment required. The PAYMENT-REQUIRED header carries x402 payment requirements." },
      "429": { description: "Rate limited." },
      "503": { description: "Official register unavailable — the payment is not settled." },
    },
  };
  if (p.queryParams) {
    op.parameters = Object.entries(p.queryParams).map(([name, q]) => ({
      name,
      in: "query",
      required: !!q.required,
      description: q.description,
      schema: { type: q.type, ...(q.enum ? { enum: q.enum } : {}) },
      ...(q.example ? { example: q.example } : {}),
    }));
  }
  if (p.bodySchema) {
    op.requestBody = { required: true, content: { "application/json": { schema: p.bodySchema, example: p.bodyExample } } };
  }
  return op;
}

export function openApiDocument(ctx: DiscoveryContext) {
  const paths: Record<string, Record<string, unknown>> = {};
  for (const p of PRODUCTS) {
    paths[p.path] ??= {};
    paths[p.path][p.method.toLowerCase()] = operation(p, ctx);
  }
  return {
    openapi: "3.1.0",
    info: {
      title: SERVICE_NAME,
      version: "1.0.0",
      description: `${SERVICE_DESCRIPTION} Payments: x402 v2, USDC on ${networkLabel(ctx.network)} (${ctx.network}).`,
      ...(ctx.contactEmail ? { contact: { email: ctx.contactEmail } } : {}),
      "x-guidance":
        "Validate identifiers first (invalid NIP/REGON/KRS → free 400). Use /pl/company/verify for yes/no checks, " +
        "/pl/company for full profiles, /pl/company/search when you only know the name, /pl/company/verify/batch for lists.",
    },
    "x-agentcash-guidance": { llmsTxtUrl: `${ctx.baseUrl}/llms.txt` },
    servers: [{ url: ctx.baseUrl }],
    paths,
    externalDocs: { description: "Data sources, licences and privacy", url: `${ctx.baseUrl}/legal` },
  };
}

export function llmsTxt(ctx: DiscoveryContext): string {
  const lines = [
    `# ${SERVICE_NAME}`,
    "",
    `> ${SERVICE_DESCRIPTION}`,
    "",
    `Payments: x402 v2, scheme "exact", USDC on ${networkLabel(ctx.network)} (${ctx.network}). Call an endpoint, receive HTTP 402 with a PAYMENT-REQUIRED header, pay, retry with PAYMENT-SIGNATURE. Invalid input is rejected with a free 400 before any payment. If an official register is down you get 503 and are not charged.`,
    "",
    "## Endpoints",
    "",
    ...PRODUCTS.map((p) => {
      const params = p.queryParams ? "?" + Object.keys(p.queryParams).map((k) => `${k}=`).join("&") : " (JSON body)";
      return `- [${p.method} ${p.path}](${ctx.baseUrl}${p.path}): ${p.summary} Price: ${p.price}. Params: ${p.method === "GET" ? params : JSON.stringify(p.bodyExample)}`;
    }),
    "",
    "## Docs",
    "",
    `- [OpenAPI](${ctx.baseUrl}/openapi.json): full schemas and examples`,
    `- [x402 discovery](${ctx.baseUrl}/.well-known/x402): machine-readable list of paid resources`,
    `- [Legal & sources](${ctx.baseUrl}/legal): data sources, licences, privacy notice`,
    "",
    "## Identifiers",
    "",
    "- NIP: 10-digit tax id (checksum validated). REGON: 9 or 14 digits. KRS: up to 10 digits (zero-padded).",
    "- Status values: active, suspended, in_liquidation, in_bankruptcy, removed, not_started, unknown (verify also: not_found).",
    "",
  ];
  return lines.join("\n");
}

/** x402scan-compatible /.well-known/x402 (no formal x402 spec; OpenAPI is preferred). */
export function wellKnownX402(ctx: DiscoveryContext) {
  return { version: 1, resources: [...new Set(PRODUCTS.map((p) => ctx.baseUrl + p.path))] };
}

export const ICON_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="12" fill="#1f2937"/><rect x="8" y="14" width="48" height="18" fill="#ffffff"/><rect x="8" y="32" width="48" height="18" fill="#dc143c"/><text x="32" y="44" font-family="Arial,sans-serif" font-size="13" font-weight="700" text-anchor="middle" fill="#ffffff">402</text></svg>`;
