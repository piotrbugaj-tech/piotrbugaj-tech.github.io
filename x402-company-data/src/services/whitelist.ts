import { cached, type Cached } from "../lib/cache";
import { sha256Hex } from "../lib/hash";
import { normalizeNrb } from "../lib/nrb";
import { UpstreamError } from "../sources/errors";
import { WhitelistInputError, type WhitelistClient } from "../sources/whitelist/client";
import { accountCheck, vatStatusInfo, type AccountCheck, type VatStatusInfo } from "../sources/whitelist/normalize";

/** Upstream allows 100 search requests/day per IP; keep headroom for other users of the shared egress IP. */
export const WL_DEFAULT_SEARCH_BUDGET = 90;

export interface WhitelistServiceOptions {
  dailySearchBudget?: number;
  /** Injectable clock (tests). */
  now?: () => Date;
}

const warsawParts = (at: Date) => {
  const p = Object.fromEntries(
    new Intl.DateTimeFormat("en-GB", {
      timeZone: "Europe/Warsaw",
      hourCycle: "h23",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    })
      .formatToParts(at)
      .map((x) => [x.type, Number(x.value)]),
  );
  return { y: p.year, m: p.month, d: p.day, localAsUtc: Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second) };
};

/** Calendar date in Europe/Warsaw as YYYY-MM-DD — the day the white list is evaluated for. */
export function warsawDate(at: Date = new Date()): string {
  const { y, m, d } = warsawParts(at);
  return `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

/** Seconds until the next Warsaw midnight (DST-aware), at least 60 (KV minimum TTL). */
export function secondsUntilWarsawMidnight(at: Date = new Date()): number {
  const { y, m, d, localAsUtc } = warsawParts(at);
  const offsetMs = localAsUtc - Math.floor(at.getTime() / 1000) * 1000;
  // DST switches happen at night, never at 00:00, so the offset now equals the one at the next midnight
  // except on the switch day itself; re-evaluate at the estimated midnight to cover that.
  const guess = Date.UTC(y, m - 1, d + 1) - offsetMs;
  const offsetAtMidnight = warsawParts(new Date(guess)).localAsUtc - guess;
  const midnight = Date.UTC(y, m - 1, d + 1) - offsetAtMidnight;
  return Math.max(60, Math.ceil((midnight - at.getTime()) / 1000));
}

export class WhitelistService {
  private readonly budget: number;
  private readonly now: () => Date;
  // Per-isolate fallback when no KV is bound (keys carry the date, so they roll over).
  private readonly mem = new Map<string, number>();

  constructor(
    private readonly client: WhitelistClient,
    private readonly kv?: KVNamespace,
    opts: WhitelistServiceOptions = {},
  ) {
    this.budget = opts.dailySearchBudget ?? WL_DEFAULT_SEARCH_BUDGET;
    this.now = opts.now ?? (() => new Date());
  }

  /** VAT status of a NIP for today (Warsaw). Cached until Warsaw midnight. */
  async vatStatus(nip: string): Promise<Cached<VatStatusInfo>> {
    const at = this.now();
    const date = warsawDate(at);
    return cached<VatStatusInfo>(this.kv, `wl:status:v1:${date}:${nip}`, { ttl: secondsUntilWarsawMidnight(at) }, async () => {
      await this.guard(date, at, true);
      try {
        const r = await this.client.searchNip(nip, date);
        return vatStatusInfo(r.subject, r, nip);
      } catch (err) {
        await this.noteLimit(err, date, at);
        throw err;
      }
    });
  }

  /** Is `nrb` a white-listed account of `nip` today? The raw account number is never stored. */
  async checkAccount(nip: string, nrb: string): Promise<Cached<AccountCheck>> {
    const account = normalizeNrb(nrb);
    if (!account) throw new WhitelistInputError("invalid bank account number (NRB)");
    const at = this.now();
    const date = warsawDate(at);
    const key = `wl:check:v1:${date}:${await sha256Hex(`${nip}:${account}`)}`;
    return cached<AccountCheck>(this.kv, key, { ttl: secondsUntilWarsawMidnight(at) }, async () => {
      await this.guard(date, at, false);
      try {
        return accountCheck(await this.client.checkAccount(nip, account, date));
      } catch (err) {
        await this.noteLimit(err, date, at);
        throw err;
      }
    });
  }

  // KV has no atomic increment, so these counters are approximate (concurrent
  // isolates can under-count). That is fine for a soft guard well below the hard limit.
  private async guard(date: string, at: Date, isSearch: boolean): Promise<void> {
    if (await this.readNumber(`wl:blocked:${date}`)) throw new UpstreamError("MF_WL", "daily request limit exhausted (WL-191), blocked until midnight", 429);
    if (!isSearch) return;
    const key = `wl:budget:${date}`;
    const used = await this.readNumber(key);
    if (used >= this.budget) throw new UpstreamError("MF_WL", "daily search budget exhausted", 429);
    await this.writeNumber(key, used + 1, at);
  }

  /** WL-191 means MF has blocked our egress IP for the rest of the day: stop calling. */
  private async noteLimit(err: unknown, date: string, at: Date): Promise<void> {
    if (err instanceof UpstreamError && /WL-191/.test(err.message)) await this.writeNumber(`wl:blocked:${date}`, 1, at);
  }

  private async readNumber(key: string): Promise<number> {
    if (!this.kv) return this.mem.get(key) ?? 0;
    try {
      return Number(await this.kv.get(key)) || 0;
    } catch (err) {
      console.warn("whitelist counter read failed", key, err);
      return 0;
    }
  }

  private async writeNumber(key: string, n: number, at: Date): Promise<void> {
    if (!this.kv) {
      this.mem.set(key, n);
      return;
    }
    try {
      await this.kv.put(key, String(n), { expirationTtl: secondsUntilWarsawMidnight(at) });
    } catch (err) {
      console.warn("whitelist counter write failed", key, err);
    }
  }
}
