// End-to-end smoke test in the real Workers runtime (workerd via `wrangler dev`),
// with a local fake x402 facilitator and a fake GUS REGON endpoint.
// Proves the paid path (402 → signed payment → data → settlement) works on workerd.
//
//   node scripts/smoke-workerd.mjs
import http from "node:http";
import { spawn } from "node:child_process";
import { privateKeyToAccount, generatePrivateKey } from "viem/accounts";
import { x402Client, wrapFetchWithPayment, decodePaymentResponseHeader } from "@x402/fetch";
import { registerExactEvmScheme } from "@x402/evm/exact/client";

const FAKE_PORT = 8790;
const WORKER_PORT = 8788;
const NETWORK = "eip155:84532";
let settles = 0;

const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const dane = (rows) => esc(`<root>${rows.map((r) => `<dane>${Object.entries(r).map(([k, v]) => `<${k}>${esc(v)}</${k}>`).join("")}</dane>`).join("")}</root>`);
const soap = (op, result) =>
  `--uuid:x+id=1\r\nContent-Type: application/xop+xml;charset=utf-8;type="application/soap+xml"\r\n\r\n` +
  `<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"><s:Body><${op}Response xmlns="http://CIS/BIR/PUBL/2014/07"><${op}Result>${result}</${op}Result></${op}Response></s:Body></s:Envelope>\r\n--uuid:x+id=1--`;

const ORLEN_SEARCH = { Regon: "610188201", Nip: "7740001454", Nazwa: "ORLEN SPÓŁKA AKCYJNA", Miejscowosc: "Płock", KodPocztowy: "09-411", Typ: "P", SilosID: "6", DataZakonczeniaDzialalnosci: "" };
const ORLEN_REPORT = { praw_regon9: "610188201", praw_nip: "7740001454", praw_nazwa: "ORLEN SPÓŁKA AKCYJNA", praw_szczegolnaFormaPrawna_Nazwa: "SPÓŁKI AKCYJNE", praw_adSiedzMiejscowosc_Nazwa: "Płock", praw_adSiedzKodPocztowy: "09411" };

const server = http.createServer(async (req, res) => {
  let body = "";
  for await (const chunk of req) body += chunk;
  const json = (status, obj) => { res.writeHead(status, { "content-type": "application/json" }); res.end(JSON.stringify(obj)); };
  if (req.url === "/facilitator/supported") return json(200, { kinds: [{ x402Version: 2, scheme: "exact", network: NETWORK }], extensions: ["bazaar"], signers: {} });
  if (req.url === "/facilitator/verify") { const b = JSON.parse(body); return json(200, { isValid: true, payer: b.paymentPayload.payload.authorization.from }); }
  if (req.url === "/facilitator/settle") { settles++; const b = JSON.parse(body); return json(200, { success: true, transaction: "0x" + "cd".repeat(32), network: NETWORK, payer: b.paymentPayload.payload.authorization.from }); }
  if (req.url === "/regon") {
    const op = /IUslugaBIR(?:zewnPubl)?\/(\w+)<\/wsa:Action>/.exec(body)?.[1];
    const result = op === "Zaloguj" ? "smoke-sid" : op === "DaneSzukajPodmioty" ? dane([ORLEN_SEARCH]) : op === "DanePobierzPelnyRaport" ? dane([ORLEN_REPORT]) : "";
    res.writeHead(200, { "content-type": "multipart/related; type=\"application/xop+xml\"" });
    return res.end(soap(op, result));
  }
  json(404, {});
});
await new Promise((r) => server.listen(FAKE_PORT, r));

const worker = spawn(
  "npx",
  ["wrangler", "dev", "--port", String(WORKER_PORT),
    "--var", "PAY_TO:0x2222222222222222222222222222222222222222",
    "--var", `NETWORK:${NETWORK}`,
    "--var", `FACILITATOR_URL:http://127.0.0.1:${FAKE_PORT}/facilitator`,
    "--var", `REGON_URL:http://127.0.0.1:${FAKE_PORT}/regon`,
    "--var", `PUBLIC_BASE_URL:http://127.0.0.1:${WORKER_PORT}`],
  { stdio: ["ignore", "pipe", "pipe"], env: { ...process.env, NO_PROXY: "127.0.0.1,localhost" } },
);
let log = "";
worker.stdout.on("data", (d) => (log += d));
worker.stderr.on("data", (d) => (log += d));

const base = `http://127.0.0.1:${WORKER_PORT}`;
const fail = (msg) => { console.error("SMOKE FAIL:", msg, "\n--- wrangler log ---\n", log.slice(-4000)); cleanup(1); };
const cleanup = (code) => { worker.kill("SIGTERM"); server.close(); process.exit(code); };

try {
  for (let i = 0; i < 60; i++) {
    try { if ((await fetch(`${base}/health`)).ok) break; } catch {}
    await new Promise((r) => setTimeout(r, 1000));
  }
  const unpaid = await fetch(`${base}/pl/company/verify?nip=7740001454`);
  if (unpaid.status !== 402) fail(`expected 402, got ${unpaid.status}: ${await unpaid.text()}`);
  const reqs = JSON.parse(atob(unpaid.headers.get("PAYMENT-REQUIRED")));
  console.log("402 OK — amount", reqs.accepts[0].amount, "network", reqs.accepts[0].network, "bazaar:", !!reqs.extensions?.bazaar);
  if (!reqs.extensions?.bazaar) fail("bazaar extension missing from 402 response");

  const client = registerExactEvmScheme(new x402Client(), { signer: privateKeyToAccount(generatePrivateKey()) });
  const paid = await wrapFetchWithPayment(fetch, client)(`${base}/pl/company/verify?nip=7740001454`);
  const body = await paid.json();
  if (paid.status !== 200 || body.name !== "ORLEN SPÓŁKA AKCYJNA" || !body.active) fail(`paid call: ${paid.status} ${JSON.stringify(body)}`);
  const receipt = decodePaymentResponseHeader(paid.headers.get("PAYMENT-RESPONSE"));
  console.log("paid 200 OK —", body.name, body.status, "tx", receipt.transaction.slice(0, 10) + "…", "settles:", settles);
  if (settles !== 1) fail(`expected 1 settlement, got ${settles}`);

  for (const path of ["/openapi.json", "/llms.txt", "/"]) {
    const r = await fetch(base + path);
    if (!r.ok) fail(`${path} -> ${r.status}`);
  }
  console.log("discovery docs OK");
  console.log("SMOKE PASS");
  cleanup(0);
} catch (e) {
  fail(e.stack ?? String(e));
}
