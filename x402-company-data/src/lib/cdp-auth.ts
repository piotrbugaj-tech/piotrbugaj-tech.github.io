// Coinbase Developer Platform (CDP) API-key JWTs for the CDP x402 facilitator,
// implemented with WebCrypto only (the official @coinbase/cdp-sdk pulls in
// axios + Solana deps we don't want in a Worker bundle).
//
// Supports both CDP key types:
//  - Ed25519 ("EdDSA"): secret = base64(32-byte seed || 32-byte public key)
//  - ECDSA P-256 ("ES256"): secret = PEM "BEGIN EC PRIVATE KEY" (SEC1) or "BEGIN PRIVATE KEY" (PKCS#8)

const enc = new TextEncoder();

function b64urlBytes(bytes: Uint8Array): string {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
const b64urlJson = (o: unknown) => b64urlBytes(enc.encode(JSON.stringify(o)));

function b64decode(s: string): Uint8Array {
  const bin = atob(s.replace(/\s+/g, ""));
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
}

/** Wraps a SEC1 ECPrivateKey (P-256) into PKCS#8 so WebCrypto can import it. */
function sec1ToPkcs8(sec1: Uint8Array): Uint8Array {
  const algId = [0x30, 0x13, 0x06, 0x07, 0x2a, 0x86, 0x48, 0xce, 0x3d, 0x02, 0x01, 0x06, 0x08, 0x2a, 0x86, 0x48, 0xce, 0x3d, 0x03, 0x01, 0x07];
  const derLen = (n: number) => (n < 0x80 ? [n] : n < 0x100 ? [0x81, n] : [0x82, n >> 8, n & 0xff]);
  const octet = [0x04, ...derLen(sec1.length), ...sec1];
  const body = [0x02, 0x01, 0x00, ...algId, ...octet];
  return Uint8Array.from([0x30, ...derLen(body.length), ...body]);
}

type LoadedKey = { key: CryptoKey; alg: "EdDSA" | "ES256" };
const keyCache = new Map<string, Promise<LoadedKey>>();

async function loadKey(secret: string): Promise<LoadedKey> {
  const pem = secret.replace(/\\n/g, "\n").trim();
  if (pem.includes("BEGIN")) {
    const b64 = pem.replace(/-----[^-]+-----/g, "");
    const der = b64decode(b64);
    const pkcs8 = pem.includes("BEGIN EC PRIVATE KEY") ? sec1ToPkcs8(der) : der;
    const key = await crypto.subtle.importKey("pkcs8", pkcs8, { name: "ECDSA", namedCurve: "P-256" }, false, ["sign"]);
    return { key, alg: "ES256" };
  }
  const raw = b64decode(pem);
  if (raw.length !== 64) throw new Error("CDP_API_KEY_SECRET: expected PEM (ES256) or base64 64-byte Ed25519 key");
  const jwk = { kty: "OKP", crv: "Ed25519", d: b64urlBytes(raw.slice(0, 32)), x: b64urlBytes(raw.slice(32)) };
  const key = await crypto.subtle.importKey("jwk", jwk, { name: "Ed25519" }, false, ["sign"]);
  return { key, alg: "EdDSA" };
}

export async function cdpJwt(keyId: string, secret: string, method: string, url: string, ttlSeconds = 120): Promise<string> {
  let loaded = keyCache.get(secret);
  if (!loaded) {
    loaded = loadKey(secret);
    keyCache.set(secret, loaded);
  }
  const { key, alg } = await loaded;
  const u = new URL(url);
  const now = Math.floor(Date.now() / 1000);
  const nonce = b64urlBytes(crypto.getRandomValues(new Uint8Array(16))).slice(0, 16);
  const header = { alg, kid: keyId, typ: "JWT", nonce };
  const claims = { sub: keyId, iss: "cdp", nbf: now, iat: now, exp: now + ttlSeconds, uris: [`${method} ${u.host}${u.pathname}`] };
  const input = `${b64urlJson(header)}.${b64urlJson(claims)}`;
  const sig = await crypto.subtle.sign(alg === "EdDSA" ? { name: "Ed25519" } : { name: "ECDSA", hash: "SHA-256" }, key, enc.encode(input));
  return `${input}.${b64urlBytes(new Uint8Array(sig))}`;
}

/** Headers for HTTPFacilitatorClient.createAuthHeaders. */
export async function cdpAuthHeaders(facilitatorUrl: string, keyId: string, secret: string) {
  const base = facilitatorUrl.replace(/\/+$/, "");
  const auth = async (method: string, path: string) => ({ Authorization: `Bearer ${await cdpJwt(keyId, secret, method, base + path)}` });
  const [verify, settle, supported, bazaar] = await Promise.all([
    auth("POST", "/verify"),
    auth("POST", "/settle"),
    auth("GET", "/supported"),
    auth("GET", "/discovery/resources"),
  ]);
  return { verify, settle, supported, bazaar };
}
