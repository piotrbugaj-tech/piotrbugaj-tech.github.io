-- Company-name search index (Cloudflare D1 / SQLite).
-- Legal entities only (never natural persons). Filled from records the service
-- resolves anyway (REGON/KRS lookups) plus optional bulk seeding.
-- `key` is computed by the code: regon, else krs, else nip (prefixed R:/K:/N:).

CREATE TABLE IF NOT EXISTS entities (
  key         TEXT PRIMARY KEY,
  nip         TEXT,
  regon       TEXT,
  krs         TEXT,
  name        TEXT NOT NULL,
  name_folded TEXT NOT NULL,   -- uppercase, no diacritics, punctuation -> spaces
  legal_form  TEXT,
  status      TEXT,
  city        TEXT,
  city_folded TEXT,
  source      TEXT,
  updated_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS entities_nip ON entities (nip);
CREATE INDEX IF NOT EXISTS entities_krs ON entities (krs);
CREATE INDEX IF NOT EXISTS entities_city ON entities (city_folded);

-- FTS5 index; its rowid mirrors entities.rowid (stable across ON CONFLICT DO UPDATE).
CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts USING fts5(
  name_folded, city_folded,
  tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS entities_ai AFTER INSERT ON entities BEGIN
  INSERT INTO entities_fts (rowid, name_folded, city_folded) VALUES (new.rowid, new.name_folded, COALESCE(new.city_folded, ''));
END;

CREATE TRIGGER IF NOT EXISTS entities_ad AFTER DELETE ON entities BEGIN
  DELETE FROM entities_fts WHERE rowid = old.rowid;
END;

CREATE TRIGGER IF NOT EXISTS entities_au AFTER UPDATE ON entities BEGIN
  DELETE FROM entities_fts WHERE rowid = old.rowid;
  INSERT INTO entities_fts (rowid, name_folded, city_folded) VALUES (new.rowid, new.name_folded, COALESCE(new.city_folded, ''));
END;
