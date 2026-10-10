// Minimal D1Database adapter over node:sqlite (real SQLite incl. FTS5) for tests.
// Implements only what SearchIndex uses: prepare().bind().run()/all()/first(), batch().
import { DatabaseSync } from "node:sqlite";
import { readFileSync } from "node:fs";

type Params = Array<string | number | null>;

class Stmt {
  constructor(private db: DatabaseSync, readonly sql: string, private params: Params = []) {}
  bind(...p: unknown[]) {
    return new Stmt(this.db, this.sql, p.map((v) => (v === undefined ? null : v)) as Params);
  }
  async run() {
    const r = this.db.prepare(this.sql).run(...this.params);
    return { success: true, results: [], meta: { changes: Number(r.changes) } };
  }
  async all<T>() {
    const results = this.db.prepare(this.sql).all(...this.params) as T[];
    return { success: true, results, meta: {} };
  }
  async first<T>(): Promise<T | null> {
    return (this.db.prepare(this.sql).get(...this.params) as T | undefined) ?? null;
  }
}

export function sqliteD1(migrations: string[] = ["0001_search_index.sql"]) {
  const db = new DatabaseSync(":memory:");
  for (const m of migrations) db.exec(readFileSync(new URL(`../../migrations/${m}`, import.meta.url), "utf8"));
  const d1 = {
    raw: db,
    prepare: (sql: string) => new Stmt(db, sql),
    async batch(stmts: Stmt[]) {
      db.exec("BEGIN");
      try {
        const out = [];
        for (const s of stmts) out.push(await s.run());
        db.exec("COMMIT");
        return out;
      } catch (e) {
        db.exec("ROLLBACK");
        throw e;
      }
    },
  };
  return d1 as unknown as D1Database & { raw: DatabaseSync };
}

/** Same schema without the FTS table/triggers, to exercise the LIKE fallback. */
export function sqliteD1NoFts() {
  const d1 = sqliteD1([]);
  d1.raw.exec(
    readFileSync(new URL("../../migrations/0001_search_index.sql", import.meta.url), "utf8").split("-- FTS5 index")[0]!,
  );
  return d1;
}
