// Polish business identifiers: normalisation + checksum validation.
// Validation runs BEFORE the payment middleware, so a malformed identifier
// gets a free 400 instead of a paid "not found".

export type IdKind = "nip" | "regon" | "krs";

export interface ParsedId {
  kind: IdKind;
  value: string;
}

const digitsOnly = (s: string) => s.replace(/[\s-]/g, "");

function weightedSum(digits: string, weights: number[]): number {
  let sum = 0;
  for (let i = 0; i < weights.length; i++) sum += Number(digits[i]) * weights[i];
  return sum;
}

/** NIP: 10 digits, mod-11 checksum on the first 9 (a remainder of 10 is never valid). */
export function normalizeNip(input: string): string | null {
  let s = digitsOnly(input.trim());
  if (/^PL\d{10}$/i.test(s)) s = s.slice(2);
  if (!/^\d{10}$/.test(s)) return null;
  const check = weightedSum(s, [6, 5, 7, 2, 3, 4, 5, 6, 7]) % 11;
  if (check === 10 || check !== Number(s[9])) return null;
  return s;
}

/** REGON: 9 digits (entity) or 14 digits (local unit), each with its own mod-11 checksum. */
export function normalizeRegon(input: string): string | null {
  const s = digitsOnly(input.trim());
  if (/^\d{9}$/.test(s)) {
    const check = weightedSum(s, [8, 9, 2, 3, 4, 5, 6, 7]) % 11 % 10;
    return check === Number(s[8]) ? s : null;
  }
  if (/^\d{14}$/.test(s)) {
    if (normalizeRegon(s.slice(0, 9)) === null) return null;
    const check = weightedSum(s, [2, 4, 8, 5, 0, 9, 7, 3, 6, 1, 2, 4, 8]) % 11 % 10;
    return check === Number(s[13]) ? s : null;
  }
  return null;
}

/** KRS number: up to 10 digits, no checksum; canonical form is zero-padded to 10. */
export function normalizeKrs(input: string): string | null {
  const s = digitsOnly(input.trim());
  if (!/^\d{1,10}$/.test(s) || /^0+$/.test(s)) return null;
  return s.padStart(10, "0");
}

export function normalizeId(kind: IdKind, input: string): string | null {
  switch (kind) {
    case "nip":
      return normalizeNip(input);
    case "regon":
      return normalizeRegon(input);
    case "krs":
      return normalizeKrs(input);
  }
}

export type IdParseResult = { ok: true; id: ParsedId } | { ok: false; error: string };

/**
 * Picks exactly one identifier out of query params (nip | regon | krs).
 */
export function parseIdFromQuery(q: Record<string, string | undefined>): IdParseResult {
  const present = (["nip", "regon", "krs"] as const).filter((k) => q[k] !== undefined && q[k] !== "");
  if (present.length === 0) return { ok: false, error: "Provide exactly one of: nip, regon, krs." };
  if (present.length > 1) return { ok: false, error: `Provide exactly one identifier, got: ${present.join(", ")}.` };
  const kind = present[0];
  const value = normalizeId(kind, q[kind]!);
  if (!value) return { ok: false, error: `Invalid ${kind.toUpperCase()} (format or checksum): "${q[kind]}".` };
  return { ok: true, id: { kind, value } };
}
