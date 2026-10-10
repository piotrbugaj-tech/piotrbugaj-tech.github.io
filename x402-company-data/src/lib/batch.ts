import { normalizeId, type IdKind, type ParsedId } from "./ids";

export const BATCH_MAX = 50;

export interface ParsedBatch {
  ids: ParsedId[];
  invalid: Array<{ kind: IdKind; input: string; error: string }>;
  error?: string;
}

/** Parses {"nip": [...], "regon": [...], "krs": [...]}; dedupes; validates checksums. */
export function parseBatch(body: unknown): ParsedBatch {
  const out: ParsedBatch = { ids: [], invalid: [] };
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return { ...out, error: 'Body must be a JSON object like {"nip": ["7740001454", ...]}.' };
  }
  const seen = new Set<string>();
  let total = 0;
  for (const kind of ["nip", "regon", "krs"] as const) {
    const list = (body as Record<string, unknown>)[kind];
    if (list === undefined) continue;
    if (!Array.isArray(list)) return { ...out, error: `"${kind}" must be an array of strings.` };
    for (const raw of list) {
      total++;
      const input = String(raw);
      const value = normalizeId(kind, input);
      if (!value) {
        out.invalid.push({ kind, input, error: "invalid format or checksum" });
        continue;
      }
      const key = `${kind}:${value}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.ids.push({ kind, value });
    }
  }
  if (total === 0) return { ...out, error: "Provide at least one identifier in nip, regon or krs." };
  if (total > BATCH_MAX) return { ...out, error: `At most ${BATCH_MAX} identifiers per batch (got ${total}).` };
  if (out.ids.length === 0) return { ...out, error: "No valid identifiers in the batch." };
  return out;
}

/** Number of billable identifiers (used for dynamic x402 pricing). */
export function batchSize(body: unknown): number {
  const parsed = parseBatch(body);
  return parsed.error ? 0 : parsed.ids.length;
}
