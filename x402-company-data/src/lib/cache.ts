// Read-through cache on Workers KV.
// Registry data changes at most daily, so a paid request should almost never
// need to hit the upstream API. Concurrent misses for the same key inside one
// isolate share a single upstream call.

export interface CacheEnvelope<T> {
  v: T;
  /** Epoch ms when the value was fetched from upstream. */
  at: number;
}

export interface Cached<T> {
  value: T;
  fetchedAt: Date;
  cached: boolean;
}

export interface CacheOptions<T> {
  /** Seconds to keep a value (KV minimum is 60). */
  ttl: number;
  /** Optional shorter TTL for "negative" values (e.g. not found). */
  negativeTtl?: number;
  isNegative?: (v: T) => boolean;
  /** Treat cached values older than this many seconds as a miss. */
  maxAgeSeconds?: number;
}

const inflight = new Map<string, Promise<Cached<unknown>>>();

export async function cached<T>(
  kv: KVNamespace | undefined,
  key: string,
  opts: CacheOptions<T>,
  load: () => Promise<T>,
): Promise<Cached<T>> {
  if (kv) {
    try {
      const hit = await kv.get<CacheEnvelope<T>>(key, "json");
      if (hit && (opts.maxAgeSeconds === undefined || Date.now() - hit.at <= opts.maxAgeSeconds * 1000)) {
        return { value: hit.v, fetchedAt: new Date(hit.at), cached: true };
      }
    } catch (err) {
      console.warn("cache read failed", key, err);
    }
  }

  const pending = inflight.get(key) as Promise<Cached<T>> | undefined;
  if (pending) return pending;

  const p = (async (): Promise<Cached<T>> => {
    const value = await load();
    const at = Date.now();
    if (kv) {
      const ttl = opts.isNegative?.(value) && opts.negativeTtl ? opts.negativeTtl : opts.ttl;
      try {
        await kv.put(key, JSON.stringify({ v: value, at } satisfies CacheEnvelope<T>), {
          expirationTtl: Math.max(60, ttl),
        });
      } catch (err) {
        console.warn("cache write failed", key, err);
      }
    }
    return { value, fetchedAt: new Date(at), cached: false };
  })();

  inflight.set(key, p);
  try {
    return await p;
  } finally {
    inflight.delete(key);
  }
}
