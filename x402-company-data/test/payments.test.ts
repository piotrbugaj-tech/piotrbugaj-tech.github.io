import { describe, expect, it, vi } from "vitest";
import { generateKeyPairSync, createPublicKey, verify as nodeVerify } from "node:crypto";
import { validateBazaarRouteExtensions } from "@x402/extensions/bazaar";
import { buildRoutes } from "../src/payments";
import { cdpJwt } from "../src/lib/cdp-auth";

const b64urlDecode = (s: string) => Buffer.from(s.replace(/-/g, "+").replace(/_/g, "/"), "base64");

describe("bazaar discovery metadata", () => {
  it("passes the SDK's schema validation for every paid route", () => {
    // Ajv cannot compile schemas inside workerd (no eval), so we validate here in Node.
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    validateBazaarRouteExtensions(buildRoutes({ PAY_TO: "0x1111111111111111111111111111111111111111" }));
    expect(warn.mock.calls).toEqual([]);
    warn.mockRestore();
  });
});

describe("CDP JWT", () => {
  it("signs Ed25519 keys in CDP's base64(seed||pub) format", async () => {
    const { privateKey, publicKey } = generateKeyPairSync("ed25519");
    const jwk = privateKey.export({ format: "jwk" }) as { d: string; x: string };
    const secret = Buffer.concat([b64urlDecode(jwk.d), b64urlDecode(jwk.x)]).toString("base64");
    const jwt = await cdpJwt("key-id-1", secret, "POST", "https://api.cdp.coinbase.com/platform/v2/x402/settle");
    const [h, p, s] = jwt.split(".");
    expect(JSON.parse(b64urlDecode(h).toString())).toMatchObject({ alg: "EdDSA", kid: "key-id-1", typ: "JWT" });
    expect(JSON.parse(b64urlDecode(p).toString())).toMatchObject({ sub: "key-id-1", iss: "cdp", uris: ["POST api.cdp.coinbase.com/platform/v2/x402/settle"] });
    expect(nodeVerify(null, Buffer.from(`${h}.${p}`), publicKey, b64urlDecode(s))).toBe(true);
  });

  it("signs ES256 keys given as SEC1 PEM", async () => {
    const { privateKey } = generateKeyPairSync("ec", { namedCurve: "P-256" });
    const pem = privateKey.export({ format: "pem", type: "sec1" }).toString();
    const jwt = await cdpJwt("key-id-2", pem, "GET", "https://api.cdp.coinbase.com/platform/v2/x402/supported");
    const [h, p, s] = jwt.split(".");
    expect(JSON.parse(b64urlDecode(h).toString()).alg).toBe("ES256");
    const ok = nodeVerify("sha256", Buffer.from(`${h}.${p}`), { key: createPublicKey(privateKey), dsaEncoding: "ieee-p1363" }, b64urlDecode(s));
    expect(ok).toBe(true);
  });
});
