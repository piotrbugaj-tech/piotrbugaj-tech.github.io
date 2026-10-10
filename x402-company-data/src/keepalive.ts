// Weekly self-test that also keeps the CDP Bazaar listing alive: Bazaar evicts
// resources ~30 days after their last settled call. Pays for one cheap verify
// call from a separate, small "keepalive" wallet (never the PAY_TO wallet).
// Runs in-process (app.fetch) so it doesn't depend on the Worker calling its own hostname.
// Opt-in: set the KEEPALIVE_PRIVATE_KEY secret and a cron trigger in wrangler.jsonc.

import { privateKeyToAccount } from "viem/accounts";
import { x402Client, wrapFetchWithPayment } from "@x402/fetch";
import { registerExactEvmScheme } from "@x402/evm/exact/client";
import type { Env } from "./env";

export const KEEPALIVE_PATH = "/pl/company/verify?nip=7740001454";

export async function keepalive(
  env: Env,
  handle: (req: Request) => Promise<Response>,
): Promise<{ status: number; skipped?: string }> {
  if (!env.KEEPALIVE_PRIVATE_KEY || !env.PUBLIC_BASE_URL) return { status: 0, skipped: "KEEPALIVE_PRIVATE_KEY or PUBLIC_BASE_URL not set" };
  const account = privateKeyToAccount(env.KEEPALIVE_PRIVATE_KEY as `0x${string}`);
  if (env.PAY_TO && account.address.toLowerCase() === env.PAY_TO.toLowerCase()) return { status: 0, skipped: "keepalive wallet must differ from PAY_TO" };
  const client = registerExactEvmScheme(new x402Client(), { signer: account });
  const inProcessFetch = (async (input: RequestInfo | URL, init?: RequestInit) => handle(new Request(input, init))) as typeof fetch;
  const res = await wrapFetchWithPayment(inProcessFetch, client)(env.PUBLIC_BASE_URL.replace(/\/+$/, "") + KEEPALIVE_PATH);
  console.log(`keepalive: ${res.status} payment-response=${res.headers.has("PAYMENT-RESPONSE")}`);
  return { status: res.status };
}
