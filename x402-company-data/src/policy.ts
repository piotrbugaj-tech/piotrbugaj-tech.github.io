import type { Env } from "./env";

/**
 * Data-protection policy knobs (see docs/research/01-licencje-i-limity.md §6–7).
 *
 * naturalPersons:
 *  - "minimal" (default): for sole traders we confirm existence/status/identifiers and
 *    offer ?name= matching, but do not return the person's name or street address.
 *  - "full": return the business name and address as published in CEIDG/REGON.
 *    Enable only after the owner's GDPR decision (Art. 14 notices, lawyer review).
 */
export interface Policy {
  naturalPersons: "minimal" | "full";
  notice: string;
}

export function policyFrom(env: Env, baseUrl: string): Policy {
  return {
    naturalPersons: env.NATURAL_PERSONS === "full" ? "full" : "minimal",
    notice: `Processed data from public Polish registers; not an official extract (odpis) or certificate. Terms, sources & privacy: ${baseUrl}/legal`,
  };
}

/** KV key marking an identifier whose owner objected (Art. 21 GDPR) — we stop disclosing it. */
export const optOutKey = (kind: string, value: string) => `optout:${kind}:${value}`;
