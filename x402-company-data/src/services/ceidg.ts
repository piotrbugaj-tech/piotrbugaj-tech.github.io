import { cached, type Cached } from "../lib/cache";
import { sha256Hex } from "../lib/hash";
import { fold } from "../lib/normalize";
import type { CeidgClient } from "../sources/ceidg/client";
import { ceidgDetails, ceidgSearchHit, type CeidgDetails, type CeidgSearchHit } from "../sources/ceidg/normalize";

export const CEIDG_TTL = 24 * 3600;
export const CEIDG_NOT_FOUND_TTL = 3600;
export const CEIDG_SEARCH_TTL = 6 * 3600;

export class CeidgService {
  constructor(
    private readonly client: CeidgClient,
    private readonly kv?: KVNamespace,
  ) {}

  private lookup(key: string, load: () => Promise<Record<string, any> | null>): Promise<Cached<CeidgDetails | null>> {
    return cached<CeidgDetails | null>(
      this.kv,
      key,
      { ttl: CEIDG_TTL, negativeTtl: CEIDG_NOT_FOUND_TTL, isNegative: (v) => v === null },
      async () => {
        const raw = await load();
        return raw ? ceidgDetails(raw) : null;
      },
    );
  }

  /** Normalised record, or null when the NIP is not a CEIDG sole trader. */
  byNip(nip: string): Promise<Cached<CeidgDetails | null>> {
    return this.lookup(`ceidg:v1:nip:${nip}`, () => this.client.firmaByNip(nip));
  }

  byRegon(regon: string): Promise<Cached<CeidgDetails | null>> {
    return this.lookup(`ceidg:v1:regon:${regon}`, () => this.client.firmaByRegon(regon));
  }

  async searchByName(name: string, opts: { city?: string; limit?: number } = {}): Promise<Cached<CeidgSearchHit[]>> {
    // Hashed so long free-text queries cannot exceed the KV key limit.
    const query = await sha256Hex(`${fold(name)}|${fold(opts.city ?? "")}|${opts.limit ?? ""}`);
    return cached<CeidgSearchHit[]>(this.kv, `ceidg:v1:search:${query}`, { ttl: CEIDG_SEARCH_TTL }, async () =>
      (await this.client.searchByName(name, opts)).map(ceidgSearchHit),
    );
  }
}
