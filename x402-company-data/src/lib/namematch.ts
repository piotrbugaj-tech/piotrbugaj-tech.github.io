import { fold } from "./normalize";

// Legal-form words and abbreviations that should not influence name matching.
const NOISE = new Set([
  "SPOLKA", "SPOLKI", "Z", "O", "OO", "ZOO", "ODPOWIEDZIALNOSCIA", "OGRANICZONA", "SP", "SA", "S", "A", "AKCYJNA", "KOMANDYTOWA",
  "KOMANDYTOWO", "AKCYJNA", "JAWNA", "PARTNERSKA", "CYWILNA", "PROSTA", "SPJ", "SPK", "SKA", "PSA", "SC", "W", "LIKWIDACJI",
  "UPADLOSCI", "I", "ORAZ", "FIRMA", "PRZEDSIEBIORSTWO",
]);

export function nameTokens(name: string): string[] {
  return fold(name)
    .replace(/[^A-Z0-9]+/g, " ")
    .split(" ")
    .filter((t) => t.length > 0 && !NOISE.has(t));
}

export interface NameMatch {
  /** 0..1 — share of the caller's tokens found in the registered name (and vice versa, averaged). */
  score: number;
  result: "match" | "partial" | "mismatch";
}

/**
 * Compares a caller-supplied name with the registered one without revealing
 * the registered name (useful for sole traders, whose names are personal data).
 */
export function matchName(candidate: string, registered: string): NameMatch {
  const a = new Set(nameTokens(candidate));
  const b = new Set(nameTokens(registered));
  if (a.size === 0 || b.size === 0) return { score: 0, result: "mismatch" };
  let common = 0;
  for (const t of a) if (b.has(t)) common++;
  const score = Math.round(((common / a.size + common / b.size) / 2) * 100) / 100;
  const result = common === a.size && common === b.size ? "match" : common / a.size >= 0.6 ? "partial" : "mismatch";
  return { score, result };
}
