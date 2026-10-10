import { cached, type Cached } from "../lib/cache";
import type { KrsClient, KrsRegister } from "../sources/krs/client";
import { krsDetails, type KrsDetails } from "../sources/krs/normalize";

export const KRS_TTL = 24 * 3600;
export const KRS_NOT_FOUND_TTL = 3600;

export class KrsService {
  constructor(
    private readonly client: KrsClient,
    private readonly kv?: KVNamespace,
  ) {}

  /** Normalised current extract, or null when the number is not in KRS. */
  async details(krs: string, prefer: KrsRegister = "P"): Promise<Cached<KrsDetails | null>> {
    return cached<KrsDetails | null>(
      this.kv,
      `krs:odpis:v1:${krs}`,
      { ttl: KRS_TTL, negativeTtl: KRS_NOT_FOUND_TTL, isNegative: (v) => v === null },
      async () => {
        const odpis = await this.client.odpisAktualny(krs, prefer);
        return odpis ? krsDetails(krs, odpis) : null;
      },
    );
  }
}
