import { describe, expect, it } from "vitest";
import { createApp } from "../src/app";
import type { Env } from "../src/env";
import { FakeFacilitator } from "./helpers/fakes";

const env: Env = { PAY_TO: "0x1111111111111111111111111111111111111111", NETWORK: "eip155:8453", PUBLIC_BASE_URL: "https://api.example.test", CONTACT_EMAIL: "ops@example.test" };
const app = createApp({ facilitator: new FakeFacilitator("eip155:8453") });
const get = (path: string, headers: Record<string, string> = {}) => app.request(`https://api.example.test${path}`, { headers }, env);

describe("discovery documents", () => {
  it("openapi.json carries agentcash x-payment-info for every paid operation", async () => {
    const doc = (await (await get("/openapi.json")).json()) as any;
    expect(doc.openapi).toBe("3.1.0");
    expect(doc.info.contact.email).toBe("ops@example.test");
    expect(doc["x-agentcash-guidance"].llmsTxtUrl).toBe("https://api.example.test/llms.txt");
    expect(doc.paths["/pl/company/verify"].get["x-payment-info"]).toEqual({ price: { mode: "fixed", currency: "USD", amount: "0.005" }, protocols: [{ x402: {} }] });
    expect(doc.paths["/pl/company/verify/batch"].post["x-payment-info"].price).toEqual({ mode: "dynamic", currency: "USD", min: "0.01", max: "0.15" });
    for (const path of Object.values(doc.paths) as any[]) for (const op of Object.values(path) as any[]) expect(op.security).toEqual([]);
  });

  it("serves /.well-known/x402, llms.txt, the icon and an HTML landing page", async () => {
    expect(await (await get("/.well-known/x402")).json()).toEqual({
      version: 1,
      resources: ["https://api.example.test/pl/company/verify", "https://api.example.test/pl/company", "https://api.example.test/pl/company/search", "https://api.example.test/pl/company/verify/batch"],
    });
    expect(await (await get("/llms.txt")).text()).toContain("/pl/company/verify");
    expect((await get("/icon.svg")).headers.get("content-type")).toBe("image/svg+xml");
    expect(await (await get("/", { accept: "text/html" })).text()).toContain("<table>");
    expect((await get("/.well-known/402index-verify.txt")).status).toBe(404);
  });

  it("402 challenge uses the canonical https resource URL without the query string", async () => {
    const res = await get("/pl/company/verify?nip=7740001454");
    const req = JSON.parse(atob(res.headers.get("PAYMENT-REQUIRED")!));
    expect(req.resource.url).toBe("https://api.example.test/pl/company/verify");
    expect(req.resource.iconUrl ?? req.resource.serviceName).toBeTruthy();
    expect(req.accepts[0].network).toBe("eip155:8453");
  });
});
