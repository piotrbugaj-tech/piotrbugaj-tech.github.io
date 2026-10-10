import { describe, expect, it } from "vitest";
import { generatePrivateKey, privateKeyToAccount } from "viem/accounts";
import { createApp } from "../src/app";
import type { Env } from "../src/env";
import { keepalive } from "../src/keepalive";
import { FakeFacilitator, fakeRegon, memoryKV, ORLEN } from "./helpers/fakes";

describe("keepalive cron", () => {
  it("makes one paid in-process call from the keepalive wallet", async () => {
    const facilitator = new FakeFacilitator();
    const app = createApp({ fetch: fakeRegon({ entities: [ORLEN] }).fetch, facilitator });
    const key = generatePrivateKey();
    const env: Env = { PAY_TO: "0x1111111111111111111111111111111111111111", NETWORK: "eip155:84532", CACHE: memoryKV(), PUBLIC_BASE_URL: "https://api.example.test", KEEPALIVE_PRIVATE_KEY: key };
    const r = await keepalive(env, (req) => Promise.resolve(app.fetch(req, env)));
    expect(r.status).toBe(200);
    expect(facilitator.settleCalls).toHaveLength(1);
    expect(facilitator.settleCalls[0].payload.payload).toMatchObject({ authorization: { from: privateKeyToAccount(key).address } });
  });

  it("is a no-op without a key, and refuses to pay from PAY_TO", async () => {
    const app = createApp({ facilitator: new FakeFacilitator() });
    expect((await keepalive({ PUBLIC_BASE_URL: "https://x.test" }, (r) => Promise.resolve(app.fetch(r, {})))).skipped).toBeTruthy();
    const key = generatePrivateKey();
    const env: Env = { PAY_TO: privateKeyToAccount(key).address, PUBLIC_BASE_URL: "https://x.test", KEEPALIVE_PRIVATE_KEY: key };
    expect((await keepalive(env, (r) => Promise.resolve(app.fetch(r, env)))).skipped).toMatch(/differ/);
  });
});
