import type { ParsedId } from "../lib/ids";
import { cached, type Cached } from "../lib/cache";
import { mapLimit } from "../lib/pool";
import { RegonClient, RegonNotFound, REGON_BATCH_MAX, type RegonRecord, type SearchParam } from "../sources/regon/client";
import { basicFromSearch, detailsFromReport, pkdFromReport, reportFor, type RegonBasic, type RegonDetails } from "../sources/regon/normalize";
import type { PkdCode } from "../schema/company";

export const REGON_TTL = 12 * 3600;
export const REGON_NOT_FOUND_TTL = 3600;
export const REGON_PKD_TTL = 7 * 24 * 3600;

export interface RegonCore {
  found: boolean;
  basic: RegonBasic | null;
  details: RegonDetails | null;
}

const PARAM: Record<ParsedId["kind"], SearchParam> = { nip: "Nip", regon: "Regon", krs: "Krs" };
const BATCH_PARAM: Record<ParsedId["kind"], SearchParam> = { nip: "Nipy", regon: "Regony9zn", krs: "Krsy" };

/** Prefer the main entity row (P/F) that is still active; CEIDG silo first for natural persons. */
export function pickMainRow(rows: RegonRecord[]): RegonRecord | null {
  if (rows.length === 0) return null;
  const score = (r: RegonRecord) =>
    (r.Typ === "P" || r.Typ === "F" ? 4 : 0) + (r.DataZakonczeniaDzialalnosci ? 0 : 2) + (r.SilosID === "1" || r.SilosID === "6" ? 1 : 0);
  return [...rows].sort((a, b) => score(b) - score(a))[0];
}

export class RegonService {
  constructor(
    private readonly client: RegonClient,
    private readonly kv?: KVNamespace,
  ) {}

  private async coreFromRow(row: RegonRecord): Promise<RegonCore> {
    const basic = basicFromSearch(row);
    const rep = reportFor(basic);
    if (!rep) return { found: true, basic, details: null };
    let details: RegonDetails | null = null;
    try {
      const rows = await this.client.report(basic.regon, rep.main);
      if (rows[0]) details = detailsFromReport(rows[0]);
    } catch (err) {
      if (!(err instanceof RegonNotFound)) throw err;
    }
    return { found: true, basic, details };
  }

  /** Search + main report for one identifier. Cached; "not found" is cached briefly. */
  async core(id: ParsedId, maxAgeSeconds?: number): Promise<Cached<RegonCore>> {
    return cached<RegonCore>(
      this.kv,
      `regon:core:v1:${id.kind}:${id.value}`,
      { ttl: REGON_TTL, negativeTtl: REGON_NOT_FOUND_TTL, isNegative: (v) => !v.found, maxAgeSeconds },
      async () => {
        let rows: RegonRecord[];
        try {
          rows = await this.client.search(PARAM[id.kind], id.value);
        } catch (err) {
          if (err instanceof RegonNotFound) return { found: false, basic: null, details: null };
          throw err;
        }
        const row = pickMainRow(rows);
        return row ? this.coreFromRow(row) : { found: false, basic: null, details: null };
      },
    );
  }

  async pkd(regon: string, type: string | null): Promise<Cached<PkdCode[]>> {
    const report = type === "F" ? "BIR11OsFizycznaPkd" : "BIR11OsPrawnaPkd";
    return cached<PkdCode[]>(this.kv, `regon:pkd:v1:${regon}`, { ttl: REGON_PKD_TTL }, async () => {
      try {
        return pkdFromReport(await this.client.report(regon, report));
      } catch (err) {
        if (err instanceof RegonNotFound) return [];
        throw err;
      }
    });
  }

  /**
   * Batch lookup: one DaneSzukajPodmioty call per 20 ids, then the main report
   * for each found entity (needed for suspension status). Uses / fills the same
   * per-id cache as core().
   */
  async coreMany(kind: ParsedId["kind"], values: string[]): Promise<Map<string, Cached<RegonCore>>> {
    const out = new Map<string, Cached<RegonCore>>();
    const misses: string[] = [];
    if (this.kv) {
      await Promise.all(
        values.map(async (v) => {
          const hit = await this.kv!.get<{ v: RegonCore; at: number }>(`regon:core:v1:${kind}:${v}`, "json").catch(() => null);
          if (hit) out.set(v, { value: hit.v, fetchedAt: new Date(hit.at), cached: true });
          else misses.push(v);
        }),
      );
    } else misses.push(...values);

    for (let i = 0; i < misses.length; i += REGON_BATCH_MAX) {
      const chunk = misses.slice(i, i + REGON_BATCH_MAX);
      let rows: RegonRecord[] = [];
      try {
        rows = await this.client.search(BATCH_PARAM[kind], chunk);
      } catch (err) {
        if (!(err instanceof RegonNotFound)) throw err;
      }
      const field = kind === "nip" ? "Nip" : kind === "regon" ? "Regon" : "Krs";
      await mapLimit(chunk, 4, async (v) => {
          // Batch rows don't echo the KRS number, so for KRS we fall back to a single lookup.
          const matching = kind === "krs" ? null : rows.filter((r) => r[field] === v);
          const res =
            matching === null
              ? await this.core({ kind, value: v })
              : await cached<RegonCore>(
                  this.kv,
                  `regon:core:v1:${kind}:${v}`,
                  { ttl: REGON_TTL, negativeTtl: REGON_NOT_FOUND_TTL, isNegative: (x) => !x.found },
                  async () => {
                    const row = pickMainRow(matching);
                    return row ? this.coreFromRow(row) : { found: false, basic: null, details: null };
                  },
                );
          out.set(v, res);
      });
    }
    return out;
  }
}
