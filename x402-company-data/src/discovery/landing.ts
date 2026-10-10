import { PRODUCTS, SERVICE_NAME } from "../products";
import { networkLabel, SERVICE_DESCRIPTION, type DiscoveryContext } from "./openapi";

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

/** Minimal human-facing page; agents should use /openapi.json or /llms.txt. */
export function landingHtml(ctx: DiscoveryContext): string {
  const rows = PRODUCTS.map(
    (p) =>
      `<tr><td><code>${p.method} ${esc(p.path)}</code></td><td>${esc(p.summary)}</td><td>${esc(p.price)}</td></tr>`,
  ).join("");
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(SERVICE_NAME)}</title>
<meta name="description" content="${esc(SERVICE_DESCRIPTION)}">
<link rel="alternate" type="application/json" href="/openapi.json" title="OpenAPI">
<style>
:root{--bg:#fff;--fg:#1a1a1a;--muted:#5c5c5c;--line:#e3e3e3;--code:#f4f4f4}
@media (prefers-color-scheme:dark){:root{--bg:#121212;--fg:#ececec;--muted:#a0a0a0;--line:#2c2c2c;--code:#1e1e1e}}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,sans-serif}
main{max-width:860px;margin:0 auto;padding:40px 16px}
p{color:var(--muted)} table{width:100%;border-collapse:collapse;margin:24px 0}
td,th{border-bottom:1px solid var(--line);padding:10px 8px;text-align:left;vertical-align:top}
code{background:var(--code);padding:2px 5px;border-radius:4px;font-size:.9em;word-break:break-all}
a{color:inherit}
</style></head><body><main>
<h1>${esc(SERVICE_NAME)}</h1>
<p>${esc(SERVICE_DESCRIPTION)}</p>
<p>Payments: x402, USDC on ${esc(networkLabel(ctx.network))}. No account, no API key.</p>
<table><thead><tr><th>Endpoint</th><th>What</th><th>Price</th></tr></thead><tbody>${rows}</tbody></table>
<p><a href="/openapi.json">OpenAPI</a> · <a href="/llms.txt">llms.txt</a> · <a href="/.well-known/x402">/.well-known/x402</a> · <a href="/legal">Sources, licences &amp; privacy</a></p>
</main></body></html>`;
}
