// Company-name search index on Cloudflare D1 (optional binding).
// The official registers (KRS, REGON) have no search-by-name API, so we index
// LEGAL ENTITIES we resolve anyway. Natural persons / sole traders are never
// stored (GDPR: no search by a person's name). Search is FTS5 (all tokens
// required, prefix on the last one); user input is reduced to [A-Z0-9] tokens,
// each quoted, and always bound as a parameter. Falls back to LIKE when the
// FTS table is missing. Every method is a no-op when the binding is absent.

import { fold } from "../lib/normalize";
import { nameTokens } from "../lib/namematch";
import type { EntityStatus, LegalForm, SearchHit } from "../schema/company";

export interface IndexEntry {
  nip: string | null;
  regon: string | null;
  krs: string | null;
  name: string;
  legalForm: LegalForm | null;
  status: EntityStatus;
  city: string | null;
  source: "REGON" | "KRS" | "CEIDG";
}

interface Row {
  nip: string | null;
  regon: string | null;
  krs: string | null;
  name: string;
  legal_form: string | null;
  status: string | null;
  city: string | null;
  source: string | null;
}

const MAX_LIMIT = 20;
const DEFAULT_LIMIT = 10;

/** Matching form: folded, every non-alphanumeric run becomes one space. */
function matchForm(s: string): string {
  return fold(s).replace(/[^A-Z0-9]+/g, " ").trim();
}

function entryKey(e: IndexEntry): string | null {
  if (e.regon) return `R:${e.regon}`;
  if (e.krs) return `K:${e.krs}`;
  if (e.nip) return `N:${e.nip}`;
  return null;
}

/** Natural persons (and partnerships named after them) must never be indexed. */
function isIndexable(e: IndexEntry): boolean {
  if (e.legalForm === "sole_proprietorship" || e.legalForm === "civil_partnership") return false;
  if (e.legalForm === null && !e.krs) return false;
  return !!e.name.trim() && entryKey(e) !== null;
}

export class SearchIndex {
  constructor(private readonly db?: D1Database) {}

  async upsert(entry: IndexEntry): Promise<void> {
    if (!this.db || !isIndexable(entry)) return;
    const key = entryKey(entry)!;
    const city = entry.city?.trim() || null;
    const stmts = [
      // Same entity first seen under a weaker key (e.g. KRS only, then REGON): drop the stale row.
      this.db
        .prepare("DELETE FROM entities WHERE key != ?1 AND ((?2 IS NOT NULL AND krs = ?2) OR (?3 IS NOT NULL AND nip = ?3))")
        .bind(key, entry.krs, entry.nip),
      this.db
        .prepare(
          `INSERT INTO entities (key, nip, regon, krs, name, name_folded, legal_form, status, city, city_folded, source, updated_at)
           VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12)
           ON CONFLICT(key) DO UPDATE SET
             nip = COALESCE(excluded.nip, nip), regon = COALESCE(excluded.regon, regon), krs = COALESCE(excluded.krs, krs),
             name = excluded.name, name_folded = excluded.name_folded, legal_form = excluded.legal_form,
             status = excluded.status, city = excluded.city, city_folded = excluded.city_folded,
             source = excluded.source, updated_at = excluded.updated_at`,
        )
        .bind(
          key, entry.nip, entry.regon, entry.krs, entry.name.trim(), matchForm(entry.name), entry.legalForm, entry.status,
          city, city ? matchForm(city) : null, entry.source, new Date().toISOString(),
        ),
    ];
    await this.db.batch(stmts);
  }

  async search(query: string, opts: { city?: string; limit?: number } = {}): Promise<SearchHit[]> {
    if (!this.db) return [];
    const tokens = nameTokens(query);
    if (tokens.length === 0 || (tokens.length === 1 && tokens[0]!.length < 2)) return [];
    const limit = Math.min(MAX_LIMIT, Math.max(1, Math.trunc(Number(opts.limit)) || DEFAULT_LIMIT));
    const city = opts.city ? matchForm(opts.city) : "";

    try {
      return await this.searchFts(tokens, city, limit);
    } catch (e) {
      if (!/no such (table|module)/i.test(String(e instanceof Error ? e.message : e))) throw e;
      return this.searchLike(tokens, city, limit);
    }
  }

  async count(): Promise<number> {
    if (!this.db) return 0;
    try {
      const r = await this.db.prepare("SELECT COUNT(*) AS n FROM entities").first<{ n: number }>();
      return r?.n ?? 0;
    } catch {
      return 0;
    }
  }

  private async searchFts(tokens: string[], city: string, limit: number): Promise<SearchHit[]> {
    // Tokens are [A-Z0-9]+ only; quoting also neutralises AND/OR/NOT/NEAR keywords.
    const terms = tokens.map((t, i) => `"${t}"${i === tokens.length - 1 ? "*" : ""}`);
    const match = `name_folded : (${terms.join(" ")})`;
    const params: unknown[] = [match];
    let sql = "SELECT e.* FROM entities_fts JOIN entities e ON e.rowid = entities_fts.rowid WHERE entities_fts MATCH ?";
    if (city) {
      sql += " AND e.city_folded LIKE ? ESCAPE '\\'";
      params.push(likePrefix(city));
    }
    sql += " ORDER BY bm25(entities_fts), length(e.name), e.name LIMIT ?";
    params.push(limit);
    const { results } = await this.db!.prepare(sql).bind(...params).all<Row>();
    return results.map(toHit);
  }

  private async searchLike(tokens: string[], city: string, limit: number): Promise<SearchHit[]> {
    const params: unknown[] = [];
    const conds = tokens.map((t, i) => {
      params.push(i === tokens.length - 1 ? `% ${t}%` : `% ${t} %`);
      return "(' ' || name_folded || ' ') LIKE ?";
    });
    if (city) {
      conds.push("city_folded LIKE ? ESCAPE '\\'");
      params.push(likePrefix(city));
    }
    params.push(limit);
    const sql = `SELECT * FROM entities WHERE ${conds.join(" AND ")} ORDER BY length(name), name LIMIT ?`;
    const { results } = await this.db!.prepare(sql).bind(...params).all<Row>();
    return results.map(toHit);
  }
}

function likePrefix(s: string): string {
  return s.replace(/[\\%_]/g, "\\$&") + "%";
}

function toHit(r: Row): SearchHit {
  return {
    name: r.name,
    identifiers: { nip: r.nip, regon: r.regon, krs: r.krs },
    legalForm: r.legal_form as LegalForm | null,
    status: (r.status ?? "unknown") as EntityStatus,
    city: r.city,
    source: (r.source ?? "REGON") as SearchHit["source"],
  };
}
