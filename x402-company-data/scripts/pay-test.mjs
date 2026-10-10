// Paid end-to-end test against a deployed Worker (Base Sepolia by default).
//
//   BUYER_PRIVATE_KEY=0x... node scripts/pay-test.mjs https://<your-worker>/pl/company/verify?nip=7740001454
//
// Use a throwaway key funded with test USDC from https://faucet.circle.com (network: Base Sepolia).
// The buyer needs no ETH: the facilitator pays gas. Never use the PAY_TO wallet's key here.
import { privateKeyToAccount } from "viem/accounts";
import { x402Client, wrapFetchWithPayment, decodePaymentResponseHeader } from "@x402/fetch";
import { registerExactEvmScheme } from "@x402/evm/exact/client";

const url = process.argv[2];
const key = process.env.BUYER_PRIVATE_KEY;
if (!url || !key) {
  console.error("usage: BUYER_PRIVATE_KEY=0x... node scripts/pay-test.mjs <url> [json-body-for-POST]");
  process.exit(1);
}
const body = process.argv[3];

const unpaid = await fetch(url, body ? { method: "POST", headers: { "content-type": "application/json" }, body } : {});
console.log("unpaid ->", unpaid.status);
const challenge = unpaid.headers.get("PAYMENT-REQUIRED");
if (challenge) {
  const req = JSON.parse(atob(challenge));
  console.log("price:", Number(req.accepts[0].amount) / 1e6, "USDC on", req.accepts[0].network, "payTo", req.accepts[0].payTo);
}

const account = privateKeyToAccount(key);
const pay = wrapFetchWithPayment(fetch, registerExactEvmScheme(new x402Client(), { signer: account }));
const res = await pay(url, body ? { method: "POST", headers: { "content-type": "application/json" }, body } : {});
console.log("paid ->", res.status);
console.log(JSON.stringify(await res.json(), null, 2));
const receipt = res.headers.get("PAYMENT-RESPONSE");
if (receipt) console.log("receipt:", decodePaymentResponseHeader(receipt));
