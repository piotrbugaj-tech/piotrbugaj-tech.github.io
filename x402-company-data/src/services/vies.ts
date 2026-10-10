import { cached, type Cached } from "../lib/cache";
import { normalizeVatInput, type ViesClient, type ViesResult } from "../sources/vies/client";

export const VIES_TTL = 24 * 3600;

export class ViesService {
  constructor(
    private readonly client: ViesClient,
    private readonly kv?: KVNamespace,
  ) {}

  /** Definitive answers (valid / invalid) are cached; "VIES could not tell" (valid === null) never is. */
  async check(countryCode: string, vatNumber: string): Promise<Cached<ViesResult>> {
    const { countryCode: cc, vatNumber: num } = normalizeVatInput(countryCode, vatNumber);
    try {
      return await cached<ViesResult>(this.kv, `vies:v1:${cc}:${num}`, { ttl: VIES_TTL }, async () => {
        const r = await this.client.check(cc, num);
        // cached() stores whatever load returns; throwing is how we skip the write.
        if (r.valid === null) throw new Unknown(r);
        return r;
      });
    } catch (err) {
      if (err instanceof Unknown) return { value: err.result, fetchedAt: new Date(), cached: false };
      throw err;
    }
  }
}

class Unknown extends Error {
  constructor(readonly result: ViesResult) {
    super("VIES gave no definitive answer");
  }
}
